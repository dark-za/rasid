from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BranchTransferIn(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=50)
    employee_name: Optional[str] = Field(None, max_length=150)
    branch_name: str = Field(..., min_length=1, max_length=100)
    start_date: date
    notes: Optional[str] = Field(None, max_length=1000)


class BranchRecordOut(BaseModel):
    id: int
    employee_id: str
    employee_name: Optional[str]
    branch_name: str
    start_date: date
    end_date: Optional[date]
    notes: Optional[str]

    class Config:
        orm_mode = True


class BranchPage(BaseModel):
    items: List[BranchRecordOut]
    total: int
    limit: int
    offset: int


class ShiftOut(BaseModel):
    id: int
    name: str
    start_time: str
    end_time: str
    grace_period_minutes: int

    class Config:
        orm_mode = True


class AttendanceLogOut(BaseModel):
    employee_id: str
    employee_name: Optional[str] = None
    check_time: str
    device: Optional[str] = None
    state: Optional[int] = None


class LateEmployeeOut(BaseModel):
    employee_id: str
    employee_name: Optional[str] = None
    arrival_time: str
    late_minutes: int


class AttendanceTodayOut(BaseModel):
    date: str
    total_records_processed: int
    logs: List[AttendanceLogOut]
    late_employees: List[LateEmployeeOut]


class HealthOut(BaseModel):
    status: str
    system: str
    time: datetime
