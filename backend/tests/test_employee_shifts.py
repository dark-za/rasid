from datetime import date, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
import models
import schemas
from database import Base
import timeutils


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'employee-shifts.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _employee(employee_id, name=None):
    return schemas.EmployeeCreateIn(
        employee_id=employee_id,
        name=name or f"موظف {employee_id}",
        active=True,
    )


def _shift(name, start, end, *, lateness_mode="after_grace", grace=15):
    return schemas.ShiftCreateIn(
        name=name,
        start_time=start,
        end_time=end,
        grace_period_minutes=grace,
        lateness_mode=lateness_mode,
        color="#123ABC",
    )


def _assignment(employee_id, shift_id, start, end=None):
    return schemas.EmployeeShiftAssignmentIn(
        employee_id=employee_id,
        shift_id=shift_id,
        start_date=start,
        end_date=end,
    )


def _setup(db_session):
    employee = main.create_employee(_employee("16"), db_session, None)
    first_shift = main.create_shift(_shift("صباحية", "08:00", "17:00"), db_session, None)
    second_shift = main.create_shift(
        _shift("ليلية", "22:00", "06:00", lateness_mode="from_start"),
        db_session,
        None,
    )
    return employee, first_shift, second_shift


def test_employee_shift_roster_uses_canonical_collection_route():
    routes = {
        (method, route.path)
        for route in main.app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }

    assert ("GET", "/api/employee-shifts") in routes
    assert ("POST", "/api/employee-shifts") in routes
    assert not any(path == "/api/employee-shift-assignments" for _, path in routes)


def test_employee_and_assignment_roster_endpoints(db_session):
    _setup(db_session)
    assigned = main.create_employee_shift_assignment(
        _assignment("16", 1, date(2026, 10, 1)), db_session, None
    )

    employees = main.get_employees(is_active=True, db=db_session)
    assignments = main.get_employee_shift_assignments(
        employee_id="16", db=db_session
    )

    assert [item["employee_id"] for item in employees] == ["16"]
    assert employees[0]["name"] == "موظف 16"
    assert employees[0]["active"] is True
    assert assigned["shift_name"] == "صباحية"
    assert len(assignments) == 1
    assert assignments[0]["shift_name"] == "صباحية"
    assert assignments[0]["end_date"] is None


def test_effective_assignment_transition_is_inclusive_and_employee_scoped(db_session):
    _setup(db_session)
    main.create_employee(_employee("22"), db_session, None)
    main.create_employee_shift_assignment(
        _assignment("16", 1, date(2026, 10, 1)), db_session, None
    )
    main.create_employee_shift_assignment(
        _assignment("16", 2, date(2026, 11, 1)), db_session, None
    )
    main.create_employee_shift_assignment(
        _assignment("22", 1, date(2026, 10, 5)), db_session, None
    )

    assignments = (
        db_session.query(models.EmployeeShiftAssignment)
        .filter_by(employee_id="16")
        .order_by(models.EmployeeShiftAssignment.start_date)
        .all()
    )
    assert [(item.start_date, item.end_date) for item in assignments] == [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), None),
    ]
    assert main._assignment_for_date(assignments, "16", date(2026, 10, 31)).shift_id == 1
    assert main._assignment_for_date(assignments, "16", date(2026, 11, 1)).shift_id == 2
    assert main._assignment_for_date(assignments, "22", date(2026, 11, 1)) is None


@pytest.mark.parametrize(
    "start",
    [date(2026, 10, 31), date(2026, 11, 1)],
)
def test_assignment_rejects_overlapping_and_same_start_boundaries(db_session, start):
    _setup(db_session)
    main.create_employee_shift_assignment(
        _assignment("16", 1, date(2026, 10, 1)), db_session, None
    )
    main.create_employee_shift_assignment(
        _assignment("16", 2, date(2026, 11, 1)), db_session, None
    )

    with pytest.raises(HTTPException) as exc:
        main.create_employee_shift_assignment(
            _assignment("16", 1, start), db_session, None
        )
    assert exc.value.status_code == 409


def test_assignment_end_must_not_precede_start():
    with pytest.raises(ValidationError):
        _assignment("16", 1, date(2026, 10, 2), date(2026, 10, 1))


