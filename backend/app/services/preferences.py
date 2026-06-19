from __future__ import annotations

import re
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppPreference, utc_now
from app.services.analysis_models import (
    ANALYSIS_MODEL_TASKS,
    default_analysis_models,
    default_model_for_task,
    model_options,
    normalize_model_id,
    task_payloads,
)
from app.services.google_credentials import (
    SERVICE_ACCOUNT_NONE_LABEL,
    managed_google_service_account_path,
    service_account_summary_from_file,
    store_managed_service_account_json,
)


IMPORT_WORKER_CONCURRENCY_KEY = "import_worker_concurrency"
ACCENT_COLOR_DAY_KEY = "accent_color_day"
ACCENT_COLOR_NIGHT_KEY = "accent_color_night"
DOCUMENT_CACHE_SIZE_MB_KEY = "document_cache_size_mb"
LIBRARY_ALTERNATING_ROWS_KEY = "library_alternating_rows"
ANALYSIS_MODEL_KEY_PREFIX = "analysis_model_"
GCS_BUCKET_KEY = "gcs_bucket"
GOOGLE_SERVICE_ACCOUNT_KEY = "google_service_account"

MIN_IMPORT_WORKER_CONCURRENCY = 1
RECOMMENDED_IMPORT_WORKER_CONCURRENCY = 4
IMPORT_WORKER_COST_WARNING_THRESHOLD = 4
DEFAULT_DOCUMENT_CACHE_SIZE_MB = 1000
DEFAULT_DAY_ACCENT = "#2563eb"
DEFAULT_NIGHT_ACCENT = "#6ea8ff"

SAFE_PREFERENCE_KEYS = {
    IMPORT_WORKER_CONCURRENCY_KEY,
    ACCENT_COLOR_DAY_KEY,
    ACCENT_COLOR_NIGHT_KEY,
    DOCUMENT_CACHE_SIZE_MB_KEY,
    LIBRARY_ALTERNATING_ROWS_KEY,
    GCS_BUCKET_KEY,
    *(f"{ANALYSIS_MODEL_KEY_PREFIX}{task.key}" for task in ANALYSIS_MODEL_TASKS),
}

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def clamp_import_worker_concurrency(value: Any, default: int = MIN_IMPORT_WORKER_CONCURRENCY) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_IMPORT_WORKER_CONCURRENCY, parsed)


def clamp_document_cache_size_mb(value: Any, default: int = DEFAULT_DOCUMENT_CACHE_SIZE_MB) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)


def normalize_hex_color(value: Any, default: str) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if HEX_COLOR_RE.match(candidate):
            return candidate.lower()
    return default


def normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in {"true", "1", "yes", "on"}:
            return True
        if candidate in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, int):
        return bool(value)
    return default


