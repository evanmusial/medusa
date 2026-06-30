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
        CLOUD_RUN_WORKERS_ENABLED_KEY,
        CLOUD_RUN_WORKER_CONCURRENCY_KEY,
        CLOUD_RUN_WORKER_FLAVOR_KEY,
        DEFAULT_DETAIL_STICKY_FIELDS,
        DEFAULT_LIBRARY_DENSITY,
        DEFAULT_LIBRARY_PAGE_SIZE,
        DETAIL_STICKY_FIELDS_KEY,
        DOWNLOAD_NAMING_TEMPLATE_KEY,
        IMPORT_WORKER_CONCURRENCY_KEY,
        LIBRARY_ALTERNATING_ROWS_KEY,
        LIBRARY_DENSITY_KEY,
        LIBRARY_PAGE_SIZE_KEY,
        clamp_cloud_run_worker_concurrency,
        clamp_import_worker_concurrency,
        cloud_run_worker_flavor_options,
        clamp_library_page_size,
        get_app_preferences,
        get_cloud_run_worker_concurrency,
        get_cloud_run_worker_flavor,
        get_cloud_run_worker_flavor_spec,
        get_cloud_run_workers_enabled,
        get_import_worker_concurrency,
        normalize_hex_color,
        normalize_detail_sticky_fields,
        normalize_library_density,
        update_app_preferences,
    )

    assert clamp_import_worker_concurrency(0) == 1
    assert clamp_import_worker_concurrency(99) == 99
    assert clamp_import_worker_concurrency("not-a-number", default=3) == 3
    assert clamp_cloud_run_worker_concurrency(0) == 1
    assert clamp_cloud_run_worker_concurrency("not-a-number", default=2) == 2
    assert [option["key"] for option in cloud_run_worker_flavor_options()] == ["economy", "balanced", "performance", "high_memory"]
    assert clamp_library_page_size(9) == 10
    assert clamp_library_page_size(37) == 37
    assert clamp_library_page_size("not-a-number", default=25) == 25
    assert normalize_hex_color("#AbC123", "#000000") == "#abc123"
    assert normalize_hex_color("blue", "#000000") == "#000000"
    assert normalize_library_density("reading") == "reading"
    assert normalize_library_density("very-large") == DEFAULT_LIBRARY_DENSITY
    assert normalize_detail_sticky_fields(["authors", "bad", "title", "authors"]) == ["authors", "title"]
    assert normalize_detail_sticky_fields([]) == DEFAULT_DETAIL_STICKY_FIELDS

    get_settings.cache_clear()
    Session = make_session()
    with Session() as db:
        assert get_app_preferences(db)["library_alternating_rows"] is True
        assert get_app_preferences(db)["library_page_size"] == DEFAULT_LIBRARY_PAGE_SIZE
        assert get_app_preferences(db)["library_density"] == DEFAULT_LIBRARY_DENSITY
        assert get_app_preferences(db)["detail_sticky_fields"] == DEFAULT_DETAIL_STICKY_FIELDS
        assert get_app_preferences(db)["download_naming_template"] == "$title ($year)"
        assert get_app_preferences(db)["citation_convention"] == CITATION_CONVENTION_APA_7
        assert get_app_preferences(db)["cloud_run_workers_enabled"] is False
        assert get_app_preferences(db)["cloud_run_worker_concurrency"] == 1
        assert get_app_preferences(db)["cloud_run_worker_flavor"] == "economy"

        preferences = update_app_preferences(
            db,
            import_worker_concurrency=3,
            cloud_run_workers_enabled=True,
            cloud_run_worker_concurrency=2,
            cloud_run_worker_flavor="balanced",
            accent_color_day="#14b8a6",
            library_alternating_rows=False,
            library_page_size=37,
            library_density="compact",
            detail_sticky_fields=["title", "authors", "doi"],
            download_naming_template="$author - $title [$pages]",
            citation_convention=CITATION_CONVENTION_APA_7,
        )

        stored = db.get(AppPreference, IMPORT_WORKER_CONCURRENCY_KEY)
        cloud_run_enabled = db.get(AppPreference, CLOUD_RUN_WORKERS_ENABLED_KEY)
        cloud_run_concurrency = db.get(AppPreference, CLOUD_RUN_WORKER_CONCURRENCY_KEY)
        cloud_run_flavor = db.get(AppPreference, CLOUD_RUN_WORKER_FLAVOR_KEY)
        accent = db.get(AppPreference, ACCENT_COLOR_DAY_KEY)
        alternating_rows = db.get(AppPreference, LIBRARY_ALTERNATING_ROWS_KEY)
        library_page_size = db.get(AppPreference, LIBRARY_PAGE_SIZE_KEY)
        library_density = db.get(AppPreference, LIBRARY_DENSITY_KEY)
        detail_sticky_fields = db.get(AppPreference, DETAIL_STICKY_FIELDS_KEY)
        download_naming = db.get(AppPreference, DOWNLOAD_NAMING_TEMPLATE_KEY)
        citation_convention = db.get(AppPreference, CITATION_CONVENTION_KEY)
        assert stored is not None
        assert cloud_run_enabled is not None
        assert cloud_run_concurrency is not None
        assert cloud_run_flavor is not None
        assert accent is not None
        assert alternating_rows is not None
        assert library_page_size is not None
        assert library_density is not None
        assert detail_sticky_fields is not None
        assert download_naming is not None
        assert citation_convention is not None
        assert stored.value == {"value": 3}
        assert cloud_run_enabled.value == {"value": True}
        assert cloud_run_concurrency.value == {"value": 2}
        assert cloud_run_flavor.value == {"value": "balanced"}
        assert accent.value == {"value": "#14b8a6"}
        assert alternating_rows.value == {"value": False}
        assert library_page_size.value == {"value": 37}
        assert library_density.value == {"value": "compact"}
        assert detail_sticky_fields.value == {"value": ["title", "authors", "doi"]}
        assert download_naming.value == {"value": "$author - $title [$pages]"}
        assert citation_convention.value == {"value": CITATION_CONVENTION_APA_7}
        assert preferences["import_worker_concurrency"] == 3
        assert preferences["cloud_run_workers_enabled"] is True
        assert preferences["cloud_run_worker_concurrency"] == 2
        assert preferences["cloud_run_worker_flavor"] == "balanced"
        assert preferences["cloud_run_worker_flavor_options"][1]["label"] == "Balanced"
        assert preferences["accent_color_day"] == "#14b8a6"
        assert preferences["library_alternating_rows"] is False
        assert preferences["library_page_size"] == 37
        assert preferences["library_density"] == "compact"
        assert preferences["detail_sticky_fields"] == ["title", "authors", "doi"]
        assert preferences["download_naming_template"] == "$author - $title [$pages]"
        assert preferences["citation_convention"] == CITATION_CONVENTION_APA_7
        assert get_import_worker_concurrency(db) == 3
        assert get_cloud_run_workers_enabled(db) is True
        assert get_cloud_run_worker_concurrency(db) == 2
        assert get_cloud_run_worker_flavor(db) == "balanced"
        assert get_cloud_run_worker_flavor_spec(db)["memory_gib"] == 4.0

        update_app_preferences(db, import_worker_concurrency=99)
        assert get_app_preferences(db)["import_worker_concurrency"] == 99
        update_app_preferences(db, cloud_run_worker_concurrency=0)
        assert get_app_preferences(db)["cloud_run_worker_concurrency"] == 1
        update_app_preferences(db, cloud_run_worker_flavor="not-real")
        assert get_app_preferences(db)["cloud_run_worker_flavor"] == "economy"
        update_app_preferences(db, library_page_size=3)
        assert get_app_preferences(db)["library_page_size"] == 10


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
        ANALYSIS_MODEL_TASKS,
        MODEL_ACCESSORY_SUMMARIES,
        MODEL_BIBLIOGRAPHY_CLEANUP,
        MODEL_FORMULA_CAPTURE,
        MODEL_KEYWORDS_TOPICS,
        MODEL_METADATA,
        MODEL_PAGE_TEXT_NORMALIZATION,
        MODEL_RAW_TEXT_EXTRACTION,
        MODEL_SUMMARY,
    )
    from app.services.preferences import (
        DEFAULT_DOCUMENT_CACHE_SIZE_MB,
        DEFAULT_VALKEY_MAXMEMORY,
        DOCUMENT_CACHE_SIZE_MB_KEY,
        VALKEY_MAXMEMORY_KEY,
        get_app_preferences,
        normalize_valkey_maxmemory,
        update_app_preferences,
    )

    Session = make_session()
    with Session() as db:
        assert get_app_preferences(db)["document_cache_size_mb"] == DEFAULT_DOCUMENT_CACHE_SIZE_MB
        assert get_app_preferences(db)["valkey_maxmemory"] == DEFAULT_VALKEY_MAXMEMORY
        assert normalize_valkey_maxmemory("8G") == "8gb"
        assert normalize_valkey_maxmemory("4096 mb") == "4096mb"
        assert normalize_valkey_maxmemory("nope", default=None) is None

        preferences = update_app_preferences(
            db,
            document_cache_size_mb=512,
            valkey_maxmemory="12gb",
            analysis_models={
                MODEL_METADATA: "gpt-5.4-mini",
                MODEL_BIBLIOGRAPHY_CLEANUP: "gemini-3.1-flash-lite",
                MODEL_KEYWORDS_TOPICS: "gpt-5.4",
                MODEL_PAGE_TEXT_NORMALIZATION: "gpt-5.4-nano",
            },
        )

        stored_cache = db.get(AppPreference, DOCUMENT_CACHE_SIZE_MB_KEY)
        stored_valkey = db.get(AppPreference, VALKEY_MAXMEMORY_KEY)
        assert stored_cache is not None
        assert stored_valkey is not None
        assert stored_cache.value == {"value": 512}
        assert stored_valkey.value == {"value": "12gb"}
        assert preferences["document_cache_size_mb"] == 512
        assert preferences["valkey_maxmemory"] == "12gb"
        assert preferences["analysis_models"][MODEL_RAW_TEXT_EXTRACTION] == "marker"
        assert preferences["analysis_models"][MODEL_METADATA] == "gpt-5.4-mini"
        assert preferences["analysis_models"][MODEL_SUMMARY] == "gpt-5.4"
        assert preferences["analysis_models"][MODEL_KEYWORDS_TOPICS] == "gpt-5.4"
        assert preferences["analysis_models"][MODEL_ACCESSORY_SUMMARIES] == "gpt-5.4"
        assert preferences["analysis_models"][MODEL_FORMULA_CAPTURE] == "gpt-5.4"
        assert preferences["analysis_models"][MODEL_BIBLIOGRAPHY_CLEANUP] == "gemini-3.1-flash-lite"
        assert preferences["analysis_models"][MODEL_PAGE_TEXT_NORMALIZATION] == "gpt-5.4-nano"

        payload = get_app_preferences(db)
        assert len(payload["analysis_model_tasks"]) == len(ANALYSIS_MODEL_TASKS)
        assert payload["model_pricing"]["updated_at"] == "2026-06-23"
        assert payload["model_pricing"]["stale"] is True
        raw_text_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_RAW_TEXT_EXTRACTION)
        assert raw_text_task["default_model"] == "marker"
        assert raw_text_task["option_groups"][0] == {"label": "Local", "options": ["docling", "marker", "pymupdf"]}
        assert raw_text_task["option_groups"][1]["label"] == "OpenAI"
        assert raw_text_task["option_groups"][2]["label"] == "Google"
        metadata_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_METADATA)
        assert metadata_task["option_groups"][0]["label"] == "OpenAI"
        assert metadata_task["option_groups"][1]["label"] == "Google"
        assert "gemini-3.1-flash-lite" in payload["model_options"]["google"]
        assert "gemini-2.5-flash" in payload["model_options"]["google"]
        assert "gemini-3.5-flash" not in payload["model_options"]["google"]
        assert all("preview" not in model for model in payload["model_options"]["google"])
        assert all(not model.startswith("gemini-2.0-") for model in payload["model_options"]["google"])
        assert "gpt-4o" in payload["model_options"]["gpt"]
        assert "gpt-5.1" in payload["model_options"]["gpt"]
        assert "gpt-5.2-pro" in payload["model_options"]["gpt"]
        assert "gpt-5.5" in payload["model_options"]["gpt"]
        assert payload["model_options"]["embedding"] == [
            "text-embedding-3-small",
            "text-embedding-3-large",
            "text-embedding-ada-002",
        ]
        assert payload["model_options"]["raw_text_extraction"][:3] == ["docling", "marker", "pymupdf"]
        tag_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_KEYWORDS_TOPICS)
        assert tag_task["selected_model"] == "gpt-5.4"
        bibliography_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_BIBLIOGRAPHY_CLEANUP)
        assert bibliography_task["default_model"] == "gpt-5-mini"
        assert bibliography_task["selected_model"] == "gemini-3.1-flash-lite"
        formula_task = next(task for task in payload["analysis_model_tasks"] if task["key"] == MODEL_FORMULA_CAPTURE)
        assert formula_task["default_model"] == "gpt-5.4"
        assert formula_task["selected_model"] == "gpt-5.4"


