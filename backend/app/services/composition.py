from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentCompositionRecord, ImportJob, OpenAIUsageRecord, utc_now
from app.services.openai_usage import estimated_cost_usd_for_record


STAGE_SEQUENCE = {
    "raw_text_extraction": 10,
    "figure_assets": 20,
    "summary_topics": 30,
    "citation_refresh": 34,
    "text_chunk_encoding": 40,
    "cache_cleanup": 50,
    "manual_correction": 90,
}

STAGE_LABELS = {
    "raw_text_extraction": "Text extraction",
    "figure_assets": "Figure extraction",
    "summary_topics": "Metadata, summary, and topics",
    "citation_refresh": "APA citation matching",
    "text_chunk_encoding": "Text chunk encoding",
    "cache_cleanup": "Cache cleanup",
    "manual_correction": "Manual correction",
}

CAPABILITY_STAGE = {
    "page_text_normalization": "raw_text_extraction",
    "summary_topics": "summary_topics",
    "citation_refresh": "citation_refresh",
    "text_chunk_encoding": "text_chunk_encoding",
}


def stage_timer() -> tuple[datetime, float]:
    return utc_now(), perf_counter()


def elapsed_ms(started_perf: float) -> int:
    return max(0, int((perf_counter() - started_perf) * 1000))


def provider_label(provider: str | None) -> str:
    normalized = (provider or "unknown").strip().lower()
    labels = {
        "openai": "OpenAI",
        "google": "Gemini",
        "gemini": "Gemini",
        "anthropic": "Anthropic",
        "local": "Local",
        "unknown": "Unknown",
    }
    return labels.get(normalized, normalized.replace("_", " ").title())


def stage_key_for_usage(record: OpenAIUsageRecord) -> str:
    if record.capability_key in CAPABILITY_STAGE:
        return CAPABILITY_STAGE[record.capability_key]
    if record.task_key in CAPABILITY_STAGE:
        return CAPABILITY_STAGE[record.task_key]
    return record.capability_key or record.task_key or "model_call"


def stage_label(stage_key: str) -> str:
    return STAGE_LABELS.get(stage_key, stage_key.replace("_", " ").title())


