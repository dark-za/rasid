from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main
import models
import timeutils


@pytest.mark.parametrize("requested", [date(2026, 1, 1), date(2026, 10, 25)])
def test_attendance_search_rejects_dates_outside_supported_window(monkeypatch, requested):
    monkeypatch.setattr(
        timeutils,
        "app_now",
        lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timeutils.app_tz("Asia/Riyadh")),
    )
    with pytest.raises(HTTPException) as exc:
        main.get_attendance(requested, None, None, None)
    assert exc.value.status_code == 422


def test_attendance_search_accepts_the_oldest_included_date(monkeypatch):
    monkeypatch.setattr(
        timeutils,
        "app_now",
        lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timeutils.app_tz("Asia/Riyadh")),
    )
    class AppDb:
        def query(self, _model):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return SimpleNamespace(start_time="08:00", grace_period_minutes=15)

    class Result:
        def fetchall(self):
            return []

    class AttendanceDb:
        def execute(self, _query, params):
            self.params = params
            return Result()

    attendance_db = AttendanceDb()
    result = main.get_attendance(
        date(2026, 7, 26), "16", AppDb(), attendance_db
    )
    assert result["date"] == "2026-07-26"
    assert attendance_db.params["employee_id"] == "16"


def test_late_report_aggregates_late_days_and_minutes():
    report = main.aggregate_late_report([
        {"late_employees": [
            {"employee_id": "16", "employee_name": "سالم", "late_minutes": 10}
        ]},
        {"late_employees": [
            {"employee_id": "16", "employee_name": "سالم", "late_minutes": 20},
            {"employee_id": "22", "employee_name": "نورة", "late_minutes": 5},
        ]},
        {"late_employees": []},
    ])
    assert report == [
        {
            "employee_id": "16",
            "employee_name": "سالم",
            "late_days": 2,
            "total_late_minutes": 30,
            "average_late_minutes": 15.0,
        },
        {
            "employee_id": "22",
            "employee_name": "نورة",
            "late_days": 1,
            "total_late_minutes": 5,
            "average_late_minutes": 5.0,
        },
    ]


class _ReportAppDb:
    def query(self, model):
        assert model is models.Shift
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return SimpleNamespace(
            id=1,
            name="صباحية",
            start_time="08:00",
            grace_period_minutes=15,
        )


def test_late_report_scans_exactly_the_requested_inclusive_range(monkeypatch):
    monkeypatch.setattr(
        timeutils,
        "app_now",
        lambda: datetime(2026, 10, 31, 12, 0, tzinfo=timeutils.app_tz("Asia/Riyadh")),
    )
    reads = []

    def read_range(_att_db, start, end, employee_id=None):
        reads.append((start, end, employee_id))
        return []

    monkeypatch.setattr(main, "_read_attendance_range", read_range)
    monkeypatch.setattr(main, "_shift_assignment_context", lambda *_args: ([], {}, None))
    monkeypatch.setattr(main, "_late_events", lambda *_args: [])
    result = main.get_late_report(
        date(2026, 10, 1), date(2026, 10, 31), _ReportAppDb(), object()
    )

    assert result["from_date"] == "2026-10-01"
    assert result["to_date"] == "2026-10-31"
    assert reads == [(date(2026, 9, 30), date(2026, 10, 31), None)]


def test_late_report_rejects_ranges_that_would_exceed_31_days(monkeypatch):
    monkeypatch.setattr(
        timeutils,
        "app_now",
        lambda: datetime(2026, 10, 31, 12, 0, tzinfo=timeutils.app_tz("Asia/Riyadh")),
    )
    reads = []
    monkeypatch.setattr(
        main, "_read_attendance_range", lambda *_args: reads.append(_args)
    )
    with pytest.raises(HTTPException) as exc:
        main.get_late_report(
            date(2026, 9, 30), date(2026, 10, 31), _ReportAppDb(), object()
        )
    assert exc.value.status_code == 422
    assert reads == []


def test_liveness_response_exposes_no_configuration_or_database_details(monkeypatch):
    monkeypatch.setenv("RASID_SESSION_SECRET", "must-not-be-exposed")
    result = main.health_live()

    assert result == {"status": "live"}
    assert "must-not-be-exposed" not in repr(result)
    assert "database" not in {key.lower() for key in result}


def test_readiness_response_is_generic_for_success_and_failure():
    class HealthyDb:
        def execute(self, _query):
            return 1

    class FailedDb:
        def execute(self, _query):
            raise RuntimeError("sensitive backend diagnostic")

    assert main.health_ready(HealthyDb(), HealthyDb()) == {"status": "ready"}

    with pytest.raises(HTTPException) as exc:
        main.health_ready(FailedDb(), HealthyDb())
    assert exc.value.status_code == 503
    assert "sensitive backend diagnostic" not in exc.value.detail


