from __future__ import annotations

from copy import deepcopy
from math import ceil
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
from app.services.openai_usage import model_pricing_status
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
DOWNLOAD_NAMING_TEMPLATE_KEY = "download_naming_template"
CITATION_CONVENTION_KEY = "citation_convention"
ANALYSIS_MODEL_KEY_PREFIX = "analysis_model_"
GCS_BUCKET_KEY = "gcs_bucket"
GOOGLE_SERVICE_ACCOUNT_KEY = "google_service_account"
IMPORT_PROCESSING_PRESETS_KEY = "import_processing_presets"
DEFAULT_IMPORT_PROCESSING_PRESET_KEY = "default_import_processing_preset_id"
SECOND_PASS_PROCESSING_ENABLED_KEY = "second_pass_processing_enabled"

MIN_IMPORT_WORKER_CONCURRENCY = 1
RECOMMENDED_IMPORT_WORKER_CONCURRENCY = 4
IMPORT_WORKER_COST_WARNING_THRESHOLD = 4
DEFAULT_DOCUMENT_CACHE_SIZE_MB = 1024
DEFAULT_DAY_ACCENT = "#2563eb"
DEFAULT_NIGHT_ACCENT = "#6ea8ff"
DEFAULT_DOWNLOAD_NAMING_TEMPLATE = "$title ($year)"
CITATION_CONVENTION_APA_7 = "apa_7"
CITATION_CONVENTIONS = {CITATION_CONVENTION_APA_7}
DOWNLOAD_TEMPLATE_TOKENS = {"title", "year", "authors", "author", "pages"}
IMPORT_PROCESSING_BALANCED_ID = "balanced"
IMPORT_PROCESSING_STRICT_LOCAL_ID = "strict_local"
IMPORT_PROCESSING_DEEP_REVIEW_ID = "deep_review"
DEFAULT_IMPORT_PROCESSING_PRESET_ID = IMPORT_PROCESSING_BALANCED_ID

SAFE_PREFERENCE_KEYS = {
    IMPORT_WORKER_CONCURRENCY_KEY,
    ACCENT_COLOR_DAY_KEY,
    ACCENT_COLOR_NIGHT_KEY,
    DOCUMENT_CACHE_SIZE_MB_KEY,
    LIBRARY_ALTERNATING_ROWS_KEY,
    DOWNLOAD_NAMING_TEMPLATE_KEY,
    CITATION_CONVENTION_KEY,
    GCS_BUCKET_KEY,
    IMPORT_PROCESSING_PRESETS_KEY,
    DEFAULT_IMPORT_PROCESSING_PRESET_KEY,
    SECOND_PASS_PROCESSING_ENABLED_KEY,
    *(f"{ANALYSIS_MODEL_KEY_PREFIX}{task.key}" for task in ANALYSIS_MODEL_TASKS),
}

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DOWNLOAD_TEMPLATE_TOKEN_RE = re.compile(r"\$(title|year|authors|author|pages)\b")
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
PRESET_ID_RE = re.compile(r"[^a-z0-9_-]+")
RESERVED_WINDOWS_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

