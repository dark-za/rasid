"""دوال الوقت والفروق الزمنية — تعمل بتوقيت التطبيق المهيأ عبر APP_TIMEZONE.

الإطار الزمني لبيانات البصمة يتحكّم فيه إعداد ATTENDANCE_EPOCH_IS_LOCAL:
  * true  (الافتراضي): قيمة AttendanceDateTime هي وقت محلي مُرمَّز كـ epoch
    (تم التحقق: فرق ثابت +10800 ث عن AttendanceUtcTime في 5995 من 6000 صف).
  * false: القيمة epoch UTC حقيقي يُحوَّل إلى توقيت التطبيق.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import config


def app_tz(name: str | None = None) -> ZoneInfo:
    """توقيت التطبيق، مع رسالة خطأ عربية واضحة عند قيمة غير صالحة."""
    tz_name = name or config.settings()["timezone"]
    try:
        return ZoneInfo(tz_name)
    except Exception as exc:
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


def late_minutes(punch_local: datetime, shift_start: time, grace_minutes: int) -> int:
    """دقائق التأخير عن (بداية الشيفت + فترة السماح)، و0 يعني عدم التأخير.

    البصمة قبل بداية الشيفت في نفس اليوم (كما بعد منتصف الليل) لا تُعدّ تأخيراً.
    """
    limit = datetime.combine(punch_local.date(), shift_start, tzinfo=punch_local.tzinfo)
    limit += timedelta(minutes=grace_minutes)
    if punch_local <= limit:
        return 0
    return int((punch_local - limit).total_seconds() // 60)