def test_legacy_bibliography_cleanup_default_rolls_forward(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import AppPreference
    from app.services.analysis_models import MODEL_BIBLIOGRAPHY_CLEANUP
    from app.services.preferences import get_app_preferences, update_app_preferences

    Session = make_session()
    with Session() as db:
        db.add(AppPreference(key="analysis_model_bibliography_cleanup", value={"value": "gpt-5.4-nano"}))
        db.commit()

        preferences = get_app_preferences(db)
        task = next(task for task in preferences["analysis_model_tasks"] if task["key"] == MODEL_BIBLIOGRAPHY_CLEANUP)
        assert preferences["analysis_models"][MODEL_BIBLIOGRAPHY_CLEANUP] == "gpt-5-mini"
        assert task["default_model"] == "gpt-5-mini"
        assert task["selected_model"] == "gpt-5-mini"

        updated = update_app_preferences(db, analysis_models={MODEL_BIBLIOGRAPHY_CLEANUP: "gemini-3.1-flash-lite"})
        assert updated["analysis_models"][MODEL_BIBLIOGRAPHY_CLEANUP] == "gemini-3.1-flash-lite"


def test_import_processing_presets_and_steps_are_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services.preferences import get_app_preferences, update_app_preferences

    Session = make_session()
    with Session() as db:
        preferences = get_app_preferences(db)

        assert preferences["default_import_processing_preset_id"] == "balanced"
        assert preferences["second_pass_processing_enabled"] is True
        assert [preset["id"] for preset in preferences["import_processing_presets"][:3]] == [
            "balanced",
            "strict_local",
            "deep_review",
        ]
        assert all(preset["built_in"] for preset in preferences["import_processing_presets"][:3])
        assert "bibliography_extraction" in {step["key"] for step in preferences["import_processing_steps"]}
        assert all("Accomplishes:" in step["tooltip"] for step in preferences["import_processing_steps"])

        custom = {
            "id": "My Balanced",
            "name": "My Balanced",
            "mode": "custom",
            "built_in": False,
            "cleanup": {"model": "gemini-3.1-flash-lite", "page_cap_min": 4, "page_cap_percent": 10},
            "bibliography": {"enabled": True, "preserve_italics": False},
            "visuals": {"enabled": False},
        }
        updated = update_app_preferences(
            db,
            import_processing_presets=[custom, {"id": "balanced", "name": "Tampered Balanced", "built_in": False}],
            default_import_processing_preset_id="custom_my_balanced",
            second_pass_processing_enabled=False,
        )

        assert updated["default_import_processing_preset_id"] == "custom_my_balanced"
        assert updated["second_pass_processing_enabled"] is False
        assert updated["import_processing_presets"][0]["name"] == "Balanced"
        saved_custom = next(preset for preset in updated["import_processing_presets"] if preset["id"] == "custom_my_balanced")
        assert saved_custom["name"] == "My Balanced"
        assert saved_custom["cleanup"]["model"] == "gemini-3.1-flash-lite"
        assert saved_custom["cleanup"]["page_cap_min"] == 4
        assert saved_custom["cleanup"]["page_cap_percent"] == 10
        assert saved_custom["bibliography"]["preserve_italics"] is False
        assert saved_custom["visuals"]["enabled"] is False
        assert not any(preset["name"] == "Tampered Balanced" for preset in updated["import_processing_presets"])


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


def test_gcs_bucket_lifecycle_status_formats_storage_class_rules(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    key_path = tmp_path / "service-account.json"
    key_path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "medusa-test",
                "client_email": "medusa@medusa-test.iam.gserviceaccount.com",
                "private_key_id": "test",
                "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
    )
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key_path))

    from app.config import get_settings
    from app.services.gcs_lifecycle import gcs_bucket_lifecycle_status
    from app.services.preferences import update_app_preferences

    class FakeCredentials:
        project_id = "medusa-test"

    class FakeBucket:
        storage_class = "STANDARD"
        location = "US"

        def reload(self):
            return None

        @property
        def lifecycle_rules(self):
            return iter(
                [
                    {
                        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
                        "condition": {"age": 30, "matchesPrefix": ["documents/"]},
                    },
                    {
                        "action": {"type": "Delete"},
                        "condition": {"age": 365, "matchesStorageClass": ["ARCHIVE"]},
                    },
                ]
            )

    class FakeClient:
        def __init__(self, *, project, credentials):
            assert project == "medusa-test"
            assert credentials.project_id == "medusa-test"

        def bucket(self, name):
            assert name == "medusa-assets"
            return FakeBucket()

    get_settings.cache_clear()
    monkeypatch.setattr("app.services.gcs_lifecycle.load_service_account_credentials", lambda _path: FakeCredentials())
    monkeypatch.setattr("google.cloud.storage.Client", FakeClient)

    Session = make_session()
    with Session() as db:
        update_app_preferences(db, gcs_bucket="medusa-assets")
        status = gcs_bucket_lifecycle_status(db)

    assert status["available"] is True
    assert status["storage_class"] == "Standard"
    assert status["location"] == "US"
    assert status["summary"] == "2 lifecycle rules configured. 1 storage-class transition. 1 delete rule."
    assert status["rules"][0]["action_label"] == "Move to Nearline"
    assert status["rules"][0]["condition_labels"] == ["after 30 days", "prefix documents/"]
    assert status["rules"][1]["action_label"] == "Delete"
    assert status["rules"][1]["condition_labels"] == ["after 365 days", "currently Archive"]


def test_gcs_bucket_lifecycle_status_reports_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    from app.config import get_settings
    from app.services.gcs_lifecycle import gcs_bucket_lifecycle_status
    from app.services.preferences import update_app_preferences

    get_settings.cache_clear()
    Session = make_session()
    with Session() as db:
        update_app_preferences(db, gcs_bucket="medusa-assets")
        status = gcs_bucket_lifecycle_status(db)

    assert status["available"] is False
    assert status["status"] == "credentials_missing"
    assert "service-account" in (status["error"] or "")


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
