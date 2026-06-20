import json
import os
import stat
from pathlib import Path

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
        CITATION_CONVENTION_APA_7,
        CITATION_CONVENTION_KEY,
        DOWNLOAD_NAMING_TEMPLATE_KEY,
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
        assert get_app_preferences(db)["download_naming_template"] == "$title ($year)"
        assert get_app_preferences(db)["citation_convention"] == CITATION_CONVENTION_APA_7

        preferences = update_app_preferences(
            db,
            import_worker_concurrency=3,
            accent_color_day="#14b8a6",
            library_alternating_rows=False,
            download_naming_template="$author - $title [$pages]",
            citation_convention=CITATION_CONVENTION_APA_7,
        )

        stored = db.get(AppPreference, IMPORT_WORKER_CONCURRENCY_KEY)
        accent = db.get(AppPreference, ACCENT_COLOR_DAY_KEY)
        alternating_rows = db.get(AppPreference, LIBRARY_ALTERNATING_ROWS_KEY)
        download_naming = db.get(AppPreference, DOWNLOAD_NAMING_TEMPLATE_KEY)
        citation_convention = db.get(AppPreference, CITATION_CONVENTION_KEY)
        assert stored is not None
        assert accent is not None
        assert alternating_rows is not None
        assert download_naming is not None
        assert citation_convention is not None
        assert stored.value == {"value": 3}
        assert accent.value == {"value": "#14b8a6"}
        assert alternating_rows.value == {"value": False}
        assert download_naming.value == {"value": "$author - $title [$pages]"}
        assert citation_convention.value == {"value": CITATION_CONVENTION_APA_7}
        assert preferences["import_worker_concurrency"] == 3
        assert preferences["accent_color_day"] == "#14b8a6"
        assert preferences["library_alternating_rows"] is False
        assert preferences["download_naming_template"] == "$author - $title [$pages]"
        assert preferences["citation_convention"] == CITATION_CONVENTION_APA_7
        assert get_import_worker_concurrency(db) == 3

        update_app_preferences(db, import_worker_concurrency=99)
        assert get_app_preferences(db)["import_worker_concurrency"] == 99


def test_download_filename_template_sanitizes_document_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document
    from app.services.preferences import render_download_filename

    document = Document(
        title='An <Invalid>/Paper: "Study"?',
        authors=[{"given": "Ada", "family": "Lovelace"}, {"given": "Grace", "family": "Hopper"}],
        publication_year=1843,
        original_filename="fallback.pdf",
        checksum_sha256="a" * 64,
        page_count=12,
    )

    assert render_download_filename(document, "$title ($year)") == "An _Invalid_Paper_ _Study_ (1843).pdf"
    assert render_download_filename(document, "$author - $authors - $pages") == "Ada Lovelace - Ada Lovelace, Grace Hopper - 12.pdf"
    assert render_download_filename(document, "CON") == "CON_.pdf"


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
        DEFAULT_DOCUMENT_CACHE_SIZE_MB,
        DOCUMENT_CACHE_SIZE_MB_KEY,
        get_app_preferences,
        update_app_preferences,
    )

    Session = make_session()
    with Session() as db:
        assert get_app_preferences(db)["document_cache_size_mb"] == DEFAULT_DOCUMENT_CACHE_SIZE_MB

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
        assert raw_text_task["option_groups"][2]["label"] == "Google"
        metadata_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_METADATA)
        assert metadata_task["option_groups"][0]["label"] == "OpenAI"
        assert metadata_task["option_groups"][1]["label"] == "Google"
        assert "gemini-2.5-flash" in payload["model_options"]["google"]
        assert all("preview" not in model for model in payload["model_options"]["google"])
        assert all(not model.startswith("gemini-2.0-") for model in payload["model_options"]["google"])
        assert "gpt-4o" in payload["model_options"]["gpt"]
        assert "gpt-5.1" in payload["model_options"]["gpt"]
        assert "gpt-5.2-pro" in payload["model_options"]["gpt"]
        assert "gpt-5.5" in payload["model_options"]["gpt"]
        assert payload["model_options"]["raw_text_extraction"][:3] == ["docling", "marker", "pymupdf"]


def test_gcs_bucket_preference_falls_back_to_env_and_can_be_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GCS_BUCKET", "env-bucket")

    from app.config import get_settings
    from app.models import AppPreference
    from app.services.preferences import GCS_BUCKET_KEY, get_app_preferences, update_app_preferences

    get_settings.cache_clear()
    Session = make_session()
    with Session() as db:
        preferences = get_app_preferences(db)
        assert preferences["gcs_bucket"] == "env-bucket"
        assert preferences["gcs_bucket_saved"] is False

        preferences = update_app_preferences(db, gcs_bucket="gs://saved-bucket/ignored-prefix")

        stored = db.get(AppPreference, GCS_BUCKET_KEY)
        assert stored is not None
        assert stored.value == {"value": "saved-bucket"}
        assert preferences["gcs_bucket"] == "saved-bucket"
        assert preferences["gcs_bucket_saved"] is True


def test_google_service_account_upload_stores_json_outside_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    from app.config import get_settings
    from app.models import AppPreference
    from app.services.google_credentials import SERVICE_ACCOUNT_NONE_LABEL
    from app.services.preferences import GOOGLE_SERVICE_ACCOUNT_KEY, get_app_preferences, store_google_service_account

    get_settings.cache_clear()
    content = json.dumps(
        {
            "type": "service_account",
            "project_id": "medusa-test",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
            "client_email": "medusa@medusa-test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    ).encode("utf-8")

    Session = make_session()
    with Session() as db:
        assert get_app_preferences(db)["google_service_account_name"] == SERVICE_ACCOUNT_NONE_LABEL

        preferences = store_google_service_account(db, content, "medusa-test.json")

        stored = db.get(AppPreference, GOOGLE_SERVICE_ACCOUNT_KEY)
        assert stored is not None
        stored_value = stored.value["value"]
        stored_path = Path(stored_value["path"])
        assert stored_path.exists()
        assert stored_value["display_name"] == "medusa@medusa-test.iam.gserviceaccount.com"
        assert "private_key" not in json.dumps(stored_value)
        assert preferences["google_service_account_name"] == "medusa@medusa-test.iam.gserviceaccount.com"
        assert preferences["google_service_account_project_id"] == "medusa-test"
        assert preferences["google_service_account_uploaded"] is True
        if os.name != "nt":
            assert stat.S_IMODE(stored_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(stored_path.parent.stat().st_mode) == 0o700


def test_service_account_name_field_requires_settings_upload(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    env_key = tmp_path / "env-service-account.json"
    env_key.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "env-project",
                "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
                "client_email": "env@env-project.iam.gserviceaccount.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(env_key))

    from app.config import get_settings
    from app.services.google_credentials import SERVICE_ACCOUNT_NONE_LABEL
    from app.services.preferences import get_app_preferences, get_google_service_account_path

    get_settings.cache_clear()
    Session = make_session()
    with Session() as db:
        preferences = get_app_preferences(db)
        assert preferences["google_service_account_name"] == SERVICE_ACCOUNT_NONE_LABEL
        assert preferences["google_service_account_source"] == "none"
        assert get_google_service_account_path(db) == str(env_key)
