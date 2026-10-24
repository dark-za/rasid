"""إعدادات المشروع والاتصال بمصدر البصمات الخارجي."""
import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv, set_key

# ملف الإعدادات الموحد في جذر المشروع (بغض النظر عن دليل التشغيل)
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_FILE)
DB_RUNTIME_FILE = Path(
    os.getenv("RASID_DB_RUNTIME_FILE", str(ENV_FILE.parent / ".db-runtime.env"))
)
load_dotenv(DB_RUNTIME_FILE, override=True)


class ConfigError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def db_password_attendance() -> str:
    """كلمة مرور مستخدم القراءة من قاعدة البصمة الخارجية."""
    return os.getenv("ATTENDANCE_PASS", "")


def _require(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    return value


def update_env_file(values: dict[str, str]) -> None:
    """Persist settings atomically while preserving unrelated environment entries."""
    DB_RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".rasid-db-", suffix=".tmp", dir=DB_RUNTIME_FILE.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        if DB_RUNTIME_FILE.exists():
            shutil.copyfile(DB_RUNTIME_FILE, temporary_path)
        for key, value in values.items():
            result = set_key(str(temporary_path), key, value, quote_mode="always")
            if not result[0]:
                raise OSError(f"Unable to persist environment setting {key}")
        os.replace(temporary_path, DB_RUNTIME_FILE)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@lru_cache(maxsize=1)
def settings() -> dict:
    return {
        "db_file": _require(
            "RASID_DB_FILE",
            str(Path(__file__).resolve().parent / "data" / "rasid.sqlite3"),
        ),
        "db_host": _require("DB_HOST", "192.168.8.3"),
        "db_port": int(_require("DB_PORT", "3306")),
        "db_user_attendance": _require("ATTENDANCE_DB_USER", "rasid_reader"),
        "db_name_attendance": _require("ATTENDANCE_DB_NAME", "smartpss_local"),
        "login_username": _require("RASID_LOGIN_USERNAME", "admin"),
        "login_password": os.getenv("RASID_LOGIN_PASSWORD", ""),
        "session_secret": os.getenv("RASID_SESSION_SECRET", ""),
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
        "timezone": _require("APP_TIMEZONE", "Asia/Riyadh"),
        # هل AttendanceDateTime وقت محلي مُرمَّز كـ epoch (true) أم UTC حقيقي (false)؟
        "attendance_epoch_is_local": _require("ATTENDANCE_EPOCH_IS_LOCAL", "true").lower()
        in {"1", "true", "yes", "on"},
    }
