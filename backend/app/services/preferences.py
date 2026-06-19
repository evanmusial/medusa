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


IMPORT_WORKER_CONCURRENCY_KEY = "import_worker_concurrency"
ACCENT_COLOR_DAY_KEY = "accent_color_day"
ACCENT_COLOR_NIGHT_KEY = "accent_color_night"
DOCUMENT_CACHE_SIZE_MB_KEY = "document_cache_size_mb"
ANALYSIS_MODEL_KEY_PREFIX = "analysis_model_"

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


def get_app_preferences(db: Session) -> dict[str, Any]:
    analysis_models = get_analysis_models(db)
    return {
        "import_worker_concurrency": get_import_worker_concurrency(db),
        "recommended_import_worker_concurrency": RECOMMENDED_IMPORT_WORKER_CONCURRENCY,
        "import_worker_cost_warning_threshold": IMPORT_WORKER_COST_WARNING_THRESHOLD,
        "accent_color_day": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_DAY_KEY), DEFAULT_DAY_ACCENT),
        "accent_color_night": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_NIGHT_KEY), DEFAULT_NIGHT_ACCENT),
        "document_cache_size_mb": get_document_cache_size_mb(db),
        "analysis_models": analysis_models,
        "analysis_model_tasks": task_payloads(analysis_models),
        "model_options": model_options(analysis_models),
    }


def update_app_preferences(
    db: Session,
    *,
    import_worker_concurrency: int | None = None,
    accent_color_day: str | None = None,
    accent_color_night: str | None = None,
    document_cache_size_mb: int | None = None,
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