def normalize_gcs_bucket(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if candidate.startswith("gs://"):
        candidate = candidate[5:]
    return candidate.split("/", 1)[0].strip()


def default_import_worker_concurrency() -> int:
    return clamp_import_worker_concurrency(get_settings().worker_import_concurrency)


def default_document_cache_size_mb() -> int:
    return clamp_document_cache_size_mb(get_settings().document_cache_size_mb)


def _stored_preference_value(preference: AppPreference | None) -> Any:
    if not preference:
        return None
    raw_value = preference.value or {}
    return raw_value.get("value") if isinstance(raw_value, dict) else None


def _get_preference_value(db: Session, key: str) -> Any:
    try:
        return _stored_preference_value(db.get(AppPreference, key))
    except SQLAlchemyError:
        return None


def _has_preference(db: Session, key: str) -> bool:
    try:
        return db.get(AppPreference, key) is not None
    except SQLAlchemyError:
        return False


def _set_preference_value(db: Session, key: str, value: Any) -> None:
    preference = db.get(AppPreference, key)
    if not preference:
        preference = AppPreference(key=key, value={})
        db.add(preference)
    preference.value = {"value": value}
    preference.updated_at = utc_now()
    db.flush()


def get_import_worker_concurrency(db: Session) -> int:
    return clamp_import_worker_concurrency(
        _get_preference_value(db, IMPORT_WORKER_CONCURRENCY_KEY),
        default_import_worker_concurrency(),
    )


def _analysis_model_preference_key(task_key: str) -> str:
    return f"{ANALYSIS_MODEL_KEY_PREFIX}{task_key}"


def get_analysis_models(db: Session) -> dict[str, str]:
    models = default_analysis_models()
    for task in ANALYSIS_MODEL_TASKS:
        models[task.key] = normalize_model_id(
            _get_preference_value(db, _analysis_model_preference_key(task.key)),
            default_model_for_task(task.key),
        )
    return models


def get_analysis_model(db: Session, task_key: str) -> str:
    return get_analysis_models(db).get(task_key, default_model_for_task(task_key))


def get_document_cache_size_mb(db: Session) -> int:
    return clamp_document_cache_size_mb(_get_preference_value(db, DOCUMENT_CACHE_SIZE_MB_KEY), default_document_cache_size_mb())


def default_gcs_bucket() -> str:
    return normalize_gcs_bucket(get_settings().gcs_bucket)


def get_gcs_bucket(db: Session) -> str:
    if _has_preference(db, GCS_BUCKET_KEY):
        return normalize_gcs_bucket(_get_preference_value(db, GCS_BUCKET_KEY))
    return default_gcs_bucket()


def _stored_google_service_account(db: Session) -> dict[str, Any]:
    value = _get_preference_value(db, GOOGLE_SERVICE_ACCOUNT_KEY)
    return value if isinstance(value, dict) else {}


def _env_google_service_account_summary() -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.google_application_credentials:
        return None
    summary = service_account_summary_from_file(settings.google_application_credentials)
    if not summary:
        return None
    return {**summary, "source": "env", "uploaded": False}


def get_google_service_account_status(db: Session) -> dict[str, Any]:
    stored = _stored_google_service_account(db)
    stored_path = stored.get("path")
    stored_summary = service_account_summary_from_file(stored_path)
    if stored_summary:
        return {
            "google_service_account_name": stored_summary["display_name"],
            "google_service_account_project_id": stored_summary.get("project_id"),
            "google_service_account_uploaded": True,
            "google_service_account_source": "uploaded",
            "google_service_account_uploaded_at": stored.get("uploaded_at"),
        }
    managed_summary = service_account_summary_from_file(managed_google_service_account_path())
    if managed_summary:
        return {
            "google_service_account_name": managed_summary["display_name"],
            "google_service_account_project_id": managed_summary.get("project_id"),
            "google_service_account_uploaded": True,
            "google_service_account_source": "uploaded",
            "google_service_account_uploaded_at": None,
        }
    return {
        "google_service_account_name": SERVICE_ACCOUNT_NONE_LABEL,
        "google_service_account_project_id": None,
        "google_service_account_uploaded": False,
        "google_service_account_source": "none",
        "google_service_account_uploaded_at": None,
    }


def get_google_service_account_path(db: Session) -> str | None:
    stored = _stored_google_service_account(db)
    stored_path = stored.get("path")
    if service_account_summary_from_file(stored_path):
        return str(stored_path)
    managed_path = managed_google_service_account_path()
    if service_account_summary_from_file(managed_path):
        return str(managed_path)
    env_summary = _env_google_service_account_summary()
    if env_summary:
        return str(env_summary["path"])
    return None


def get_google_project_id(db: Session) -> str | None:
    status = get_google_service_account_status(db)
    project_id = status.get("google_service_account_project_id") or get_settings().google_cloud_project
    return str(project_id).strip() if project_id else None


def get_active_google_service_account_path() -> str | None:
    try:
        from app.database import session_scope

        with session_scope() as db:
            return get_google_service_account_path(db)
    except Exception:
        settings = get_settings()
        summary = service_account_summary_from_file(settings.google_application_credentials)
        return str(summary["path"]) if summary else None


def get_active_google_project_id() -> str | None:
    try:
        from app.database import session_scope

        with session_scope() as db:
            return get_google_project_id(db)
    except Exception:
        settings = get_settings()
        summary = service_account_summary_from_file(settings.google_application_credentials)
        return (summary or {}).get("project_id") or settings.google_cloud_project


def get_active_storage_settings() -> dict[str, Any]:
    settings = get_settings()
    try:
        from app.database import session_scope

        with session_scope() as db:
            bucket = get_gcs_bucket(db)
            credentials_path = get_google_service_account_path(db)
    except Exception:
        bucket = default_gcs_bucket()
        credentials_path = get_active_google_service_account_path()
    return {
        "gcs_bucket": bucket or None,
        "gcs_prefix": settings.gcs_prefix,
        "google_credentials_path": credentials_path,
    }


def get_app_preferences(db: Session) -> dict[str, Any]:
    analysis_models = get_analysis_models(db)
    gcs_bucket = get_gcs_bucket(db)
    return {
        "import_worker_concurrency": get_import_worker_concurrency(db),
        "recommended_import_worker_concurrency": RECOMMENDED_IMPORT_WORKER_CONCURRENCY,
        "import_worker_cost_warning_threshold": IMPORT_WORKER_COST_WARNING_THRESHOLD,
        "accent_color_day": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_DAY_KEY), DEFAULT_DAY_ACCENT),
        "accent_color_night": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_NIGHT_KEY), DEFAULT_NIGHT_ACCENT),
        "document_cache_size_mb": get_document_cache_size_mb(db),
        "library_alternating_rows": normalize_bool(_get_preference_value(db, LIBRARY_ALTERNATING_ROWS_KEY), True),
        "gcs_bucket": gcs_bucket,
        "gcs_bucket_saved": _has_preference(db, GCS_BUCKET_KEY),
        "analysis_models": analysis_models,
        "analysis_model_tasks": task_payloads(analysis_models),
        "model_options": model_options(analysis_models),
        **get_google_service_account_status(db),
    }


