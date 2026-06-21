from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import session_scope
from app.models import Document, ModelPricingRecord, OpenAIUsageRecord


logger = logging.getLogger(__name__)

UsageRecorder = Callable[[dict[str, Any]], None]
USAGE_PERIODS: dict[str, timedelta | None] = {
    "last_day": timedelta(days=1),
    "last_month": timedelta(days=30),
    "last_3_months": timedelta(days=90),
    "all_time": None,
}
PRICE_SOURCE_URL = "https://developers.openai.com/api/docs/pricing"
GOOGLE_PRICE_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/pricing"
PRICE_UPDATED_AT = "2026-06-21"
PRICE_STALE_AFTER_DAYS = 2
PRICE_BASIS = (
    "OpenAI standard API/model-page pricing for enabled GPT model families and embeddings plus Google Gemini "
    "Developer API paid-tier standard text token pricing per 1M tokens; historical rows are used when available, "
    "and unrecognized models are left unpriced."
)
PRICE_RATE_KEYS = (
    "input",
    "cached_input",
    "output",
    "input_over_200k",
    "cached_input_over_200k",
    "output_over_200k",
)
CURRENT_MODEL_TOKEN_PRICES_USD_PER_MILLION: dict[str, dict[str, float | None]] = {
    "gpt-4o": {"input": 2.5, "cached_input": 1.25, "output": 10.0},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0},
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.4},
    "gpt-5-pro": {"input": 15.0, "cached_input": None, "output": 120.0},
    "gpt-5.1": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.0},
    "gpt-5.2-pro": {"input": 21.0, "cached_input": None, "output": 168.0},
    "gpt-5.5": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
    "gpt-5.5-pro": {"input": 30.0, "cached_input": None, "output": 180.0},
    "gpt-5.4": {"input": 2.5, "cached_input": 0.25, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.5},
    "gpt-5.4-nano": {"input": 0.2, "cached_input": 0.02, "output": 1.25},
    "gpt-5.4-pro": {"input": 30.0, "cached_input": None, "output": 180.0},
    "text-embedding-3-small": {"input": 0.02, "cached_input": None, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "cached_input": None, "output": 0.0},
    "text-embedding-ada-002": {"input": 0.1, "cached_input": None, "output": 0.0},
    "gemini-3.1-flash-lite": {"input": 0.25, "cached_input": 0.025, "output": 1.5},
    "gemini-2.5-pro": {
        "input": 1.25,
        "cached_input": 0.125,
        "output": 10.0,
        "input_over_200k": 2.5,
        "cached_input_over_200k": 0.25,
        "output_over_200k": 15.0,
    },
    "gemini-2.5-flash": {"input": 0.3, "cached_input": 0.03, "output": 2.5},
    "gemini-2.5-flash-lite": {"input": 0.1, "cached_input": 0.01, "output": 0.4},
}
LEGACY_MODEL_TOKEN_PRICES_USD_PER_MILLION: dict[str, dict[str, float | None]] = {
    "gemini-3.5-flash": {"input": 1.5, "cached_input": 0.15, "output": 9.0},
    "gemini-2.0-flash": {"input": 0.1, "cached_input": 0.025, "output": 0.4},
    "gemini-2.0-flash-lite": {"input": 0.075, "cached_input": None, "output": 0.3},
}
MODEL_TOKEN_PRICES_USD_PER_MILLION: dict[str, dict[str, float | None]] = {
    **CURRENT_MODEL_TOKEN_PRICES_USD_PER_MILLION,
    **LEGACY_MODEL_TOKEN_PRICES_USD_PER_MILLION,
}
MODEL_PRICE_ALIASES = {
    "gemini-2.0-flash-001": "gemini-2.0-flash",
    "gemini-2.0-flash-lite-001": "gemini-2.0-flash-lite",
    "gemini-flash-latest": "gemini-2.5-flash",
    "gemini-flash-lite-latest": "gemini-3.1-flash-lite",
    "gemini-pro-latest": "gemini-2.5-pro",
}


@dataclass(frozen=True)
class OpenAIUsageContext:
    document_id: str | None = None
    import_job_id: str | None = None
    concordance_run_id: str | None = None
    concordance_job_id: str | None = None
    source: str | None = None
    capability_key: str | None = None
    page_number: int | None = None
    recorder: UsageRecorder | None = None

    def for_page(self, page_number: int) -> "OpenAIUsageContext":
        return replace(self, page_number=page_number)


