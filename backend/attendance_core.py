"""منطق معالجة بصمات اليوم — دوال نقية لا تعتمد على قاعدة البيانات.

تُستخدم من endpoint الحضور وتُختبر مباشرة في tests/test_attendance_core.py.
"""
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Optional

import timeutils

_LOG_FORMAT = "%Y-%m-%d %H:%M:%S"
LatenessMode = timeutils.LatenessMode


def build_employee_summary(
    logs: Iterable[dict],
    late_employees: Optional[Iterable[dict]] = None,
) -> list[dict]:
    """ينشئ ملخصاً لكل موظف حضر: أول بصمة، آخر بصمة، عدد البصمات، وتفاصيل التأخير."""
    late_map: dict[str, dict] = {}
    if late_employees:
        for item in late_employees:
            late_map[str(item.get("employee_id"))] = item

    grouped: dict[str, list[dict]] = {}
    for log in logs:
        grouped.setdefault(str(log.get("employee_id")), []).append(log)

    summary = []
    for emp_id, emp_logs in grouped.items():
        emp_logs.sort(key=lambda x: x["check_time"])
        late_info = late_map.get(emp_id)
        is_late = late_info is not None and late_info.get("late_minutes", 0) > 0
        summary.append(
            {
                "employee_id": emp_id,
                "employee_name": emp_logs[0].get("employee_name"),
                "first_punch": emp_logs[0]["check_time"],
                "last_punch": emp_logs[-1]["check_time"],
                "punch_count": len(emp_logs),
                "is_late": is_late,
                "late_minutes": late_info.get("late_minutes", 0) if late_info else 0,
                "shift_name": late_info.get("shift_name") if late_info else None,
            }
        )
    return summary


def process_attendance_rows(
    rows: Iterable[tuple],
    *,
    shift_start: time,
    grace_minutes: int,
    debounce_minutes: float,
    local_mode: Optional[bool] = None,
    shift_end: Optional[time] = None,
    lateness_mode: LatenessMode = "after_grace",
) -> dict[str, list]:
    """يفلتر التبصيم المتكرر ويحسب المتأخرين.

    الصفوف المدخلة: (person_id, person_name, ts_ms, state, device)
    مرتّبة تصاعدياً بالوقت. تُرجع {"logs": [...], "late_employees": [...]}
    بتوقيت التطبيق. عند تمرير shift_end تُنسب بصمات ما بعد منتصف الليل قبل
    نهاية الشيفت الليلي إلى يوم بدايته. حذف shift_end يحافظ على سلوك النداء القديم.
    """
    if lateness_mode not in ("after_grace", "from_start"):
        raise ValueError(f"unsupported lateness_mode: {lateness_mode!r}")
    if not isinstance(grace_minutes, int) or isinstance(grace_minutes, bool):
        raise TypeError("grace_minutes must be an integer")
    if grace_minutes < 0:
        raise ValueError("grace_minutes must be non-negative")
    if not isinstance(shift_start, time):
        raise TypeError("shift_start must be a datetime.time value")
    if shift_end is not None:
        if not isinstance(shift_end, time):
            raise TypeError("shift_end must be a datetime.time value")
        if shift_end == shift_start:
            raise ValueError("shift_end must differ from shift_start")

    debounce = timedelta(minutes=debounce_minutes)
    converted: list[tuple] = []

    for person_id, person_name, ts_ms, state, device in rows:
        if ts_ms is None:
            continue
        try:
            punch_time = timeutils.epoch_ms_to_local(int(ts_ms), local_mode)
        except (TypeError, ValueError, OSError, OverflowError):
            # صف بوقت تالف — نتجاهله كما كان سلوك النظام سابقاً
            continue
        converted.append(
            (punch_time, str(person_id or "Unknown"), person_name, state, device)
        )

    # ترتيب زمني مضمون حتى لو جاءت الصفوف غير مرتّبة (يضبط أيضاً منطق الـ debounce)
    converted.sort(key=lambda item: item[0])

    filtered_logs: list[dict] = []
    last_punch: dict[str, datetime] = {}
    first_arrival: dict[tuple[str, date | None], datetime] = {}
    employee_names: dict[tuple[str, date | None], Any] = {}

    for punch_time, employee_id, person_name, state, device in converted:
        previous = last_punch.get(employee_id)
        if previous is not None and (punch_time - previous) < debounce:
            continue

        last_punch[employee_id] = punch_time
        attendance_day: date | None = None
        if shift_end is not None:
            attendance_day = punch_time.date()
            if shift_end < shift_start and punch_time.time() < shift_end:
                attendance_day -= timedelta(days=1)
        arrival_key = (employee_id, attendance_day)
        if arrival_key not in first_arrival:
            first_arrival[arrival_key] = punch_time
            employee_names[arrival_key] = person_name

        filtered_logs.append(
            {
                "employee_id": employee_id,
                "employee_name": person_name,
                "check_time": punch_time.strftime(_LOG_FORMAT),
                "device": device,
                "state": state,
            }
        )

    late_employees = []
    for (employee_id, attendance_day), punch in first_arrival.items():
        minutes = timeutils.late_minutes(
            punch,
            shift_start,
            grace_minutes,
            lateness_mode=lateness_mode,
            shift_date=attendance_day,
        )
        if minutes > 0:
            late_employees.append(
                {
                    "employee_id": employee_id,
                    "employee_name": employee_names.get((employee_id, attendance_day)),
                    "arrival_time": punch.strftime(_LOG_FORMAT),
                    "late_minutes": minutes,
                }
            )

    employee_summary = build_employee_summary(filtered_logs, late_employees)
    return {
        "logs": filtered_logs,
        "late_employees": late_employees,
        "employee_summary": employee_summary,
    }
