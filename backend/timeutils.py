"""دوال الوقت والفروق الزمنية — تعمل بتوقيت التطبيق المهيأ عبر APP_TIMEZONE.

الإطار الزمني لبيانات البصمة يتحكّم فيه إعداد ATTENDANCE_EPOCH_IS_LOCAL:
  * true  (الافتراضي): قيمة AttendanceDateTime هي وقت محلي مُرمَّز كـ epoch
    (تم التحقق: فرق ثابت +10800 ث عن AttendanceUtcTime في 5995 من 6000 صف).
  * false: القيمة epoch UTC حقيقي يُحوَّل إلى توقيت التطبيق.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config

LatenessMode = Literal["after_grace", "from_start"]


def app_tz(name: str | None = None) -> ZoneInfo:
    """توقيت التطبيق، مع رسالة خطأ عربية واضحة عند قيمة غير صالحة."""
    tz_name = name or config.settings()["timezone"]
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise config.ConfigError(f"قيمة APP_TIMEZONE غير صالحة: {tz_name!r}") from exc


def app_now() -> datetime:
    """الوقت الحالي بتوقيت التطبيق."""
    return datetime.now(app_tz())


def epoch_ms_to_local(ts_ms: int, local_mode: bool | None = None) -> datetime:
    """تحويل epoch بالميلي ثانية إلى وقت مُوَيَّز بتوقيت التطبيق.

    local_mode=None يعني قراءة الإعداد. في الوضع المحلي تُعاد وسم القيمة
    بتوقيت التطبيق دون تحويل (لأنها أصلاً تمثّل الحائط المحلي).
    """
    mode = config.settings()["attendance_epoch_is_local"] if local_mode is None else local_mode
    as_utc = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
    if mode:
        return as_utc.replace(tzinfo=app_tz())
    return as_utc.astimezone(app_tz())


def local_to_epoch_ms(dt_local: datetime, local_mode: bool | None = None) -> int:
    """تحويل وقت مُوَيَّز إلى التنسيق المخزَّن في AttendanceDateTime."""
    mode = config.settings()["attendance_epoch_is_local"] if local_mode is None else local_mode
    if mode:
        wall = dt_local.replace(tzinfo=None)
        return int(wall.replace(tzinfo=timezone.utc).timestamp() * 1000)
    return int(dt_local.timestamp() * 1000)


def day_bounds_epoch_ms(day: date, local_mode: bool | None = None) -> tuple[int, int]:
    """حدود اليوم بتوقيت التطبيق بالتنسيق المخزَّن: (بداية اليوم, بداية الغد).

    النهاية حصرية — أي بصمة عند 00:00:00.000 التالي لا تندرج في هذا اليوم.
    """
    tz = app_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return local_to_epoch_ms(start, local_mode), local_to_epoch_ms(end, local_mode)


def attendance_day_bounds_epoch_ms(
    day: date,
    shift_start: time,
    shift_end: time,
    local_mode: bool | None = None,
) -> tuple[int, int]:
    """حدود قراءة يوم الحضور، مع تضمين ذيل الشيفت الليلي في صباح اليوم التالي.

    النهاية حصرية. عند عبور الشيفت منتصف الليل، تتوقف القراءة عند وقت انتهائه
    في اليوم التالي، حتى تُنسب بصمات ذلك الجزء إلى يوم بداية الشيفت.
    """
    _validate_shift(shift_start, shift_end)
    start = datetime.combine(day, time.min, tzinfo=app_tz())
    end_day = day + timedelta(days=1)
    end_time = time.min
    if shift_end < shift_start:
        end_time = shift_end
    end = datetime.combine(end_day, end_time, tzinfo=app_tz())
    return local_to_epoch_ms(start, local_mode), local_to_epoch_ms(end, local_mode)


def _validate_shift(shift_start: time, shift_end: time) -> None:
    if not isinstance(shift_start, time) or not isinstance(shift_end, time):
        raise TypeError("shift_start and shift_end must be datetime.time values")
    if shift_start == shift_end:
        raise ValueError("shift_end must differ from shift_start")


def late_minutes(
    punch_local: datetime,
    shift_start: time,
    grace_minutes: int,
    *,
    lateness_mode: LatenessMode = "after_grace",
    shift_date: date | None = None,
) -> int:
    """دقائق التأخير، إما بعد السماح أو من بداية الشيفت.

    البصمة قبل بداية الشيفت في نفس اليوم (كما بعد منتصف الليل) لا تُعدّ تأخيراً.
    """
    if lateness_mode not in ("after_grace", "from_start"):
        raise ValueError(f"unsupported lateness_mode: {lateness_mode!r}")
    if not isinstance(grace_minutes, int) or isinstance(grace_minutes, bool):
        raise TypeError("grace_minutes must be an integer")
    if grace_minutes < 0:
        raise ValueError("grace_minutes must be non-negative")
    if not isinstance(shift_start, time):
        raise TypeError("shift_start must be a datetime.time value")

    limit = datetime.combine(
        shift_date or punch_local.date(), shift_start, tzinfo=punch_local.tzinfo
    )
    if lateness_mode == "after_grace":
        limit += timedelta(minutes=grace_minutes)
    if punch_local <= limit:
        return 0
    return int((punch_local - limit).total_seconds() // 60)
