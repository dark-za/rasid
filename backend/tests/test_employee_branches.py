from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
import models
import schemas
from database import Base


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'branches.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(models.Employee(employee_id="16", name="موظف 16", active=True))
        session.add(models.Employee(employee_id="22", name="موظف 22", active=True))
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def _assignment(employee_id, branch_name, start_date, employee_name=None):
    return schemas.BranchTransferIn(
        employee_id=employee_id,
        employee_name=employee_name or f"موظف {employee_id}",
        branch_name=branch_name,
        start_date=start_date,
    )


def test_employee_branch_changes_form_inclusive_non_overlapping_periods(db_session):
    first = main.assign_employee_branch(
        _assignment("16", "الفرع الأول", date(2026, 10, 1)), db_session, None
    )["data"]
    second = main.assign_employee_branch(
        _assignment("16", "الفرع الثاني", date(2026, 10, 5)), db_session, None
    )["data"]
    other_employee = main.assign_employee_branch(
        _assignment("22", "فرع مستقل", date(2026, 10, 3)), db_session, None
    )["data"]

    first_saved = db_session.get(models.EmployeeBranchHistory, first.id)
    assert (first_saved.start_date, first_saved.end_date) == (
        date(2026, 10, 1),
        date(2026, 10, 4),
    )
    assert (second.start_date, second.end_date) == (date(2026, 10, 5), None)
    assert (other_employee.employee_id, other_employee.end_date) == ("22", None)


def test_employee_branch_change_rejects_same_or_earlier_start_boundary(db_session):
    main.assign_employee_branch(
        _assignment("16", "الفرع الأول", date(2026, 10, 1)), db_session, None
    )
    main.assign_employee_branch(
        _assignment("16", "الفرع الثاني", date(2026, 10, 5)), db_session, None
    )

    for boundary in (date(2026, 10, 4), date(2026, 10, 5)):
        with pytest.raises(HTTPException) as exc:
            main.assign_employee_branch(
                _assignment("16", "فرع مكرر", boundary), db_session, None
            )
        assert exc.value.status_code == 409


def test_future_branch_transition_preserves_assignment_until_day_before_start(db_session):
    main.assign_employee_branch(
        _assignment("16", "الفرع الحالي", date(2026, 10, 1)), db_session, None
    )

    future = main.assign_employee_branch(
        _assignment("16", "الفرع المستقبلي", date(2026, 11, 1)), db_session, None
    )["data"]
    history = (
        db_session.query(models.EmployeeBranchHistory)
        .filter_by(employee_id="16")
        .order_by(models.EmployeeBranchHistory.start_date)
        .all()
    )

    assert [(row.start_date, row.end_date) for row in history] == [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), None),
    ]
    assert future.branch_name == "الفرع المستقبلي"


def test_employee_branch_roster_endpoint_returns_paginated_history(db_session):
    main.assign_employee_branch(
        _assignment("16", "الفرع الأول", date(2026, 10, 1)), db_session, None
    )
    main.assign_employee_branch(
        _assignment("22", "الفرع الثاني", date(2026, 10, 2)), db_session, None
    )

    page = main.get_employee_branches(limit=1, offset=0, db=db_session)

    assert page["total"] == 2
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert len(page["items"]) == 1
    assert page["items"][0].employee_id == "22"


def test_assign_branch_rejects_missing_employee(db_session):
    with pytest.raises(HTTPException) as exc:
        main.assign_employee_branch(
            schemas.BranchTransferIn(
                employee_id="999_not_found",
                branch_name="فرع غير معروف",
                start_date=date(2026, 10, 1),
            ),
            db_session,
            None,
        )
    assert exc.value.status_code == 404
    assert "الموظف غير موجود" in exc.value.detail


def test_assign_branch_auto_populates_employee_name(db_session):
    res = main.assign_employee_branch(
        schemas.BranchTransferIn(
            employee_id="16",
            employee_name=None,
            branch_name="فرع تلقائي الاسم",
            start_date=date(2026, 10, 1),
        ),
        db_session,
        None,
    )
    assert res["data"].employee_name == "موظف 16"
    record = db_session.get(models.EmployeeBranchHistory, res["data"].id)
    assert record.employee_name == "موظف 16"


def test_delete_latest_employee_branch_reopens_predecessor(db_session):
    first = main.assign_employee_branch(
        _assignment("16", "الفرع الأول", date(2026, 10, 1)), db_session, None
    )["data"]
    second = main.assign_employee_branch(
        _assignment("16", "الفرع الثاني", date(2026, 10, 10)), db_session, None
    )["data"]

    first_saved = db_session.get(models.EmployeeBranchHistory, first.id)
    assert first_saved.end_date == date(2026, 10, 9)

    delete_res = main.delete_employee_branch(second.id, db_session, None)
    assert delete_res == {"status": "success"}

    db_session.expire_all()
    assert db_session.get(models.EmployeeBranchHistory, second.id) is None
    reopened = db_session.get(models.EmployeeBranchHistory, first.id)
    assert reopened is not None
    assert reopened.end_date is None


def test_delete_employee_branch_rejects_non_latest_and_missing(db_session):
    first = main.assign_employee_branch(
        _assignment("16", "الفرع الأول", date(2026, 10, 1)), db_session, None
    )["data"]
    second = main.assign_employee_branch(
        _assignment("16", "الفرع الثاني", date(2026, 10, 10)), db_session, None
    )["data"]

    # Trying to delete first when second exists -> rejects with 400
    with pytest.raises(HTTPException) as exc:
        main.delete_employee_branch(first.id, db_session, None)
    assert exc.value.status_code == 400
    assert "يمكن فقط حذف آخر سجل فرع للموظف" in exc.value.detail

    # Trying to delete non-existent id -> rejects with 404
    with pytest.raises(HTTPException) as exc404:
        main.delete_employee_branch(99999, db_session, None)
    assert exc404.value.status_code == 404
