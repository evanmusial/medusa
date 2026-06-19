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

    from app.config import get_settings
    from app.models import AppPreference
    from app.services.preferences import (
        ACCENT_COLOR_DAY_KEY,
        IMPORT_WORKER_CONCURRENCY_KEY,
        LIBRARY_ALTERNATING_ROWS_KEY,
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

    get_settings.cache_clear()
    Session = make_session()
    with Session() as db:
        assert get_app_preferences(db)["library_alternating_rows"] is True

        preferences = update_app_preferences(
            db,
            import_worker_concurrency=3,
            accent_color_day="#14b8a6",
            library_alternating_rows=False,
        )

        stored = db.get(AppPreference, IMPORT_WORKER_CONCURRENCY_KEY)
        accent = db.get(AppPreference, ACCENT_COLOR_DAY_KEY)
        alternating_rows = db.get(AppPreference, LIBRARY_ALTERNATING_ROWS_KEY)
        assert stored is not None
        assert accent is not None
        assert alternating_rows is not None
        assert stored.value == {"value": 3}
        assert accent.value == {"value": "#14b8a6"}
        assert alternating_rows.value == {"value": False}
        assert preferences["import_worker_concurrency"] == 3
        assert preferences["accent_color_day"] == "#14b8a6"
        assert preferences["library_alternating_rows"] is False
        assert get_import_worker_concurrency(db) == 3

        update_app_preferences(db, import_worker_concurrency=99)
        assert get_app_preferences(db)["import_worker_concurrency"] == 99


def test_analysis_model_and_cache_preferences_are_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import AppPreference
    from app.services.analysis_models import (
        MODEL_ACCESSORY_SUMMARIES,
        MODEL_KEYWORDS_TOPICS,
        MODEL_METADATA,
        MODEL_PAGE_TEXT_NORMALIZATION,
        MODEL_RAW_TEXT_EXTRACTION,
        MODEL_SUMMARY,
    )
    from app.services.preferences import (
        DOCUMENT_CACHE_SIZE_MB_KEY,
        get_app_preferences,
        update_app_preferences,
    )

    Session = make_session()
    with Session() as db:
        preferences = update_app_preferences(
            db,
            document_cache_size_mb=512,
            analysis_models={
                MODEL_METADATA: "gpt-5.4-mini",
                MODEL_PAGE_TEXT_NORMALIZATION: "gpt-5.4-nano",
            },
        )

        stored_cache = db.get(AppPreference, DOCUMENT_CACHE_SIZE_MB_KEY)
        assert stored_cache is not None
        assert stored_cache.value == {"value": 512}
        assert preferences["document_cache_size_mb"] == 512
        assert preferences["analysis_models"][MODEL_RAW_TEXT_EXTRACTION] == "marker"
        assert preferences["analysis_models"][MODEL_METADATA] == "gpt-5.4-mini"
        assert preferences["analysis_models"][MODEL_SUMMARY] == "gpt-5.4"
        assert preferences["analysis_models"][MODEL_KEYWORDS_TOPICS] == "gpt-5.4-mini"
        assert preferences["analysis_models"][MODEL_ACCESSORY_SUMMARIES] == "gpt-5.4"
        assert preferences["analysis_models"][MODEL_PAGE_TEXT_NORMALIZATION] == "gpt-5.4-nano"

        payload = get_app_preferences(db)
        assert len(payload["analysis_model_tasks"]) == 8
        raw_text_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_RAW_TEXT_EXTRACTION)
        assert raw_text_task["default_model"] == "marker"
        assert raw_text_task["option_groups"][0] == {"label": "Local", "options": ["docling", "marker", "pymupdf"]}
        assert raw_text_task["option_groups"][1]["label"] == "OpenAI"
        assert "gpt-4o" in payload["model_options"]["gpt"]
        assert "gpt-5.1" in payload["model_options"]["gpt"]
        assert "gpt-5.2-pro" in payload["model_options"]["gpt"]
        assert "gpt-5.5" in payload["model_options"]["gpt"]
        assert payload["model_options"]["raw_text_extraction"][:3] == ["docling", "marker", "pymupdf"]
