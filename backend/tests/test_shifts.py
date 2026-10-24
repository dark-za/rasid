import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base
import models  # noqa: F401 — registers application tables on Base.metadata
import schemas


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shifts.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _shift(name, *, active=False, start="08:00", end="17:00"):
    return schemas.ShiftCreateIn(
        name=name,
        start_time=start,
        end_time=end,
        grace_period_minutes=15,
        lateness_mode="after_grace",
        color="#3B82F6",
        is_active=active,
    )


def test_multiple_shift_templates_keep_their_own_properties(db_session):
    first = main.create_shift(_shift("صباحية"), db_session, None)
    second = main.create_shift(
        schemas.ShiftCreateIn(
            name="مسائية",
            start_time="16:00",
            end_time="23:00",
            grace_period_minutes=5,
            lateness_mode="from_start",
            color="#AABBCC",
        ),
        db_session,
        None,
    )

    assert first.is_active is False
    assert (second.lateness_mode, second.color) == ("from_start", "#AABBCC")


def test_shift_rejects_invalid_time_grace_color_or_lateness_mode():
    with pytest.raises(ValidationError):
        _shift("خطأ", start="8:00")
    with pytest.raises(ValidationError):
        schemas.ShiftCreateIn(
            name="خطأ",
            start_time="08:00",
            end_time="17:00",
            grace_period_minutes=-1,
        )
    with pytest.raises(ValidationError):
        schemas.ShiftCreateIn(
            name="لون خاطئ",
            start_time="08:00",
            end_time="17:00",
            color="blue",
        )
    with pytest.raises(ValidationError):
        schemas.ShiftCreateIn(
            name="نمط خاطئ",
            start_time="08:00",
            end_time="17:00",
            lateness_mode="unknown",
        )


def test_overnight_shift_is_valid_and_equal_times_are_invalid(db_session):
    overnight = main.create_shift(
        _shift("ليلية", start="22:00", end="06:00"), db_session, None
    )
    assert (overnight.start_time, overnight.end_time) == ("22:00", "06:00")

    with pytest.raises(HTTPException) as exc:
        main.create_shift(_shift("غير صالحة", start="08:00", end="08:00"), db_session, None)
    assert exc.value.status_code == 422


def test_shift_color_is_normalized_and_can_be_updated(db_session):
    shift = main.create_shift(
        schemas.ShiftCreateIn(
            name="ملونة",
            start_time="08:00",
            end_time="17:00",
            color="#aabbcc",
        ),
        db_session,
        None,
    )
    assert shift.color == "#AABBCC"

    updated = main.update_shift(
        shift.id, schemas.ShiftUpdateIn(color="#1a2b3c"), db_session, None
    )
    assert updated.color == "#1A2B3C"


def test_updating_shift_to_overnight_is_allowed_but_equal_times_are_rejected(db_session):
    shift = main.create_shift(_shift("صباحية"), db_session, None)

    overnight = main.update_shift(
        shift.id,
        schemas.ShiftUpdateIn(start_time="17:00", end_time="08:00"),
        db_session,
        None,
    )
    assert (overnight.start_time, overnight.end_time) == ("17:00", "08:00")

    with pytest.raises(HTTPException) as exc:
        main.update_shift(
            shift.id, schemas.ShiftUpdateIn(end_time="17:00"), db_session, None
        )
    assert exc.value.status_code == 422
    db_session.refresh(shift)
    assert (shift.start_time, shift.end_time) == ("17:00", "08:00")
