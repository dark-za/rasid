"""إعدادات المشروع: تحميل متغيّرات البيئة وفك تشفير الأسرار.

تسلسل أولوية كلمة سر قاعدة البيانات:
  1. DB_PASS_ENC  -> نص مُشفَّر (Fernet) يُفكّ بـ RASID_SECRETS_KEY  (موصى به)
  2. DB_PASS      -> نص صريح (للتطوير المحلي فقط)
"""
import os
from functools import lru_cache

from dotenv import load_dotenv

from security import decrypt

load_dotenv()


class ConfigError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def db_password() -> str:
    encrypted = os.getenv("DB_PASS_ENC", "").strip()
    if encrypted:
        key = os.getenv("RASID_SECRETS_KEY", "").strip()
        if not key:
            raise ConfigError(
                "DB_PASS_ENC موجود لكن RASID_SECRETS_KEY غير مضبوط — "
                "لا يمكن فك تشفير كلمة سر قاعدة البيانات"
            )
        return decrypt(encrypted, key)
    return os.getenv("DB_PASS", "")


def _require(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    return value


@lru_cache(maxsize=1)
def settings() -> dict:
    return {
        "db_host": _require("DB_HOST", "127.0.0.1"),
        "db_port": int(_require("DB_PORT", "3306")),
        "db_user": _require("DB_USER", "root"),
        "db_name_app": _require("APP_DB_NAME", "rasid_db"),
        "db_name_attendance": _require("ATTENDANCE_DB_NAME", "smartpss_local"),
        "api_key": _require("RASID_API_KEY", ""),
        "cors_origins": [
            o.strip()
            for o in _require(
                "CORS_ORIGINS", "http://localhost:3005,http://127.0.0.1:3005"
            ).split(",")
            if o.strip()
        ],
        "debounce_minutes": float(_require("DEBOUNCE_MINUTES", "5")),
        "default_shift_start": _require("DEFAULT_SHIFT_START", "08:00"),
        "default_grace_minutes": int(_require("DEFAULT_GRACE_MINUTES", "15")),
    }
