from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentCompositionRecord, ImportJob, OpenAIUsageRecord, utc_now
from app.services.analysis_models import (
    MODEL_APA_CITATION,
    MODEL_CORE_DOCUMENT_INTELLIGENCE,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_SUMMARY,
    MODEL_TEXT_CHUNK_ENCODING,
)
from app.services.openai_usage import estimated_cost_usd_for_record


STAGE_SEQUENCE = {
    "import_cost_estimate": 1,
    "raw_text_extraction": 10,
    "document_structure_cleanup": 12,
    "structured_tables": 14,
    "bibliography_extraction": 16,
    "visual_asset_extraction": 20,
    "figure_assets": 20,
    "summary_topics": 30,
    "citation_refresh": 34,
    "text_chunk_encoding": 40,
    "cache_cleanup": 50,
    "manual_correction": 90,
}

STAGE_LABELS = {
    "import_cost_estimate": "Import cost estimate",
    "raw_text_extraction": "Text extraction",
    "document_structure_cleanup": "Document structure cleanup",
    "structured_tables": "Structured tables",
    "bibliography_extraction": "Bibliography extraction",
    "visual_asset_extraction": "Visual asset extraction",
    "figure_assets": "Figure extraction",
    "summary_topics": "Metadata, summary, and topics",
    "citation_refresh": "APA citation matching",
    "text_chunk_encoding": "Text chunk encoding",
    "cache_cleanup": "Cache cleanup",
    "manual_correction": "Manual correction",
}

IMPORT_COST_ESTIMATE_STAGE = "import_cost_estimate"

CAPABILITY_STAGE = {
    "document_structure_cleanup": "document_structure_cleanup",
    "structured_tables": "structured_tables",
    "page_text_normalization": "raw_text_extraction",
    "bibliography_extraction": "bibliography_extraction",
    "visual_asset_extraction": "visual_asset_extraction",
    "visual_asset_context": "visual_asset_extraction",
    "figure_assets": "visual_asset_extraction",
    "summary_topics": "summary_topics",
    "citation_refresh": "citation_refresh",
    "text_chunk_encoding": "text_chunk_encoding",
}

PIPELINE_TASK_OFFSETS = {
    MODEL_PAGE_TEXT_NORMALIZATION: 0.2,
    MODEL_METADATA: 0.1,
    MODEL_CORE_DOCUMENT_INTELLIGENCE: 0.1,
    MODEL_SUMMARY: 0.2,
    MODEL_KEYWORDS_TOPICS: 0.3,
    MODEL_APA_CITATION: 0.1,
    MODEL_TEXT_CHUNK_ENCODING: 0.1,
}

