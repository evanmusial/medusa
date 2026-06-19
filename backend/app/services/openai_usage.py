from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import session_scope
from app.models import OpenAIUsageRecord


logger = logging.getLogger(__name__)

UsageRecorder = Callable[[dict[str, Any]], None]
USAGE_PERIODS: dict[str, timedelta | None] = {
    "last_day": timedelta(days=1),
    "last_month": timedelta(days=30),
    "last_3_months": timedelta(days=90),
    "all_time": None,
}
PRICE_SOURCE_URL = "https://developers.openai.com/api/docs/pricing"
PRICE_UPDATED_AT = "2026-06-19"
PRICE_BASIS = "OpenAI standard API pricing per 1M tokens; unrecognized models are left unpriced."
MODEL_TOKEN_PRICES_USD_PER_MILLION: dict[str, dict[str, float | None]] = {
    "gpt-5.5": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
    "gpt-5.5-pro": {"input": 30.0, "cached_input": None, "output": 180.0},
    "gpt-5.4": {"input": 2.5, "cached_input": 0.25, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.5},
    "gpt-5.4-nano": {"input": 0.2, "cached_input": 0.02, "output": 1.25},
    "gpt-5.4-pro": {"input": 30.0, "cached_input": None, "output": 180.0},
    "text-embedding-3-small": {"input": 0.02, "cached_input": None, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "cached_input": None, "output": 0.0},
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
        "provider": "openai",
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


def _pricing_for_model(model: str | None) -> dict[str, float | None] | None:
    if not model:
        return None
    model_id = model.strip()
    if model_id in MODEL_TOKEN_PRICES_USD_PER_MILLION:
        return MODEL_TOKEN_PRICES_USD_PER_MILLION[model_id]
    for prefix in sorted(MODEL_TOKEN_PRICES_USD_PER_MILLION, key=len, reverse=True):
        if model_id.startswith(f"{prefix}-20"):
            return MODEL_TOKEN_PRICES_USD_PER_MILLION[prefix]
    return None


def _estimated_cost_usd(model: str | None, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float | None:
    pricing = _pricing_for_model(model)
    if not pricing:
        return None
    cached_tokens = min(max(cached_input_tokens, 0), max(input_tokens, 0))
    uncached_input_tokens = max(input_tokens - cached_tokens, 0)
    cached_rate = pricing["cached_input"]
    if cached_tokens and cached_rate is None:
        return None
    input_cost = uncached_input_tokens * float(pricing["input"] or 0)
    cached_cost = cached_tokens * float(cached_rate or 0)
    output_cost = max(output_tokens, 0) * float(pricing["output"] or 0)
    return (input_cost + cached_cost + output_cost) / 1_000_000


def _cost_rollup_from_rows(rows: list[tuple[Any, ...]]) -> dict[Any, dict[str, int | float]]:
    rollup: dict[Any, dict[str, int | float]] = {}
    for group_value, model, request_count, input_tokens, cached_input_tokens, output_tokens in rows:
        cost = _estimated_cost_usd(
            model,
            _coalesced_sum(input_tokens),
            _coalesced_sum(cached_input_tokens),
            _coalesced_sum(output_tokens),
        )
        key = group_value or "unknown"
        current = rollup.setdefault(
            key,
            {"estimated_cost_usd": 0.0, "priced_request_count": 0, "unpriced_request_count": 0},
        )
        if cost is None:
            current["unpriced_request_count"] = int(current["unpriced_request_count"]) + _coalesced_sum(request_count)
        else:
            current["estimated_cost_usd"] = float(current["estimated_cost_usd"]) + cost
            current["priced_request_count"] = int(current["priced_request_count"]) + _coalesced_sum(request_count)
    return rollup


def _group_cost_rollup(query, group_field: str) -> dict[Any, dict[str, int | float]]:
    column = getattr(OpenAIUsageRecord, group_field)
    rows = (
        query.with_entities(
            column,
            OpenAIUsageRecord.model,
            func.count(OpenAIUsageRecord.id),
            func.sum(OpenAIUsageRecord.input_tokens),
            func.sum(OpenAIUsageRecord.cached_input_tokens),
            func.sum(OpenAIUsageRecord.output_tokens),
        )
        .group_by(column, OpenAIUsageRecord.model)
        .all()
    )
    return _cost_rollup_from_rows(rows)


def _summary_from_query(query) -> dict[str, Any]:
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
    cost_rollup = _group_cost_rollup(query, "model")
    estimated_cost_usd = sum(float(item["estimated_cost_usd"]) for item in cost_rollup.values())
    priced_request_count = sum(int(item["priced_request_count"]) for item in cost_rollup.values())
    unpriced_request_count = sum(int(item["unpriced_request_count"]) for item in cost_rollup.values())
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


def _group_rows(query, group_field: str, *, limit: int = 12) -> list[dict[str, Any]]:
    column = getattr(OpenAIUsageRecord, group_field)
    cost_rollup = _group_cost_rollup(query, group_field)
    rows = (
        query.with_entities(
            column,
            func.count(OpenAIUsageRecord.id),
            func.sum(OpenAIUsageRecord.input_tokens),
            func.sum(OpenAIUsageRecord.cached_input_tokens),
            func.sum(OpenAIUsageRecord.output_tokens),
            func.sum(OpenAIUsageRecord.reasoning_output_tokens),
            func.sum(OpenAIUsageRecord.total_tokens),
            func.sum(OpenAIUsageRecord.input_file_bytes),
            func.sum(case((OpenAIUsageRecord.status == "failed", 1), else_=0)),
        )
        .group_by(column)
        .order_by(func.sum(OpenAIUsageRecord.total_tokens).desc(), func.count(OpenAIUsageRecord.id).desc())
    )
    rows = rows.limit(limit).all() if limit else rows.all()
    return [
        {
            group_field: row[0] or "unknown",
            "request_count": _coalesced_sum(row[1]),
            "input_tokens": _coalesced_sum(row[2]),
            "cached_input_tokens": _coalesced_sum(row[3]),
            "output_tokens": _coalesced_sum(row[4]),
            "reasoning_output_tokens": _coalesced_sum(row[5]),
            "total_tokens": _coalesced_sum(row[6]),
            "input_file_bytes": _coalesced_sum(row[7]),
            "failed_request_count": _coalesced_sum(row[8]),
            "estimated_cost_usd": round(float(cost_rollup.get(row[0] or "unknown", {}).get("estimated_cost_usd", 0.0)), 6),
            "priced_request_count": int(cost_rollup.get(row[0] or "unknown", {}).get("priced_request_count", 0)),
            "unpriced_request_count": int(cost_rollup.get(row[0] or "unknown", {}).get("unpriced_request_count", 0)),
        }
        for row in rows
    ]


def openai_usage_summary(db: Session, *, period: str = "all_time", recent_limit: int = 12) -> dict[str, Any]:
    normalized_period = period if period in USAGE_PERIODS else "all_time"
    base = _apply_period(db.query(OpenAIUsageRecord), normalized_period)
    recent = (
        base.order_by(OpenAIUsageRecord.created_at.desc())
        .limit(recent_limit)
        .all()
    )
    return {
        "period": normalized_period,
        "summary": _summary_from_query(base),
        "by_task": _group_rows(base, "task_key"),
        "by_model": _group_rows(base, "model"),
        "recent": [
            {
                "id": item.id,
                "created_at": item.created_at,
                "document_id": item.document_id,
                "source": item.source,
                "task_key": item.task_key,
                "operation": item.operation,
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
                    if (
                        cost := _estimated_cost_usd(
                            item.model,
                            item.input_tokens,
                            item.cached_input_tokens,
                            item.output_tokens,
                        )
                    )
                    is None
                    else round(cost, 6)
                ),
                "error_message": item.error_message,
            }
            for item in recent
        ],
        "pricing": {
            "basis": PRICE_BASIS,
            "source_url": PRICE_SOURCE_URL,
            "updated_at": PRICE_UPDATED_AT,
        },
    }