IMPORT_PROCESSING_STEPS: tuple[dict[str, Any], ...] = (
    {
        "key": "stage_upload",
        "label": "Stage Upload",
        "default_enabled": True,
        "configurable": False,
        "description": "Hashes the uploaded file, checks duplicate checksums, stores the original, creates durable staged queue rows, and records the selected processing preset snapshot.",
        "accomplishes": "Makes the upload resumable and keeps later Settings edits from changing queued work.",
    },
    {
        "key": "raw_text_extraction",
        "label": "Raw Text Extraction",
        "default_enabled": True,
        "configurable": True,
        "description": "Extracts raw page text with the selected local extractor, using Marker by default and PyMuPDF as the fallback.",
        "accomplishes": "Preserves raw page text as the source evidence before cleanup, normalization, search, and enrichment.",
    },
    {
        "key": "document_structure_cleanup",
        "label": "Structure Cleanup",
        "default_enabled": True,
        "configurable": True,
        "description": "Runs deterministic cleanup for repeated headers and footers, page numbers, whitespace, wrapped lines, bullets, drop caps, decorative text art, and obvious front matter noise.",
        "accomplishes": "Produces cleaner body text while storing removed boilerplate separately for audit and retry.",
    },
    {
        "key": "ocr_fallback",
        "label": "OCR Fallback",
        "default_enabled": True,
        "configurable": True,
        "description": "Audits low-text or scanned pages for OCR eligibility under the selected preset; Google Vision execution is still pending integration.",
        "accomplishes": "Identifies pages that need OCR without adding provider cost until the OCR retry loop is wired.",
    },
    {
        "key": "page_text_normalization",
        "label": "Page Normalization",
        "default_enabled": True,
        "configurable": True,
        "description": "Locally normalizes clean pages and escalates only flagged pages to the selected cheap model, subject to the preset cap.",
        "accomplishes": "Repairs page reading flow without repeatedly sending whole PDFs through cloud models.",
    },
    {
        "key": "structured_tables",
        "label": "Structured Tables",
        "default_enabled": True,
        "configurable": True,
        "description": "Detects table-like regions as cleanup evidence; first-class table rows, cells, captions, and page regions are still planned.",
        "accomplishes": "Keeps table evidence visible for audit while richer table persistence is built.",
    },
    {
        "key": "visual_asset_extraction",
        "label": "Visual Assets",
        "default_enabled": True,
        "configurable": True,
        "description": "Extracts embedded images, page image regions, vector charts, diagrams, photos, maps, scans, and table-like visual regions as cropped assets.",
        "accomplishes": "Creates durable figure assets with page geometry, orientation hints, captions, and extraction warnings.",
    },
    {
        "key": "visual_asset_context",
        "label": "Visual Context",
        "default_enabled": True,
        "configurable": True,
        "description": "Links figures to local captions, nearby text, and explicit mentions such as Figure 2; cropped-region visual model calls are still pending.",
        "accomplishes": "Gives each extracted visual local document context now, with visual gists and model-backed review still planned.",
    },
    {
        "key": "bibliography_extraction",
        "label": "Bibliography",
        "default_enabled": True,
        "configurable": True,
        "description": "Detects references, bibliography, and works-cited sections and stores the document's own reference list as one normalized Bibliography source per line.",
        "accomplishes": "Keeps source reference lists searchable and editable without source-list numbering, generated APA citation text, or project bibliographies getting mixed together.",
    },
    {
        "key": "metadata",
        "label": "Metadata",
        "default_enabled": True,
        "configurable": True,
        "description": "Extracts or fills scholarly identity fields such as title, authors, year, venue, DOI, abstract, and source evidence after text and assets are available.",
        "accomplishes": "Gives citations, search, summaries, and organization surfaces reliable document identity without treating weak model output as verified metadata.",
    },
    {
        "key": "summary",
        "label": "Summary",
        "default_enabled": True,
        "configurable": True,
        "description": "Generates the main paragraph-style research summary from extracted text using the selected summary model.",
        "accomplishes": "Provides a readable technical overview while keeping summary generation on a cheaper routed model than citation-critical work.",
    },
    {
        "key": "apa_citation",
        "label": "APA Citation",
        "default_enabled": True,
        "configurable": True,
        "description": "Builds citation metadata from DOI and Crossref evidence first, then uses the selected APA model only for fallback judgment or uncertain candidate generation.",
        "accomplishes": "Keeps verified citations evidence-backed and sends only uncertain citation work to a model-backed review path.",
    },
    {
        "key": "keywords_topics",
        "label": "Tag Suggestions",
        "default_enabled": True,
        "configurable": True,
        "description": "Suggests candidate tags from extracted text using the selected tag model and the existing-tag manifest, then passes results through governance scoring.",
        "accomplishes": "Prefers reusable library tags and records weak candidates without silently expanding the taxonomy.",
    },
    {
        "key": "text_chunk_encoding",
        "label": "Text Chunk Encoding",
        "default_enabled": True,
        "configurable": True,
        "description": "Chunks cleaned text and sends chunk text to the selected embedding model for semantic/vector search.",
        "accomplishes": "Makes the imported document discoverable through search and related-document workflows.",
    },
    {
        "key": "composition_ledger",
        "label": "Composition Ledger",
        "default_enabled": True,
        "configurable": False,
        "description": "Records preset-aware import estimates, local stage timings, model/provider choices, token and file-context usage, warnings, failures, and actual costs when calls occur.",
        "accomplishes": "Makes the quality/cost tradeoff visible on staged rows, Composition, Budget & Costs, and Concordance evidence.",
    },
)

