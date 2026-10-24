from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

import attendance_core
import timeutils

RIYADH = ZoneInfo("Asia/Riyadh")


def _ms(dt: datetime) -> int:
    """تحويل وقت محلي إلى التنسيق المخزَّن (وضع محلي — الافتراضي)."""
    return timeutils.local_to_epoch_ms(dt, local_mode=True)


def _rows(*punches):
    """بناء صفوف بصمات: (employee_id, name, ts_ms, state, device)."""
    return [
        (emp_id, name, _ms(dt), 0, "جهاز-1")
        for dt, emp_id, name in punches
    ]


def _process(rows, grace=15, shift=time(8, 0), debounce=5.0):
    return attendance_core.process_attendance_rows(
        rows,
        shift_start=shift,
        grace_minutes=grace,
        debounce_minutes=debounce,
        local_mode=True,
    )


# ---------------------------------------------------------------------------
# فلترة التبصيم المتكرر (Debounce)
# ---------------------------------------------------------------------------

def test_two_punches_within_debounce_keep_one():
    rows = _rows(
        (datetime(2026, 10, 24, 8, 0), "16", "سالم"),
        (datetime(2026, 10, 24, 8, 3), "16", "سالم"),  # بعد 3 دقائق
    )
    result = _process(rows)
    assert len(result["logs"]) == 1
    assert result["logs"][0]["check_time"] == "2026-10-24 08:00:00"


def test_two_punches_beyond_debounce_keep_both():
    rows = _rows(
        (datetime(2026, 10, 24, 8, 0), "16", "سالم"),
        (datetime(2026, 10, 24, 8, 6), "16", "سالم"),  # بعد 6 دقائق
    )
    assert len(_process(rows)["logs"]) == 2


def test_debounce_is_per_employee():
    rows = _rows(
        (datetime(2026, 10, 24, 8, 0), "16", "سالم"),
        (datetime(2026, 10, 24, 8, 1), "71", "عبدالرحمن"),
    )
    assert len(_process(rows)["logs"]) == 2


# ---------------------------------------------------------------------------
# المتأخرون
# ---------------------------------------------------------------------------

def test_late_employee_reported_with_name_and_minutes():
    rows = _rows((datetime(2026, 10, 24, 8, 20), "16", "سالم"))
    result = _process(rows)
    assert result["late_employees"] == [
        {
            "employee_id": "16",
            "employee_name": "سالم",
            "arrival_time": "2026-10-24 08:20:00",
            "late_minutes": 5,
        }
    ]


def test_on_time_employee_not_reported_late():
    rows = _rows((datetime(2026, 10, 24, 7, 59), "16", "سالم"))
    assert _process(rows)["late_employees"] == []


@pytest.mark.parametrize(
    ("grace", "expected_late_minutes"),
    [(0, 10), (15, 0)],
)
def test_lateness_respects_the_selected_shift_grace_mode(grace, expected_late_minutes):
    rows = _rows((datetime(2026, 10, 24, 8, 10), "16", "سالم"))
    late = _process(rows, grace=grace)["late_employees"]
    assert [employee["late_minutes"] for employee in late] == (
        [expected_late_minutes] if expected_late_minutes else []
    )


def test_lateness_uses_first_punch_only():
    rows = _rows(
        (datetime(2026, 10, 24, 7, 55), "16", "سالم"),   # الحضور الأول في الوقت
        (datetime(2026, 10, 24, 8, 30), "16", "سالم"),   # خروج/بصمة لاحقة
    )
    assert _process(rows)["late_employees"] == []


def test_after_midnight_punch_not_late():
    rows = _rows((datetime(2026, 10, 24, 0, 12), "16", "سالم"))
    assert _process(rows)["late_employees"] == []


# ---------------------------------------------------------------------------
# صفوف تالفة
# ---------------------------------------------------------------------------

def test_invalid_timestamp_rows_are_skipped():
    rows = [
        ("16", "سالم", None, 0, "جهاز-1"),
        ("16", "سالم", "ليس-رقماً", 0, "جهاز-1"),
        ("16", "سالم", _ms(datetime(2026, 10, 24, 8, 20)), 0, "جهاز-1"),
    ]
    result = _process(rows)
    assert len(result["logs"]) == 1
    assert len(result["late_employees"]) == 1


def test_unknown_employee_id_when_missing():
    rows = [(None, None, _ms(datetime(2026, 10, 24, 7, 0)), 0, "جهاز-1")]
    result = _process(rows)
    assert result["logs"][0]["employee_id"] == "Unknown"
    assert result["late_employees"] == []


# ---------------------------------------------------------------------------
# الحقول المحفوظة والترتيب
# ---------------------------------------------------------------------------

def test_logs_keep_name_device_state_and_order():
    rows = _rows(
        (datetime(2026, 10, 24, 9, 0), "71", "عبدالرحمن"),
        (datetime(2026, 10, 24, 7, 0), "16", "سالم"),
    )
    rows[0] = (rows[0][0], rows[0][1], rows[0][2], 11, "جهاز-2")
    result = _process(rows)
    logs = result["logs"]
    assert [log["employee_id"] for log in logs] == ["16", "71"]  # حسب الوقت
    assert logs[1]["state"] == 11
    assert logs[1]["device"] == "جهاز-2"
    assert logs[1]["employee_name"] == "عبدالرحمن"


def test_employee_summary_aggregates_first_last_and_count():
    rows = _rows(
        (datetime(2026, 10, 24, 7, 50), '16', 'سالم'),
        (datetime(2026, 10, 24, 12, 30), '16', 'سالم'),
        (datetime(2026, 10, 24, 17, 5), '16', 'سالم'),
        (datetime(2026, 10, 24, 8, 25), '71', 'عبدالرحمن'),
    )
    result = _process(rows, grace=15)
    summary = {item['employee_id']: item for item in result['employee_summary']}

    assert '16' in summary
    assert summary['16']['first_punch'] == '2026-10-24 07:50:00'
    assert summary['16']['last_punch'] == '2026-10-24 17:05:00'
    assert summary['16']['punch_count'] == 3
    assert summary['16']['is_late'] is False
    assert summary['16']['late_minutes'] == 0

    assert '71' in summary
    assert summary['71']['first_punch'] == '2026-10-24 08:25:00'
    assert summary['71']['last_punch'] == '2026-10-24 08:25:00'
    assert summary['71']['punch_count'] == 1
    assert summary['71']['is_late'] is True
    assert summary['71']['late_minutes'] == 10
