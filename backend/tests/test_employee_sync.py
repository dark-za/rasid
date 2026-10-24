from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
import models
from database import Base


class AttendanceRows:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""

    def execute(self, query):
        self.query = str(query)
        return self

    def fetchall(self):
        return self.rows


def test_sync_imports_external_employees_and_preserves_local_active_status():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(models.Employee(employee_id="16", name="اسم قديم", active=False))
            db.commit()

            attendance = AttendanceRows([("16", "سالم"), ("17", "منى")])
            result = main._sync_employee_roster(attendance, db)

            assert result == {"created": 1, "updated": 1, "total": 2}
            assert "GROUP BY PersonID" in attendance.query
            employees = {
                employee.employee_id: employee
                for employee in db.query(models.Employee).all()
            }
            assert employees["16"].name == "سالم"
            assert employees["16"].active is False
            assert employees["17"].name == "منى"
            assert employees["17"].active is True
    finally:
        engine.dispose()


def test_deactivate_and_activate_employee_persists_in_database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(models.Employee(employee_id="99", name="خالد", active=True))
            db.commit()

            # Test deactivation
            res = main.deactivate_employee("99", db, None)
            assert res["status"] == "success"
            assert res["employee"]["active"] is False

        # Verify in a fresh session to ensure persistence
        with Session(engine) as db2:
            emp = db2.query(models.Employee).filter_by(employee_id="99").one()
            assert emp.active is False
            assert emp.is_active is False

            # Test activation
            res_act = main.activate_employee("99", db2, None)
            assert res_act["status"] == "success"
            assert res_act["employee"]["active"] is True

        # Verify activation in fresh session
        with Session(engine) as db3:
            emp = db3.query(models.Employee).filter_by(employee_id="99").one()
            assert emp.active is True
            assert emp.is_active is True

            # Test non-existent employee raises 404
            with pytest.raises(HTTPException) as exc_deact:
                main.deactivate_employee("non_existent", db3, None)
            assert exc_deact.value.status_code == 404

            with pytest.raises(HTTPException) as exc_act:
                main.activate_employee("non_existent", db3, None)
            assert exc_act.value.status_code == 404
    finally:
        engine.dispose()