def update_app_preferences(
    db: Session,
    *,
    import_worker_concurrency: int | None = None,
    accent_color_day: str | None = None,
    accent_color_night: str | None = None,
    document_cache_size_mb: int | None = None,
    library_alternating_rows: bool | None = None,
    gcs_bucket: str | None = None,
    analysis_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    if import_worker_concurrency is not None:
        _set_preference_value(
            db,
            IMPORT_WORKER_CONCURRENCY_KEY,
            clamp_import_worker_concurrency(import_worker_concurrency),
        )
    if accent_color_day is not None:
        _set_preference_value(db, ACCENT_COLOR_DAY_KEY, normalize_hex_color(accent_color_day, DEFAULT_DAY_ACCENT))
    if accent_color_night is not None:
        _set_preference_value(db, ACCENT_COLOR_NIGHT_KEY, normalize_hex_color(accent_color_night, DEFAULT_NIGHT_ACCENT))
    if document_cache_size_mb is not None:
        _set_preference_value(db, DOCUMENT_CACHE_SIZE_MB_KEY, clamp_document_cache_size_mb(document_cache_size_mb))
    if library_alternating_rows is not None:
        _set_preference_value(db, LIBRARY_ALTERNATING_ROWS_KEY, bool(library_alternating_rows))
    if gcs_bucket is not None:
        _set_preference_value(db, GCS_BUCKET_KEY, normalize_gcs_bucket(gcs_bucket))
    if analysis_models is not None:
        for task in ANALYSIS_MODEL_TASKS:
            if task.key not in analysis_models:
                continue
            _set_preference_value(
                db,
                _analysis_model_preference_key(task.key),
                normalize_model_id(analysis_models.get(task.key), default_model_for_task(task.key)),
            )
    return get_app_preferences(db)


def store_google_service_account(db: Session, content: bytes, uploaded_filename: str | None = None) -> dict[str, Any]:
    summary = store_managed_service_account_json(content, uploaded_filename)
    _set_preference_value(
        db,
        GOOGLE_SERVICE_ACCOUNT_KEY,
        {
            **summary,
            "uploaded_at": utc_now().isoformat(),
        },
    )
    return get_app_preferences(db)
