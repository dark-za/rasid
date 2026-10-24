import re
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, root_validator, validator


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)


class LoginOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class DatabaseConnectionIn(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(3306, ge=1, le=65535)
    attendance_database: str = Field(..., min_length=1, max_length=64)
    attendance_username: str = Field(..., min_length=1, max_length=100)
    attendance_password: Optional[str] = Field(None, max_length=256)

    @validator(
        "host",
        "attendance_database",
        "attendance_username",
    )
    def values_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("هذه القيمة مطلوبة")
        return value


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
    is_current: bool = False
    is_future: bool = False

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
    lateness_mode: str
    color: str
    is_active: bool

    class Config:
        orm_mode = True


class ShiftCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    start_time: str
    end_time: str
    grace_period_minutes: int = Field(15, ge=0)
    lateness_mode: str = "after_grace"
    color: str = "#3B82F6"
    is_active: bool = True

    @validator("name")
    def name_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("اسم الوردية مطلوب")
        return value

    @validator("start_time", "end_time")
    def valid_time_format(cls, value):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("يجب أن يكون الوقت بصيغة HH:MM")
        return value

    @validator("lateness_mode")
    def valid_lateness_mode(cls, value):
        if value not in {"after_grace", "from_start"}:
            raise ValueError("نمط احتساب التأخير غير صالح")
        return value

    @validator("color")
    def valid_color(cls, value):
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("يجب أن يكون اللون بصيغة HEX مثل #3B82F6")
        return value.upper()


class ShiftUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    grace_period_minutes: Optional[int] = Field(None, ge=0)
    lateness_mode: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None

    @validator("name")
    def optional_name_not_blank(cls, value):
        if value is None:
            raise ValueError("لا يمكن مسح اسم الوردية")
        value = value.strip()
        if not value:
            raise ValueError("اسم الوردية مطلوب")
        return value

    @validator("start_time", "end_time")
    def valid_optional_time_format(cls, value):
        if value is None:
            raise ValueError("لا يمكن مسح وقت الوردية")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("يجب أن يكون الوقت بصيغة HH:MM")
        return value

    @validator("lateness_mode")
    def valid_optional_lateness_mode(cls, value):
        if value is not None and value not in {"after_grace", "from_start"}:
            raise ValueError("نمط احتساب التأخير غير صالح")
        return value

    @validator("color")
    def valid_optional_color(cls, value):
        if value is None:
            raise ValueError("لا يمكن مسح لون الوردية")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("يجب أن يكون اللون بصيغة HEX مثل #3B82F6")
        return value.upper()

    @validator("grace_period_minutes", "is_active")
    def optional_shift_values_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("لا يمكن ترك قيمة الوردية فارغة")
        return value


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
    shift_date: Optional[str] = Field(
        None, description="Shift start date; an overnight after-midnight punch remains on this date."
    )
    shift_name: Optional[str] = None


class EmployeeDailySummaryOut(BaseModel):
    employee_id: str
    employee_name: Optional[str] = None
    first_punch: str
    last_punch: str
    punch_count: int
    late_minutes: int = 0
    is_late: bool = False
    shift_name: Optional[str] = None


class UnpunchedEmployeeOut(BaseModel):
    employee_id: str
    employee_name: Optional[str] = None
    shift_name: Optional[str] = None
    status: str = "لم يسجل بصمة بعد"


class AttendanceTodayOut(BaseModel):
    """Logs are grouped by calendar date; overnight late attribution uses shift start date."""

    date: str = Field(..., description="Calendar date used to select the displayed punch logs.")
    total_records_processed: int
    logs: List[AttendanceLogOut]
    late_employees: List[LateEmployeeOut]
    employee_summary: List[EmployeeDailySummaryOut] = Field(default_factory=list)
    unpunched_employees: List[UnpunchedEmployeeOut] = Field(default_factory=list)


class LateReportEmployeeOut(BaseModel):
    employee_id: str
    employee_name: Optional[str] = None
    late_days: int
    total_late_minutes: int
    average_late_minutes: float


class LateReportOut(BaseModel):
    """Range dates are inclusive shift-start dates; overnight tails belong to the prior start date."""

    from_date: str = Field(..., description="Inclusive first shift-start date.")
    to_date: str = Field(..., description="Inclusive last shift-start date.")
    shift_name: Optional[str]
    shift_start: Optional[str] = Field(
        None, description="Null when the report contains employee-specific shift schedules."
    )
    grace_period_minutes: Optional[int] = Field(
        None, description="Null when grace periods vary by assigned shift."
    )
    total_late_days: int
    total_late_minutes: int
    employees: List[LateReportEmployeeOut]


class HealthOut(BaseModel):
    status: str
    system: str
    time: datetime


class EmployeeOut(BaseModel):
    employee_id: str
    name: str
    active: bool

    class Config:
        orm_mode = True


class EmployeeCreateIn(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=150)
    active: bool = True

    @root_validator(pre=True)
    def accept_legacy_employee_fields(cls, values):
        values = dict(values or {})
        if "name" not in values and "employee_name" in values:
            values["name"] = values.pop("employee_name")
        if "active" not in values and "is_active" in values:
            values["active"] = values.pop("is_active")
        return values

    @validator("employee_id", "name")
    def trim_employee_fields(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("بيانات الموظف مطلوبة")
        return value


class EmployeeUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    active: Optional[bool] = None

    @root_validator(pre=True)
    def accept_legacy_employee_fields(cls, values):
        values = dict(values or {})
        if "name" not in values and "employee_name" in values:
            values["name"] = values.pop("employee_name")
        if "active" not in values and "is_active" in values:
            values["active"] = values.pop("is_active")
        return values

    @validator("name")
    def trim_optional_name(cls, value):
        if value is None:
            raise ValueError("لا يمكن مسح اسم الموظف")
        value = value.strip()
        if not value:
            raise ValueError("اسم الموظف مطلوب")
        return value

    @validator("active")
    def active_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("حالة الموظف مطلوبة")
        return value


class EmployeeShiftAssignmentIn(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=50)
    shift_id: int = Field(..., ge=1)
    start_date: date = Field(..., description="Inclusive first assignment date.")
    end_date: Optional[date] = Field(
        None, description="Inclusive last assignment date; null means no scheduled end."
    )

    @validator("employee_id")
    def trim_assignment_employee_id(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("رقم الموظف مطلوب")
        return value

    @validator("end_date")
    def valid_assignment_dates(cls, value, values):
        start = values.get("start_date")
        if value is not None and start is not None and value < start:
            raise ValueError("تاريخ نهاية التكليف يجب ألا يسبق تاريخ بدايته")
        return value


class EmployeeShiftAssignmentOut(BaseModel):
    id: int
    employee_id: str
    shift_id: int
    start_date: date = Field(..., description="Inclusive first assignment date.")
    end_date: Optional[date] = Field(
        None, description="Inclusive last assignment date; null means no scheduled end."
    )
    shift_name: Optional[str] = None

    class Config:
        orm_mode = True
