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
    MODEL_FORMULA_CAPTURE,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_SUMMARY,
    MODEL_TEXT_CHUNK_ENCODING,
)
from app.services.openai_usage import estimated_cost_usd_for_record, estimated_costs_usd_for_records


STAGE_SEQUENCE = {
    "import_cost_estimate": 1,
    "raw_text_extraction": 10,
    "document_structure_cleanup": 12,
    "ocr_fallback": 13,
    "structured_tables": 14,
    "page_text_normalization": 16,
    "bibliography_extraction": 18,
    "formula_capture": 19,
    "visual_asset_extraction": 20,
    "figure_assets": 20,
    "visual_asset_context": 22,
    "summary_topics": 30,
    "tag_governance": 31,
    "summary_refresh": 32,
    "citation_refresh": 34,
    "text_chunk_encoding": 40,
    "search_index": 42,
    "cache_cleanup": 50,
    "recommendations": 60,
    "manual_correction": 90,
}

STAGE_LABELS = {
    "import_cost_estimate": "Import cost estimate",
    "raw_text_extraction": "Text extraction",
    "document_structure_cleanup": "Document structure cleanup",
    "ocr_fallback": "OCR fallback",
    "structured_tables": "Structured tables",
    "page_text_normalization": "Page text normalization",
    "bibliography_extraction": "Bibliography extraction",
    "formula_capture": "Formula capture",
    "visual_asset_extraction": "Visual asset extraction",
    "figure_assets": "Figure extraction",
    "visual_asset_context": "Visual asset context",
    "summary_topics": "Metadata, summary, and topics",
    "tag_governance": "Tag governance",
    "summary_refresh": "Summary refresh",
    "citation_refresh": "APA citation matching",
    "text_chunk_encoding": "Text chunk encoding",
    "search_index": "Search index",
    "cache_cleanup": "Cache cleanup",
    "recommendations": "Related paper recommendations",
    "manual_correction": "Manual correction",
}

IMPORT_COST_ESTIMATE_STAGE = "import_cost_estimate"

CAPABILITY_STAGE = {
    "document_structure_cleanup": "document_structure_cleanup",
    "structured_tables": "structured_tables",
    "page_text_normalization": "page_text_normalization",
    "bibliography_extraction": "bibliography_extraction",
    "formula_capture": "formula_capture",
    "visual_asset_extraction": "visual_asset_extraction",
    "visual_asset_context": "visual_asset_context",
    "figure_assets": "visual_asset_extraction",
    "search_index": "search_index",
    "summary_topics": "summary_topics",
    "tag_governance": "tag_governance",
    "summary_refresh": "summary_refresh",
    "citation_refresh": "citation_refresh",
    "text_chunk_encoding": "text_chunk_encoding",
    "recommendations": "recommendations",
}

PIPELINE_TASK_OFFSETS = {
    MODEL_PAGE_TEXT_NORMALIZATION: 0.2,
    MODEL_METADATA: 0.1,
    MODEL_CORE_DOCUMENT_INTELLIGENCE: 0.1,
    MODEL_SUMMARY: 0.2,
    MODEL_KEYWORDS_TOPICS: 0.3,
    MODEL_APA_CITATION: 0.1,
    MODEL_FORMULA_CAPTURE: 0.2,
    MODEL_TEXT_CHUNK_ENCODING: 0.1,
}

PIPELINE_LOCAL_OFFSETS = {
    "raw_text_extraction": 0.0,
    "document_structure_cleanup": 0.0,
    "ocr_fallback": 0.0,
    "structured_tables": 0.0,
    "page_text_normalization": 0.0,
    "bibliography_extraction": 0.0,
    "formula_capture": 0.0,
    "visual_asset_extraction": 0.0,
    "figure_assets": 0.0,
    "visual_asset_context": 0.0,
    "summary_topics": 0.9,
    "summary_refresh": 0.0,
    "text_chunk_encoding": 0.9,
    "search_index": 0.0,
    "cache_cleanup": 0.0,
    "recommendations": 0.0,
}

PIPELINE_RECORD_KINDS = {"local", "llm", "embedding", "concordance", "estimate_step"}
ESTIMATE_FALLBACK_TASK_KEYS = {
    "raw_text_extraction",
    "document_structure_cleanup",
    "ocr_fallback",
    "structured_tables",
    MODEL_PAGE_TEXT_NORMALIZATION,
    "bibliography_extraction",
    "formula_capture",
    "visual_asset_extraction",
    "visual_asset_context",
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
    record_metadata = {"source": "import" if job else "local", **(metadata or {})}
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
        record_metadata=record_metadata,
    )
    db.add(record)
    return record