def record_import_stage(
    db: Session,
    *,
    document: Document,
    job: ImportJob | None,
    stage_key: str,
    label: str | None = None,
    provider: str = "local",
    method: str | None = None,
    model: str | None = None,
    status: str = "complete",
    started_at: datetime | None = None,
    duration_ms: int | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentCompositionRecord:
    completed_at = utc_now()
    record = DocumentCompositionRecord(
        document_id=document.id,
        import_job_id=job.id if job else None,
        sequence=STAGE_SEQUENCE.get(stage_key, 80),
        record_kind="local",
        stage_key=stage_key,
        stage_label=label or stage_label(stage_key),
        provider=provider,
        method=method,
        model=model,
        status=status,
        amount_usd=0.0,
        duration_ms=duration_ms,
        started_at=started_at,
        completed_at=completed_at,
        message=message,
        record_metadata=metadata or {},
    )
    db.add(record)
    return record


def record_import_erratum(
    db: Session,
    *,
    document: Document | None,
    job: ImportJob | None,
    stage_key: str,
    message: str,
    level: str = "error",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not document:
        return
    db.add(
        DocumentCompositionRecord(
            document_id=document.id,
            import_job_id=job.id if job else None,
            sequence=STAGE_SEQUENCE.get(stage_key, 80),
            record_kind="erratum",
            stage_key=stage_key,
            stage_label=stage_label(stage_key),
            provider=None,
            method=None,
            model=None,
            status=level,
            amount_usd=0.0,
            duration_ms=None,
            completed_at=utc_now(),
            message=message[:2000],
            record_metadata=metadata or {},
        )
    )


def record_manual_edit(
    db: Session,
    *,
    document: Document,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        DocumentCompositionRecord(
            document_id=document.id,
            sequence=STAGE_SEQUENCE["manual_correction"],
            record_kind="edit",
            stage_key="manual_correction",
            stage_label=STAGE_LABELS["manual_correction"],
            provider="local",
            method="user_edit",
            status="complete",
            amount_usd=0.0,
            duration_ms=0,
            completed_at=utc_now(),
            message=message,
            record_metadata=metadata or {},
        )
    )


def sync_import_usage_composition(db: Session, *, document: Document, job: ImportJob | None) -> int:
    query = db.query(OpenAIUsageRecord).filter(OpenAIUsageRecord.document_id == document.id)
    if job:
        query = query.filter(OpenAIUsageRecord.import_job_id == job.id)
    existing_usage_ids = {
        row[0]
        for row in db.query(DocumentCompositionRecord.usage_record_id)
        .filter(
            DocumentCompositionRecord.document_id == document.id,
            DocumentCompositionRecord.usage_record_id.isnot(None),
        )
        .all()
    }
    count = 0
    for usage in query.order_by(OpenAIUsageRecord.created_at, OpenAIUsageRecord.id).all():
        if usage.id in existing_usage_ids:
            continue
        cost = estimated_cost_usd_for_record(usage)
        stage_key = stage_key_for_usage(usage)
        endpoint = usage.endpoint or usage.operation
        record_kind = "embedding" if "embedding" in endpoint or "embedding" in usage.model else "llm"
        db.add(
            DocumentCompositionRecord(
                document_id=document.id,
                import_job_id=usage.import_job_id,
                usage_record_id=usage.id,
                sequence=STAGE_SEQUENCE.get(stage_key, 80),
                record_kind=record_kind,
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                provider=usage.provider,
                method=usage.operation or usage.endpoint,
                model=usage.model,
                status=usage.status,
                amount_usd=cost,
                duration_ms=None,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                completed_at=usage.created_at,
                message=usage.error_message,
                record_metadata={
                    "endpoint": usage.endpoint,
                    "task_key": usage.task_key,
                    "capability_key": usage.capability_key,
                    "cached_input_tokens": usage.cached_input_tokens,
                    "reasoning_output_tokens": usage.reasoning_output_tokens,
                    "used_pdf_file": usage.used_pdf_file,
                    "input_file_bytes": usage.input_file_bytes,
                },
            )
        )
        count += 1
    if count:
        db.flush()
    return count


def active_import_cost_usd(db: Session, import_job_ids: list[str]) -> float:
    if not import_job_ids:
        return 0.0
    total = 0.0
    for usage in db.query(OpenAIUsageRecord).filter(OpenAIUsageRecord.import_job_id.in_(import_job_ids)).all():
        total += estimated_cost_usd_for_record(usage) or 0.0
    return round(total, 6)


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _sum_duration(records: list[DocumentCompositionRecord]) -> int:
    return sum(max(0, int(record.duration_ms or 0)) for record in records if record.record_kind == "local")


def _group_key(record: DocumentCompositionRecord, *fields: str) -> tuple[Any, ...]:
    return tuple(getattr(record, field) for field in fields)


def document_composition_summary(db: Session, document: Document) -> dict[str, Any]:
    records = (
        db.query(DocumentCompositionRecord)
        .filter(DocumentCompositionRecord.document_id == document.id)
        .order_by(DocumentCompositionRecord.sequence, DocumentCompositionRecord.created_at, DocumentCompositionRecord.id)
        .all()
    )
    if not records:
        return {
            "document_id": document.id,
            "available": False,
            "total_estimated_cost_usd": 0.0,
            "total_duration_seconds": 0,
            "cost_entries": [],
            "provider_breakdown": [],
            "local_duration_entries": [],
            "pipeline": [],
            "errata": [],
        }

    cost_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    provider_groups: dict[str, dict[str, Any]] = {}
    local_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    pipeline_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    errata: list[dict[str, Any]] = []

    for record in records:
        amount = _float(record.amount_usd)
        provider = provider_label(record.provider)
        if amount > 0:
            key = _group_key(record, "provider", "model", "stage_key", "record_kind")
            group = cost_groups.setdefault(
                key,
                {
                    "label": record.model or record.method or provider,
                    "stage_key": record.stage_key,
                    "stage_label": record.stage_label,
                    "provider": provider,
                    "method": record.method,
                    "model": record.model,
                    "record_kind": record.record_kind,
                    "amount_usd": 0.0,
                    "duration_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "call_count": 0,
                },
            )
            group["amount_usd"] += amount
            group["input_tokens"] += record.input_tokens
            group["output_tokens"] += record.output_tokens
            group["total_tokens"] += record.total_tokens
            group["call_count"] += 1
            provider_group = provider_groups.setdefault(provider, {"provider": provider, "amount_usd": 0.0, "call_count": 0})
            provider_group["amount_usd"] += amount
            provider_group["call_count"] += 1

        if record.record_kind == "local" and record.duration_ms:
            key = _group_key(record, "stage_key", "method", "model")
            group = local_groups.setdefault(
                key,
                {
                    "label": record.stage_label,
                    "stage_key": record.stage_key,
                    "stage_label": record.stage_label,
                    "provider": provider,
                    "method": record.method,
                    "model": record.model,
                    "record_kind": record.record_kind,
                    "amount_usd": 0.0,
                    "duration_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "call_count": 0,
                },
            )
            group["duration_ms"] += record.duration_ms or 0
            group["call_count"] += 1

        if record.record_kind in {"local", "llm", "embedding"}:
            key = _group_key(record, "stage_key", "provider", "method", "model", "record_kind")
            group = pipeline_groups.setdefault(
                key,
                {
                    "label": record.stage_label,
                    "stage_key": record.stage_key,
                    "stage_label": record.stage_label,
                    "provider": provider,
                    "method": record.method,
                    "model": record.model,
                    "record_kind": record.record_kind,
                    "amount_usd": 0.0,
                    "duration_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "call_count": 0,
                    "sequence": record.sequence,
                },
            )
            group["amount_usd"] += amount
            group["duration_ms"] += record.duration_ms or 0
            group["input_tokens"] += record.input_tokens
            group["output_tokens"] += record.output_tokens
            group["total_tokens"] += record.total_tokens
            group["call_count"] += 1

        if record.record_kind in {"erratum", "edit"} or record.status in {"failed", "error", "warning"}:
            errata.append(
                {
                    "label": record.stage_label,
                    "stage_key": record.stage_key,
                    "stage_label": record.stage_label,
                    "provider": provider if record.provider else None,
                    "method": record.method,
                    "model": record.model,
                    "record_kind": record.record_kind,
                    "status": record.status,
                    "message": record.message,
                    "amount_usd": amount,
                    "duration_ms": record.duration_ms or 0,
                    "created_at": record.created_at,
                }
            )

    def rounded_groups(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for value in values:
            row = dict(value)
            row["amount_usd"] = round(_float(row.get("amount_usd")), 6)
            row["duration_ms"] = int(row.get("duration_ms") or 0)
            rows.append(row)
        return rows

    cost_entries = sorted(rounded_groups(list(cost_groups.values())), key=lambda row: row["amount_usd"], reverse=True)
    provider_breakdown = sorted(
        rounded_groups(list(provider_groups.values())),
        key=lambda row: row["amount_usd"],
        reverse=True,
    )
    local_duration_entries = sorted(
        rounded_groups(list(local_groups.values())),
        key=lambda row: row["duration_ms"],
        reverse=True,
    )
    pipeline = sorted(
        rounded_groups(list(pipeline_groups.values())),
        key=lambda row: (row.get("sequence") or 0, row["stage_key"], row.get("model") or row.get("method") or ""),
    )
    total_cost = round(sum(row["amount_usd"] for row in cost_entries), 6)
    return {
        "document_id": document.id,
        "available": True,
        "total_estimated_cost_usd": total_cost,
        "total_duration_seconds": round(_sum_duration(records) / 1000),
        "cost_entries": cost_entries,
        "provider_breakdown": provider_breakdown,
        "local_duration_entries": local_duration_entries,
        "pipeline": pipeline,
        "errata": errata,
    }