def _value(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _int_value(source: Any, key: str) -> int:
    value = _value(source, key, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _nested_int(source: Any, parent_key: str, key: str) -> int:
    return _int_value(_value(source, parent_key), key)


def _text_length(response: Any) -> int:
    output_text = _value(response, "output_text")
    return len(output_text) if isinstance(output_text, str) else 0


def _request_id(response: Any) -> str | None:
    value = _value(response, "id") or _value(response, "_request_id") or _value(response, "request_id")
    return str(value) if value else None


def _usage_metadata(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        try:
            return usage.model_dump()
        except Exception:
            pass
    return {
        key: value
        for key in dir(usage)
        if not key.startswith("_") and not callable(value := getattr(usage, key, None))
    }


def build_openai_usage_record(
    *,
    context: OpenAIUsageContext | None,
    task_key: str,
    operation: str,
    endpoint: str,
    model: str,
    status: str,
    provider: str = "openai",
    response: Any | None = None,
    error: Exception | str | None = None,
    input_text_characters: int = 0,
    input_file_bytes: int = 0,
    used_pdf_file: bool = False,
) -> dict[str, Any]:
    usage = _value(response, "usage")
    input_tokens = _int_value(usage, "input_tokens") or _int_value(usage, "prompt_tokens")
    output_tokens = _int_value(usage, "output_tokens") or _int_value(usage, "completion_tokens")
    total_tokens = _int_value(usage, "total_tokens")
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "document_id": context.document_id if context else None,
        "import_job_id": context.import_job_id if context else None,
        "concordance_run_id": context.concordance_run_id if context else None,
        "concordance_job_id": context.concordance_job_id if context else None,
        "source": context.source if context else None,
        "capability_key": context.capability_key if context else None,
        "page_number": context.page_number if context else None,
        "task_key": task_key,
        "operation": operation,
        "provider": provider,
        "endpoint": endpoint,
        "model": model,
        "status": status,
        "request_id": _request_id(response),
        "used_pdf_file": used_pdf_file,
        "input_file_bytes": max(0, int(input_file_bytes or 0)),
        "input_text_characters": max(0, int(input_text_characters or 0)),
        "output_text_characters": _text_length(response),
        "input_tokens": input_tokens,
        "cached_input_tokens": _nested_int(usage, "input_tokens_details", "cached_tokens")
        or _nested_int(usage, "prompt_tokens_details", "cached_tokens"),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": _nested_int(usage, "output_tokens_details", "reasoning_tokens")
        or _nested_int(usage, "completion_tokens_details", "reasoning_tokens"),
        "total_tokens": total_tokens,
        "error_message": str(error)[:2000] if error else None,
        "usage_metadata": _usage_metadata(usage),
    }


def persist_openai_usage(record: dict[str, Any]) -> None:
    try:
        with session_scope() as db:
            db.add(OpenAIUsageRecord(**record))
    except Exception:
        logger.warning("Could not persist OpenAI usage record", exc_info=True)


def record_openai_usage(
    context: OpenAIUsageContext | None,
    *,
    task_key: str,
    operation: str,
    endpoint: str,
    model: str,
    status: str,
    provider: str = "openai",
    response: Any | None = None,
    error: Exception | str | None = None,
    input_text_characters: int = 0,
    input_file_bytes: int = 0,
    used_pdf_file: bool = False,
) -> None:
    if context is None:
        return
    record = build_openai_usage_record(
        context=context,
        task_key=task_key,
        operation=operation,
        endpoint=endpoint,
        model=model,
        status=status,
        provider=provider,
        response=response,
        error=error,
        input_text_characters=input_text_characters,
        input_file_bytes=input_file_bytes,
        used_pdf_file=used_pdf_file,
    )
    if context.recorder:
        context.recorder(record)
        return
    persist_openai_usage(record)


def _coalesced_sum(column) -> int:
    return int(column or 0)


def _period_start(period: str) -> datetime | None:
    delta = USAGE_PERIODS.get(period)
    if delta is None:
        return None
    return datetime.now(timezone.utc) - delta


def _apply_period(query, period: str):
    since = _period_start(period)
    if since is None:
        return query
    return query.filter(OpenAIUsageRecord.created_at >= since)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _source_observed_at() -> datetime:
    return datetime.fromisoformat(f"{PRICE_UPDATED_AT}T00:00:00+00:00")


def _provider_for_model(model: str | None, provider: str | None = None) -> str:
    if provider:
        return provider
    if isinstance(model, str) and model.strip().startswith("gemini-"):
        return "google"
    return "openai"


def _source_url_for_provider(provider: str) -> str:
    return GOOGLE_PRICE_SOURCE_URL if provider == "google" else PRICE_SOURCE_URL


def _canonical_model_id(model: str | None) -> str | None:
    if not model:
        return None
    model_id = model.strip()
    model_id = MODEL_PRICE_ALIASES.get(model_id, model_id)
    if model_id in MODEL_TOKEN_PRICES_USD_PER_MILLION:
        return model_id
    for prefix in sorted(MODEL_TOKEN_PRICES_USD_PER_MILLION, key=len, reverse=True):
        if model_id.startswith(f"{prefix}-20"):
            return prefix
    return model_id


def _pricing_for_model(model: str | None) -> dict[str, float | None] | None:
    canonical = _canonical_model_id(model)
    if not canonical:
        return None
    return MODEL_TOKEN_PRICES_USD_PER_MILLION.get(canonical)


def _rate(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _price_signature(pricing: dict[str, float | None]) -> tuple[float | None, ...]:
    return tuple(_rate(pricing.get(key)) for key in PRICE_RATE_KEYS)


def _record_price_signature(record: ModelPricingRecord) -> tuple[float | None, ...]:
    return (
        _rate(record.input_usd_per_million),
        _rate(record.cached_input_usd_per_million),
        _rate(record.output_usd_per_million),
        _rate(record.input_over_200k_usd_per_million),
        _rate(record.cached_input_over_200k_usd_per_million),
        _rate(record.output_over_200k_usd_per_million),
    )


def _pricing_from_record(record: ModelPricingRecord) -> dict[str, float | None]:
    return {
        "input": _rate(record.input_usd_per_million),
        "cached_input": _rate(record.cached_input_usd_per_million),
        "output": _rate(record.output_usd_per_million),
        "input_over_200k": _rate(record.input_over_200k_usd_per_million),
        "cached_input_over_200k": _rate(record.cached_input_over_200k_usd_per_million),
        "output_over_200k": _rate(record.output_over_200k_usd_per_million),
    }


def _model_pricing_record(
    *,
    provider: str,
    model: str,
    pricing: dict[str, float | None],
    checked_at: datetime,
    observed_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> ModelPricingRecord:
    return ModelPricingRecord(
        provider=provider,
        model=model,
        price_basis="standard",
        currency="USD",
        input_usd_per_million=pricing.get("input"),
        cached_input_usd_per_million=pricing.get("cached_input"),
        output_usd_per_million=pricing.get("output"),
        input_over_200k_usd_per_million=pricing.get("input_over_200k"),
        cached_input_over_200k_usd_per_million=pricing.get("cached_input_over_200k"),
        output_over_200k_usd_per_million=pricing.get("output_over_200k"),
        source_url=_source_url_for_provider(provider),
        observed_at=observed_at or checked_at,
        last_checked_at=checked_at,
        pricing_metadata={
            "source_updated_at": PRICE_UPDATED_AT,
            "rates_per": "1M tokens",
            **(metadata or {}),
        },
    )


def _current_price_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for model, pricing in CURRENT_MODEL_TOKEN_PRICES_USD_PER_MILLION.items():
        provider = _provider_for_model(model)
        entries.append(
            {
                "provider": provider,
                "model": model,
                "pricing": pricing,
                "source_url": _source_url_for_provider(provider),
                "metadata": {
                    "source_updated_at": PRICE_UPDATED_AT,
                    "rates_per": "1M tokens",
                    "current_enabled_model": True,
                },
            }
        )
    return entries


def refresh_model_pricing(db: Session, *, checked_at: datetime | None = None) -> dict[str, Any]:
    now = _as_utc(checked_at) or datetime.now(timezone.utc)
    inserted = 0
    changed = 0
    unchanged = 0
    for entry in _current_price_entries():
        active = (
            db.query(ModelPricingRecord)
            .filter(
                ModelPricingRecord.provider == entry["provider"],
                ModelPricingRecord.model == entry["model"],
                ModelPricingRecord.price_basis == "standard",
                ModelPricingRecord.superseded_at.is_(None),
            )
            .order_by(ModelPricingRecord.observed_at.desc(), ModelPricingRecord.created_at.desc())
            .first()
        )
        pricing = entry["pricing"]
        if active is None:
            db.add(
                _model_pricing_record(
                    provider=entry["provider"],
                    model=entry["model"],
                    pricing=pricing,
                    checked_at=now,
                    observed_at=now,
                    metadata=entry["metadata"],
                )
            )
            inserted += 1
            continue
        active.source_url = entry["source_url"]
        active.pricing_metadata = entry["metadata"]
        if _record_price_signature(active) == _price_signature(pricing):
            active.last_checked_at = now
            unchanged += 1
            continue
        active.superseded_at = now
        db.add(
            _model_pricing_record(
                provider=entry["provider"],
                model=entry["model"],
                pricing=pricing,
                checked_at=now,
                observed_at=now,
                metadata=entry["metadata"],
            )
        )
        changed += 1
    db.flush()
    status = model_pricing_status(db)
    return {
        **status,
        "inserted_count": inserted,
        "changed_count": changed,
        "unchanged_count": unchanged,
        "checked_count": inserted + changed + unchanged,
    }


def seed_model_pricing_if_empty(db: Session) -> dict[str, Any]:
    existing = db.query(func.count(ModelPricingRecord.id)).scalar() or 0
    if existing:
        return model_pricing_status(db)
    return refresh_model_pricing(db, checked_at=_source_observed_at())


def model_pricing_status(db: Session) -> dict[str, Any]:
    active_rows = db.query(ModelPricingRecord).filter(ModelPricingRecord.superseded_at.is_(None)).all()
    last_refreshed_at = max((_as_utc(row.last_checked_at) for row in active_rows if row.last_checked_at), default=None)
    now = datetime.now(timezone.utc)
    stale = last_refreshed_at is None or now - last_refreshed_at > timedelta(days=PRICE_STALE_AFTER_DAYS)
    provider_counts: dict[str, int] = {}
    for row in active_rows:
        provider_counts[row.provider] = provider_counts.get(row.provider, 0) + 1
    return {
        "basis": PRICE_BASIS,
        "source_url": PRICE_SOURCE_URL,
        "source_urls": {
            "OpenAI": PRICE_SOURCE_URL,
            "Google": GOOGLE_PRICE_SOURCE_URL,
        },
        "updated_at": PRICE_UPDATED_AT,
        "last_refreshed_at": last_refreshed_at,
        "stale": stale,
        "stale_after_days": PRICE_STALE_AFTER_DAYS,
        "model_count": len(active_rows),
        "current_model_count": len(CURRENT_MODEL_TOKEN_PRICES_USD_PER_MILLION),
        "provider_counts": provider_counts,
    }


def _pricing_index(db: Session | None) -> dict[tuple[str, str], list[ModelPricingRecord]]:
    if db is None:
        return {}
    rows = (
        db.query(ModelPricingRecord)
        .order_by(ModelPricingRecord.observed_at.desc(), ModelPricingRecord.created_at.desc())
        .all()
    )
    index: dict[tuple[str, str], list[ModelPricingRecord]] = {}
    for row in rows:
        index.setdefault((row.provider, row.model), []).append(row)
    return index


def _pricing_from_index(
    model: str | None,
    *,
    provider: str | None = None,
    at: datetime | None = None,
    pricing_index: dict[tuple[str, str], list[ModelPricingRecord]] | None = None,
) -> dict[str, float | None] | None:
    canonical = _canonical_model_id(model)
    if not canonical or not pricing_index:
        return _pricing_for_model(model)
    normalized_at = _as_utc(at)
    rows = pricing_index.get((_provider_for_model(canonical, provider), canonical), [])
    for row in rows:
        observed_at = _as_utc(row.observed_at)
        superseded_at = _as_utc(row.superseded_at)
        if normalized_at is None:
            if superseded_at is None:
                return _pricing_from_record(row)
            continue
        if observed_at and observed_at <= normalized_at and (superseded_at is None or superseded_at > normalized_at):
            return _pricing_from_record(row)
    active = next((row for row in rows if row.superseded_at is None), None)
    if active:
        return _pricing_from_record(active)
    return _pricing_for_model(model)


def _estimated_cost_usd(
    model: str | None,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    pricing: dict[str, float | None] | None = None,
) -> float | None:
    pricing = pricing or _pricing_for_model(model)
    if not pricing:
        return None
    if input_tokens > 200_000 and pricing.get("input_over_200k") is not None:
        pricing = {
            **pricing,
            "input": pricing.get("input_over_200k"),
            "cached_input": pricing.get("cached_input_over_200k"),
            "output": pricing.get("output_over_200k"),
        }
    cached_tokens = min(max(cached_input_tokens, 0), max(input_tokens, 0))
    uncached_input_tokens = max(input_tokens - cached_tokens, 0)
    cached_rate = pricing["cached_input"]
    if cached_tokens and cached_rate is None:
        return None
    input_cost = uncached_input_tokens * float(pricing["input"] or 0)
    cached_cost = cached_tokens * float(cached_rate or 0)
    output_cost = max(output_tokens, 0) * float(pricing["output"] or 0)
    return (input_cost + cached_cost + output_cost) / 1_000_000


def _cost_for_record(
    record: OpenAIUsageRecord,
    pricing_index: dict[tuple[str, str], list[ModelPricingRecord]] | None = None,
) -> float | None:
    pricing = _pricing_from_index(
        record.model,
        provider=record.provider,
        at=record.created_at,
        pricing_index=pricing_index,
    )
    return _estimated_cost_usd(
        record.model,
        record.input_tokens,
        record.cached_input_tokens,
        record.output_tokens,
        pricing=pricing,
    )


def estimated_cost_usd_for_record(record: OpenAIUsageRecord, db: Session | None = None) -> float | None:
    return _cost_for_record(record, _pricing_index(db))


def estimated_cost_usd_for_model_tokens(
    model: str | None,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    provider: str | None = None,
    db: Session | None = None,
) -> float | None:
    pricing = _pricing_from_index(model, provider=provider, pricing_index=_pricing_index(db))
    return _estimated_cost_usd(
        model,
        input_tokens=max(0, int(input_tokens or 0)),
        cached_input_tokens=max(0, int(cached_input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        pricing=pricing,
    )


def _summary_from_query(
    query,
    records: list[OpenAIUsageRecord],
    pricing_index: dict[tuple[str, str], list[ModelPricingRecord]] | None = None,
) -> dict[str, Any]:
    row = query.with_entities(
        func.count(OpenAIUsageRecord.id),
        func.sum(OpenAIUsageRecord.input_tokens),
        func.sum(OpenAIUsageRecord.cached_input_tokens),
        func.sum(OpenAIUsageRecord.output_tokens),
        func.sum(OpenAIUsageRecord.reasoning_output_tokens),
        func.sum(OpenAIUsageRecord.total_tokens),
        func.sum(OpenAIUsageRecord.input_file_bytes),
        func.sum(OpenAIUsageRecord.input_text_characters),
        func.sum(OpenAIUsageRecord.output_text_characters),
        func.sum(case((OpenAIUsageRecord.status == "failed", 1), else_=0)),
        func.min(OpenAIUsageRecord.created_at),
        func.max(OpenAIUsageRecord.created_at),
    ).one()
    request_count = _coalesced_sum(row[0])
    failed_request_count = _coalesced_sum(row[9])
    estimated_cost_usd = 0.0
    priced_request_count = 0
    unpriced_request_count = 0
    for record in records:
        cost = _cost_for_record(record, pricing_index)
        if cost is None:
            unpriced_request_count += 1
        else:
            estimated_cost_usd += cost
            priced_request_count += 1
    return {
        "request_count": request_count,
        "successful_request_count": max(0, request_count - failed_request_count),
        "failed_request_count": failed_request_count,
        "input_tokens": _coalesced_sum(row[1]),
        "cached_input_tokens": _coalesced_sum(row[2]),
        "output_tokens": _coalesced_sum(row[3]),
        "reasoning_output_tokens": _coalesced_sum(row[4]),
        "total_tokens": _coalesced_sum(row[5]),
        "input_file_bytes": _coalesced_sum(row[6]),
        "input_text_characters": _coalesced_sum(row[7]),
        "output_text_characters": _coalesced_sum(row[8]),
        "oldest_created_at": row[10],
        "newest_created_at": row[11],
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "priced_request_count": priced_request_count,
        "unpriced_request_count": unpriced_request_count,
    }


def _calendar_start(value: datetime | None, granularity: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        normalized = value.replace(tzinfo=timezone.utc)
    else:
        normalized = value.astimezone(timezone.utc)
    if granularity == "day":
        return normalized.replace(hour=0, minute=0, second=0, microsecond=0)
    return normalized.replace(minute=0, second=0, microsecond=0)


def _group_key(record: OpenAIUsageRecord, group_field: str) -> Any:
    if group_field == "calendar_day":
        return _calendar_start(record.created_at, "day")
    if group_field == "calendar_hour":
        return _calendar_start(record.created_at, "hour")
    return getattr(record, group_field)


def _group_rows(
    records: list[OpenAIUsageRecord],
    group_field: str,
    *,
    limit: int = 12,
    document_titles: dict[str, str] | None = None,
    pricing_index: dict[tuple[str, str], list[ModelPricingRecord]] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[Any, dict[str, Any]] = {}
    for record in records:
        raw_key = _group_key(record, group_field)
        key = raw_key or "unknown"
        row = groups.setdefault(
            key,
            {
                "group_key": key.isoformat() if isinstance(key, datetime) else str(key),
                "label": None,
                "request_count": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 0,
                "input_file_bytes": 0,
                "failed_request_count": 0,
                "estimated_cost_usd": 0.0,
                "priced_request_count": 0,
                "unpriced_request_count": 0,
            },
        )
        if group_field in {"model", "task_key", "provider", "document_id"}:
            row[group_field] = raw_key or "unknown"
        if group_field in {"calendar_day", "calendar_hour"} and isinstance(raw_key, datetime):
            row["calendar_start"] = raw_key
        if group_field == "document_id":
            row["document_id"] = raw_key
            row["label"] = (document_titles or {}).get(raw_key or "", "Unlinked document" if raw_key is None else raw_key)
        row["request_count"] += 1
        row["input_tokens"] += record.input_tokens
        row["cached_input_tokens"] += record.cached_input_tokens
        row["output_tokens"] += record.output_tokens
        row["reasoning_output_tokens"] += record.reasoning_output_tokens
        row["total_tokens"] += record.total_tokens
        row["input_file_bytes"] += record.input_file_bytes
        row["failed_request_count"] += 1 if record.status == "failed" else 0
        cost = _cost_for_record(record, pricing_index)
        if cost is None:
            row["unpriced_request_count"] += 1
        else:
            row["estimated_cost_usd"] += cost
            row["priced_request_count"] += 1
    if group_field in {"calendar_day", "calendar_hour"}:
        rows = sorted(groups.values(), key=lambda item: item.get("calendar_start") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    else:
        rows = sorted(groups.values(), key=lambda item: (item["total_tokens"], item["request_count"]), reverse=True)
    if limit:
        rows = rows[:limit]
    for row in rows:
        row["estimated_cost_usd"] = round(float(row["estimated_cost_usd"]), 6)
    return rows


def openai_usage_summary(db: Session, *, period: str = "all_time", recent_limit: int = 12) -> dict[str, Any]:
    normalized_period = period if period in USAGE_PERIODS else "all_time"
    base = _apply_period(db.query(OpenAIUsageRecord), normalized_period)
    records = base.all()
    pricing_index = _pricing_index(db)
    document_ids = sorted({record.document_id for record in records if record.document_id})
    document_titles = {
        document.id: document.title or document.filename
        for document in db.query(Document).filter(Document.id.in_(document_ids)).all()
    } if document_ids else {}
    recent = (
        base.order_by(OpenAIUsageRecord.created_at.desc())
        .limit(recent_limit)
        .all()
    )
    return {
        "period": normalized_period,
        "summary": _summary_from_query(base, records, pricing_index),
        "by_task": _group_rows(records, "task_key", pricing_index=pricing_index),
        "by_model": _group_rows(records, "model", pricing_index=pricing_index),
        "by_document": _group_rows(records, "document_id", document_titles=document_titles, pricing_index=pricing_index),
        "by_calendar_day": _group_rows(records, "calendar_day", limit=30, pricing_index=pricing_index),
        "by_calendar_hour": _group_rows(records, "calendar_hour", limit=48, pricing_index=pricing_index),
        "recent": [
            {
                "id": item.id,
                "created_at": item.created_at,
                "document_id": item.document_id,
                "source": item.source,
                "task_key": item.task_key,
                "operation": item.operation,
                "provider": item.provider,
                "model": item.model,
                "endpoint": item.endpoint,
                "status": item.status,
                "page_number": item.page_number,
                "used_pdf_file": item.used_pdf_file,
                "input_file_bytes": item.input_file_bytes,
                "input_tokens": item.input_tokens,
                "cached_input_tokens": item.cached_input_tokens,
                "output_tokens": item.output_tokens,
                "reasoning_output_tokens": item.reasoning_output_tokens,
                "total_tokens": item.total_tokens,
                "estimated_cost_usd": (
                    None
                    if (cost := _cost_for_record(item, pricing_index)) is None
                    else round(cost, 6)
                ),
                "error_message": item.error_message,
            }
            for item in recent
        ],
        "pricing": model_pricing_status(db),
    }
