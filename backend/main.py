from datetime import date, datetime, time, timedelta
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import attendance_core
import auth
import config
import database
import models
import schemas
import timeutils
from database import get_attendance_db, get_db, init_db

app = FastAPI(title="Rasid Attendance System", version="2.0.0")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
    except (config.ConfigError, RuntimeError, ValueError, database.SQLAlchemyError):
        logger.exception(
            "Database startup check failed; admin database configuration remains available"
        )


def require_authenticated_user(authorization: str = Header(default="")):
    return auth.require_authenticated_user(authorization)


@app.post("/api/auth/login", response_model=schemas.LoginOut)
def login(payload: schemas.LoginIn):
    try:
        token = auth.issue_access_token(payload.username, payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except auth.AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": auth.TOKEN_TTL_SECONDS,
    }


def _database_settings_output() -> dict:
    current = config.settings()
    return {
        "host": current["db_host"],
        "port": current["db_port"],
        "attendance_database": current["db_name_attendance"],
        "attendance_username": current["db_user_attendance"],
        "attendance_password_set": bool(config.db_password_attendance()),
    }


def _attendance_database_candidate(
    payload: schemas.DatabaseConnectionIn,
) -> tuple[dict, str]:
    attendance_password = payload.attendance_password or config.db_password_attendance()
    if not attendance_password:
        raise HTTPException(
            status_code=422,
            detail="أدخل كلمة مرور قاعدة البصمة.",
        )
    settings = {
        "db_host": payload.host,
        "db_port": payload.port,
        "db_name_attendance": payload.attendance_database,
        "db_user_attendance": payload.attendance_username,
    }
    return settings, attendance_password


@app.get("/api/admin/database")
def get_database_settings(_: str = Depends(require_authenticated_user)):
    return _database_settings_output()


@app.post("/api/admin/database/test")
def test_database_settings(
    payload: schemas.DatabaseConnectionIn,
    _: str = Depends(require_authenticated_user),
):
    settings, attendance_password = _attendance_database_candidate(payload)
    result = {
        "attendance_connected": database.test_attendance_connection(
            settings, attendance_password
        )
    }
    result["ready"] = result["attendance_connected"]
    return result


@app.put("/api/admin/database")
def update_database_settings(
    payload: schemas.DatabaseConnectionIn,
    _: str = Depends(require_authenticated_user),
):
    settings, attendance_password = _attendance_database_candidate(payload)
    if not database.test_attendance_connection(settings, attendance_password):
        raise HTTPException(status_code=422, detail="تعذر الاتصال بقاعدة بيانات البصمة؛ لم تُحفظ الإعدادات.")

    persisted_values = {
        "DB_HOST": settings["db_host"],
        "DB_PORT": str(settings["db_port"]),
        "ATTENDANCE_DB_NAME": settings["db_name_attendance"],
        "ATTENDANCE_DB_USER": settings["db_user_attendance"],
        "ATTENDANCE_PASS": attendance_password,
    }
    try:
        config.update_env_file(persisted_values)
    except OSError as exc:
        logger.exception("Failed to persist database settings")
        raise HTTPException(
            status_code=500,
            detail="تعذر حفظ إعدادات الاتصال في ملف .env؛ لم يتغير اتصال التطبيق.",
        ) from exc
    for key, value in persisted_values.items():
        os.environ[key] = value
    config.settings.cache_clear()
    config.db_password_attendance.cache_clear()
    database.reset_engines()
    return {
        "status": "saved",
        "message": "تم اختبار اتصال قاعدة البصمة وحفظ إعداداتها.",
        "settings": _database_settings_output(),
    }


@app.get("/", response_model=schemas.HealthOut)
def read_root():
    return {
        "status": "online",
        "system": "راصد - نظام متابعة الحضور والانصراف",
        "time": timeutils.app_now(),
    }


@app.get("/health/live")
def health_live():
    return {"status": "live"}


@app.get("/health/ready")
def health_ready(
    app_db: Session = Depends(get_db),
    att_db: Session = Depends(get_attendance_db),
):
    try:
        app_db.execute(text("SELECT 1"))
        att_db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="الخدمة غير جاهزة")
    return {"status": "ready"}