def test_shift_lateness_modes_and_overnight_start_date_attribution(db_session):
    _setup(db_session)
    from_start_shift = main.create_shift(
        _shift("صباحية من وقت البداية", "08:00", "17:00", lateness_mode="from_start"),
        db_session,
        None,
    )
    assignments = [
        models.EmployeeShiftAssignment(
            id=1,
            employee_id="16",
            shift_id=1,
            start_date=date(2026, 10, 24),
        )
    ]
    shifts = {
        1: db_session.query(models.Shift).filter_by(name="صباحية").one(),
        2: db_session.query(models.Shift).filter_by(name="ليلية").one(),
        from_start_shift.id: from_start_shift,
    }
    punch = (
        datetime(2026, 10, 24, 8, 10, tzinfo=timeutils.app_tz()),
        "16",
        "موظف 16",
        0,
        "جهاز",
    )
    grace_based = main._late_events(
        [punch], assignments, shifts, {"16"}, date(2026, 10, 24), date(2026, 10, 24)
    )
    assignments[0].shift_id = from_start_shift.id
    from_start = main._late_events(
        [punch], assignments, shifts, {"16"}, date(2026, 10, 24), date(2026, 10, 24)
    )
    assignments[0].shift_id = 2
    overnight_punch = (
        datetime(2026, 10, 25, 0, 20, tzinfo=timeutils.app_tz()),
        "16",
        "موظف 16",
        0,
        "جهاز",
    )
    start_based = main._late_events(
        [overnight_punch],
        assignments,
        shifts,
        {"16"},
        date(2026, 10, 24),
        date(2026, 10, 24),
    )

    assert grace_based == []
    assert from_start[0]["late_minutes"] == 10
    assert start_based[0]["late_minutes"] == 140
    assert start_based[0]["shift_date"] == date(2026, 10, 24)


def test_unassigned_employee_is_not_classified_as_late_or_absent(db_session):
    _setup(db_session)
    shift = db_session.query(models.Shift).filter_by(name="صباحية").one()
    punch = (
        datetime(2026, 10, 24, 9, 0, tzinfo=timeutils.app_tz()),
        "16",
        "موظف 16",
        0,
        "جهاز",
    )

    events = main._late_events(
        [punch],
        [],
        {shift.id: shift},
        {"16"},
        date(2026, 10, 24),
        date(2026, 10, 24),
    )

    assert events == []


def test_future_branch_history_is_marked_future_not_current(db_session, monkeypatch):
    _setup(db_session)
    monkeypatch.setattr(
        timeutils,
        "app_now",
        lambda: datetime(2026, 10, 24, 12, 0, tzinfo=timeutils.app_tz()),
    )
    main.assign_employee_branch(
        schemas.BranchTransferIn(
            employee_id="16",
            branch_name="فرع قادم",
            start_date=date(2026, 11, 1),
        ),
        db_session,
        None,
    )

    page = main.get_employee_branches(limit=50, offset=0, db=db_session)

    assert page["items"][0].is_future is True
    assert page["items"][0].is_current is False


def test_delete_latest_employee_shift_assignment_reopens_predecessor(db_session):
    employee, shift1, shift2 = _setup(db_session)
    first = main.create_employee_shift_assignment(
        _assignment("16", shift1.id, date(2026, 10, 1)),
        db_session,
        None,
    )
    second = main.create_employee_shift_assignment(
        _assignment("16", shift2.id, date(2026, 10, 15)),
        db_session,
        None,
    )

    first_saved = db_session.get(models.EmployeeShiftAssignment, first["id"])
    assert first_saved.end_date == date(2026, 10, 14)

    res = main.delete_employee_shift_assignment(second["id"], db_session, None)
    assert res == {"status": "success"}

    db_session.expire_all()
    assert db_session.get(models.EmployeeShiftAssignment, second["id"]) is None
    reopened = db_session.get(models.EmployeeShiftAssignment, first["id"])
    assert reopened is not None
    assert reopened.end_date is None


def test_delete_employee_shift_assignment_rejects_non_latest_and_missing(db_session):
    employee, shift1, shift2 = _setup(db_session)
    first = main.create_employee_shift_assignment(
        _assignment("16", shift1.id, date(2026, 10, 1)),
        db_session,
        None,
    )
    second = main.create_employee_shift_assignment(
        _assignment("16", shift2.id, date(2026, 10, 15)),
        db_session,
        None,
    )

    # Trying to delete first when second exists -> rejects with 400
    with pytest.raises(HTTPException) as exc:
        main.delete_employee_shift_assignment(first["id"], db_session, None)
    assert exc.value.status_code == 400
    assert "يمكن فقط حذف آخر تكليف وردية للموظف" in exc.value.detail

    # Trying to delete non-existent assignment id -> rejects with 404
    with pytest.raises(HTTPException) as exc404:
        main.delete_employee_shift_assignment(99999, db_session, None)
    assert exc404.value.status_code == 404
