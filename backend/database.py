"""اتصالات قاعدة البيانات.

قاعدتان:
  * قاعدة "راصد" (APP_DB_NAME)  -> جداول النظام (shifts, employee_branch_history) — كتابة.
  * قاعدة البصمة (ATTENDANCE_DB_NAME) -> جدول AttendanceRecordInfo — قراءة فقط.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import config

Base = declarative_base()


def _url(database: str | None = None) -> URL:
    s = config.settings()
    return URL.create(
        "mysql+pymysql",
        username=s["db_user"],
        password=config.db_password(),
        host=s["db_host"],
        port=s["db_port"],
        database=database,
    )


app_engine = create_engine(_url(config.settings()["db_name_app"]), pool_pre_ping=True)
attendance_engine = create_engine(_url(config.settings()["db_name_attendance"]), pool_pre_ping=True)

AppSession = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)
AttendanceSession = sessionmaker(autocommit=False, autoflush=False, bind=attendance_engine)


def ensure_app_database() -> None:
    """إنشاء قاعدة بيانات راصد إن لم تكن موجودة (لا نلمس قاعدة البصمة)."""
    app_db_name = config.settings()["db_name_app"]
    server_engine = create_engine(_url(None), pool_pre_ping=True)
    with server_engine.begin() as conn:
        conn.execute(
            text(f"CREATE DATABASE IF NOT EXISTS `{app_db_name}` "
                 "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
    server_engine.dispose()


def init_db() -> None:
    ensure_app_database()
    Base.metadata.create_all(bind=app_engine)


def get_db():
    db = AppSession()
    try:
        yield db
    finally:
        db.close()


def get_attendance_db():
    db = AttendanceSession()
    try:
        yield db
    finally:
        db.close()