PIPELINE_LOCAL_OFFSETS = {
    "raw_text_extraction": 0.0,
    "document_structure_cleanup": 0.0,
    "structured_tables": 0.0,
    "bibliography_extraction": 0.0,
    "visual_asset_extraction": 0.0,
    "figure_assets": 0.0,
    "summary_topics": 0.9,
    "text_chunk_encoding": 0.9,
    "cache_cleanup": 0.0,
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


def record_import_cost_estimate(
    db: Session,
    *,
    document: Document,
    job: ImportJob | None,
    estimated_cost_usd: float,
    estimate_basis: str,
    estimated_page_count: int | None,
    model_preferences: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentCompositionRecord:
    record_metadata = {
        "estimate_basis": estimate_basis,
        "estimated_page_count": estimated_page_count,
        "model_preferences": model_preferences or {},
        **(metadata or {}),
    }
    existing = (
        db.query(DocumentCompositionRecord)
        .filter(
            DocumentCompositionRecord.document_id == document.id,
            DocumentCompositionRecord.import_job_id == (job.id if job else None),
            DocumentCompositionRecord.record_kind == "estimate",
            DocumentCompositionRecord.stage_key == IMPORT_COST_ESTIMATE_STAGE,
        )
        .one_or_none()
    )
    record = existing or DocumentCompositionRecord(
        document_id=document.id,
        import_job_id=job.id if job else None,
        record_kind="estimate",
        stage_key=IMPORT_COST_ESTIMATE_STAGE,
        stage_label=STAGE_LABELS[IMPORT_COST_ESTIMATE_STAGE],
    )
    record.sequence = STAGE_SEQUENCE[IMPORT_COST_ESTIMATE_STAGE]
    record.provider = "medusa"
    record.method = estimate_basis
    record.model = None
    record.status = "estimated"
    record.amount_usd = max(0.0, float(estimated_cost_usd or 0.0))
    record.duration_ms = 0
    record.input_tokens = 0
    record.output_tokens = 0
    record.total_tokens = 0
    record.completed_at = utc_now()
    record.message = "Pre-processing import cost estimate."
    record.record_metadata = record_metadata
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
        cost = estimated_cost_usd_for_record(usage, db)
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
        total += estimated_cost_usd_for_record(usage, db) or 0.0
    return round(total, 6)


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _record_metadata(record: DocumentCompositionRecord) -> dict[str, Any]:
    return record.record_metadata if isinstance(record.record_metadata, dict) else {}


def _timestamp_sort_value(value: datetime | None) -> float:
    return value.timestamp() if value else float("inf")


def _pipeline_record_order(record: DocumentCompositionRecord, fallback_index: int) -> tuple[float, float, int]:
    task_key = _record_metadata(record).get("task_key")
    base = float(record.sequence if record.sequence is not None else STAGE_SEQUENCE.get(record.stage_key, 80))
    if isinstance(task_key, str) and task_key in PIPELINE_TASK_OFFSETS:
        offset = PIPELINE_TASK_OFFSETS[task_key]
    elif record.record_kind == "local":
        offset = PIPELINE_LOCAL_OFFSETS.get(record.stage_key, 0.5)
    else:
        offset = 0.4
    occurred_at = record.completed_at or record.started_at or record.created_at
    return (base + offset, _timestamp_sort_value(occurred_at), fallback_index)


def _sum_duration(records: list[DocumentCompositionRecord]) -> int:
    return sum(max(0, int(record.duration_ms or 0)) for record in records if record.record_kind == "local")


def _group_key(record: DocumentCompositionRecord, *fields: str) -> tuple[Any, ...]:
    return tuple(getattr(record, field) for field in fields)


def _estimate_comparison(records: list[DocumentCompositionRecord]) -> dict[str, Any] | None:
    estimate_records = [
        record
        for record in records
        if record.record_kind == "estimate" and record.stage_key == IMPORT_COST_ESTIMATE_STAGE and _float(record.amount_usd) > 0
    ]
    if not estimate_records:
        return None
    estimate = max(estimate_records, key=lambda record: record.completed_at or record.created_at)
    metadata = _record_metadata(estimate)
    estimated_cost = round(_float(estimate.amount_usd), 6)
    actual_cost = round(
        sum(
            _float(record.amount_usd)
            for record in records
            if record.record_kind in {"llm", "embedding"} and _float(record.amount_usd) > 0
        ),
        6,
    )
    variance = round(actual_cost - estimated_cost, 6) if actual_cost > 0 else None
    variance_percent = round((variance / estimated_cost) * 100, 2) if variance is not None and estimated_cost > 0 else None
    ratio = round(actual_cost / estimated_cost, 4) if actual_cost > 0 and estimated_cost > 0 else None
    if actual_cost <= 0:
        status = "pending"
    elif variance_percent is not None and abs(variance_percent) <= 5:
        status = "close"
    elif actual_cost > estimated_cost:
        status = "over"
    else:
        status = "under"
    estimated_page_count = metadata.get("estimated_page_count")
    if not isinstance(estimated_page_count, int) or estimated_page_count <= 0:
        estimated_page_count = None
    return {
        "estimated_cost_usd": estimated_cost,
        "actual_cost_usd": actual_cost,
        "variance_usd": variance,
        "variance_percent": variance_percent,
        "actual_to_estimate_ratio": ratio,
        "estimated_page_count": estimated_page_count,
        "basis": metadata.get("estimate_basis") or estimate.method,
        "status": status,
        "created_at": estimate.completed_at or estimate.created_at,
    }


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
            "estimate_comparison": None,
        }

    cost_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    provider_groups: dict[str, dict[str, Any]] = {}
    local_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    pipeline_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    errata: list[dict[str, Any]] = []

    for record_index, record in enumerate(records):
        amount = _float(record.amount_usd)
        provider = provider_label(record.provider)
        if amount > 0 and record.record_kind != "estimate":
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
            pipeline_order = _pipeline_record_order(record, record_index)
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
                    "created_at": record.completed_at or record.started_at or record.created_at,
                    "_sort_order": pipeline_order,
                },
            )
            if pipeline_order < group["_sort_order"]:
                group["_sort_order"] = pipeline_order
                group["created_at"] = record.completed_at or record.started_at or record.created_at
            group["amount_usd"] += amount
            group["duration_ms"] += record.duration_ms or 0
            group["input_tokens"] += record.input_tokens
            group["output_tokens"] += record.output_tokens
            group["total_tokens"] += record.total_tokens
            group["call_count"] += 1

        if record.record_kind == "erratum" or record.status in {"failed", "error", "warning"}:
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
        key=lambda row: row.get("_sort_order") or (row.get("sequence") or 0, float("inf"), 0),
    )
    for row in pipeline:
        row.pop("_sort_order", None)
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
        "estimate_comparison": _estimate_comparison(records),
    }