def test_attendance_daily_summary_and_unpunched_employees():
    class MockEmployee:
        def __init__(self, emp_id, name):
            self.employee_id = emp_id
            self.name = name
            self.active = True

    class MockShift:
        def __init__(self, s_id, name):
            self.id = s_id
            self.name = name
            self.start_time = "08:00"
            self.end_time = "17:00"
            self.grace_period_minutes = 15
            self.lateness_mode = "after_grace"

    class MockAssignment:
        def __init__(self, emp_id, s_id):
            self.employee_id = emp_id
            self.shift_id = s_id
            self.start_date = date(2026, 10, 1)
            self.end_date = None
            self.id = 1

    emp1 = MockEmployee("101", "أحمد")
    emp2 = MockEmployee("102", "خالد")
    shift1 = MockShift(1, "صباحية")
    assign1 = MockAssignment("101", 1)
    assign2 = MockAssignment("102", 1)

    class AppDb:
        def query(self, model):
            self.model = model
            return self
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def first(self):
            return shift1
        def all(self):
            if self.model is models.Employee:
                return [emp1, emp2]
            if self.model is models.Shift:
                return [shift1]
            if self.model is models.EmployeeShiftAssignment:
                return [assign1, assign2]
            return []

    p1 = timeutils.local_to_epoch_ms(datetime(2026, 10, 24, 8, 5, tzinfo=timeutils.app_tz()))
    p2 = timeutils.local_to_epoch_ms(datetime(2026, 10, 24, 17, 2, tzinfo=timeutils.app_tz()))

    class AttDb:
        def execute(self, *args, **kwargs):
            class Res:
                def fetchall(self):
                    return [
                        ("101", "أحمد", p1, 0, "جهاز-1"),
                        ("101", "أحمد", p2, 0, "جهاز-1"),
                    ]
            return Res()

    result = main._attendance_for_date(date(2026, 10, 24), AppDb(), AttDb())

    assert len(result["employee_summary"]) == 1
    summary1 = result["employee_summary"][0]
    assert summary1["employee_id"] == "101"
    assert summary1["first_punch"] == "2026-10-24 08:05:00"
    assert summary1["last_punch"] == "2026-10-24 17:02:00"
    assert summary1["punch_count"] == 2
    assert summary1["is_late"] is False

    assert len(result["unpunched_employees"]) == 1
    unpunched = result["unpunched_employees"][0]
    assert unpunched["employee_id"] == "102"
    assert unpunched["employee_name"] == "خالد"
    assert unpunched["shift_name"] == "صباحية"
    assert unpunched["status"] == "لم يسجل بصمة بعد"


def test_overnight_late_shift_attribution_does_not_duplicate_across_days():
    class MockShift:
        def __init__(self):
            self.id = 2
            self.name = "ليلية"
            self.start_time = "22:00"
            self.end_time = "06:00"
            self.grace_period_minutes = 15
            self.lateness_mode = "after_grace"

    class MockAssignment:
        def __init__(self):
            self.employee_id = "16"
            self.shift_id = 2
            self.start_date = date(2026, 10, 20)
            self.end_date = None
            self.id = 1

    class MockEmployee:
        def __init__(self):
            self.employee_id = '16'
            self.name = 'سالم'
            self.active = True

    shift = MockShift()
    assign = MockAssignment()
    emp = MockEmployee()

    class AppDb:
        def query(self, model):
            self.model = model
            return self
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def first(self):
            return shift
        def all(self):
            if self.model is models.Employee:
                return [emp]
            if self.model is models.Shift:
                return [shift]
            if self.model is models.EmployeeShiftAssignment:
                return [assign]
            return []

    # Employee 16 arrived late at 00:30 on 2026-10-25 for overnight shift of 2026-10-24
    p = timeutils.local_to_epoch_ms(datetime(2026, 10, 25, 0, 30, tzinfo=timeutils.app_tz()))

    class AttDb:
        def execute(self, *args, **kwargs):
            class Res:
                def fetchall(self):
                    return [("16", "سالم", p, 0, "جهاز-1")]
            return Res()

    # Query 2026-10-24 (shift start day): should include the late employee
    res_24 = main._attendance_for_date(date(2026, 10, 24), AppDb(), AttDb())
    assert len(res_24["late_employees"]) == 1
    assert res_24["late_employees"][0]["employee_id"] == "16"
    assert res_24["late_employees"][0]["shift_date"] == "2026-10-24"

    # Query 2026-10-25 (next day): should NOT include employee 16 from yesterday's overnight shift
    res_25 = main._attendance_for_date(date(2026, 10, 25), AppDb(), AttDb())
    assert len(res_25["late_employees"]) == 0
