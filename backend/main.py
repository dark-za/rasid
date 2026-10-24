from datetime import date, datetime, time, timedelta
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import attendance_core
import config
import models
import schemas
import timeutils
from database import get_attendance_db, get_db, init_db

app = FastAPI(title="Rasid Attendance System", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings()["cors_origins"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    try:
        init_db()
    except Exception as exc:  # noqa: BLE001 — نسجل ولا نمنع إقلاع الخادم
        print(f"[rasid] تحذير: تعذر تهيئة قاعدة بيانات راصد: {exc}")


def require_api_key(x_api_key: str = Header(default="")):
    expected_key = config.settings()["api_key"]
    if not expected_key:
        raise HTTPException(status_code=503, detail="واجهة API غير مهيأة بمفتاح وصول")

    if not hmac.compare_digest(x_api_key, expected_key):
        raise HTTPException(status_code=401, detail="مفتاح الوصول غير صحيح")


@app.get("/", response_model=schemas.HealthOut)
def read_root():
    return {
        "status": "online",
        "system": "راصد - نظام متابعة الحضور والانصراف",
        "time": timeutils.app_now(),
    }


def _first_shift(db: Session):
    shift = db.query(models.Shift).order_by(models.Shift.id).first()
    cfg = config.settings()
    if not shift:
        return cfg["default_shift_start"], cfg["default_grace_minutes"]
    return shift.start_time, shift.grace_period_minutes


def _parse_shift_start(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="وقت بداية الشيفت غير صحيح في القاعدة") from exc


@app.get("/api/attendance/today", response_model=schemas.AttendanceTodayOut)
def get_today_attendance(
    _: None = Depends(require_api_key),
    app_db: Session = Depends(get_db),
    att_db: Session = Depends(get_attendance_db),
):
    cfg = config.settings()
    start_ms, end_ms = timeutils.day_bounds_epoch_ms(timeutils.app_now().date())

    try:
        rows = att_db.execute(
            text(
                """
                SELECT PersonID, PersonName, AttendanceDateTime, AttendanceState, DeviceName
                FROM AttendanceRecordInfo
                WHERE AttendanceDateTime >= :start_ms AND AttendanceDateTime < :end_ms
                ORDER BY AttendanceDateTime ASC
                """
            ),
            {"start_ms": start_ms, "end_ms": end_ms},
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="تعذر قراءة سجلات الحضور") from exc

    # فلترة التبصيم المتكرر وحساب المتأخرين (منطق نقية في attendance_core)
    shift_start_str, grace_minutes = _first_shift(app_db)
    result = attendance_core.process_attendance_rows(
        rows,
        shift_start=_parse_shift_start(shift_start_str),
        grace_minutes=grace_minutes,
        debounce_minutes=cfg["debounce_minutes"],
    )

    return {
        "date": timeutils.app_now().strftime("%Y-%m-%d"),
        "total_records_processed": len(result["logs"]),
        "logs": result["logs"],
        "late_employees": result["late_employees"],
    }


@app.get("/api/shifts", response_model=list[schemas.ShiftOut])
def get_shifts(db: Session = Depends(get_db), _: None = Depends(require_api_key)):
    shifts = db.query(models.Shift).all()
    if not shifts:
        cfg = config.settings()
        db.add(
            models.Shift(
                name="الشيفت الصباحي الأساسي",
                start_time=cfg["default_shift_start"],
                end_time="17:00",
                grace_period_minutes=cfg["default_grace_minutes"],
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        shifts = db.query(models.Shift).all()
    return shifts


@app.get("/api/employee-branches", response_model=schemas.BranchPage)
def get_employee_branches(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    total = db.query(models.EmployeeBranchHistory).count()
    items = (
        db.query(models.EmployeeBranchHistory)
        .order_by(
            models.EmployeeBranchHistory.start_date.desc(),
            models.EmployeeBranchHistory.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.post("/api/employee-branches")
def assign_employee_branch(
    payload: schemas.BranchTransferIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    s_date = payload.start_date

    # قفل صفوف الموظف لمنع التداخل عند طلبين متزامنين
    active_records = (
        db.query(models.EmployeeBranchHistory)
        .filter(
            models.EmployeeBranchHistory.employee_id == payload.employee_id,
            models.EmployeeBranchHistory.end_date.is_(None),
        )
        .with_for_update()
        .all()
    )

    if any(s_date <= record.start_date for record in active_records):
        raise HTTPException(
            status_code=409, detail="تاريخ النقل يجب أن يكون بعد بداية الفرع الحالي"
        )

    overlapping_future = (
        db.query(models.EmployeeBranchHistory)
        .filter(
            models.EmployeeBranchHistory.employee_id == payload.employee_id,
            models.EmployeeBranchHistory.start_date >= s_date,
        )
        .first()
    )
    if overlapping_future:
        raise HTTPException(
            status_code=409, detail="يوجد سجل فرع يبدأ في هذا التاريخ أو بعده"
        )

    overlapping_history = (
        db.query(models.EmployeeBranchHistory)
        .filter(
            models.EmployeeBranchHistory.employee_id == payload.employee_id,
            models.EmployeeBranchHistory.start_date <= s_date,
            models.EmployeeBranchHistory.end_date.isnot(None),
            models.EmployeeBranchHistory.end_date >= s_date,
        )
        .first()
    )
    if overlapping_history:
        raise HTTPException(status_code=409, detail="تاريخ النقل يتداخل مع سجل فرع سابق")

    for rec in active_records:
        rec.end_date = s_date - timedelta(days=1)

    new_record = models.EmployeeBranchHistory(
        employee_id=payload.employee_id,
        employee_name=payload.employee_name,
        branch_name=payload.branch_name,
        start_date=s_date,
        notes=payload.notes,
    )
    db.add(new_record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="تعارض في بيانات نقل الموظف")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="تعذر حفظ نقل الموظف")
    db.refresh(new_record)
    return {"status": "success", "data": schemas.BranchRecordOut.from_orm(new_record)}
