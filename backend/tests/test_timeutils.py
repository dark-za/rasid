from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

import config
import timeutils

RIYADH = ZoneInfo("Asia/Riyadh")


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """إعادة تهيئة إعدادات المشروع بعد كل اختبار يغيّر متغيّرات البيئة."""
    yield
    config.settings.cache_clear()


# ---------------------------------------------------------------------------
# حساب التأخير
# ---------------------------------------------------------------------------

def test_punch_0820_riyadh_is_late_by_5_minutes():
    punch = datetime(2026, 10, 24, 8, 20, tzinfo=RIYADH)
    assert timeutils.late_minutes(punch, time(8, 0), 15) == 5


def test_punch_0759_is_not_late():
    punch = datetime(2026, 10, 24, 7, 59, tzinfo=RIYADH)
    assert timeutils.late_minutes(punch, time(8, 0), 15) == 0


def test_punch_exactly_at_grace_limit_is_not_late():
    punch = datetime(2026, 10, 24, 8, 15, tzinfo=RIYADH)
    assert timeutils.late_minutes(punch, time(8, 0), 15) == 0


def test_punch_one_minute_after_grace_is_late_by_one():
    punch = datetime(2026, 10, 24, 8, 16, tzinfo=RIYADH)
    assert timeutils.late_minutes(punch, time(8, 0), 15) == 1


def test_after_midnight_punch_is_not_late():
    # بصمة 00:12 لا تُعدّ تأخيراً: حساب الحد في نفس يوم البصمة
    punch = datetime(2026, 10, 24, 0, 12, tzinfo=RIYADH)
    assert timeutils.late_minutes(punch, time(8, 0), 15) == 0


# ---------------------------------------------------------------------------
# حدود اليوم ومنتصف الليل
# ---------------------------------------------------------------------------

def test_day_bounds_local_mode_cover_exactly_one_day():
    start, end = timeutils.day_bounds_epoch_ms(date(2026, 10, 24), local_mode=True)
    assert end - start == 86_400_000  # الرياض بلا DST


def test_day_bounds_local_mode_midnight_boundaries():
    start, end = timeutils.day_bounds_epoch_ms(date(2026, 10, 24), local_mode=True)
    assert timeutils.epoch_ms_to_local(start, True) == datetime(2026, 10, 24, 0, 0, 0, tzinfo=RIYADH)
    # النهاية حصرية: آخر لحظة في اليوم تعود لليوم نفسه
    last_ms = timeutils.epoch_ms_to_local(end - 1, True)
    assert last_ms.date() == date(2026, 10, 24)
    assert (last_ms.hour, last_ms.minute, last_ms.second) == (23, 59, 59)
    # بداية اليوم التالي تعود لليوم التالي
    assert timeutils.epoch_ms_to_local(end, True) == datetime(2026, 10, 25, 0, 0, 0, tzinfo=RIYADH)


def test_day_bounds_utc_mode_constants():
    # منتصف ليل الرياض 2026-10-24 = 2026-10-23 21:00 UTC
    start, end = timeutils.day_bounds_epoch_ms(date(2026, 10, 24), local_mode=False)
    assert start == 1792789200000
    assert end == 1792875600000


def test_punch_at_midnight_belongs_to_next_day():
    next_day_midnight = datetime(2026, 10, 25, 0, 0, 0, tzinfo=RIYADH)
    start, end = timeutils.day_bounds_epoch_ms(date(2026, 10, 24), local_mode=True)
    stored = timeutils.local_to_epoch_ms(next_day_midnight, True)
    assert not (start <= stored < end)
    start_next, _ = timeutils.day_bounds_epoch_ms(date(2026, 10, 25), local_mode=True)
    assert stored == start_next


# ---------------------------------------------------------------------------
# تحويل الـ epoch بالوضعين — ببيانات حقيقية
# ---------------------------------------------------------------------------

def test_real_row_local_mode():
    # صف حقيقي: AttendanceDateTime=1792803666000 و AttendanceUtcTime=1792792866 (فرق +10800s)
    # الوضع المحلي: القراءة الصحيحة للحائط = 2026-10-24 01:01:06 بتوقيت الرياض
    converted = timeutils.epoch_ms_to_local(1792803666000, local_mode=True)
    assert converted == datetime(2026, 10, 24, 1, 1, 6, tzinfo=RIYADH)


def test_real_row_utc_mode_shifts_by_three_hours():
    # الوضع الخاطئ (اعتبارها UTC حقيقي) يعرض 04:01:06 بدل 01:01:06 — خطأ +3 ساعات
    converted = timeutils.epoch_ms_to_local(1792803666000, local_mode=False)
    assert converted == datetime(2026, 10, 24, 4, 1, 6, tzinfo=RIYADH)


def test_local_roundtrip():
    original = datetime(2026, 10, 24, 8, 30, 15, tzinfo=RIYADH)
    stored = timeutils.local_to_epoch_ms(original, True)
    assert timeutils.epoch_ms_to_local(stored, True) == original


def test_utc_roundtrip():
    original = datetime(2026, 10, 24, 8, 30, 15, tzinfo=RIYADH)
    stored = timeutils.local_to_epoch_ms(original, False)
    assert timeutils.epoch_ms_to_local(stored, False) == original


# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------

def test_invalid_timezone_raises_config_error(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Not/AZone")
    config.settings.cache_clear()
    with pytest.raises(config.ConfigError, match="APP_TIMEZONE"):
        timeutils.app_tz()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("0", False), ("no", False), ("", False),
    ],
)
def test_attendance_epoch_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("ATTENDANCE_EPOCH_IS_LOCAL", raw)
    config.settings.cache_clear()
    assert config.settings()["attendance_epoch_is_local"] is expected


def test_default_timezone_is_riyadh(monkeypatch):
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    config.settings.cache_clear()
    assert config.settings()["timezone"] == "Asia/Riyadh"
