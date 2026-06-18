from __future__ import annotations

import json
from dataclasses import dataclass
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
    ProjectItem,
    SavedSearch,
    Tag,
    utc_now,
)
from app.services.ai import get_ai_service
from app.services.citations import format_apa_citation, merge_citation_metadata
from app.services.figures import process_document_figures_from_storage
from app.services.processing import (
    document_metadata,
    document_reading_text,
    fill_missing_document_metadata,
    get_or_create_tag,
    log_event,
    normalize_document_pages,
    rebuild_document_text_chunks,
)
from app.services.storage import get_storage_service
from app.services.verifier import crossref_lookup, crossref_to_citation_metadata, enough_metadata_for_verified_citation


@dataclass(frozen=True)
class CapabilityDefinition:
    key: str
    label: str
    version: int
    description: str


CURRENT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        key="page_text_normalization",
        label="Page text normalization",
        version=1,
        description="Conform extracted page text into readable paragraph flow while preserving the original document order.",
    ),
    CapabilityDefinition(
        key="search_index",
        label="Search index",
        version=2,
        description="Rebuild full-text search from metadata, normalized page text, summaries, notes, attributes, tags, and domains.",
    ),
    CapabilityDefinition(
        key="citation_refresh",
        label="Citation refresh",
        version=2,
        description="Regenerate APA citation text and refresh verification evidence without hiding uncertain cases.",
    ),
    CapabilityDefinition(
        key="summary_topics",
        label="AI metadata and summary",
        version=3,
        description="Use the configured AI adapter with PDF context to fill missing metadata, concise markdown summaries, APA candidates, and topic tags.",
    ),
    CapabilityDefinition(
        key="figure_assets",
        label="Figure assets",
        version=1,
        description="Extract embedded PDF figures/images into durable storage and attach them to document records.",
    ),
)

