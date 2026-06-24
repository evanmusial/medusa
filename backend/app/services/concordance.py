from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    CitationCandidate,
    ConcordanceJob,
    ConcordanceRun,
    Document,
    DocumentCapability,
    Domain,
    OpenAIUsageRecord,
    ProjectItem,
    SavedSearch,
    Tag,
    utc_now,
)
from app.services.ai import get_ai_service
from app.services.analysis_models import (
    MODEL_APA_CITATION,
    MODEL_BIBLIOGRAPHY_CLEANUP,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_SUMMARY,
    is_google_text_model,
)
from app.services.citations import decode_html_entities, merge_citation_metadata
from app.services.bibliography import extract_document_bibliography
from app.services.composition import elapsed_ms, record_concordance_stage, record_import_erratum, stage_timer, sync_import_usage_composition
from app.services.document_cache import ensure_document_pdf_bytes
from app.services.document_visibility import filter_library_visible_documents
from app.services.figures import process_document_figures_from_storage
from app.services.history import (
    changed_snapshot_fields,
    document_correction_snapshot,
    document_page_snapshot,
    record_document_version,
)
from app.services.openai_usage import OpenAIUsageContext
from app.services.openai_usage import estimated_cost_usd_for_model_tokens
from app.services.preferences import get_analysis_model, get_analysis_models
from app.services.preferences import import_processing_cloud_page_cap, import_processing_snapshot
from app.services.processing import (
    apply_document_citations,
    document_metadata,
    fill_missing_document_metadata,
    log_event,
    normalize_document_pages,
    rebuild_document_text_chunks,
)
from app.services.second_pass import clean_document_structure
from app.services.figures import enrich_figure_context
from app.services.recommendations import refresh_document_recommendations
from app.services.search import rebuild_document_search_text
from app.services.tag_governance import apply_import_tag_governance
from app.services.tags import existing_tag_manifest
from app.services.verifier import (
    crossref_lookup,
    crossref_to_citation_metadata,
    enough_metadata_for_verified_citation,
    extract_doi_from_text,
)


@dataclass(frozen=True)
class CapabilityDefinition:
    key: str
    label: str
    version: int
    description: str


@dataclass(frozen=True)
class ConcordanceModelRequirement:
    task_key: str
    field_key: str
    label: str
    model: str | None
    estimated_pages: int | None = None


CURRENT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        key="document_structure_cleanup",
        label="Document structure cleanup",
        version=1,
        description="Remove repeated headers/footers, page numbers, decorative text art, front matter noise, whitespace artifacts, drop caps, and bullet/list damage while preserving raw page text.",
    ),
    CapabilityDefinition(
        key="structured_tables",
        label="Structured tables",
        version=1,
        description="Detect table-like extracted regions and preserve table evidence separately from narrative body text.",
    ),
    CapabilityDefinition(
        key="ocr_fallback",
        label="OCR fallback",
        version=1,
        description="Audit low-text/scanned pages for OCR eligibility and run OCR when the selected preset and credentials allow it.",
    ),
    CapabilityDefinition(
        key="page_text_normalization",
        label="Page text normalization",
        version=3,
        description="Conform extracted page text into standard readable flow across columns and around graphics without converting graphics to text.",
    ),
    CapabilityDefinition(
        key="search_index",
        label="Search index",
        version=3,
        description="Rebuild full-text search from metadata, author contacts, normalized page text, summaries, figures, notes, attributes, tags, and domains.",
    ),
    CapabilityDefinition(
        key="citation_refresh",
        label="Citation refresh",
        version=4,
        description="Regenerate APA reference-list and in-text citation text with model/provenance tracking.",
    ),
    CapabilityDefinition(
        key="summary_topics",
        label="AI metadata and summary",
        version=8,
        description="Use routed document intelligence plus tag governance: high-quality metadata, GPT-5.4 summaries from text, and scored GPT-5.4-mini topic tags without generating APA unless citation refresh needs it.",
    ),
    CapabilityDefinition(
        key="bibliography_extraction",
        label="Bibliography extraction",
        version=1,
        description="Extract the source document's own reference list into the Bibliography field, preserving Markdown italics from PDF span evidence when available.",
    ),
    CapabilityDefinition(
        key="visual_asset_extraction",
        label="Visual asset extraction",
        version=2,
        description="Run the second-pass 300 DPI visual extractor/audit for images, charts, vector graphics, diagrams, photos, maps, scans, and unclaimed visual regions.",
    ),
    CapabilityDefinition(
        key="visual_asset_context",
        label="Visual asset context",
        version=1,
        description="Link figures and tables to captions, nearby headings, surrounding paragraphs, and explicit references such as Figure 2 or Table 1.",
    ),
    CapabilityDefinition(
        key="recommendations",
        label="Related paper recommendations",
        version=1,
        description="Refresh DOI-based related-paper recommendations and mark recommendations already present in the library.",
    ),
)

SUMMARY_REFRESH_CAPABILITY = CapabilityDefinition(
    key="summary_refresh",
    label="Summary refresh",
    version=1,
    description="Regenerate the main document summary using only the selected Summary model.",
)

TAG_REFRESH_CAPABILITY = CapabilityDefinition(
    key="tag_refresh",
    label="Tag refresh",
    version=1,
    description="Replace this document's tag assignments by rerunning import-style tag suggestions and existing-first tag governance.",
)

LEGACY_FIGURE_ASSETS_CAPABILITY = CapabilityDefinition(
    key="figure_assets",
    label="Figure assets",
    version=4,
    description="Legacy alias for visual asset extraction.",
)

CAPABILITY_BY_KEY = {
    capability.key: capability
    for capability in (*CURRENT_CAPABILITIES, SUMMARY_REFRESH_CAPABILITY, TAG_REFRESH_CAPABILITY, LEGACY_FIGURE_ASSETS_CAPABILITY)
}

CONCORDANCE_LOCAL_MODELS = {
    "",
    "local",
    "none",
    "marker",
    "pymupdf",
    "docling",
    "google_vision",
}

CONCORDANCE_TOKEN_PROFILES: dict[str, dict[str, int]] = {
    MODEL_METADATA: {"input_base": 1_000, "input_per_page": 1_300, "output_base": 1_200},
    MODEL_SUMMARY: {"input_base": 1_000, "input_per_page": 1_800, "output_base": 1_400},
    MODEL_APA_CITATION: {"input_base": 4_000, "input_per_page": 450, "output_base": 900},
    MODEL_KEYWORDS_TOPICS: {"input_base": 900, "input_per_page": 1_000, "output_base": 850},
    MODEL_PAGE_TEXT_NORMALIZATION: {"input_base": 150, "input_per_page": 1_600, "output_base": 350, "output_per_page": 900},
}


def _summary_needs_markdown_refresh(summary: str | None) -> bool:
    if not summary:
        return True
    if summary.startswith("Metadata extraction is pending."):
        return True
    stripped = summary.strip()
    if not stripped:
        return True
    has_markdown_structure = any(marker in stripped for marker in ("\n-", "\n*", "\n#", "**"))
    return not has_markdown_structure and len(stripped) > 500


