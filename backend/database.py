"""SQLite storage for Rasid and read-only access to the external attendance database."""
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import config

Base = declarative_base()


def _attendance_url() -> URL:
    settings = config.settings()
    return URL.create(
        "mysql+pymysql",
        username=settings["db_user_attendance"],
        password=config.db_password_attendance(),
        host=settings["db_host"],
        port=settings["db_port"],
        database=settings["db_name_attendance"],
    )


@lru_cache(maxsize=1)
def _app_engine():
    path = Path(config.settings()["db_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_options(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    @event.listens_for(engine, "first_connect")
    def enable_write_ahead_log(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


@lru_cache(maxsize=1)
def _attendance_engine():
    return create_engine(_attendance_url(), pool_pre_ping=True)


def test_attendance_connection(settings: dict, attendance_password: str) -> bool:
    """Check the external attendance database without changing it."""
    engine = create_engine(
        URL.create(
            "mysql+pymysql",
            username=settings["db_user_attendance"],
            password=attendance_password,
            host=settings["db_host"],
            port=settings["db_port"],
            database=settings["db_name_attendance"],
        ),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    finally:
        engine.dispose()


def reset_engines() -> None:
    for engine_factory in (_app_engine, _attendance_engine):
        if engine_factory.cache_info().currsize:
            engine_factory().dispose()
        engine_factory.cache_clear()


AppSession = sessionmaker(autocommit=False, autoflush=False)
AttendanceSession = sessionmaker(autocommit=False, autoflush=False)

SCHEMA_MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            "ALTER TABLE shifts ADD COLUMN lateness_mode VARCHAR(20) DEFAULT 'after_grace' NOT NULL",
            "ALTER TABLE shifts ADD COLUMN color VARCHAR(7) DEFAULT '#4F46E5' NOT NULL",
            "ALTER TABLE employees ADD COLUMN active BOOLEAN DEFAULT 1 NOT NULL",
        ],
    ),
]


def get_user_version(engine=None) -> int:
    target_engine = engine or _app_engine()
    with target_engine.connect() as conn:
        return int(conn.execute(text("PRAGMA user_version")).scalar() or 0)


def apply_migrations(engine=None) -> int:
    """Apply pending schema migrations using PRAGMA user_version."""
    target_engine = engine or _app_engine()
    if target_engine.dialect.name != "sqlite":
        return 0
    with target_engine.begin() as conn:
        current_version = conn.execute(text("PRAGMA user_version")).scalar() or 0
        for version, statements in SCHEMA_MIGRATIONS:
            if version > current_version:
                for stmt in statements:
                    try:
                        conn.execute(text(stmt))
                    except SQLAlchemyError as exc:
                        if "duplicate column name" in str(exc).lower():
                            continue
                        raise
                conn.execute(text(f"PRAGMA user_version = {int(version)}"))
                current_version = version
        return current_version


def init_db() -> None:
    import models  # noqa: F401 — register application tables on Base.metadata

    Base.metadata.create_all(_app_engine())
    apply_migrations(_app_engine())


def get_db():
    db = AppSession(bind=_app_engine())
    try:
        yield db
    finally:
        db.close()


def get_attendance_db():
    db = AttendanceSession(bind=_attendance_engine())
    try:
        yield db
    finally:
        db.close()
