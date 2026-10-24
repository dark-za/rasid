from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    true,
)
from sqlalchemy.orm import relationship, synonym
from database import Base


class EmployeeBranchHistory(Base):
    __tablename__ = "employee_branch_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    employee_id = Column(String(50), index=True, nullable=False)
    employee_name = Column(String(150), nullable=True)
    branch_name = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)


class Employee(Base):
    __tablename__ = "employees"

    employee_id = Column(String(50), primary_key=True)
    name = Column(String(150), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default=true())
    is_active = synonym("active")

    shift_assignments = relationship(
        "EmployeeShiftAssignment", back_populates="employee"
    )


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    start_time = Column(String(10), nullable=False) # e.g., "08:00"
    end_time = Column(String(10), nullable=False)   # e.g., "17:00"
    grace_period_minutes = Column(Integer, default=15)
    is_active = Column(Boolean, nullable=False, default=False, server_default=false())
    lateness_mode = Column(String(20), nullable=False, default="after_grace",
                           server_default="after_grace")
    color = Column(String(7), nullable=False, default="#4F46E5",
                   server_default="#4F46E5")
    enabled = synonym("is_active")

    employee_assignments = relationship(
        "EmployeeShiftAssignment", back_populates="shift"
    )


class EmployeeShiftAssignment(Base):
    __tablename__ = "employee_shift_assignments"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_employee_shift_assignment_date_range",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    employee_id = Column(
        String(50), ForeignKey("employees.employee_id"), nullable=False
    )
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)

    employee = relationship("Employee", back_populates="shift_assignments")
    shift = relationship("Shift", back_populates="employee_assignments")