def current_capabilities() -> list[dict[str, Any]]:
    return [
        {
            "key": capability.key,
            "label": capability.label,
            "version": capability.version,
            "description": capability.description,
        }
        for capability in CURRENT_CAPABILITIES
    ]


def concordance_stage_model(db: Session, capability_key: str) -> str | None:
    if capability_key == "document_structure_cleanup":
        preset = import_processing_snapshot(db)
        cleanup = preset.get("cleanup") if isinstance(preset.get("cleanup"), dict) else {}
        if not bool(cleanup.get("cloud_escalation", True)):
            return "local"
        return str(cleanup.get("model") or get_analysis_model(db, MODEL_PAGE_TEXT_NORMALIZATION))
    if capability_key == "page_text_normalization":
        return get_analysis_model(db, MODEL_PAGE_TEXT_NORMALIZATION)
    if capability_key == "summary_refresh":
        return get_analysis_model(db, MODEL_SUMMARY)
    if capability_key == "tag_refresh":
        return get_analysis_model(db, MODEL_KEYWORDS_TOPICS)
    if capability_key == "summary_topics":
        models = get_analysis_models(db)
        return ", ".join(
            model
            for model in [
                models.get(MODEL_METADATA),
                models.get(MODEL_SUMMARY),
                models.get(MODEL_KEYWORDS_TOPICS),
            ]
            if model
        )
    if capability_key == "citation_refresh":
        return get_analysis_model(db, MODEL_APA_CITATION)
    if capability_key == "bibliography_extraction":
        return get_analysis_model(db, MODEL_BIBLIOGRAPHY_CLEANUP)
    return None


def concordance_stage_status(evidence: dict[str, Any]) -> str:
    status = evidence.get("status")
    if isinstance(status, str) and status:
        return status
    if evidence.get("skipped"):
        return "skipped"
    return "complete"


def _document_page_count(document: Document) -> int:
    if document.page_count and document.page_count > 0:
        return int(document.page_count)
    if document.pages:
        return len(document.pages)
    return 1


def _is_cloud_model(model: str | None) -> bool:
    normalized = (model or "").strip().lower()
    if normalized in CONCORDANCE_LOCAL_MODELS:
        return False
    return normalized.startswith(("gpt-", "o", "text-embedding-")) or is_google_text_model(normalized)


def _token_estimate(task_key: str, page_count: int) -> tuple[int, int]:
    profile = CONCORDANCE_TOKEN_PROFILES.get(task_key, {"input_base": 500, "input_per_page": 1_000, "output_base": 500})
    input_tokens = int(profile.get("input_base", 0)) + int(profile.get("input_per_page", 0)) * max(1, page_count)
    output_tokens = int(profile.get("output_base", 0)) + int(profile.get("output_per_page", 0)) * max(1, page_count)
    return max(0, input_tokens), max(0, output_tokens)


def _document_has_meaningful_summary(document: Document) -> bool:
    summary = (document.rich_summary or "").strip()
    if not summary:
        return False
    lowered = summary.lower()
    return "summary refresh is pending" not in lowered and "metadata extraction is pending" not in lowered


def _document_has_metadata_identity(document: Document) -> bool:
    return bool(
        document.title
        and (
            document.authors
            or document.publication_year
            or document.journal
            or document.publisher
            or document.doi
            or document.abstract
        )
    )


def _metadata_models(document: Document, task_key: str) -> set[str]:
    evidence = document.metadata_evidence or {}
    models: set[str] = set()
    for section_key in ("ai", "concordance_ai"):
        section = evidence.get(section_key)
        if not isinstance(section, dict):
            continue
        section_models = section.get("models")
        if isinstance(section_models, dict) and isinstance(section_models.get(task_key), str):
            models.add(str(section_models[task_key]))
        if task_key == MODEL_SUMMARY and isinstance(section.get("model"), str):
            models.add(str(section["model"]))
    if task_key == MODEL_SUMMARY:
        section = evidence.get("summary_refresh")
        if isinstance(section, dict) and isinstance(section.get("model"), str):
            models.add(str(section["model"]))
    if task_key == MODEL_APA_CITATION:
        for section_key in ("ai_apa", "citation_refresh"):
            section = evidence.get(section_key)
            if isinstance(section, dict) and isinstance(section.get("model"), str):
                models.add(str(section["model"]))
    if task_key == MODEL_PAGE_TEXT_NORMALIZATION:
        section = evidence.get("page_text_normalization")
        if isinstance(section, dict):
            section_models = section.get("models")
            if isinstance(section_models, dict):
                models.update(str(model) for model in section_models if isinstance(model, str) and model)
    return models


def _latest_successful_task_model(db: Session, document_id: str, task_key: str, model: str) -> bool:
    return bool(
        db.query(OpenAIUsageRecord.id)
        .filter(
            OpenAIUsageRecord.document_id == document_id,
            OpenAIUsageRecord.task_key == task_key,
            OpenAIUsageRecord.model == model,
            OpenAIUsageRecord.status != "failed",
        )
        .order_by(OpenAIUsageRecord.created_at.desc())
        .first()
    )


def _model_requirement_current(db: Session, document: Document, requirement: ConcordanceModelRequirement) -> bool:
    model = (requirement.model or "").strip()
    if not model or not _is_cloud_model(model):
        return False
    if requirement.task_key == MODEL_SUMMARY and not _document_has_meaningful_summary(document):
        return False
    if requirement.task_key == MODEL_METADATA and not _document_has_metadata_identity(document):
        return False
    if requirement.task_key == MODEL_APA_CITATION:
        if (
            document.apa_citation
            and document.apa_in_text_citation
            and document.apa_citation_model == model
            and document.apa_in_text_citation_model == model
        ):
            return True
    if requirement.task_key == MODEL_PAGE_TEXT_NORMALIZATION and not any(page.normalized_text for page in document.pages):
        return False
    if model in _metadata_models(document, requirement.task_key):
        return True
    return _latest_successful_task_model(db, document.id, requirement.task_key, model)