CAPABILITY_BY_KEY = {capability.key: capability for capability in CURRENT_CAPABILITIES}


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
    query = db.query(Document).filter(Document.deleted_at.is_(None))
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
        query = query.filter(or_(Document.title.ilike(like), Document.search_text.ilike(like), Document.apa_citation.ilike(like)))
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
            query = query.filter(or_(Document.title.ilike(like), Document.search_text.ilike(like), Document.apa_citation.ilike(like)))
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
    selected_keys = capability_keys or [capability.key for capability in CURRENT_CAPABILITIES]
    unknown_keys = sorted(set(selected_keys) - set(CAPABILITY_BY_KEY))
    if unknown_keys:
        raise ValueError(f"Unknown Concordance capability: {', '.join(unknown_keys)}")

    documents = documents_for_scope(db, scope_type, scope_data)
    run = ConcordanceRun(
        label=label,
        scope_type=scope_type,
        scope_data=scope_data,
        capability_keys=selected_keys,
        status="queued",
    )
    db.add(run)
    db.flush()

    queued_count = 0
    for document in documents:
        for key in selected_keys:
            capability = CAPABILITY_BY_KEY[key]
            if not force and _document_has_current_capability(db, document.id, capability):
                continue
            if _already_queued_or_running(db, document.id, key):
                continue
            db.add(
                ConcordanceJob(
                    run_id=run.id,
                    document_id=document.id,
                    capability_key=key,
                    target_version=capability.version,
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


def _stringify_attribute_value(value: dict[str, Any]) -> str:
    if "value" in value:
        return str(value["value"])
    return json.dumps(value, sort_keys=True)


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

            if job.capability_key == "page_text_normalization":
                evidence = self._normalize_page_text(db, document)
            elif job.capability_key == "search_index":
                evidence = self._rebuild_search_index(document)
            elif job.capability_key == "citation_refresh":
                evidence = self._refresh_citation(db, document)
            elif job.capability_key == "summary_topics":
                evidence = self._refresh_summary_topics(db, document)
            elif job.capability_key == "figure_assets":
                evidence = self._extract_figures(db, document)
            else:
                raise RuntimeError(f"Unsupported Concordance capability: {job.capability_key}")

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
        page_text = document_reading_text(document)
        notes = "\n\n".join(note.body for note in document.notes if not note.deleted_at)
        attributes = "\n\n".join(
            f"{value.definition.name}: {_stringify_attribute_value(value.value)}" for value in document.attributes if value.definition
        )
        document.search_text = "\n\n".join(
            part
            for part in [
                document.title,
                " ".join(" ".join(filter(None, [author.get("given"), author.get("family")])) for author in document.authors or []),
                document.abstract,
                document.rich_summary,
                document.apa_citation,
                page_text,
                " ".join(figure.gist or "" for figure in document.figures),
                notes,
                attributes,
                " ".join(tag.name for tag in document.tags),
                " ".join(domain.name for domain in document.domains),
            ]
            if part
        )
        return {"indexed_characters": len(document.search_text or ""), "pages": len(document.pages)}

    def _normalize_page_text(self, db: Session, document: Document) -> dict[str, Any]:
        summary = normalize_document_pages(document)
        reading_text = rebuild_document_text_chunks(db, document)
        evidence = dict(document.metadata_evidence or {})
        evidence["page_text_normalization"] = summary
        document.metadata_evidence = evidence
        search_evidence = self._rebuild_search_index(document)
        return {
            **summary,
            "readable_characters": len(reading_text),
            "search_indexed_characters": search_evidence["indexed_characters"],
        }

    def _extract_figures(self, db: Session, document: Document) -> dict[str, Any]:
        return process_document_figures_from_storage(db, document)

    def _refresh_citation(self, db: Session, document: Document) -> dict[str, Any]:
        evidence = dict(document.metadata_evidence or {})
        crossref = crossref_lookup(document.doi, document.title) or evidence.get("crossref")
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
        document.apa_citation = format_apa_citation(metadata)
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
        return {"verified": verified, "crossref_evidence": bool(crossref), "filled_fields": filled_fields}

    def _refresh_summary_topics(self, db: Session, document: Document) -> dict[str, Any]:
        ai = get_ai_service()
        pdf_bytes = self._document_pdf_bytes(document)
        metadata = ai.extract_metadata(document.original_filename, document.search_text or "", pdf_bytes=pdf_bytes)
        evidence = dict(document.metadata_evidence or {})
        evidence["concordance_ai"] = {
            "confidence": metadata.get("confidence"),
            "needs_review_reasons": metadata.get("needs_review_reasons") or [],
            "citation_warnings": metadata.get("citation_warnings") or [],
            **(metadata.get("_openai") or {}),
        }
        document.metadata_evidence = evidence

        if _summary_needs_markdown_refresh(document.rich_summary):
            document.rich_summary = metadata.get("rich_summary") or document.rich_summary
        for key in ["subtitle", "publication_year", "journal", "publisher", "doi", "abstract"]:
            if getattr(document, key) in (None, "", []):
                setattr(document, key, metadata.get(key))
        if not document.authors and metadata.get("authors"):
            document.authors = metadata["authors"]
        if not document.universities and metadata.get("universities"):
            document.universities = metadata["universities"]
        if metadata.get("apa_citation") and document.citation_status != "verified":
            existing = (
                db.query(CitationCandidate)
                .filter(
                    CitationCandidate.document_id == document.id,
                    CitationCandidate.source == "openai-apa",
                    CitationCandidate.status == "needs_review",
                )
                .first()
            )
            if not existing:
                db.add(
                    CitationCandidate(
                        document_id=document.id,
                        source="openai-apa",
                        citation_text=metadata.get("apa_citation"),
                        source_metadata=document_metadata(document),
                        confidence=metadata.get("confidence"),
                        status="needs_review",
                    )
                )

        added_tags = 0
        for topic in metadata.get("topics") or []:
            tag = get_or_create_tag(db, topic, "topic")
            if tag not in document.tags:
                document.tags.append(tag)
                added_tags += 1
        for keyword in metadata.get("keywords") or []:
            tag = get_or_create_tag(db, keyword, "keyword")
            if tag not in document.tags:
                document.tags.append(tag)
                added_tags += 1
        return {
            "confidence": metadata.get("confidence"),
            "tags_added": added_tags,
            "used_pdf_file": bool((metadata.get("_openai") or {}).get("used_pdf_file")),
            "ai_apa_candidate": bool(metadata.get("apa_citation")),
        }

    def _document_pdf_bytes(self, document: Document) -> bytes | None:
        if not document.gcs_uri:
            return None
        try:
            return get_storage_service().get_bytes(document.gcs_uri)
        except Exception:
            return None
