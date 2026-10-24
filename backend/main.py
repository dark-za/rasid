from datetime import date, datetime, time, timedelta
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
import models
import schemas
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
        "time": datetime.now(),
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
    now = datetime.now()
    day_start = datetime(now.year, now.month, now.day)
    day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
    start_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000)

    try:
        rows = att_db.execute(
            text(
                """
                SELECT PersonID, PersonName, AttendanceDateTime, AttendanceState, DeviceName
                FROM AttendanceRecordInfo
                WHERE AttendanceDateTime BETWEEN :start_ms AND :end_ms
                ORDER BY AttendanceDateTime ASC
                """
            ),
            {"start_ms": start_ms, "end_ms": end_ms},
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="تعذر قراءة سجلات الحضور") from exc

    # معالجة التبصيم المتكرر (Debounce افتراضي 5 دقائق لكل موظف)
    debounce = timedelta(minutes=cfg["debounce_minutes"])
    filtered_logs = []
    last_punch: dict[str, datetime] = {}

    for person_id, person_name, ts_ms, state, device in rows:
        if ts_ms is None:
            continue
        try:
            p_time = datetime.fromtimestamp(int(ts_ms) / 1000)
        except (TypeError, ValueError, OSError):
            continue

        emp_id = str(person_id or "Unknown")
        previous = last_punch.get(emp_id)
        if previous is not None and (p_time - previous) < debounce:
            continue

        last_punch[emp_id] = p_time
        filtered_logs.append(
            {
                "employee_id": emp_id,
                "employee_name": person_name,
                "check_time": p_time.strftime("%Y-%m-%d %H:%M:%S"),
                "device": device,
                "state": state,
            }
        )

    # حساب المتأخرين مقابل بداية الشيفت + فترة السماح
    shift_start_str, grace_minutes = _first_shift(app_db)
    shift_start = _parse_shift_start(shift_start_str)
    grace = timedelta(minutes=grace_minutes)

    first_punches: dict[str, dict] = {}
    for log in filtered_logs:
        emp = log["employee_id"]
        if emp not in first_punches:
            first_punches[emp] = log

    late_employees = []
    for emp, log in first_punches.items():
        t = datetime.strptime(log["check_time"], "%Y-%m-%d %H:%M:%S")
        limit_time = datetime.combine(t.date(), shift_start) + grace
        if t > limit_time:
            late_employees.append(
                {
                    "employee_id": emp,
                    "employee_name": log.get("employee_name"),
                    "arrival_time": log["check_time"],
                    "late_minutes": int((t - limit_time).total_seconds() // 60),
                }
            )

    return {
        "date": day_start.strftime("%Y-%m-%d"),
        "total_records_processed": len(filtered_logs),
        "logs": filtered_logs,
        "late_employees": late_employees,
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