def concordance_model_requirements(
    db: Session,
    capability_key: str,
    document: Document | None = None,
) -> list[ConcordanceModelRequirement]:
    model_preferences = get_analysis_models(db)
    if capability_key == "document_structure_cleanup":
        preset = import_processing_snapshot(db)
        cleanup = preset.get("cleanup") if isinstance(preset.get("cleanup"), dict) else {}
        if not bool(cleanup.get("enabled", True)) or not bool(cleanup.get("cloud_escalation", True)):
            return []
        page_count = _document_page_count(document) if document is not None else None
        estimated_pages = import_processing_cloud_page_cap(preset, page_count or 1) if page_count else None
        return [
            ConcordanceModelRequirement(
                task_key=MODEL_PAGE_TEXT_NORMALIZATION,
                field_key="cleaned_page_text",
                label="Flagged-page normalization",
                model=str(cleanup.get("model") or model_preferences.get(MODEL_PAGE_TEXT_NORMALIZATION)),
                estimated_pages=estimated_pages,
            )
        ]
    if capability_key == "page_text_normalization":
        preset = import_processing_snapshot(db)
        page_count = _document_page_count(document) if document is not None else None
        estimated_pages = import_processing_cloud_page_cap(preset, page_count or 1) if page_count else None
        return [
            ConcordanceModelRequirement(
                task_key=MODEL_PAGE_TEXT_NORMALIZATION,
                field_key="page_text",
                label="Page text normalization",
                model=model_preferences.get(MODEL_PAGE_TEXT_NORMALIZATION),
                estimated_pages=estimated_pages,
            )
        ]
    if capability_key == "summary_refresh":
        return [
            ConcordanceModelRequirement(
                task_key=MODEL_SUMMARY,
                field_key="rich_summary",
                label="Summary",
                model=model_preferences.get(MODEL_SUMMARY),
            )
        ]
    if capability_key == "tag_refresh":
        return [
            ConcordanceModelRequirement(
                task_key=MODEL_KEYWORDS_TOPICS,
                field_key="tags",
                label="Tag suggestions",
                model=model_preferences.get(MODEL_KEYWORDS_TOPICS),
            )
        ]
    if capability_key == "summary_topics":
        return [
            ConcordanceModelRequirement(
                task_key=MODEL_METADATA,
                field_key="metadata",
                label="Metadata",
                model=model_preferences.get(MODEL_METADATA),
            ),
            ConcordanceModelRequirement(
                task_key=MODEL_KEYWORDS_TOPICS,
                field_key="tags",
                label="Tag suggestions",
                model=model_preferences.get(MODEL_KEYWORDS_TOPICS),
            ),
            ConcordanceModelRequirement(
                task_key=MODEL_SUMMARY,
                field_key="rich_summary",
                label="Summary",
                model=model_preferences.get(MODEL_SUMMARY),
            ),
        ]
    if capability_key == "citation_refresh":
        return [
            ConcordanceModelRequirement(
                task_key=MODEL_APA_CITATION,
                field_key="apa_citation",
                label="APA citation",
                model=model_preferences.get(MODEL_APA_CITATION),
            )
        ]
    return []


def _same_model_noop(
    db: Session,
    document: Document,
    capability_key: str,
) -> tuple[bool, list[ConcordanceModelRequirement]]:
    requirements = [requirement for requirement in concordance_model_requirements(db, capability_key, document) if _is_cloud_model(requirement.model)]
    if not requirements:
        return False, []
    return all(_model_requirement_current(db, document, requirement) for requirement in requirements), requirements


def _estimate_requirement_cost(
    db: Session,
    document: Document,
    requirement: ConcordanceModelRequirement,
) -> dict[str, Any]:
    page_count = max(1, int(requirement.estimated_pages or _document_page_count(document)))
    model = requirement.model or "local"
    row: dict[str, Any] = {
        "task_key": requirement.task_key,
        "field_key": requirement.field_key,
        "label": requirement.label,
        "model": model,
        "estimated_pages": page_count,
        "estimated_cost_usd": 0.0,
        "basis": "local",
        "status": "local",
    }
    if not _is_cloud_model(model):
        return row
    input_tokens, output_tokens = _token_estimate(requirement.task_key, page_count)
    row["estimated_input_tokens"] = input_tokens
    row["estimated_output_tokens"] = output_tokens
    priced = estimated_cost_usd_for_model_tokens(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        db=db,
    )
    if priced is None:
        row["basis"] = "unpriced_model"
        row["status"] = "unpriced"
        return row
    row["estimated_cost_usd"] = round(max(0.0, priced), 6)
    row["basis"] = "model_pricing"
    row["status"] = "estimated"
    return row


def _plan_concordance_item(
    db: Session,
    document: Document,
    capability: CapabilityDefinition,
    *,
    force: bool,
) -> dict[str, Any]:
    noop, requirements = (False, []) if force else _same_model_noop(db, document, capability.key)
    if noop:
        return {
            "document": document,
            "document_id": document.id,
            "document_title": document.title,
            "capability_key": capability.key,
            "capability_label": capability.label,
            "target_version": capability.version,
            "status": "model_no_op",
            "reason": "The relevant field already has successful output from the currently selected model.",
            "estimated_cost_usd": 0.0,
            "estimate_basis": "same_model_no_op",
            "requirements": [_requirement_payload(requirement) for requirement in requirements],
            "cost_steps": [],
        }
    if _already_queued_or_running(db, document.id, capability.key):
        return {
            "document": document,
            "document_id": document.id,
            "document_title": document.title,
            "capability_key": capability.key,
            "capability_label": capability.label,
            "target_version": capability.version,
            "status": "already_queued",
            "reason": "A Concordance job for this document and capability is already queued or running.",
            "estimated_cost_usd": 0.0,
            "estimate_basis": "already_queued",
            "requirements": [_requirement_payload(requirement) for requirement in requirements],
            "cost_steps": [],
        }
    if not force and not requirements and _document_has_current_capability(db, document.id, capability):
        return {
            "document": document,
            "document_id": document.id,
            "document_title": document.title,
            "capability_key": capability.key,
            "capability_label": capability.label,
            "target_version": capability.version,
            "status": "current_version",
            "reason": "The document already records the current capability version.",
            "estimated_cost_usd": 0.0,
            "estimate_basis": "current_version",
            "requirements": [_requirement_payload(requirement) for requirement in requirements],
            "cost_steps": [],
        }
    requirements = concordance_model_requirements(db, capability.key, document)
    pending_requirements = (
        requirements
        if force
        else [
            requirement
            for requirement in requirements
            if not (_is_cloud_model(requirement.model) and _model_requirement_current(db, document, requirement))
        ]
    )
    cost_steps = [_estimate_requirement_cost(db, document, requirement) for requirement in pending_requirements]
    estimated_cost = round(sum(float(step.get("estimated_cost_usd") or 0.0) for step in cost_steps), 6)
    if cost_steps and any(step.get("status") == "unpriced" for step in cost_steps):
        basis = "partially_unpriced" if estimated_cost > 0 else "unpriced_model"
    elif cost_steps and estimated_cost > 0:
        basis = "model_pricing"
    else:
        basis = "local_or_no_cloud_calls"
    return {
        "document": document,
        "document_id": document.id,
        "document_title": document.title,
        "capability_key": capability.key,
        "capability_label": capability.label,
        "target_version": capability.version,
        "status": "planned",
        "reason": "Will be queued for Concordance.",
        "estimated_cost_usd": estimated_cost,
        "estimate_basis": basis,
        "requirements": [_requirement_payload(requirement) for requirement in requirements],
        "cost_steps": cost_steps,
    }


