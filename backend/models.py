from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import relationship
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

class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    start_time = Column(String(10), nullable=False) # e.g., "08:00"
    end_time = Column(String(10), nullable=False)   # e.g., "17:00"
    grace_period_minutes = Column(Integer, default=15)
