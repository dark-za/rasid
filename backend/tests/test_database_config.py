from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

import config
import database
import main
import models
import schemas


@pytest.fixture(autouse=True)
def clear_config_and_engine_caches():
    yield
    config.settings.cache_clear()
    config.db_password_attendance.cache_clear()
    database.reset_engines()


def test_admin_database_settings_include_only_external_attendance_database(monkeypatch):
    monkeypatch.setenv("ATTENDANCE_PASS", "attendance-secret-value")
    config.settings.cache_clear()
    config.db_password_attendance.cache_clear()

    response = main._database_settings_output()

    assert response["attendance_password_set"] is True
    assert "rasid_database" not in response
    assert "attendance-secret-value" not in repr(response)


def test_database_settings_are_persisted_atomically(tmp_path: Path, monkeypatch):
    runtime_file = tmp_path / ".db-runtime.env"
    runtime_file.write_text("EXISTING_SETTING='keep me'\n", encoding="utf-8")
    monkeypatch.setattr(config, "DB_RUNTIME_FILE", runtime_file)

    config.update_env_file({"DB_HOST": "db.example.internal", "ATTENDANCE_PASS": "plain-value"})

    values = dotenv_values(runtime_file)
    assert values["EXISTING_SETTING"] == "keep me"
    assert values["DB_HOST"] == "db.example.internal"
    assert values["ATTENDANCE_PASS"] == "plain-value"
    assert list(tmp_path.glob(".rasid-db-*.tmp")) == []


def test_attendance_connection_test_succeeds(monkeypatch):
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _query):
            return 1

    class FakeEngine:
        disposed = False

        def connect(self):
            return FakeConnection()

        def dispose(self):
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(database, "create_engine", lambda *_args, **_kwargs: engine)

    assert database.test_attendance_connection(
        {
            "db_host": "db.example.internal",
            "db_port": 3306,
            "db_name_attendance": "smartpss_local",
            "db_user_attendance": "rasid_reader",
        },
        "attendance-password",
    )
    assert engine.disposed


def test_attendance_connection_test_reports_failure(monkeypatch):
    class FakeConnection:
        def __enter__(self):
            raise SQLAlchemyError("private connection detail")

        def __exit__(self, *_args):
            return False

    class FakeEngine:
        disposed = False

        def connect(self):
            return FakeConnection()

        def dispose(self):
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(database, "create_engine", lambda *_args, **_kwargs: engine)

    assert not database.test_attendance_connection(
        {
            "db_host": "db.example.internal",
            "db_port": 3306,
            "db_name_attendance": "smartpss_local",
            "db_user_attendance": "rasid_reader",
        },
        "attendance-password",
    )
    assert engine.disposed


def test_attendance_connection_input_rejects_invalid_port():
    with pytest.raises(ValueError):
        schemas.DatabaseConnectionIn(
            host="db.example.internal",
            port=70000,
            attendance_database="smartpss_local",
            attendance_username="rasid_reader",
        )


def test_local_sqlite_database_is_created_and_keeps_data(tmp_path, monkeypatch):
    database_file = tmp_path / "rasid.sqlite3"
    monkeypatch.setenv("RASID_DB_FILE", str(database_file))
    config.settings.cache_clear()

    database.init_db()
    engine = database._app_engine()
    with database.AppSession(bind=engine) as session:
        session.add(
            models.Shift(
                name="صباحية",
                start_time="08:00",
                end_time="17:00",
                grace_period_minutes=15,
                lateness_mode="after_grace",
                color="#3B82F6",
                is_active=True,
            )
        )
        session.commit()

    database.reset_engines()
    database.init_db()
    with database.AppSession(bind=database._app_engine()) as session:
        assert session.query(models.Shift).one().name == "صباحية"
    assert {"employees", "shifts", "employee_shift_assignments"} <= set(
        inspect(database._app_engine()).get_table_names()
    )


def test_saving_attendance_settings_does_not_require_or_change_local_database(
    tmp_path, monkeypatch
):
    runtime_file = tmp_path / ".db-runtime.env"
    monkeypatch.setattr(config, "DB_RUNTIME_FILE", runtime_file)
    monkeypatch.setenv("RASID_DB_FILE", str(tmp_path / "rasid.sqlite3"))
    monkeypatch.setenv("ATTENDANCE_PASS", "")
    config.settings.cache_clear()
    config.db_password_attendance.cache_clear()
    monkeypatch.setattr(database, "test_attendance_connection", lambda *_args: True)

    result = main.update_database_settings(
        schemas.DatabaseConnectionIn(
            host="attendance.example.internal",
            port=3307,
            attendance_database="smartpss_local",
            attendance_username="rasid_reader",
            attendance_password="attendance-password",
        ),
        _="admin",
    )

    persisted = dotenv_values(runtime_file)
    assert result["status"] == "saved"
    assert persisted["DB_HOST"] == "attendance.example.internal"
    assert persisted["DB_PORT"] == "3307"
    assert persisted["ATTENDANCE_PASS"] == "attendance-password"
    assert "RASID_SECRETS_KEY" not in persisted
    assert "ATTENDANCE_PASS_ENC" not in persisted
    assert not (tmp_path / "rasid.sqlite3").exists()