def _requirement_payload(requirement: ConcordanceModelRequirement) -> dict[str, Any]:
    return {
        "task_key": requirement.task_key,
        "field_key": requirement.field_key,
        "label": requirement.label,
        "model": requirement.model,
        "estimated_pages": requirement.estimated_pages,
    }


def _public_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "document"}


def plan_concordance_run(
    db: Session,
    *,
    scope_type: str = "library",
    scope_data: dict[str, Any] | None = None,
    capability_keys: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    scope_data = scope_data or {}
    selected_keys = capability_keys or [capability.key for capability in CURRENT_CAPABILITIES]
    unknown_keys = sorted(set(selected_keys) - set(CAPABILITY_BY_KEY))
    if unknown_keys:
        raise ValueError(f"Unknown Concordance capability: {', '.join(unknown_keys)}")

    documents = documents_for_scope(db, scope_type, scope_data)
    items: list[dict[str, Any]] = []
    for document in documents:
        for key in selected_keys:
            items.append(_plan_concordance_item(db, document, CAPABILITY_BY_KEY[key], force=force))
    planned = [item for item in items if item["status"] == "planned"]
    skipped = [item for item in items if item["status"] != "planned"]
    cost_steps = [step for item in planned for step in item.get("cost_steps", [])]
    return {
        "scope_type": scope_type,
        "scope_data": scope_data,
        "capability_keys": selected_keys,
        "document_count": len(documents),
        "planned_jobs": len(planned),
        "skipped_jobs": len(skipped),
        "model_no_op_jobs": sum(1 for item in skipped if item["status"] == "model_no_op"),
        "already_queued_jobs": sum(1 for item in skipped if item["status"] == "already_queued"),
        "current_version_jobs": sum(1 for item in skipped if item["status"] == "current_version"),
        "estimated_cost_usd": round(sum(float(item.get("estimated_cost_usd") or 0.0) for item in planned), 6),
        "priced_call_count": sum(1 for step in cost_steps if float(step.get("estimated_cost_usd") or 0.0) > 0),
        "unpriced_call_count": sum(1 for step in cost_steps if step.get("status") == "unpriced"),
        "local_job_count": sum(
            1
            for item in planned
            if float(item.get("estimated_cost_usd") or 0.0) <= 0
            and not any(step.get("status") == "unpriced" for step in item.get("cost_steps", []))
        ),
        "items": items,
    }


def estimate_concordance_run(
    db: Session,
    *,
    scope_type: str = "library",
    scope_data: dict[str, Any] | None = None,
    capability_keys: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    plan = plan_concordance_run(
        db,
        scope_type=scope_type,
        scope_data=scope_data,
        capability_keys=capability_keys,
        force=force,
    )
    return {
        **plan,
        "items": [_public_plan_item(item) for item in plan["items"]],
    }


def refresh_concordance_run_progress(db: Session, run: ConcordanceRun) -> None:
    db.flush()
    run.completed_jobs = db.query(ConcordanceJob).filter(
        ConcordanceJob.run_id == run.id,
        ConcordanceJob.status == "complete",
    ).count()
    run.failed_jobs = db.query(ConcordanceJob).filter(
        ConcordanceJob.run_id == run.id,
        ConcordanceJob.status == "failed",
    ).count()
    running_jobs = db.query(ConcordanceJob).filter(
        ConcordanceJob.run_id == run.id,
        ConcordanceJob.status == "running",
    ).count()
    finished_jobs = run.completed_jobs + run.failed_jobs
    if run.total_jobs == 0:
        run.status = "complete"
    elif finished_jobs >= run.total_jobs:
        run.status = "complete" if run.failed_jobs == 0 else "complete_with_errors"
    elif finished_jobs > 0 or running_jobs > 0:
        run.status = "running"
    else:
        run.status = "queued"


def _document_has_current_capability(db: Session, document_id: str, capability: CapabilityDefinition) -> bool:
    state = (
        db.query(DocumentCapability)
        .filter(
            DocumentCapability.document_id == document_id,
            DocumentCapability.capability_key == capability.key,
        )
        .one_or_none()
    )
    return bool(state and state.status == "complete" and state.version >= capability.version)


def _already_queued_or_running(db: Session, document_id: str, capability_key: str) -> bool:
    return bool(
        db.query(ConcordanceJob)
        .filter(
            ConcordanceJob.document_id == document_id,
            ConcordanceJob.capability_key == capability_key,
            ConcordanceJob.status.in_(["queued", "running"]),
        )
        .first()
    )


def documents_for_scope(db: Session, scope_type: str, scope_data: dict[str, Any]) -> list[Document]:
    query = filter_library_visible_documents(db.query(Document))
    if scope_type == "library":
        pass
    elif scope_type == "documents":
        document_ids = scope_data.get("document_ids") or []
        if not document_ids:
            return []
        query = query.filter(Document.id.in_(document_ids))
    elif scope_type == "domain":
        domain_id = scope_data.get("domain_id")
        if not domain_id:
            return []
        query = query.filter(Document.domains.any(Domain.id == domain_id))
    elif scope_type == "project":
        project_id = scope_data.get("project_id")
        if not project_id:
            return []
        query = query.join(ProjectItem, ProjectItem.document_id == Document.id).filter(ProjectItem.project_id == project_id)
    elif scope_type == "search":
        term = str(scope_data.get("query") or "").strip()
        if not term:
            return []
        like = f"%{term}%"
        query = query.filter(
            or_(
                Document.title.ilike(like),
                Document.search_text.ilike(like),
                Document.apa_citation.ilike(like),
                Document.apa_in_text_citation.ilike(like),
            )
        )
    elif scope_type == "saved_search":
        saved_search_id = scope_data.get("saved_search_id")
        if not saved_search_id:
            return []
        saved_search = db.get(SavedSearch, saved_search_id)
        if not saved_search or saved_search.deleted_at:
            return []
        term = str(saved_search.query or "").strip()
        filters = saved_search.filters or {}
        if term:
            like = f"%{term}%"
            query = query.filter(
                or_(
                    Document.title.ilike(like),
                    Document.search_text.ilike(like),
                    Document.apa_citation.ilike(like),
                    Document.apa_in_text_citation.ilike(like),
                )
            )
        if filters.get("domain_id"):
            query = query.filter(Document.domains.any(Domain.id == filters["domain_id"]))
        if filters.get("tag_id"):
            query = query.filter(Document.tags.any(Tag.id == filters["tag_id"]))
        if filters.get("read_status"):
            query = query.filter(Document.read_status == filters["read_status"])
        if filters.get("priority"):
            query = query.filter(Document.priority == filters["priority"])
        if filters.get("citation_status"):
            query = query.filter(Document.citation_status == filters["citation_status"])
    else:
        raise ValueError(f"Unsupported Concordance scope: {scope_type}")
    return query.order_by(Document.created_at.desc()).all()


def create_concordance_run(
    db: Session,
    *,
    scope_type: str = "library",
    scope_data: dict[str, Any] | None = None,
    capability_keys: list[str] | None = None,
    force: bool = False,
    label: str | None = None,
) -> ConcordanceRun:
    scope_data = scope_data or {}
    plan = plan_concordance_run(
        db,
        scope_type=scope_type,
        scope_data=scope_data,
        capability_keys=capability_keys,
        force=force,
    )
    run = ConcordanceRun(
        label=label,
        scope_type=scope_type,
        scope_data={**scope_data, "_force": True} if force else scope_data,
        capability_keys=plan["capability_keys"],
        status="queued",
    )
    db.add(run)
    db.flush()

    queued_count = 0
    for item in plan["items"]:
        if item["status"] != "planned":
            continue
        document = item.get("document")
        if not isinstance(document, Document):
            continue
        db.add(
            ConcordanceJob(
                run_id=run.id,
                document_id=document.id,
                capability_key=item["capability_key"],
                target_version=int(item["target_version"]),
                status="queued",
            )
        )
        queued_count += 1
    run.total_jobs = queued_count
    refresh_concordance_run_progress(db, run)
    return run


def mark_document_capability(
    db: Session,
    document: Document,
    capability_key: str,
    target_version: int,
    evidence: dict[str, Any],
) -> None:
    state = (
        db.query(DocumentCapability)
        .filter(
            DocumentCapability.document_id == document.id,
            DocumentCapability.capability_key == capability_key,
        )
        .one_or_none()
    )
    if not state:
        state = DocumentCapability(document_id=document.id, capability_key=capability_key, version=target_version)
        db.add(state)
    state.version = target_version
    state.status = "complete"
    state.evidence = evidence
    state.completed_at = utc_now()


class ConcordanceProcessor:
    def process_job(self, db: Session, job: ConcordanceJob) -> None:
        document = job.document
        if not document or document.deleted_at:
            job.status = "failed"
            job.last_error = "Document record is missing."
            return

        try:
            job.status = "running"
            job.attempts += 1
            job.locked_at = utc_now()
            log_event(
                db,
                job=None,
                document=document,
                event_type="concordance_started",
                message=f"Concordance started for {job.capability_key}.",
                payload={"run_id": job.run_id, "capability_key": job.capability_key, "target_version": job.target_version},
            )
            db.commit()

            stage_started_at, stage_started_perf = stage_timer()
            run_force = bool(job.run and (job.run.scope_data or {}).get("_force"))
            model_noop, noop_requirements = (False, []) if run_force else _same_model_noop(db, document, job.capability_key)
            if model_noop:
                evidence = {
                    "status": "model_no_op",
                    "skipped": True,
                    "reason": "The relevant field already has successful output from the currently selected model.",
                    "model_requirements": [_requirement_payload(requirement) for requirement in noop_requirements],
                }
            elif job.capability_key == "page_text_normalization":
                evidence = self._normalize_page_text(db, document, job)
            elif job.capability_key == "document_structure_cleanup":
                evidence = self._clean_document_structure(db, document, job)
            elif job.capability_key == "structured_tables":
                evidence = self._refresh_structured_tables(db, document)
            elif job.capability_key == "ocr_fallback":
                evidence = self._audit_ocr_fallback(document)
            elif job.capability_key == "search_index":
                evidence = self._rebuild_search_index(document)
            elif job.capability_key == "citation_refresh":
                evidence = self._refresh_citation(db, document, job)
            elif job.capability_key == "summary_refresh":
                evidence = self._refresh_summary(db, document, job)
            elif job.capability_key == "tag_refresh":
                evidence = self._refresh_tags(db, document, job)
            elif job.capability_key == "summary_topics":
                evidence = self._refresh_summary_topics(db, document, job)
            elif job.capability_key == "bibliography_extraction":
                evidence = self._extract_bibliography(db, document, job)
            elif job.capability_key == "figure_assets":
                evidence = self._extract_figures(db, document)
            elif job.capability_key == "visual_asset_extraction":
                evidence = self._extract_figures(db, document)
            elif job.capability_key == "visual_asset_context":
                evidence = self._refresh_visual_context(document)
            elif job.capability_key == "recommendations":
                evidence = self._refresh_recommendations(db, document)
            else:
                raise RuntimeError(f"Unsupported Concordance capability: {job.capability_key}")

            capability = CAPABILITY_BY_KEY.get(job.capability_key)
            record_concordance_stage(
                db,
                document=document,
                concordance_job=job,
                stage_key=job.capability_key,
                label=capability.label if capability else job.capability_key.replace("_", " ").title(),
                method=job.capability_key,
                model=concordance_stage_model(db, job.capability_key),
                status=concordance_stage_status(evidence),
                started_at=stage_started_at,
                duration_ms=elapsed_ms(stage_started_perf),
                metadata=evidence,
            )
            sync_import_usage_composition(db, document=document, job=None)
            mark_document_capability(db, document, job.capability_key, job.target_version, evidence)
            job.status = "complete"
            job.locked_at = None
            job.completed_at = utc_now()
            run = db.get(ConcordanceRun, job.run_id)
            if run:
                refresh_concordance_run_progress(db, run)
            log_event(
                db,
                job=None,
                document=document,
                event_type="concordance_complete",
                message=f"Concordance complete for {job.capability_key}.",
                payload={"run_id": job.run_id, "capability_key": job.capability_key, **evidence},
            )
            db.commit()
        except Exception as exc:
            if document:
                record_concordance_stage(
                    db,
                    document=document,
                    concordance_job=job,
                    stage_key=job.capability_key,
                    label=CAPABILITY_BY_KEY.get(job.capability_key, CapabilityDefinition(job.capability_key, job.capability_key, 0, "")).label,
                    method=job.capability_key,
                    model=concordance_stage_model(db, job.capability_key),
                    status="failed",
                    message=str(exc),
                    metadata={"error": str(exc)},
                )
                sync_import_usage_composition(db, document=document, job=None)
                record_import_erratum(
                    db,
                    document=document,
                    job=None,
                    stage_key=job.capability_key,
                    message=str(exc),
                    metadata={"source": "concordance", "concordance_run_id": job.run_id, "concordance_job_id": job.id},
                )
            job.status = "failed"
            job.locked_at = None
            job.last_error = str(exc)
            run = db.get(ConcordanceRun, job.run_id)
            if run:
                refresh_concordance_run_progress(db, run)
            log_event(
                db,
                job=None,
                document=document,
                event_type="concordance_failed",
                message=str(exc),
                level="error",
                payload={"run_id": job.run_id, "capability_key": job.capability_key},
            )
            db.commit()

    def _rebuild_search_index(self, document: Document) -> dict[str, Any]:
        document.search_text = rebuild_document_search_text(document)
        return {"indexed_characters": len(document.search_text or ""), "pages": len(document.pages)}

    def _usage_context(self, document: Document, job: ConcordanceJob, capability_key: str | None = None) -> OpenAIUsageContext:
        return OpenAIUsageContext(
            document_id=document.id,
            concordance_run_id=job.run_id,
            concordance_job_id=job.id,
            source="concordance",
            capability_key=capability_key or job.capability_key,
        )

    def _normalize_page_text(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        pdf_bytes = self._document_pdf_bytes(db, document)
        before = document_correction_snapshot(document)
        page_before = {page.id: document_page_snapshot(page) for page in document.pages}
        summary = normalize_document_pages(
            document,
            db=db,
            model=get_analysis_model(db, MODEL_PAGE_TEXT_NORMALIZATION),
            pdf_bytes=pdf_bytes,
            usage_context=self._usage_context(document, job, "page_text_normalization"),
            protect_manual=True,
        )
        reading_text = rebuild_document_text_chunks(db, document)
        evidence = dict(document.metadata_evidence or {})
        evidence["page_text_normalization"] = summary
        document.metadata_evidence = evidence
        search_evidence = self._rebuild_search_index(document)
        changed_pages = [
            {
                "before": page_before[page.id],
                "after": document_page_snapshot(page),
            }
            for page in document.pages
            if page.id in page_before and page_before[page.id] != document_page_snapshot(page)
        ]
        if changed_pages:
            record_document_version(
                db,
                document=document,
                change_note="Concordance page text normalization",
                changed_fields={"pages", "search_text"},
                before=before,
                after=document_correction_snapshot(document),
                extra={"pages": changed_pages},
            )
        return {
            **summary,
            "readable_characters": len(reading_text),
            "search_indexed_characters": search_evidence["indexed_characters"],
        }

    def _clean_document_structure(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        before = document_correction_snapshot(document)
        page_before = {page.id: document_page_snapshot(page) for page in document.pages}
        preset = import_processing_snapshot(db)
        cleanup_result = clean_document_structure(document, preset)
        cleanup_text_by_page_id = cleanup_result.pop("cleaned_text_by_page_id", {})
        cleanup_config = preset.get("cleanup") if isinstance(preset.get("cleanup"), dict) else {}
        summary = normalize_document_pages(
            document,
            db=db,
            model=str(cleanup_config.get("model") or get_analysis_model(db, MODEL_PAGE_TEXT_NORMALIZATION)),
            usage_context=self._usage_context(document, job, "document_structure_cleanup"),
            normalization_text_by_page_id=cleanup_text_by_page_id if isinstance(cleanup_text_by_page_id, dict) else None,
            cloud_enabled=bool(cleanup_config.get("cloud_escalation", True)),
            auto_max_pages_override=import_processing_cloud_page_cap(preset, len(document.pages)),
            protect_manual=True,
        )
        reading_text = rebuild_document_text_chunks(db, document)
        evidence = dict(document.metadata_evidence or {})
        evidence["import_processing_preset"] = preset
        evidence["document_structure_cleanup"] = cleanup_result
        evidence["structured_tables"] = cleanup_result.get("structured_tables", {})
        evidence["page_text_normalization"] = summary
        document.metadata_evidence = evidence
        search_evidence = self._rebuild_search_index(document)
        changed_pages = [
            {
                "before": page_before[page.id],
                "after": document_page_snapshot(page),
            }
            for page in document.pages
            if page.id in page_before and page_before[page.id] != document_page_snapshot(page)
        ]
        if changed_pages:
            record_document_version(
                db,
                document=document,
                change_note="Concordance document structure cleanup",
                changed_fields={"pages", "search_text"},
                before=before,
                after=document_correction_snapshot(document),
                extra={"pages": changed_pages, "manual_pages_protected": summary.get("sources", {}).get("manual_protected", 0)},
            )
        return {
            **cleanup_result,
            "page_text_normalization": summary,
            "readable_characters": len(reading_text),
            "search_indexed_characters": search_evidence["indexed_characters"],
        }

    def _refresh_structured_tables(self, db: Session, document: Document) -> dict[str, Any]:
        preset = import_processing_snapshot(db)
        cleanup_result = clean_document_structure(document, preset)
        cleanup_result.pop("cleaned_text_by_page_id", None)
        evidence = dict(document.metadata_evidence or {})
        evidence["structured_tables"] = cleanup_result.get("structured_tables", {})
        document.metadata_evidence = evidence
        return evidence["structured_tables"]

    def _audit_ocr_fallback(self, document: Document) -> dict[str, Any]:
        low_text_pages = [page.page_number for page in document.pages if page.low_text]
        evidence = dict(document.metadata_evidence or {})
        ocr_evidence = {
            "low_text_pages": low_text_pages,
            "eligible_pages": low_text_pages,
            "status": "pending_provider_integration" if low_text_pages else "not_needed",
        }
        evidence["ocr_fallback"] = ocr_evidence
        document.metadata_evidence = evidence
        return ocr_evidence

    def _extract_bibliography(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        run_force = bool(job.run and (job.run.scope_data or {}).get("_force"))
        if document.bibliography and not run_force:
            return {"status": "skipped_existing_bibliography", "characters": len(document.bibliography)}
        preset = import_processing_snapshot(db)
        bibliography_config = preset.get("bibliography") if isinstance(preset.get("bibliography"), dict) else {}
        if not bool(bibliography_config.get("enabled", True)):
            return {"status": "disabled_by_preset"}
        pdf_bytes = self._document_pdf_bytes(db, document)
        result: dict[str, Any]
        if pdf_bytes and bool(bibliography_config.get("preserve_italics", True)):
            with NamedTemporaryFile(suffix=".pdf") as handle:
                handle.write(pdf_bytes)
                handle.flush()
                result = extract_document_bibliography(document, Path(handle.name))
        else:
            result = extract_document_bibliography(document)
        bibliography = result.get("bibliography")
        evidence = result.get("evidence") or {}
        if bibliography and run_force:
            cleanup_model = get_analysis_model(db, MODEL_BIBLIOGRAPHY_CLEANUP)
            try:
                cleanup = get_ai_service().normalize_bibliography(
                    document.original_filename or document.title or "document.pdf",
                    bibliography,
                    model=cleanup_model,
                    usage_context=self._usage_context(document, job, "bibliography_extraction"),
                    prompt_cache_key=f"medusa-bibliography:{document.id}",
                )
                bibliography = cleanup.get("bibliography") or bibliography
                evidence["model_cleanup"] = {
                    "status": "formatted" if (cleanup.get("_openai") or {}).get("configured") else "local_fallback",
                    "model": (cleanup.get("_openai") or {}).get("model") or cleanup_model,
                    "confidence": cleanup.get("confidence"),
                    "notes": cleanup.get("notes") or [],
                    "formatting": "apa_markdown_one_source_per_line",
                }
                if (cleanup.get("_openai") or {}).get("configured"):
                    evidence["formatting"] = "apa_markdown_model_cleanup"
            except Exception as exc:
                evidence["model_cleanup"] = {
                    "status": "failed",
                    "model": cleanup_model,
                    "error": str(exc),
                    "formatting": "local_fallback",
                }
        if bibliography:
            before = document_correction_snapshot(document)
            document.bibliography = bibliography
            metadata_evidence = dict(document.metadata_evidence or {})
            metadata_evidence["bibliography_extraction"] = evidence
            document.metadata_evidence = metadata_evidence
            document.search_text = rebuild_document_search_text(document)
            record_document_version(
                db,
                document=document,
                change_note="Concordance bibliography extraction",
                changed_fields={"bibliography", "search_text"},
                before=before,
                after=document_correction_snapshot(document),
            )
            return {**evidence, "characters": len(bibliography)}
        metadata_evidence = dict(document.metadata_evidence or {})
        metadata_evidence["bibliography_extraction"] = evidence
        document.metadata_evidence = metadata_evidence
        return evidence

    def _extract_figures(self, db: Session, document: Document) -> dict[str, Any]:
        return process_document_figures_from_storage(db, document)

    def _refresh_visual_context(self, document: Document) -> dict[str, Any]:
        result = enrich_figure_context(document)
        evidence = dict(document.metadata_evidence or {})
        evidence["visual_asset_context"] = result
        document.metadata_evidence = evidence
        return result

    def _refresh_recommendations(self, db: Session, document: Document) -> dict[str, Any]:
        if not document.doi:
            return {"recommendation_count": 0, "skipped": "missing_doi"}
        recommendations = refresh_document_recommendations(db, document)
        return {
            "recommendation_count": len(recommendations),
            "existing_matches": sum(1 for item in recommendations if item.existing_document_id),
            "with_pdf": sum(1 for item in recommendations if item.pdf_url),
        }

    def _refresh_citation(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        before = document_correction_snapshot(document)
        evidence = dict(document.metadata_evidence or {})
        if not document.doi:
            document.doi = extract_doi_from_text(document.search_text)
        crossref = crossref_lookup(document.doi, document.title, document.authors, document.publication_year) or evidence.get("crossref")
        filled_fields: list[str] = []
        crossref_metadata: dict[str, Any] = {}
        if crossref:
            evidence["crossref"] = crossref
            crossref_metadata = crossref_to_citation_metadata(crossref)
            filled_fields = fill_missing_document_metadata(document, crossref_metadata)
            if filled_fields:
                evidence["crossref_filled_fields"] = sorted(set([*evidence.get("crossref_filled_fields", []), *filled_fields]))
        document.metadata_evidence = evidence
        metadata = merge_citation_metadata(crossref_metadata, document_metadata(document))
        model_preferences = get_analysis_models(db)
        citation_model = model_preferences[MODEL_APA_CITATION]
        if crossref:
            apply_document_citations(document, metadata, model=citation_model, source="crossref")
        else:
            ai = get_ai_service()
            apa_candidate = ai.generate_apa_citation_candidate(
                document.original_filename,
                document.search_text or "",
                metadata,
                model=citation_model,
                usage_context=self._usage_context(document, job, "citation_refresh"),
                prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:apa",
            )
            evidence["ai_apa"] = {
                "confidence": apa_candidate.get("confidence"),
                "citation_warnings": apa_candidate.get("citation_warnings") or [],
                "needs_review_reasons": apa_candidate.get("needs_review_reasons") or [],
                **(apa_candidate.get("_openai") or {}),
            }
            document.metadata_evidence = evidence
            apply_document_citations(
                document,
                metadata,
                reference_list=apa_candidate.get("apa_citation"),
                in_text=apa_candidate.get("apa_in_text_citation"),
                model=(apa_candidate.get("_openai") or {}).get("model") or citation_model,
                source="model",
            )
        verified = enough_metadata_for_verified_citation(metadata) and bool(document.doi or crossref)
        document.citation_status = "verified" if verified else "needs_review"
        if verified:
            (
                db.query(CitationCandidate)
                .filter(CitationCandidate.document_id == document.id, CitationCandidate.status == "needs_review")
                .update({"status": "superseded"}, synchronize_session=False)
            )
        else:
            existing = (
                db.query(CitationCandidate)
                .filter(
                    CitationCandidate.document_id == document.id,
                    CitationCandidate.source == "concordance-citation",
                    CitationCandidate.status == "needs_review",
                )
                .first()
            )
            if not existing:
                db.add(
                    CitationCandidate(
                        document_id=document.id,
                        source="concordance-citation",
                        citation_text=document.apa_citation,
                        source_metadata=metadata,
                        confidence=document.metadata_confidence,
                        status="needs_review",
                    )
                )
        after = document_correction_snapshot(document)
        changed_fields = changed_snapshot_fields(before, after)
        if changed_fields:
            record_document_version(
                db,
                document=document,
                change_note="Concordance citation refresh",
                changed_fields=changed_fields,
                before=before,
                after=after,
                extra={"run_id": job.run_id, "concordance_job_id": job.id},
            )
        return {
            "verified": verified,
            "crossref_evidence": bool(crossref),
            "filled_fields": filled_fields,
            "citation_model": document.apa_citation_model,
            "citation_source": document.apa_citation_source,
        }

    def _refresh_summary(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        before = document_correction_snapshot(document)
        ai = get_ai_service()
        summary_model = get_analysis_model(db, MODEL_SUMMARY)
        summary = ai.generate_document_summary(
            document.original_filename,
            document.search_text or "",
            model=summary_model,
            usage_context=self._usage_context(document, job, "summary_refresh"),
            prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:summary",
        )
        metadata_evidence = dict(document.metadata_evidence or {})
        metadata_evidence["summary_refresh"] = {
            "confidence": summary.get("confidence"),
            "needs_review_reasons": summary.get("needs_review_reasons") or [],
            **(summary.get("_openai") or {}),
        }
        document.metadata_evidence = metadata_evidence
        if summary.get("rich_summary"):
            document.rich_summary = summary["rich_summary"]
        after = document_correction_snapshot(document)
        changed_fields = changed_snapshot_fields(before, after)
        if changed_fields:
            document.search_text = rebuild_document_search_text(document)
            record_document_version(
                db,
                document=document,
                change_note="Concordance summary refresh",
                changed_fields=changed_fields,
                before=before,
                after=after,
                extra={"run_id": job.run_id, "concordance_job_id": job.id},
            )
        return {
            "confidence": summary.get("confidence"),
            "summary_model": (summary.get("_openai") or {}).get("model") or summary_model,
            "configured": (summary.get("_openai") or {}).get("configured", True),
        }

    def _refresh_tags(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        before = document_correction_snapshot(document)
        ai = get_ai_service()
        tag_model = get_analysis_model(db, MODEL_KEYWORDS_TOPICS)
        keywords = ai.extract_keywords_topics(
            document.original_filename,
            document.search_text or "",
            model=tag_model,
            existing_tags=existing_tag_manifest(db),
            usage_context=self._usage_context(document, job, "tag_refresh"),
            prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:tag-refresh",
        )
        if (keywords.get("_openai") or {}).get("configured") is False:
            raise RuntimeError("Tag Suggestions model is not configured; existing tags were left unchanged.")

        before_tag_count = len(document.tags)
        before_tag_names = sorted(tag.name for tag in document.tags)
        tag_governance = apply_import_tag_governance(
            db,
            document=document,
            topics=keywords.get("topics") or [],
            keywords=keywords.get("keywords") or [],
            source="tag_refresh",
            concordance_job_id=job.id,
            ai=ai,
            usage_context=self._usage_context(document, job, "tag_governance"),
            replace_existing=True,
        )
        document.search_text = rebuild_document_search_text(document)
        after = document_correction_snapshot(document)
        after_tag_names = sorted(tag.name for tag in document.tags)
        removed_tag_names = sorted(set(before_tag_names) - set(after_tag_names))
        changed_fields = changed_snapshot_fields(before, after)
        if changed_fields:
            record_document_version(
                db,
                document=document,
                change_note="Concordance tag refresh",
                changed_fields=changed_fields,
                before=before,
                after=after,
                extra={"run_id": job.run_id, "concordance_job_id": job.id},
            )
        return {
            "confidence": keywords.get("confidence"),
            "tag_model": (keywords.get("_openai") or {}).get("model") or tag_model,
            "configured": (keywords.get("_openai") or {}).get("configured", True),
            "tags_before": before_tag_count,
            "tags_after": len(document.tags),
            "tags_removed": len(removed_tag_names),
            "removed_tags": removed_tag_names,
            "tag_governance": tag_governance,
        }

    def _refresh_summary_topics(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        before = document_correction_snapshot(document)
        ai = get_ai_service()
        pdf_bytes = self._document_pdf_bytes(db, document)
        model_preferences = get_analysis_models(db)
        metadata_requirement = ConcordanceModelRequirement(
            task_key=MODEL_METADATA,
            field_key="metadata",
            label="Metadata",
            model=model_preferences[MODEL_METADATA],
        )
        summary_requirement = ConcordanceModelRequirement(
            task_key=MODEL_SUMMARY,
            field_key="rich_summary",
            label="Summary",
            model=model_preferences[MODEL_SUMMARY],
        )
        tags_requirement = ConcordanceModelRequirement(
            task_key=MODEL_KEYWORDS_TOPICS,
            field_key="tags",
            label="Tag suggestions",
            model=model_preferences[MODEL_KEYWORDS_TOPICS],
        )
        metadata_current = _model_requirement_current(db, document, metadata_requirement)
        summary_current = _model_requirement_current(db, document, summary_requirement)
        tags_current = _model_requirement_current(db, document, tags_requirement)

        metadata: dict[str, Any] = {}
        summary: dict[str, Any] = {}
        keywords: dict[str, Any] = {}
        called_models: dict[str, str] = {}
        skipped_fields: list[str] = []
        if metadata_current:
            skipped_fields.append("metadata")
        else:
            metadata = ai.extract_document_identity(
                document.original_filename,
                document.search_text or "",
                pdf_bytes=pdf_bytes,
                model=model_preferences[MODEL_METADATA],
                usage_context=self._usage_context(document, job, "summary_topics"),
                prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:metadata",
            )
            called_models[MODEL_METADATA] = (metadata.get("_openai") or {}).get("model") or model_preferences[MODEL_METADATA]
        if summary_current:
            skipped_fields.append("rich_summary")
        else:
            summary = ai.generate_document_summary(
                document.original_filename,
                document.search_text or "",
                model=model_preferences[MODEL_SUMMARY],
                usage_context=self._usage_context(document, job, "summary_topics"),
                prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:summary",
            )
            called_models[MODEL_SUMMARY] = (summary.get("_openai") or {}).get("model") or model_preferences[MODEL_SUMMARY]
        if tags_current:
            skipped_fields.append("tags")
        else:
            keywords = ai.extract_keywords_topics(
                document.original_filename,
                document.search_text or "",
                model=model_preferences[MODEL_KEYWORDS_TOPICS],
                existing_tags=existing_tag_manifest(db),
                usage_context=self._usage_context(document, job, "summary_topics"),
                prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:tags",
            )
            called_models[MODEL_KEYWORDS_TOPICS] = (keywords.get("_openai") or {}).get("model") or model_preferences[MODEL_KEYWORDS_TOPICS]

        confidence_values = [
            value
            for value in [metadata.get("confidence"), summary.get("confidence"), keywords.get("confidence")]
            if isinstance(value, (int, float))
        ]
        needs_review_reasons = [
            *(metadata.get("needs_review_reasons") or []),
            *(summary.get("needs_review_reasons") or []),
            *(keywords.get("needs_review_reasons") or []),
        ]
        evidence = dict(document.metadata_evidence or {})
        evidence["concordance_ai"] = {
            "confidence": min(confidence_values) if confidence_values else None,
            "needs_review_reasons": needs_review_reasons,
            "models": called_models,
            "skipped_fields": skipped_fields,
            "used_pdf_file": bool((metadata.get("_openai") or {}).get("used_pdf_file")),
            "pdf_file_bytes": (metadata.get("_openai") or {}).get("pdf_file_bytes", 0),
        }
        document.metadata_evidence = evidence

        if summary.get("rich_summary"):
            document.rich_summary = summary["rich_summary"]
        for key in ["subtitle", "publication_year", "journal", "publisher", "doi", "abstract"]:
            if getattr(document, key) in (None, "", []):
                setattr(document, key, metadata.get(key))
        if not document.authors and metadata.get("authors"):
            document.authors = metadata["authors"]
        if not document.universities and metadata.get("universities"):
            document.universities = metadata["universities"]

        before_tag_count = len(document.tags)
        tag_governance: dict[str, Any] = {"skipped": "same_model_no_op"} if tags_current else {}
        if not tags_current:
            tag_governance = apply_import_tag_governance(
                db,
                document=document,
                topics=keywords.get("topics") or [],
                keywords=keywords.get("keywords") or [],
                source="concordance",
                concordance_job_id=job.id,
                ai=ai,
                usage_context=self._usage_context(document, job, "tag_governance"),
            )
        added_tags = max(0, len(document.tags) - before_tag_count)
        after = document_correction_snapshot(document)
        changed_fields = changed_snapshot_fields(before, after)
        if changed_fields:
            record_document_version(
                db,
                document=document,
                change_note="Concordance summary and topics refresh",
                changed_fields=changed_fields,
                before=before,
                after=after,
                extra={"run_id": job.run_id, "concordance_job_id": job.id},
            )
        return {
            "confidence": min(confidence_values) if confidence_values else None,
            "tags_added": added_tags,
            "tag_governance": tag_governance,
            "called_models": called_models,
            "skipped_fields": skipped_fields,
            "used_pdf_file": bool((metadata.get("_openai") or {}).get("used_pdf_file")),
            "ai_apa_candidate": False,
        }

    def _document_pdf_bytes(self, db: Session, document: Document) -> bytes | None:
        try:
            return ensure_document_pdf_bytes(db, document, source="concordance")
        except Exception:
            return None