def _first_shift(db: Session):
    shift = _active_shift(db)
    cfg = config.settings()
    if not shift:
        return cfg["default_shift_start"], cfg["default_grace_minutes"]
    return shift.start_time, shift.grace_period_minutes


def _active_shift(db: Session):
    shift = (
        db.query(models.Shift)
        .filter(models.Shift.is_active.is_(True))
        .order_by(models.Shift.id)
        .first()
    )
    return shift


def _parse_shift_start(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="وقت بداية الشيفت غير صحيح في القاعدة") from exc


def _parse_shift_time(value: str, field_name: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"وقت {field_name} غير صحيح في القاعدة") from exc


def _shift_assignment_context(
    app_db: Session, start: date, end: date
) -> tuple[list, dict[int, object], set[str] | None]:
    """Load assignments/shifts once for a report window, including overnight starts."""
    first_day = start - timedelta(days=1)
    try:
        assignments = (
            app_db.query(models.EmployeeShiftAssignment)
            .filter(
                models.EmployeeShiftAssignment.start_date <= end,
                (models.EmployeeShiftAssignment.end_date.is_(None))
                | (models.EmployeeShiftAssignment.end_date >= first_day),
            )
            .order_by(
                models.EmployeeShiftAssignment.employee_id,
                models.EmployeeShiftAssignment.start_date,
            )
            .all()
        )
    except AttributeError:
        # Keep lightweight test doubles and old deployments without roster models usable.
        return [], {}, None
    shift_ids = {assignment.shift_id for assignment in assignments}
    shifts = (
        app_db.query(models.Shift)
        .filter(models.Shift.id.in_(shift_ids))
        .all()
        if shift_ids
        else []
    )
    shift_by_id = {shift.id: shift for shift in shifts}
    employee_ids = {assignment.employee_id for assignment in assignments}
    active_ids = None
    if employee_ids:
        active_column = getattr(models.Employee, "is_active", None)
        if active_column is None:
            active_column = models.Employee.active
        active_ids = {
            employee.employee_id
            for employee in app_db.query(models.Employee)
            .filter(
                models.Employee.employee_id.in_(employee_ids),
                active_column.is_(True),
            )
            .all()
        }
    return assignments, shift_by_id, active_ids


def _assignment_for_date(assignments: list, employee_id: str, day: date):
    matching = [
        assignment
        for assignment in assignments
        if assignment.employee_id == employee_id
        and assignment.start_date <= day
        and (assignment.end_date is None or assignment.end_date >= day)
    ]
    return max(matching, key=lambda item: (item.start_date, item.id), default=None)


def _shift_session(shift, shift_day: date) -> tuple[datetime, datetime]:
    start_time = _parse_shift_time(shift.start_time, "بداية الوردية")
    end_time = _parse_shift_time(shift.end_time, "نهاية الوردية")
    if start_time == end_time:
        raise HTTPException(status_code=500, detail="وقت بداية الوردية ونهايتها متطابقان")
    start = datetime.combine(shift_day, start_time, tzinfo=timeutils.app_tz())
    end_day = shift_day + timedelta(days=1) if end_time < start_time else shift_day
    end = datetime.combine(end_day, end_time, tzinfo=timeutils.app_tz())
    return start, end


def _read_attendance_range(att_db: Session, start: date, end: date, employee_id=None):
    """Read one bounded half-open timestamp range from SmartPSS."""
    start_ms = timeutils.local_to_epoch_ms(
        datetime.combine(start, time.min, tzinfo=timeutils.app_tz())
    )
    end_ms = timeutils.local_to_epoch_ms(
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=timeutils.app_tz())
    )
    query = """
        SELECT PersonID, PersonName, AttendanceDateTime, AttendanceState, DeviceName
        FROM AttendanceRecordInfo
        WHERE AttendanceDateTime >= :start_ms AND AttendanceDateTime < :end_ms
    """
    params = {"start_ms": start_ms, "end_ms": end_ms}
    if employee_id:
        query += " AND PersonID = :employee_id"
        params["employee_id"] = employee_id
    query += " ORDER BY AttendanceDateTime ASC"
    try:
        rows = att_db.execute(text(query), params).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="تعذر قراءة سجلات الحضور") from exc
    return rows


