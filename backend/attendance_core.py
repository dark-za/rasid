"""منطق معالجة بصمات اليوم — دوال نقية لا تعتمد على قاعدة البيانات.

تُستخدم من endpoint الحضور وتُختبر مباشرة في tests/test_attendance_core.py.
"""
from datetime import datetime, time, timedelta
from typing import Any, Iterable, Optional

import timeutils

_LOG_FORMAT = "%Y-%m-%d %H:%M:%S"


def process_attendance_rows(
    rows: Iterable[tuple],
    *,
    shift_start: time,
    grace_minutes: int,
    debounce_minutes: float,
    local_mode: Optional[bool] = None,
) -> dict[str, list]:
    """يفلتر التبصيم المتكرر ويحسب المتأخرين.

    الصفوف المدخلة: (person_id, person_name, ts_ms, state, device)
    مرتّبة تصاعدياً بالوقت. تُرجع {"logs": [...], "late_employees": [...]}
    بتوقيت التطبيق.
    """
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
    first_arrival: dict[str, datetime] = {}
    employee_names: dict[str, Any] = {}

    for punch_time, employee_id, person_name, state, device in converted:
        previous = last_punch.get(employee_id)
        if previous is not None and (punch_time - previous) < debounce:
            continue

        last_punch[employee_id] = punch_time
        if employee_id not in first_arrival:
            first_arrival[employee_id] = punch_time
            employee_names[employee_id] = person_name

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
    for employee_id, punch in first_arrival.items():
        minutes = timeutils.late_minutes(punch, shift_start, grace_minutes)
        if minutes > 0:
            late_employees.append(
                {
                    "employee_id": employee_id,
                    "employee_name": employee_names.get(employee_id),
                    "arrival_time": punch.strftime(_LOG_FORMAT),
                    "late_minutes": minutes,
                }
            )

    return {"logs": filtered_logs, "late_employees": late_employees}
