from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_import_worker_concurrency_preference_is_clamped_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import AppPreference
    from app.services.preferences import (
        ACCENT_COLOR_DAY_KEY,
        IMPORT_WORKER_CONCURRENCY_KEY,
        clamp_import_worker_concurrency,
        get_app_preferences,
        get_import_worker_concurrency,
        normalize_hex_color,
        update_app_preferences,
    )

    assert clamp_import_worker_concurrency(0) == 1
    assert clamp_import_worker_concurrency(99) == 99
    assert clamp_import_worker_concurrency("not-a-number", default=3) == 3
    assert normalize_hex_color("#AbC123", "#000000") == "#abc123"
    assert normalize_hex_color("blue", "#000000") == "#000000"

    Session = make_session()
    with Session() as db:
        preferences = update_app_preferences(db, import_worker_concurrency=3, accent_color_day="#14b8a6")

        stored = db.get(AppPreference, IMPORT_WORKER_CONCURRENCY_KEY)
        accent = db.get(AppPreference, ACCENT_COLOR_DAY_KEY)
        assert stored is not None
        assert accent is not None
        assert stored.value == {"value": 3}
        assert accent.value == {"value": "#14b8a6"}
        assert preferences["import_worker_concurrency"] == 3
        assert preferences["accent_color_day"] == "#14b8a6"
        assert get_import_worker_concurrency(db) == 3

        update_app_preferences(db, import_worker_concurrency=99)
        assert get_app_preferences(db)["import_worker_concurrency"] == 99