def _punch_datetimes(rows: list[tuple]) -> list[tuple]:
    punches = []
    for person_id, person_name, ts_ms, state, device in rows:
        if ts_ms is None:
            continue
        try:
            punch_time = timeutils.epoch_ms_to_local(int(ts_ms))
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        punches.append((punch_time, str(person_id or "Unknown"), person_name, state, device))
    return sorted(punches, key=lambda item: item[0])


def _late_events(
    punches: list[tuple],
    assignments: list,
    shifts: dict[int, object],
    active_employee_ids: set[str] | None,
    start_date: date,
    end_date: date,
    employee_names: dict[str, str] | None = None,
) -> list[dict]:
    """Attribute late arrivals to an assigned shift's start date, including overnight tails."""
    debounce = timedelta(minutes=config.settings()["debounce_minutes"])
    latest_punch: dict[str, datetime] = {}
    candidates: dict[tuple[str, date], tuple[datetime, object, str | None]] = {}
    punch_names: dict[str, str] = {}
    for punch_time, employee_id, person_name, _state, _device in punches:
        if person_name and employee_id not in punch_names:
            punch_names[employee_id] = person_name
        previous = latest_punch.get(employee_id)
        if previous is not None and punch_time - previous < debounce:
            continue
        latest_punch[employee_id] = punch_time
        if active_employee_ids is not None and employee_id not in active_employee_ids:
            continue
        matches = []
        for shift_day in (punch_time.date(), punch_time.date() - timedelta(days=1)):
            if shift_day < start_date or shift_day > end_date:
                continue
            assignment = _assignment_for_date(assignments, employee_id, shift_day)
            shift = shifts.get(assignment.shift_id) if assignment else None
            if shift is None:
                continue
            session_start, session_end = _shift_session(shift, shift_day)
            # Include reasonable early arrivals and the full shift end; midnight tails are
            # mapped to the previous evening's start date rather than the punch date.
            if session_start - timedelta(hours=12) <= punch_time <= session_end:
                matches.append((shift_day, shift, session_start))
        if not matches:
            continue
        # A punch during an already-started overnight shift belongs there, not to a
        # next-day shift whose early-arrival window happens to overlap after midnight.
        started = [match for match in matches if match[2] <= punch_time]
        chosen = max(started, key=lambda match: match[2]) if started else min(
            matches, key=lambda match: match[2]
        )
        shift_day, shift, _session_start = chosen
        key = (employee_id, shift_day)
        old = candidates.get(key)
        if old is None or punch_time < old[0]:
            candidates[key] = (punch_time, shift, person_name)

    events = []
    for (employee_id, shift_day), (punch_time, shift, punch_emp_name) in candidates.items():
        session_start, _ = _shift_session(shift, shift_day)
        mode = getattr(shift, "lateness_mode", "after_grace")
        grace = int(shift.grace_period_minutes)
        threshold = session_start
        if mode == "after_grace":
            threshold += timedelta(minutes=grace)
        late_minutes = (
            int((punch_time - threshold).total_seconds() // 60)
            if punch_time > threshold
            else 0
        )
        if late_minutes > 0:
            name = (
                (employee_names.get(employee_id) if employee_names else None)
                or punch_emp_name
                or punch_names.get(employee_id)
            )
            events.append(
                {
                    "employee_id": employee_id,
                    "employee_name": name,
                    "late_minutes": late_minutes,
                    "shift_date": shift_day,
                    "shift_name": shift.name,
                    "arrival_time": punch_time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    return events


def _attendance_for_date(
    day: date,
    app_db: Session,
    att_db: Session,
    employee_id: str | None = None,
    shift_config: tuple[str, int] | None = None,
):
    cfg = config.settings()
    rows = _read_attendance_range(
        att_db, day - timedelta(days=1), day + timedelta(days=1), employee_id
    )
    shift_start_str, grace_minutes = shift_config or _first_shift(app_db)
    result = attendance_core.process_attendance_rows(
        rows,
        shift_start=_parse_shift_start(shift_start_str),
        grace_minutes=grace_minutes,
        debounce_minutes=cfg["debounce_minutes"],
    )
    day_logs = [
        item for item in result["logs"] if item["check_time"][:10] == day.isoformat()
    ]
    assignments = []
    shifts = {}
    active_ids = None
    active_employees_map: dict[str, str] = {}
    try:
        assignments, shifts, active_ids = _shift_assignment_context(
            app_db, day - timedelta(days=1), day
        )
        if active_ids and hasattr(app_db, "query"):
            try:
                q = app_db.query(models.Employee).filter(
                    models.Employee.employee_id.in_(active_ids)
                )
                if hasattr(q, "all"):
                    active_employees_map = {
                        e.employee_id: getattr(e, "name", None) for e in q.all()
                    }
            except Exception:
                active_employees_map = {}
        late_events = _late_events(
            _punch_datetimes(rows),
            assignments,
            shifts,
            active_ids,
            day - timedelta(days=1),
            day,
            active_employees_map,
        )
    except (AttributeError, Exception):
        late_events = []

    late_employees_for_day = [
        {
            "employee_id": event["employee_id"],
            "employee_name": event["employee_name"],
            "arrival_time": event["arrival_time"],
            "late_minutes": event["late_minutes"],
            "shift_date": event["shift_date"].isoformat()
            if hasattr(event["shift_date"], "isoformat")
            else str(event["shift_date"]),
            "shift_name": event["shift_name"],
        }
        for event in late_events
        if event["shift_date"] == day
    ]

    late_map = {e["employee_id"]: e for e in late_employees_for_day}

    # Group punches for the day by employee
    emp_punches: dict[str, list[dict]] = {}
    for log in day_logs:
        emp_punches.setdefault(log["employee_id"], []).append(log)

    # In case an overnight worker punched after midnight, ensure they are represented
    for e in late_employees_for_day:
        if e["employee_id"] not in emp_punches:
            emp_punches[e["employee_id"]] = [
                {
                    "check_time": e["arrival_time"],
                    "employee_name": e.get("employee_name"),
                }
            ]

    # Build employee summary
    employee_summary = []
    for emp_id, p_logs in emp_punches.items():
        if employee_id and emp_id != employee_id:
            continue
        p_logs.sort(key=lambda x: x["check_time"])
        first_punch = p_logs[0]["check_time"]
        last_punch = p_logs[-1]["check_time"]
        punch_count = len(p_logs)
        emp_name = p_logs[0].get("employee_name") or active_employees_map.get(emp_id)

        if emp_id in late_map:
            is_late = True
            late_minutes = late_map[emp_id]["late_minutes"]
            shift_name = late_map[emp_id].get("shift_name")
        else:
            assignment = (
                _assignment_for_date(assignments, emp_id, day) if assignments else None
            )
            shift = shifts.get(assignment.shift_id) if assignment and shifts else None
            is_late = False
            late_minutes = 0
            shift_name = shift.name if shift else None

        employee_summary.append(
            {
                "employee_id": emp_id,
                "employee_name": emp_name,
                "first_punch": first_punch,
                "last_punch": last_punch,
                "punch_count": punch_count,
                "late_minutes": late_minutes,
                "is_late": is_late,
                "shift_name": shift_name,
            }
        )
    employee_summary.sort(key=lambda x: x["first_punch"])

    # Identify unpunched employees: active employees scheduled for a shift on this day who did not punch
    unpunched_employees = []
    punched_ids = set(emp_punches.keys())
    if active_ids:
        candidate_active_ids = (
            [employee_id] if employee_id and employee_id in active_ids else list(active_ids)
        )
        for candidate_id in sorted(candidate_active_ids):
            if candidate_id in punched_ids:
                continue
            assignment = (
                _assignment_for_date(assignments, candidate_id, day) if assignments else None
            )
            if assignment is None:
                continue
            shift = shifts.get(assignment.shift_id) if assignment and shifts else None
            unpunched_employees.append(
                {
                    "employee_id": candidate_id,
                    "employee_name": active_employees_map.get(candidate_id),
                    "shift_name": shift.name if shift else None,
                    "status": "لم يسجل بصمة بعد",
                }
            )

    return {
        "date": day.strftime("%Y-%m-%d"),
        "total_records_processed": len(day_logs),
        "logs": day_logs,
        "late_employees": late_employees_for_day,
        "employee_summary": employee_summary,
        "unpunched_employees": unpunched_employees,
    }


@app.get("/api/attendance/today", response_model=schemas.AttendanceTodayOut)
def get_today_attendance(
    app_db: Session = Depends(get_db),
    att_db: Session = Depends(get_attendance_db),
):
    return _attendance_for_date(timeutils.app_now().date(), app_db, att_db)


@app.get("/api/attendance", response_model=schemas.AttendanceTodayOut)
def get_attendance(
    attendance_date: date | None = Query(None, alias="date"),
    employee_id: str | None = Query(None, min_length=1, max_length=50),
    app_db: Session = Depends(get_db),
    att_db: Session = Depends(get_attendance_db),
):
    today = timeutils.app_now().date()
    day = attendance_date or today
    if day > today or day < today - timedelta(days=90):
        raise HTTPException(status_code=422, detail="التاريخ يجب أن يكون خلال آخر 90 يوماً")
    return _attendance_for_date(day, app_db, att_db, employee_id)


def aggregate_late_report(daily_results: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for result in daily_results:
        for late in result["late_employees"]:
            employee_id = late["employee_id"]
            employee = totals.setdefault(
                employee_id,
                {
                    "employee_id": employee_id,
                    "employee_name": late["employee_name"],
                    "late_days": 0,
                    "total_late_minutes": 0,
                },
            )
            employee["employee_name"] = late["employee_name"] or employee["employee_name"]
            employee["late_days"] += 1
            employee["total_late_minutes"] += late["late_minutes"]

    report = []
    for employee in totals.values():
        employee["average_late_minutes"] = round(
            employee["total_late_minutes"] / employee["late_days"], 1
        )
        report.append(employee)
    return sorted(
        report,
        key=lambda employee: (-employee["total_late_minutes"], employee["employee_id"]),
    )


@app.get("/api/reports/late", response_model=schemas.LateReportOut)
def get_late_report(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    app_db: Session = Depends(get_db),
    att_db: Session = Depends(get_attendance_db),
):
    today = timeutils.app_now().date()
    end = to_date or today
    start = from_date or (end - timedelta(days=29))
    if start > end:
        raise HTTPException(status_code=422, detail="تاريخ البداية يجب أن يسبق تاريخ النهاية")
    if (end - start).days > 30:
        raise HTTPException(status_code=422, detail="أقصى فترة للتقرير 31 يوماً")
    if end > today or start < today - timedelta(days=90):
        raise HTTPException(status_code=422, detail="الفترة يجب أن تكون خلال آخر 90 يوماً")

    # One SmartPSS query covers the complete requested interval plus the prior day
    # needed to evaluate overnight shifts ending after midnight.
    rows = _read_attendance_range(att_db, start - timedelta(days=1), end)
    assignments, shifts, active_ids = _shift_assignment_context(app_db, start, end)
    employee_names: dict[str, str] = {}
    if active_ids and hasattr(app_db, "query"):
        try:
            emps = (
                app_db.query(models.Employee)
                .filter(models.Employee.employee_id.in_(active_ids))
                .all()
            )
            if hasattr(emps, "__iter__"):
                employee_names = {
                    e.employee_id: getattr(e, "name", None) for e in emps
                }
        except Exception:
            employee_names = {}
    events = _late_events(
        _punch_datetimes(rows),
        assignments,
        shifts,
        active_ids,
        start,
        end,
        employee_names,
    )
    by_day: dict[date, list[dict]] = {}
    for event in events:
        by_day.setdefault(event["shift_date"], []).append(
            {
                "employee_id": event["employee_id"],
                "employee_name": event["employee_name"],
                "late_minutes": event["late_minutes"],
            }
        )
    daily_results = [
        {"late_employees": by_day.get(start + timedelta(days=offset), [])}
        for offset in range((end - start).days + 1)
    ]

    employees = aggregate_late_report(daily_results)
    return {
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "shift_name": "حسب الوردية المعيّنة لكل موظف",
        "shift_start": None,
        "grace_period_minutes": None,
        "total_late_days": sum(employee["late_days"] for employee in employees),
        "total_late_minutes": sum(employee["total_late_minutes"] for employee in employees),
        "employees": employees,
    }


@app.get("/api/shifts", response_model=list[schemas.ShiftOut])
def get_shifts(db: Session = Depends(get_db)):
    return db.query(models.Shift).order_by(models.Shift.id).all()


@app.post("/api/shifts", response_model=schemas.ShiftOut)
def create_shift(
    payload: schemas.ShiftCreateIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    if payload.end_time == payload.start_time:
        raise HTTPException(status_code=422, detail="وقت بداية الوردية ونهايتها لا يجوز أن يتطابقا")
    shift = models.Shift(**payload.dict())
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@app.put("/api/shifts/{shift_id}", response_model=schemas.ShiftOut)
def update_shift(
    shift_id: int,
    payload: schemas.ShiftUpdateIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    shift = db.query(models.Shift).filter(models.Shift.id == shift_id).with_for_update().first()
    if shift is None:
        raise HTTPException(status_code=404, detail="الوردية غير موجودة")

    changes = payload.dict(exclude_unset=True)
    start_time = changes.get("start_time", shift.start_time)
    end_time = changes.get("end_time", shift.end_time)
    if end_time == start_time:
        raise HTTPException(status_code=422, detail="وقت بداية الوردية ونهايتها لا يجوز أن يتطابقا")
    for key, value in changes.items():
        setattr(shift, key, value)
    db.commit()
    db.refresh(shift)
    return shift


@app.delete("/api/shifts/{shift_id}")
def delete_shift(
    shift_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    shift = db.query(models.Shift).filter(models.Shift.id == shift_id).with_for_update().first()
    if shift is None:
        raise HTTPException(status_code=404, detail="الوردية غير موجودة")
    assignment = (
        db.query(models.EmployeeShiftAssignment)
        .filter(models.EmployeeShiftAssignment.shift_id == shift_id)
        .first()
    )
    if assignment:
        raise HTTPException(status_code=409, detail="لا يمكن حذف وردية مرتبطة بتكليف موظف")
    db.delete(shift)
    db.commit()
    return {"status": "success"}


@app.get("/api/employees", response_model=list[schemas.EmployeeOut])
def get_employees(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Employee)
    if is_active is not None:
        query = query.filter(_employee_active_column().is_(is_active))
    return [
        _employee_output(employee)
        for employee in query.order_by(_employee_name_column(), models.Employee.employee_id).all()
    ]


def _sync_employee_roster(att_db: Session, db: Session) -> dict:
    rows = att_db.execute(text(
        "SELECT PersonID, MAX(PersonName) AS PersonName "
        "FROM AttendanceRecordInfo "
        "WHERE PersonID IS NOT NULL AND PersonID <> '' "
        "GROUP BY PersonID"
    )).fetchall()
    created = 0
    updated = 0
    try:
        for employee_id, employee_name in rows:
            employee_id = str(employee_id).strip()
            if not employee_id:
                continue
            name = str(employee_name or employee_id).strip() or employee_id
            employee = db.query(models.Employee).filter(
                models.Employee.employee_id == employee_id
            ).first()
            if employee is None:
                db.add(models.Employee(employee_id=employee_id, name=name, active=True))
                created += 1
            elif employee.name != name:
                employee.name = name
                updated += 1
        db.commit()
    except database.SQLAlchemyError:
        db.rollback()
        raise
    return {"created": created, "updated": updated, "total": created + updated}


@app.post("/api/employees/sync")
def sync_employees(
    att_db: Session = Depends(get_attendance_db),
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    try:
        return _sync_employee_roster(att_db, db)
    except database.SQLAlchemyError as exc:
        logger.exception("Failed to synchronize employee roster from attendance database")
        raise HTTPException(
            status_code=503,
            detail="تعذر جلب الموظفين من قاعدة البصمة. تحقق من الاتصال وجدول AttendanceRecordInfo.",
        ) from exc


@app.post("/api/employees", response_model=schemas.EmployeeOut, status_code=201)
def create_employee(
    payload: schemas.EmployeeCreateIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    if db.query(models.Employee).filter(
        models.Employee.employee_id == payload.employee_id
    ).first():
        raise HTTPException(status_code=409, detail="الموظف مسجل بالفعل")
    employee = models.Employee(
        employee_id=payload.employee_id,
        **{
            ("name" if hasattr(models.Employee, "name") else "employee_name"): payload.name,
            ("active" if hasattr(models.Employee, "active") else "is_active"): payload.active,
        },
    )
    db.add(employee)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="الموظف مسجل بالفعل")
    db.refresh(employee)
    return _employee_output(employee)


@app.put("/api/employees/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(
    employee_id: str,
    payload: schemas.EmployeeUpdateIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .with_for_update()
        .first()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    for key, value in payload.dict(exclude_unset=True).items():
        model_key = (
            ("name" if hasattr(models.Employee, "name") else "employee_name")
            if key == "name"
            else ("active" if hasattr(models.Employee, "active") else "is_active")
        )
        setattr(employee, model_key, value)
    db.commit()
    db.refresh(employee)
    return _employee_output(employee)


@app.delete("/api/employees/{employee_id}")
@app.post("/api/employees/{employee_id}/deactivate")
def deactivate_employee(
    employee_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .with_for_update()
        .first()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    employee.active = False
    if hasattr(employee, "is_active"):
        try:
            employee.is_active = False
        except Exception:
            pass
    db.commit()
    db.refresh(employee)
    return {"status": "success", "employee": _employee_output(employee)}


@app.post("/api/employees/{employee_id}/activate")
def activate_employee(
    employee_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .with_for_update()
        .first()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    employee.active = True
    if hasattr(employee, "is_active"):
        try:
            employee.is_active = True
        except Exception:
            pass
    db.commit()
    db.refresh(employee)
    return {"status": "success", "employee": _employee_output(employee)}


def _assignment_output(assignment, shift=None):
    result = schemas.EmployeeShiftAssignmentOut.from_orm(assignment).dict()
    result["shift_name"] = shift.name if shift is not None else None
    return result


def _employee_name_column():
    return getattr(models.Employee, "employee_name", getattr(models.Employee, "name", None))


def _employee_active_column():
    return getattr(models.Employee, "is_active", getattr(models.Employee, "active", None))


def _employee_output(employee):
    return {
        "employee_id": employee.employee_id,
        "name": getattr(employee, "name", getattr(employee, "employee_name", "")),
        "active": bool(getattr(employee, "active", getattr(employee, "is_active", False))),
    }


@app.get(
    "/api/employee-shifts",
    response_model=list[schemas.EmployeeShiftAssignmentOut],
)
def get_employee_shift_assignments(
    employee_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.EmployeeShiftAssignment)
    if employee_id:
        query = query.filter(models.EmployeeShiftAssignment.employee_id == employee_id)
    assignments = query.order_by(
        models.EmployeeShiftAssignment.start_date.desc(),
        models.EmployeeShiftAssignment.id.desc(),
    ).all()
    shifts = {
        shift.id: shift
        for shift in db.query(models.Shift)
        .filter(models.Shift.id.in_({item.shift_id for item in assignments}))
        .all()
    } if assignments else {}
    return [_assignment_output(item, shifts.get(item.shift_id)) for item in assignments]


@app.post(
    "/api/employee-shifts",
    response_model=schemas.EmployeeShiftAssignmentOut,
    status_code=201,
)
def create_employee_shift_assignment(
    payload: schemas.EmployeeShiftAssignmentIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == payload.employee_id)
        .with_for_update()
        .first()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    shift = db.query(models.Shift).filter(models.Shift.id == payload.shift_id).first()
    if shift is None:
        raise HTTPException(status_code=404, detail="الوردية غير موجودة")

    assignments = (
        db.query(models.EmployeeShiftAssignment)
        .filter(models.EmployeeShiftAssignment.employee_id == payload.employee_id)
        .order_by(models.EmployeeShiftAssignment.start_date)
        .with_for_update()
        .all()
    )
    new_start, new_end = payload.start_date, payload.end_date
    if any(item.start_date >= new_start for item in assignments):
        raise HTTPException(status_code=409, detail="يوجد تكليف يبدأ في هذا التاريخ أو بعده")

    predecessor = None
    for item in assignments:
        item_end = item.end_date
        overlaps = (item_end is None or item_end >= new_start) and (
            new_end is None or item.start_date <= new_end
        )
        if not overlaps:
            continue
        if item_end is None and item.start_date < new_start:
            predecessor = item
        else:
            raise HTTPException(status_code=409, detail="فترة التكليف تتداخل مع تكليف سابق")

    if predecessor is not None:
        predecessor.end_date = new_start - timedelta(days=1)
    assignment = models.EmployeeShiftAssignment(
        employee_id=payload.employee_id,
        shift_id=payload.shift_id,
        start_date=new_start,
        end_date=new_end,
    )
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="تعارض في فترة تكليف الوردية")
    db.refresh(assignment)
    return _assignment_output(assignment, shift)


@app.delete("/api/employee-shifts/{assignment_id}")
def delete_employee_shift_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    assignment = (
        db.query(models.EmployeeShiftAssignment)
        .filter(models.EmployeeShiftAssignment.id == assignment_id)
        .with_for_update()
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="تكليف الوردية غير موجود")

    employee_id = assignment.employee_id

    latest_assignment = (
        db.query(models.EmployeeShiftAssignment)
        .filter(models.EmployeeShiftAssignment.employee_id == employee_id)
        .order_by(
            models.EmployeeShiftAssignment.start_date.desc(),
            models.EmployeeShiftAssignment.id.desc(),
        )
        .with_for_update()
        .first()
    )

    if latest_assignment and latest_assignment.id != assignment.id:
        raise HTTPException(
            status_code=400,
            detail="يمكن فقط حذف آخر تكليف وردية للموظف",
        )

    predecessor = (
        db.query(models.EmployeeShiftAssignment)
        .filter(
            models.EmployeeShiftAssignment.employee_id == employee_id,
            models.EmployeeShiftAssignment.id != assignment.id,
            models.EmployeeShiftAssignment.start_date <= assignment.start_date,
        )
        .order_by(
            models.EmployeeShiftAssignment.start_date.desc(),
            models.EmployeeShiftAssignment.id.desc(),
        )
        .with_for_update()
        .first()
    )

    if predecessor is not None:
        if (
            predecessor.end_date == assignment.start_date - timedelta(days=1)
            or predecessor.end_date is not None
        ):
            predecessor.end_date = None

    db.delete(assignment)
    db.commit()
    return {"status": "success"}


@app.get("/api/employee-branches", response_model=schemas.BranchPage)
def get_employee_branches(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
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
    today = timeutils.app_now().date()
    return {
        "items": [
            schemas.BranchRecordOut.from_orm(item).copy(
                update={
                    "is_current": item.start_date <= today
                    and (item.end_date is None or item.end_date >= today),
                    "is_future": item.start_date > today,
                }
            )
            for item in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/employee-branches")
def assign_employee_branch(
    payload: schemas.BranchTransferIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == payload.employee_id)
        .with_for_update()
        .first()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")

    employee_name = payload.employee_name
    if not employee_name or not str(employee_name).strip():
        employee_name = getattr(employee, "name", getattr(employee, "employee_name", None))
    else:
        employee_name = str(employee_name).strip()

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
        employee_name=employee_name,
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
    today = timeutils.app_now().date()
    return {
        "status": "success",
        "data": schemas.BranchRecordOut.from_orm(new_record).copy(
            update={
                "is_current": new_record.start_date <= today,
                "is_future": new_record.start_date > today,
            }
        ),
    }



@app.delete("/api/employee-branches/{history_id}")
def delete_employee_branch(
    history_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_authenticated_user),
):
    record = (
        db.query(models.EmployeeBranchHistory)
        .filter(models.EmployeeBranchHistory.id == history_id)
        .with_for_update()
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="سجل الفرع غير موجود")

    employee_id = record.employee_id

    latest_record = (
        db.query(models.EmployeeBranchHistory)
        .filter(models.EmployeeBranchHistory.employee_id == employee_id)
        .order_by(
            models.EmployeeBranchHistory.start_date.desc(),
            models.EmployeeBranchHistory.id.desc(),
        )
        .with_for_update()
        .first()
    )

    if latest_record and latest_record.id != record.id:
        raise HTTPException(
            status_code=400,
            detail="يمكن فقط حذف آخر سجل فرع للموظف",
        )

    predecessor = (
        db.query(models.EmployeeBranchHistory)
        .filter(
            models.EmployeeBranchHistory.employee_id == employee_id,
            models.EmployeeBranchHistory.id != record.id,
            models.EmployeeBranchHistory.start_date <= record.start_date,
        )
        .order_by(
            models.EmployeeBranchHistory.start_date.desc(),
            models.EmployeeBranchHistory.id.desc(),
        )
        .with_for_update()
        .first()
    )

    if predecessor is not None:
        predecessor.end_date = None

    db.delete(record)
    db.commit()
    return {"status": "success"}