_IMPORT_PROCESSING_BUILT_INS: tuple[dict[str, Any], ...] = (
    {
        "id": IMPORT_PROCESSING_BALANCED_ID,
        "name": "Balanced",
        "mode": "balanced",
        "built_in": True,
        "description": "Default local-first processing with capped cheap model escalation for pages or cropped regions that need help.",
        "cleanup": {
            "enabled": True,
            "deterministic": True,
            "cloud_escalation": True,
            "model": "gpt-5.4-mini",
            "fallback_model": "gemini-3.1-flash-lite",
            "remove_headers_footers": True,
            "remove_page_numbers": True,
            "normalize_whitespace": True,
            "repair_line_wraps": True,
            "repair_bullets": True,
            "repair_drop_caps": True,
            "remove_text_art": True,
            "front_matter_noise": True,
            "page_cap_min": 6,
            "page_cap_percent": 15,
        },
        "ocr": {"enabled": True, "low_text_only": True, "provider": "google_vision", "min_text_characters": 120},
        "structured_tables": {"enabled": True, "local_detection": True},
        "bibliography": {"enabled": True, "preserve_italics": True},
        "visuals": {
            "enabled": True,
            "audit_enabled": True,
            "context_enabled": True,
            "local_multi_pass": True,
            "model": "gemini-3.1-flash-lite",
            "fallback_model": "gpt-5.4-mini",
            "crop_only": True,
            "premium_model_allowed": False,
        },
        "cost": {"max_cloud_cleanup_pages_min": 6, "max_cloud_cleanup_page_percent": 15, "visual_model_calls": "cropped_regions_only"},
    },
    {
        "id": IMPORT_PROCESSING_STRICT_LOCAL_ID,
        "name": "Strict Local",
        "mode": "strict_local",
        "built_in": True,
        "description": "No cloud cleanup, no cloud visual gists, and no cloud OCR; keeps deterministic cleanup and local extraction/audit only.",
        "cleanup": {
            "enabled": True,
            "deterministic": True,
            "cloud_escalation": False,
            "model": "local",
            "fallback_model": "local",
            "remove_headers_footers": True,
            "remove_page_numbers": True,
            "normalize_whitespace": True,
            "repair_line_wraps": True,
            "repair_bullets": True,
            "repair_drop_caps": True,
            "remove_text_art": True,
            "front_matter_noise": True,
            "page_cap_min": 0,
            "page_cap_percent": 0,
        },
        "ocr": {"enabled": False, "low_text_only": True, "provider": "none", "min_text_characters": 120},
        "structured_tables": {"enabled": True, "local_detection": True},
        "bibliography": {"enabled": True, "preserve_italics": True},
        "visuals": {
            "enabled": True,
            "audit_enabled": True,
            "context_enabled": True,
            "local_multi_pass": True,
            "model": "local",
            "fallback_model": "local",
            "crop_only": True,
            "premium_model_allowed": False,
        },
        "cost": {"max_cloud_cleanup_pages_min": 0, "max_cloud_cleanup_page_percent": 0, "visual_model_calls": "none"},
    },
    {
        "id": IMPORT_PROCESSING_DEEP_REVIEW_ID,
        "name": "Deep Review",
        "mode": "deep_review",
        "built_in": True,
        "description": "Explicit high-quality processing with stronger models, higher caps, OCR fallback, and premium visual/document review allowed.",
        "cleanup": {
            "enabled": True,
            "deterministic": True,
            "cloud_escalation": True,
            "model": "gpt-5.4",
            "fallback_model": "gemini-2.5-flash",
            "remove_headers_footers": True,
            "remove_page_numbers": True,
            "normalize_whitespace": True,
            "repair_line_wraps": True,
            "repair_bullets": True,
            "repair_drop_caps": True,
            "remove_text_art": True,
            "front_matter_noise": True,
            "page_cap_min": 20,
            "page_cap_percent": 45,
        },
        "ocr": {"enabled": True, "low_text_only": True, "provider": "google_vision", "min_text_characters": 120},
        "structured_tables": {"enabled": True, "local_detection": True},
        "bibliography": {"enabled": True, "preserve_italics": True},
        "visuals": {
            "enabled": True,
            "audit_enabled": True,
            "context_enabled": True,
            "local_multi_pass": True,
            "model": "gemini-2.5-flash",
            "fallback_model": "gpt-5.4",
            "crop_only": True,
            "premium_model_allowed": True,
            "premium_model": "gpt-5.5",
        },
        "cost": {"max_cloud_cleanup_pages_min": 20, "max_cloud_cleanup_page_percent": 45, "visual_model_calls": "cropped_regions_only"},
    },
)


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


