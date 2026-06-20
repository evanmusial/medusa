from __future__ import annotations

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
from app.services.analysis_models import (
    MODEL_APA_CITATION,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_SUMMARY,
)
from app.services.citations import decode_html_entities, merge_citation_metadata
from app.services.document_cache import ensure_document_pdf_bytes
from app.services.figures import process_document_figures_from_storage
from app.services.history import (
    changed_snapshot_fields,
    document_correction_snapshot,
    document_page_snapshot,
    record_document_version,
)
from app.services.openai_usage import OpenAIUsageContext
from app.services.preferences import get_analysis_model, get_analysis_models
from app.services.processing import (
    apply_document_citations,
    document_metadata,
    fill_missing_document_metadata,
    get_or_create_tag,
    log_event,
    normalize_document_pages,
    rebuild_document_text_chunks,
)
from app.services.recommendations import refresh_document_recommendations
from app.services.search import rebuild_document_search_text
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


CURRENT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
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
        version=7,
        description="Use routed document intelligence: high-quality metadata, GPT-5.4 summaries from text, and GPT-5.4-mini topic tags without generating APA unless citation refresh needs it.",
    ),
    CapabilityDefinition(
        key="figure_assets",
        label="Figure assets",
        version=3,
        description="Extract rendered image and vector figure/chart/photo crops into durable storage with page geometry, labels, and captions.",
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

CAPABILITY_BY_KEY = {capability.key: capability for capability in (*CURRENT_CAPABILITIES, SUMMARY_REFRESH_CAPABILITY)}


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
                evidence = self._normalize_page_text(db, document, job)
            elif job.capability_key == "search_index":
                evidence = self._rebuild_search_index(document)
            elif job.capability_key == "citation_refresh":
                evidence = self._refresh_citation(db, document, job)
            elif job.capability_key == "summary_refresh":
                evidence = self._refresh_summary(db, document, job)
            elif job.capability_key == "summary_topics":
                evidence = self._refresh_summary_topics(db, document, job)
            elif job.capability_key == "figure_assets":
                evidence = self._extract_figures(db, document)
            elif job.capability_key == "recommendations":
                evidence = self._refresh_recommendations(db, document)
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

    def _extract_figures(self, db: Session, document: Document) -> dict[str, Any]:
        return process_document_figures_from_storage(db, document)

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

    def _refresh_summary_topics(self, db: Session, document: Document, job: ConcordanceJob) -> dict[str, Any]:
        before = document_correction_snapshot(document)
        ai = get_ai_service()
        pdf_bytes = self._document_pdf_bytes(db, document)
        model_preferences = get_analysis_models(db)
        metadata = ai.extract_metadata(
            document.original_filename,
            document.search_text or "",
            pdf_bytes=pdf_bytes,
            models={
                MODEL_METADATA: model_preferences[MODEL_METADATA],
                MODEL_SUMMARY: model_preferences[MODEL_SUMMARY],
                MODEL_APA_CITATION: model_preferences[MODEL_APA_CITATION],
                MODEL_KEYWORDS_TOPICS: model_preferences[MODEL_KEYWORDS_TOPICS],
            },
            existing_tags=existing_tag_manifest(db),
            usage_context=self._usage_context(document, job, "summary_topics"),
            prompt_cache_key=f"medusa-doc:{document.checksum_sha256}",
        )
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
                        citation_text=decode_html_entities(metadata.get("apa_citation")),
                        source_metadata=document_metadata(document),
                        confidence=metadata.get("confidence"),
                        status="needs_review",
                    )
                )

        added_tags = 0
        for topic in metadata.get("topics") or []:
            tag = get_or_create_tag(db, topic)
            if tag and tag not in document.tags:
                document.tags.append(tag)
                added_tags += 1
        for keyword in metadata.get("keywords") or []:
            tag = get_or_create_tag(db, keyword)
            if tag and tag not in document.tags:
                document.tags.append(tag)
                added_tags += 1
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
            "confidence": metadata.get("confidence"),
            "tags_added": added_tags,
            "used_pdf_file": bool((metadata.get("_openai") or {}).get("used_pdf_file")),
            "ai_apa_candidate": bool(metadata.get("apa_citation")),
        }

    def _document_pdf_bytes(self, db: Session, document: Document) -> bytes | None:
        try:
            return ensure_document_pdf_bytes(db, document, source="concordance")
        except Exception:
            return None
