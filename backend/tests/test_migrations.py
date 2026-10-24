from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

import config
import database
import models


@pytest.fixture(autouse=True)
def clear_config_and_engine_caches():
    yield
    config.settings.cache_clear()
    config.db_password_attendance.cache_clear()
    database.reset_engines()


def test_init_db_applies_migrations_and_sets_user_version(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_rasid.sqlite3"
    monkeypatch.setenv("RASID_DB_FILE", str(db_file))
    config.settings.cache_clear()

    # Before init_db, file shouldn't exist
    assert not db_file.exists()

    database.init_db()
    assert db_file.exists()

    expected_version = database.SCHEMA_MIGRATIONS[-1][0]
    assert database.get_user_version() == expected_version

    # Calling init_db again is idempotent
    database.init_db()
    assert database.get_user_version() == expected_version


def test_migration_upgrades_legacy_sqlite_schema(tmp_path: Path):
    db_file = tmp_path / "legacy.sqlite3"
    engine = create_engine(f"sqlite:///{db_file}")

    # Simulate legacy database created before lateness_mode, color, and active were added
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    start_time VARCHAR(10) NOT NULL,
                    end_time VARCHAR(10) NOT NULL,
                    grace_period_minutes INTEGER DEFAULT 15,
                    is_active BOOLEAN DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE employees (
                    employee_id VARCHAR(50) PRIMARY KEY,
                    name VARCHAR(150) NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO shifts (name, start_time, end_time) VALUES ('دوام عام', '08:00', '16:00')"
            )
        )
        conn.execute(
            text("INSERT INTO employees (employee_id, name) VALUES ('EMP01', 'أحمد')")
        )
        conn.execute(text("PRAGMA user_version = 0"))

    assert database.get_user_version(engine) == 0

    # Verify columns before migration
    inspector = inspect(engine)
    shift_cols_before = {col["name"] for col in inspector.get_columns("shifts")}
    emp_cols_before = {col["name"] for col in inspector.get_columns("employees")}
    assert "lateness_mode" not in shift_cols_before
    assert "color" not in shift_cols_before
    assert "active" not in emp_cols_before

    # Apply migrations
    applied_ver = database.apply_migrations(engine)
    assert applied_ver == database.SCHEMA_MIGRATIONS[-1][0]
    assert database.get_user_version(engine) == applied_ver

    # Verify columns after migration
    inspector = inspect(engine)
    shift_cols_after = {col["name"] for col in inspector.get_columns("shifts")}
    emp_cols_after = {col["name"] for col in inspector.get_columns("employees")}
    assert "lateness_mode" in shift_cols_after
    assert "color" in shift_cols_after
    assert "active" in emp_cols_after

    # Verify existing data preserved
    with engine.connect() as conn:
        shift_row = conn.execute(
            text("SELECT name, lateness_mode, color FROM shifts WHERE id = 1")
        ).fetchone()
        assert shift_row[0] == "دوام عام"
        assert shift_row[1] == "after_grace"
        assert shift_row[2] == "#4F46E5"

        emp_row = conn.execute(
            text("SELECT employee_id, name, active FROM employees WHERE employee_id = 'EMP01'")
        ).fetchone()
        assert emp_row[0] == "EMP01"
        assert emp_row[1] == "أحمد"
        assert emp_row[2] == 1

    engine.dispose()


def test_incremental_future_migration_execution(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "future.sqlite3"
    engine = create_engine(f"sqlite:///{db_file}")

    # Set up base version 1
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE employees (employee_id VARCHAR(50) PRIMARY KEY, name VARCHAR(150))"))
        conn.execute(text("PRAGMA user_version = 1"))

    assert database.get_user_version(engine) == 1

    # Add a mock migration 2
    mock_migrations = list(database.SCHEMA_MIGRATIONS) + [
        (2, ["ALTER TABLE employees ADD COLUMN department VARCHAR(100) DEFAULT 'HQ' NOT NULL"]),
    ]
    monkeypatch.setattr(database, "SCHEMA_MIGRATIONS", mock_migrations)

    new_version = database.apply_migrations(engine)
    assert new_version == 2
    assert database.get_user_version(engine) == 2

    # Column should be present
    inspector = inspect(engine)
    emp_cols = {col["name"] for col in inspector.get_columns("employees")}
    assert "department" in emp_cols

    # Running again does nothing
    assert database.apply_migrations(engine) == 2

    engine.dispose()