def normalize_import_processing_preset_id(value: Any, default: str = DEFAULT_IMPORT_PROCESSING_PRESET_ID) -> str:
    if not isinstance(value, str):
        return default
    candidate = PRESET_ID_RE.sub("_", value.strip().lower()).strip("_-")
    return candidate[:80] or default


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_percent(value: Any, *, default: int) -> int:
    return _bounded_int(value, default=default, minimum=0, maximum=100)


def _merge_dict(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = deepcopy(defaults)
    if not isinstance(value, dict):
        return merged
    for key, incoming in value.items():
        if isinstance(incoming, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], incoming)
        else:
            merged[key] = incoming
    return merged


def built_in_import_processing_presets() -> list[dict[str, Any]]:
    return [deepcopy(preset) for preset in _IMPORT_PROCESSING_BUILT_INS]


def import_processing_steps() -> list[dict[str, Any]]:
    return [
        {
            **step,
            "tooltip": f"{step['description']} Accomplishes: {step['accomplishes']}",
        }
        for step in IMPORT_PROCESSING_STEPS
    ]


def _preset_by_id(presets: list[dict[str, Any]], preset_id: str) -> dict[str, Any] | None:
    return next((preset for preset in presets if preset.get("id") == preset_id), None)


def _normalize_custom_import_processing_preset(value: Any, *, used_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_name = value.get("name")
    name = " ".join(str(raw_name or "").split())[:120] or "Custom preset"
    raw_id = value.get("id") or name
    preset_id = normalize_import_processing_preset_id(raw_id, default="custom")
    if preset_id in {IMPORT_PROCESSING_BALANCED_ID, IMPORT_PROCESSING_STRICT_LOCAL_ID, IMPORT_PROCESSING_DEEP_REVIEW_ID}:
        return None
    if not preset_id.startswith("custom_") and not preset_id.startswith("custom-"):
        preset_id = f"custom_{preset_id}"
    base = deepcopy(_IMPORT_PROCESSING_BUILT_INS[0])
    merged = _merge_dict(base, value)
    suffix = 2
    unique_id = preset_id
    while unique_id in used_ids:
        unique_id = f"{preset_id}_{suffix}"
        suffix += 1
    cleanup = merged.get("cleanup") if isinstance(merged.get("cleanup"), dict) else {}
    cost = merged.get("cost") if isinstance(merged.get("cost"), dict) else {}
    visuals = merged.get("visuals") if isinstance(merged.get("visuals"), dict) else {}
    ocr = merged.get("ocr") if isinstance(merged.get("ocr"), dict) else {}
    tables = merged.get("structured_tables") if isinstance(merged.get("structured_tables"), dict) else {}
    bibliography = merged.get("bibliography") if isinstance(merged.get("bibliography"), dict) else {}
    cleanup_page_cap_min = _bounded_int(
        cleanup.get("page_cap_min", cost.get("max_cloud_cleanup_pages_min")),
        default=6,
        minimum=0,
        maximum=500,
    )
    cleanup_page_cap_percent = _bounded_percent(
        cleanup.get("page_cap_percent", cost.get("max_cloud_cleanup_page_percent")),
        default=15,
    )
    normalized = {
        "id": unique_id,
        "name": name,
        "mode": str(merged.get("mode") or "custom").strip().lower()[:80] or "custom",
        "built_in": False,
        "description": " ".join(str(merged.get("description") or "Custom import processing preset.").split())[:280],
        "cleanup": {
            "enabled": normalize_bool(cleanup.get("enabled"), True),
            "deterministic": normalize_bool(cleanup.get("deterministic"), True),
            "cloud_escalation": normalize_bool(cleanup.get("cloud_escalation"), True),
            "model": normalize_model_id(cleanup.get("model"), "gpt-5.4-mini"),
            "fallback_model": normalize_model_id(cleanup.get("fallback_model"), "gemini-3.1-flash-lite"),
            "remove_headers_footers": normalize_bool(cleanup.get("remove_headers_footers"), True),
            "remove_page_numbers": normalize_bool(cleanup.get("remove_page_numbers"), True),
            "normalize_whitespace": normalize_bool(cleanup.get("normalize_whitespace"), True),
            "repair_line_wraps": normalize_bool(cleanup.get("repair_line_wraps"), True),
            "repair_bullets": normalize_bool(cleanup.get("repair_bullets"), True),
            "repair_drop_caps": normalize_bool(cleanup.get("repair_drop_caps"), True),
            "remove_text_art": normalize_bool(cleanup.get("remove_text_art"), True),
            "front_matter_noise": normalize_bool(cleanup.get("front_matter_noise"), True),
            "page_cap_min": cleanup_page_cap_min,
            "page_cap_percent": cleanup_page_cap_percent,
        },
        "ocr": {
            "enabled": normalize_bool(ocr.get("enabled"), True),
            "low_text_only": normalize_bool(ocr.get("low_text_only"), True),
            "provider": str(ocr.get("provider") or "google_vision").strip().lower()[:80],
            "min_text_characters": _bounded_int(ocr.get("min_text_characters"), default=120, minimum=0, maximum=2000),
        },
        "structured_tables": {
            "enabled": normalize_bool(tables.get("enabled"), True),
            "local_detection": normalize_bool(tables.get("local_detection"), True),
        },
        "bibliography": {
            "enabled": normalize_bool(bibliography.get("enabled"), True),
            "preserve_italics": normalize_bool(bibliography.get("preserve_italics"), True),
        },
        "visuals": {
            "enabled": normalize_bool(visuals.get("enabled"), True),
            "audit_enabled": normalize_bool(visuals.get("audit_enabled"), True),
            "context_enabled": normalize_bool(visuals.get("context_enabled"), True),
            "local_multi_pass": normalize_bool(visuals.get("local_multi_pass"), True),
            "model": normalize_model_id(visuals.get("model"), "gemini-3.1-flash-lite"),
            "fallback_model": normalize_model_id(visuals.get("fallback_model"), "gpt-5.4-mini"),
            "crop_only": normalize_bool(visuals.get("crop_only"), True),
            "premium_model_allowed": normalize_bool(visuals.get("premium_model_allowed"), False),
            "premium_model": normalize_model_id(visuals.get("premium_model"), "gpt-5.5"),
        },
        "cost": {
            "max_cloud_cleanup_pages_min": cleanup_page_cap_min,
            "max_cloud_cleanup_page_percent": cleanup_page_cap_percent,
            "visual_model_calls": str(cost.get("visual_model_calls") or "cropped_regions_only").strip()[:80],
        },
    }
    used_ids.add(unique_id)
    return normalized


def normalize_import_processing_presets(value: Any) -> list[dict[str, Any]]:
    presets = built_in_import_processing_presets()
    used_ids = {preset["id"] for preset in presets}
    raw_presets = value if isinstance(value, list) else []
    for raw_preset in raw_presets:
        preset = _normalize_custom_import_processing_preset(raw_preset, used_ids=used_ids)
        if preset:
            presets.append(preset)
        if len(presets) >= 27:
            break
    return presets


def import_processing_cloud_page_cap(preset: dict[str, Any], page_count: int) -> int:
    cleanup = preset.get("cleanup") if isinstance(preset.get("cleanup"), dict) else {}
    if not normalize_bool(cleanup.get("cloud_escalation"), True):
        return 0
    min_pages = _bounded_int(cleanup.get("page_cap_min"), default=6, minimum=0, maximum=500)
    percent = _bounded_percent(cleanup.get("page_cap_percent"), default=15)
    return max(min_pages, ceil(max(0, page_count) * percent / 100))


def normalize_download_naming_template(value: Any) -> str:
    if not isinstance(value, str):
        return DEFAULT_DOWNLOAD_NAMING_TEMPLATE
    candidate = " ".join(value.replace("\x00", "").split()).strip()
    return candidate[:240] or DEFAULT_DOWNLOAD_NAMING_TEMPLATE


def normalize_citation_convention(value: Any) -> str:
    if isinstance(value, str) and value.strip() in CITATION_CONVENTIONS:
        return value.strip()
    return CITATION_CONVENTION_APA_7


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


def get_download_naming_template(db: Session) -> str:
    return normalize_download_naming_template(_get_preference_value(db, DOWNLOAD_NAMING_TEMPLATE_KEY))


def get_citation_convention(db: Session) -> str:
    return normalize_citation_convention(_get_preference_value(db, CITATION_CONVENTION_KEY))


def get_second_pass_processing_enabled(db: Session) -> bool:
    return normalize_bool(_get_preference_value(db, SECOND_PASS_PROCESSING_ENABLED_KEY), get_settings().second_pass_processing_enabled)


def get_import_processing_presets(db: Session) -> list[dict[str, Any]]:
    return normalize_import_processing_presets(_get_preference_value(db, IMPORT_PROCESSING_PRESETS_KEY))


def get_default_import_processing_preset_id(db: Session) -> str:
    presets = get_import_processing_presets(db)
    preset_ids = {preset["id"] for preset in presets}
    candidate = normalize_import_processing_preset_id(
        _get_preference_value(db, DEFAULT_IMPORT_PROCESSING_PRESET_KEY),
        DEFAULT_IMPORT_PROCESSING_PRESET_ID,
    )
    return candidate if candidate in preset_ids else DEFAULT_IMPORT_PROCESSING_PRESET_ID


def get_import_processing_preset(db: Session, preset_id: str | None = None) -> dict[str, Any]:
    presets = get_import_processing_presets(db)
    selected_id = normalize_import_processing_preset_id(preset_id, get_default_import_processing_preset_id(db))
    preset = _preset_by_id(presets, selected_id) or _preset_by_id(presets, DEFAULT_IMPORT_PROCESSING_PRESET_ID) or presets[0]
    return deepcopy(preset)


def import_processing_snapshot(db: Session, preset_id: str | None = None) -> dict[str, Any]:
    preset = get_import_processing_preset(db, preset_id)
    return {
        **preset,
        "snapshot_version": 1,
        "snapshot_at": utc_now().isoformat(),
        "second_pass_enabled": get_second_pass_processing_enabled(db),
    }


def author_display_name(author: Any) -> str:
    if isinstance(author, str):
        return " ".join(author.split())
    if not isinstance(author, dict):
        return ""
    explicit_name = author.get("name")
    if isinstance(explicit_name, str) and explicit_name.strip():
        return " ".join(explicit_name.split())
    parts = [author.get("given"), author.get("family")]
    return " ".join(str(part).strip() for part in parts if isinstance(part, str) and part.strip())


def sanitize_download_filename_stem(value: str) -> str:
    candidate = INVALID_FILENAME_CHARS_RE.sub("_", value)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")
    candidate = re.sub(r"_+", "_", candidate).strip("_ ")
    if candidate.lower().endswith(".pdf"):
        candidate = candidate[:-4].rstrip(" ._")
    if not candidate:
        candidate = "document"
    if candidate.upper() in RESERVED_WINDOWS_FILENAMES:
        candidate = f"{candidate}_"
    candidate = candidate[:180].rstrip(" .") or "document"
    if candidate.upper() in RESERVED_WINDOWS_FILENAMES:
        candidate = f"{candidate}_"
    return candidate


def render_download_filename(document: Any, template: str | None = None) -> str:
    template = normalize_download_naming_template(template or DEFAULT_DOWNLOAD_NAMING_TEMPLATE)
    authors = [author_display_name(author) for author in (getattr(document, "authors", None) or [])]
    authors = [author for author in authors if author]
    replacements = {
        "title": getattr(document, "title", None) or original_filename_stem(getattr(document, "original_filename", None)) or "Untitled document",
        "year": str(getattr(document, "publication_year", None) or "n.d."),
        "authors": ", ".join(authors) or "Unknown author",
        "author": authors[0] if authors else "Unknown author",
        "pages": str(getattr(document, "page_count", None) or ""),
    }

    def replace_token(match: re.Match[str]) -> str:
        return replacements.get(match.group(1), "")

    stem = sanitize_download_filename_stem(DOWNLOAD_TEMPLATE_TOKEN_RE.sub(replace_token, template))
    return f"{stem}.pdf"


def original_filename_stem(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".pdf").strip()


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
    import_processing_presets = get_import_processing_presets(db)
    return {
        "import_worker_concurrency": get_import_worker_concurrency(db),
        "recommended_import_worker_concurrency": RECOMMENDED_IMPORT_WORKER_CONCURRENCY,
        "import_worker_cost_warning_threshold": IMPORT_WORKER_COST_WARNING_THRESHOLD,
        "accent_color_day": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_DAY_KEY), DEFAULT_DAY_ACCENT),
        "accent_color_night": normalize_hex_color(_get_preference_value(db, ACCENT_COLOR_NIGHT_KEY), DEFAULT_NIGHT_ACCENT),
        "document_cache_size_mb": get_document_cache_size_mb(db),
        "library_alternating_rows": normalize_bool(_get_preference_value(db, LIBRARY_ALTERNATING_ROWS_KEY), True),
        "download_naming_template": get_download_naming_template(db),
        "citation_convention": get_citation_convention(db),
        "gcs_bucket": gcs_bucket,
        "gcs_bucket_saved": _has_preference(db, GCS_BUCKET_KEY),
        "analysis_models": analysis_models,
        "analysis_model_tasks": task_payloads(analysis_models),
        "model_options": model_options(analysis_models),
        "model_pricing": model_pricing_status(db),
        "import_processing_presets": import_processing_presets,
        "default_import_processing_preset_id": get_default_import_processing_preset_id(db),
        "import_processing_steps": import_processing_steps(),
        "second_pass_processing_enabled": get_second_pass_processing_enabled(db),
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
    download_naming_template: str | None = None,
    citation_convention: str | None = None,
    gcs_bucket: str | None = None,
    analysis_models: dict[str, str] | None = None,
    import_processing_presets: list[dict[str, Any]] | None = None,
    default_import_processing_preset_id: str | None = None,
    second_pass_processing_enabled: bool | None = None,
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
    if download_naming_template is not None:
        _set_preference_value(db, DOWNLOAD_NAMING_TEMPLATE_KEY, normalize_download_naming_template(download_naming_template))
    if citation_convention is not None:
        _set_preference_value(db, CITATION_CONVENTION_KEY, normalize_citation_convention(citation_convention))
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
    if import_processing_presets is not None:
        normalized_presets = normalize_import_processing_presets(import_processing_presets)
        custom_presets = [preset for preset in normalized_presets if not preset.get("built_in")]
        _set_preference_value(db, IMPORT_PROCESSING_PRESETS_KEY, custom_presets)
    if default_import_processing_preset_id is not None:
        presets = get_import_processing_presets(db)
        candidate = normalize_import_processing_preset_id(default_import_processing_preset_id)
        if not _preset_by_id(presets, candidate):
            candidate = DEFAULT_IMPORT_PROCESSING_PRESET_ID
        _set_preference_value(db, DEFAULT_IMPORT_PROCESSING_PRESET_KEY, candidate)
    if second_pass_processing_enabled is not None:
        _set_preference_value(db, SECOND_PASS_PROCESSING_ENABLED_KEY, bool(second_pass_processing_enabled))
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