def record_concordance_stage(
    db: Session,
    *,
    document: Document,
    concordance_job: Any,
    stage_key: str,
    label: str | None = None,
    method: str | None = None,
    model: str | None = None,
    status: str = "complete",
    started_at: datetime | None = None,
    duration_ms: int | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentCompositionRecord:
    completed_at = utc_now()
    run_id = getattr(concordance_job, "run_id", None)
    job_id = getattr(concordance_job, "id", None)
    capability_key = getattr(concordance_job, "capability_key", stage_key)
    target_version = getattr(concordance_job, "target_version", None)
    stage = CAPABILITY_STAGE.get(stage_key, stage_key)
    base_label = label or stage_label(stage)
    record_metadata = {
        "source": "concordance",
        "concordance_run_id": run_id,
        "concordance_job_id": job_id,
        "capability_key": capability_key,
        "target_version": target_version,
        **(metadata or {}),
    }
    record = DocumentCompositionRecord(
        document_id=document.id,
        sequence=STAGE_SEQUENCE.get(stage, 80),
        record_kind="concordance",
        stage_key=stage,
        stage_label=f"Concordance: {base_label}",
        provider="local",
        method=method or capability_key or "concordance",
        model=model,
        status=status,
        amount_usd=0.0,
        duration_ms=duration_ms,
        started_at=started_at,
        completed_at=completed_at,
        message=message,
        record_metadata=record_metadata,
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
        "source": "import" if job else "estimate",
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
        usage_source = usage.source or "unknown"
        usage_stage_label = stage_label(stage_key)
        if usage_source == "concordance":
            usage_stage_label = f"Concordance: {usage_stage_label}"
        db.add(
            DocumentCompositionRecord(
                document_id=document.id,
                import_job_id=usage.import_job_id,
                usage_record_id=usage.id,
                sequence=STAGE_SEQUENCE.get(stage_key, 80),
                record_kind=record_kind,
                stage_key=stage_key,
                stage_label=usage_stage_label,
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
                    "source": usage_source,
                    "endpoint": usage.endpoint,
                    "task_key": usage.task_key,
                    "capability_key": usage.capability_key,
                    "concordance_run_id": usage.concordance_run_id,
                    "concordance_job_id": usage.concordance_job_id,
                    "import_job_id": usage.import_job_id,
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


def _metadata_int(metadata: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(metadata.get(key) or default)
    except (TypeError, ValueError):
        return default


def _record_stage_key(record: DocumentCompositionRecord) -> str:
    metadata = _record_metadata(record)
    capability_key = metadata.get("capability_key")
    if record.record_kind in {"llm", "embedding"} and isinstance(capability_key, str) and capability_key in CAPABILITY_STAGE:
        return CAPABILITY_STAGE[capability_key]
    return record.stage_key


def _record_stage_label(record: DocumentCompositionRecord) -> str:
    stage = _record_stage_key(record)
    if stage != record.stage_key:
        return stage_label(stage)
    return record.stage_label


def _record_sequence(record: DocumentCompositionRecord) -> int:
    return STAGE_SEQUENCE.get(_record_stage_key(record), record.sequence if record.sequence is not None else 80)


def _record_method(record: DocumentCompositionRecord) -> str | None:
    metadata = _record_metadata(record)
    if (
        record.record_kind in {"local", "concordance"}
        and record.stage_key == "page_text_normalization"
        and record.method == "local_first_auto"
        and _metadata_int(metadata, "auto_cloud_pages") <= 0
    ):
        return "local_auto"
    return record.method


def _record_model(record: DocumentCompositionRecord) -> str | None:
    if (
        record.record_kind in {"local", "concordance"}
        and record.stage_key == "page_text_normalization"
        and record.method == "local_first_auto"
    ):
        return None
    if record.record_kind == "local" and record.stage_key == "text_chunk_encoding" and record.method == "embedding_index":
        return None
    return record.model


def _usage_costs_by_id(db: Session, records: list[DocumentCompositionRecord]) -> dict[str, float | None]:
    usage_ids = sorted(
        {
            record.usage_record_id
            for record in records
            if record.usage_record_id and record.record_kind in {"llm", "embedding"}
        }
    )
    if not usage_ids:
        return {}
    usage_records = db.query(OpenAIUsageRecord).filter(OpenAIUsageRecord.id.in_(usage_ids)).all()
    return estimated_costs_usd_for_records(usage_records, db)


def _record_amount(record: DocumentCompositionRecord, usage_costs: dict[str, float | None]) -> float:
    if record.usage_record_id and record.record_kind in {"llm", "embedding"}:
        cost = usage_costs.get(record.usage_record_id)
        if cost is not None:
            return max(0.0, float(cost or 0.0))
    return _float(record.amount_usd)


def _timestamp_sort_value(value: datetime | None) -> float:
    return value.timestamp() if value else float("inf")


def _record_source(record: DocumentCompositionRecord) -> str:
    metadata = _record_metadata(record)
    value = metadata.get("source")
    if isinstance(value, str) and value:
        return value
    if record.import_job_id:
        return "import"
    if record.record_kind == "concordance":
        return "concordance"
    return record.record_kind or "unknown"


def _record_task_identity(record: DocumentCompositionRecord) -> str:
    metadata = _record_metadata(record)
    capability_key = metadata.get("capability_key")
    if isinstance(capability_key, str) and capability_key and capability_key != record.stage_key and capability_key in CAPABILITY_STAGE:
        return capability_key
    task_key = metadata.get("task_key")
    if isinstance(task_key, str) and task_key:
        return task_key
    if isinstance(capability_key, str) and capability_key:
        return capability_key
    return _record_stage_key(record)


def _pipeline_record_order(record: DocumentCompositionRecord, fallback_index: int) -> tuple[float, float, int]:
    metadata = _record_metadata(record)
    task_key = metadata.get("task_key")
    stage = _record_stage_key(record)
    base = float(_record_sequence(record))
    if isinstance(task_key, str) and task_key in PIPELINE_TASK_OFFSETS:
        offset = PIPELINE_TASK_OFFSETS[task_key]
    elif record.record_kind == "local":
        offset = PIPELINE_LOCAL_OFFSETS.get(stage, 0.5)
    elif record.record_kind == "concordance":
        offset = PIPELINE_LOCAL_OFFSETS.get(stage, 0.05)
    else:
        offset = 0.4
    source = _record_source(record)
    if source == "concordance":
        occurred_at = record.started_at or record.completed_at or record.created_at
        return (1000.0, _timestamp_sort_value(occurred_at), int((base + offset) * 1000) + fallback_index)
    occurred_at = record.completed_at or record.started_at or record.created_at
    return (base + offset, _timestamp_sort_value(occurred_at), fallback_index)


def _sum_duration(records: list[DocumentCompositionRecord]) -> int:
    return sum(max(0, int(record.duration_ms or 0)) for record in records if record.record_kind in {"local", "concordance"})


def _pipeline_group_key(record: DocumentCompositionRecord) -> tuple[Any, ...]:
    metadata = _record_metadata(record)
    return (
        _record_stage_key(record),
        record.provider,
        _record_method(record),
        _record_model(record),
        record.record_kind,
        _record_source(record),
        metadata.get("concordance_run_id"),
        metadata.get("concordance_job_id"),
        metadata.get("task_key"),
    )


def _estimate_stage_key(task_key: str) -> str:
    if task_key in CAPABILITY_STAGE:
        return CAPABILITY_STAGE[task_key]
    if task_key in {MODEL_METADATA, MODEL_SUMMARY, MODEL_KEYWORDS_TOPICS, MODEL_CORE_DOCUMENT_INTELLIGENCE}:
        return "summary_topics"
    if task_key == MODEL_APA_CITATION:
        return "citation_refresh"
    if task_key == MODEL_TEXT_CHUNK_ENCODING:
        return "text_chunk_encoding"
    return task_key


def _latest_import_estimate(records: list[DocumentCompositionRecord]) -> DocumentCompositionRecord | None:
    estimate_records = [
        record
        for record in records
        if record.record_kind == "estimate" and record.stage_key == IMPORT_COST_ESTIMATE_STAGE
    ]
    if not estimate_records:
        return None
    return max(estimate_records, key=lambda record: record.completed_at or record.created_at)


def _estimate_step_rows(
    records: list[DocumentCompositionRecord],
    represented_task_keys: set[str],
) -> list[dict[str, Any]]:
    estimate = _latest_import_estimate(records)
    if not estimate:
        return []
    metadata = _record_metadata(estimate)
    raw_steps = metadata.get("step_estimates")
    if not isinstance(raw_steps, list):
        return []
    rows: list[dict[str, Any]] = []
    created_at = estimate.completed_at or estimate.created_at
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            continue
        task_key = str(raw_step.get("task_key") or "").strip()
        if not task_key or task_key in represented_task_keys:
            continue
        if task_key not in ESTIMATE_FALLBACK_TASK_KEYS:
            continue
        status = str(raw_step.get("status") or raw_step.get("basis") or "estimated")
        if status in {"disabled_by_preset", "not_expected"}:
            continue
        stage_key = _estimate_stage_key(task_key)
        stage_sequence = STAGE_SEQUENCE.get(stage_key, 80)
        rows.append(
            {
                "label": raw_step.get("label") or stage_label(stage_key),
                "stage_key": stage_key,
                "stage_label": raw_step.get("label") or stage_label(stage_key),
                "provider": "Medusa estimate",
                "method": raw_step.get("basis") or "estimate",
                "model": raw_step.get("model"),
                "record_kind": "estimate_step",
                "status": status,
                "amount_usd": _float(raw_step.get("estimated_cost_usd")),
                "duration_ms": 0,
                "input_tokens": int(raw_step.get("estimated_input_tokens") or 0),
                "output_tokens": int(raw_step.get("estimated_output_tokens") or 0),
                "total_tokens": int(raw_step.get("estimated_input_tokens") or 0) + int(raw_step.get("estimated_output_tokens") or 0),
                "call_count": 0,
                "sequence": stage_sequence,
                "created_at": created_at,
                "_sort_order": (
                    float(stage_sequence) + (index / 100.0),
                    _timestamp_sort_value(created_at),
                    -1,
                ),
            }
        )
        represented_task_keys.add(task_key)
    return rows


def _estimate_comparison(records: list[DocumentCompositionRecord], usage_costs: dict[str, float | None]) -> dict[str, Any] | None:
    estimate = _latest_import_estimate(records)
    if not estimate or _float(estimate.amount_usd) <= 0:
        return None
    metadata = _record_metadata(estimate)
    estimated_cost = round(_float(estimate.amount_usd), 6)
    actual_cost = round(
        sum(
            _record_amount(record, usage_costs)
            for record in records
            if record.record_kind in {"llm", "embedding"} and _record_amount(record, usage_costs) > 0
        ),
        9,
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
    represented_task_keys: set[str] = set()
    errata: list[dict[str, Any]] = []
    usage_costs = _usage_costs_by_id(db, records)

    for record_index, record in enumerate(records):
        amount = _record_amount(record, usage_costs)
        provider = provider_label(record.provider)
        display_stage_key = _record_stage_key(record)
        display_stage_label = _record_stage_label(record)
        display_method = _record_method(record)
        display_model = _record_model(record)
        if amount > 0 and record.record_kind != "estimate":
            key = (record.provider, display_model, display_stage_key, record.record_kind)
            group = cost_groups.setdefault(
                key,
                {
                    "label": display_model or display_method or provider,
                    "stage_key": display_stage_key,
                    "stage_label": display_stage_label,
                    "provider": provider,
                    "method": display_method,
                    "model": display_model,
                    "record_kind": record.record_kind,
                    "status": record.status,
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

        if record.record_kind in {"local", "concordance"} and record.duration_ms:
            metadata = _record_metadata(record)
            key = (
                display_stage_key,
                display_method,
                display_model,
                _record_source(record),
                metadata.get("concordance_run_id"),
                metadata.get("concordance_job_id"),
            )
            group = local_groups.setdefault(
                key,
                {
                    "label": display_stage_label,
                    "stage_key": display_stage_key,
                    "stage_label": display_stage_label,
                    "provider": provider,
                    "method": display_method,
                    "model": display_model,
                    "record_kind": record.record_kind,
                    "status": record.status,
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

        if record.record_kind in PIPELINE_RECORD_KINDS:
            represented_task_keys.add(_record_task_identity(record))
            key = _pipeline_group_key(record)
            pipeline_order = _pipeline_record_order(record, record_index)
            group = pipeline_groups.setdefault(
                key,
                {
                    "label": display_stage_label,
                    "stage_key": display_stage_key,
                    "stage_label": display_stage_label,
                    "provider": provider,
                    "method": display_method,
                    "model": display_model,
                    "record_kind": record.record_kind,
                    "status": record.status,
                    "amount_usd": 0.0,
                    "duration_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "call_count": 0,
                    "sequence": _record_sequence(record),
                    "created_at": record.completed_at or record.started_at or record.created_at,
                    "_sort_order": pipeline_order,
                },
            )
            if pipeline_order < group["_sort_order"]:
                group["_sort_order"] = pipeline_order
                group["created_at"] = record.completed_at or record.started_at or record.created_at
                group["status"] = record.status
            group["amount_usd"] += amount
            group["duration_ms"] += record.duration_ms or 0
            group["input_tokens"] += record.input_tokens
            group["output_tokens"] += record.output_tokens
            group["total_tokens"] += record.total_tokens
            group["call_count"] += 1

        if record.record_kind == "erratum" or record.status in {"failed", "error", "warning"}:
            errata.append(
                {
                    "label": display_stage_label,
                    "stage_key": display_stage_key,
                    "stage_label": display_stage_label,
                    "provider": provider if record.provider else None,
                    "method": display_method,
                    "model": display_model,
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
            row["amount_usd"] = round(_float(row.get("amount_usd")), 9)
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
        rounded_groups([*pipeline_groups.values(), *_estimate_step_rows(records, represented_task_keys)]),
        key=lambda row: row.get("_sort_order") or (row.get("sequence") or 0, float("inf"), 0),
    )
    for row in pipeline:
        row.pop("_sort_order", None)
    total_cost = round(sum(_float(group.get("amount_usd")) for group in cost_groups.values()), 9)
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
        "estimate_comparison": _estimate_comparison(records, usage_costs),
    }
