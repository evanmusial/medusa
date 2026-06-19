from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppPreference, utc_now


IMPORT_WORKER_CONCURRENCY_KEY = "import_worker_concurrency"
ACCENT_COLOR_DAY_KEY = "accent_color_day"
ACCENT_COLOR_NIGHT_KEY = "accent_color_night"

MIN_IMPORT_WORKER_CONCURRENCY = 1
RECOMMENDED_IMPORT_WORKER_CONCURRENCY = 4
IMPORT_WORKER_COST_WARNING_THRESHOLD = 4
DEFAULT_DAY_ACCENT = "#2563eb"
DEFAULT_NIGHT_ACCENT = "#6ea8ff"

SAFE_PREFERENCE_KEYS = {
    IMPORT_WORKER_CONCURRENCY_KEY,
    ACCENT_COLOR_DAY_KEY,
    ACCENT_COLOR_NIGHT_KEY,
}

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def clamp_import_worker_concurrency(value: Any, default: int = MIN_IMPORT_WORKER_CONCURRENCY) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_IMPORT_WORKER_CONCURRENCY, parsed)


def normalize_hex_color(value: Any, default: str) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if HEX_COLOR_RE.match(candidate):
            return candidate.lower()
    return default


def default_import_worker_concurrency() -> int:
    return clamp_import_worker_concurrency(get_settings().worker_import_concurrency)


def _stored_preference_value(preference: AppPreference | None) -> Any:
    if not preference:
        return None
    raw_value = preference.value or {}
    return raw_value.get("value") if isinstance(raw_value, dict) else None


def _get_preference_value(db: Session, key: str) -> Any:
    return _stored_preference_value(db.get(AppPreference, key))


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


def get_app_preferences(db: Session) -> dict[str, int | str]:
    return {
        "import_worker_concurrency": get_import_worker_concurrency(db),
        "recommended_import_worker_concurrency": RECOMMENDED_IMPORT_WORKER_CONCURRENCY,
        "import_worker_cost_warning_threshold": IMPORT_WORKER_COST_WARNING_THRESHOLD,
        "accent_color_day": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_DAY_KEY), DEFAULT_DAY_ACCENT),
        "accent_color_night": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_NIGHT_KEY), DEFAULT_NIGHT_ACCENT),
    }


def update_app_preferences(
    db: Session,
    *,
    import_worker_concurrency: int | None = None,
    accent_color_day: str | None = None,
    accent_color_night: str | None = None,
) -> dict[str, int | str]:
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
    return get_app_preferences(db)
