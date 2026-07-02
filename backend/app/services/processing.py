from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CitationCandidate,
    Document,
    DocumentPage,
    ImportBatch,
    ImportJob,
    ProcessingEvent,
    PortfolioVersion,
    TextChunk,
    utc_now,
)
from app.services.ai import get_ai_service
from app.services.analysis_models import (
    MODEL_APA_CITATION,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_RAW_TEXT_EXTRACTION,
    MODEL_SUMMARY,
    MODEL_TEXT_CHUNK_ENCODING,
)
from app.services.bibliography import bibliography_visual_ocr_enabled, extract_document_bibliography
from app.services.citations import merge_citation_metadata, validate_apa_citation_pair
from app.services.composition import (
    elapsed_ms,
    record_import_erratum,
    record_import_stage,
    stage_timer,
    sync_import_usage_composition,
)
from app.services.document_cache import (
    enforce_document_cache_budget,
    ensure_document_cache_file,
    mark_processing_cache_retained,
    metadata_cache_path,
)
from app.services.extraction import extract_pdf_text, normalize_extracted_text, sanitize_extracted_text, split_text_into_chunks
from app.services.figures import process_document_figures, strip_figure_markers_from_text
from app.services.history import document_correction_snapshot, record_document_version
from app.services.openai_usage import OpenAIUsageContext
from app.services.preferences import get_analysis_model, get_analysis_models
from app.services.preferences import import_processing_cloud_page_cap, import_processing_snapshot
from app.services.publications import document_publication_citation_metadata, refresh_document_publication_metadata
from app.services.second_pass import clean_document_structure
from app.services.tag_governance import apply_import_tag_governance
from app.services.tags import existing_tag_manifest
from app.services.verifier import (
    crossref_lookup,
    crossref_to_citation_metadata,
    discover_doi_from_title,
    enough_metadata_for_verified_citation,
    extract_doi_from_text,
    local_doi_resolution_evidence,
    stable_source_link_evidence,
)


IMPORT_STEP_ORDER = {
    "stored": 0,
    "extracting": 0,
    "cleaning_structure": 0,
    "normalizing_pages": 0,
    "extracting_bibliography": 0,
    "extracted": 1,
    "extracting_figures": 1,
    "figures": 2,
    "enriching": 2,
    "enriched": 3,
    "indexing": 3,
    "indexed": 4,
    "cleaning_cache": 4,
    "complete": 5,
}


def composition_stage_key_for_job_step(step: str | None) -> str:
    if not step:
        return "raw_text_extraction"
    if step == "cleaning_structure":
        return "document_structure_cleanup"
    if step == "extracting_bibliography":
        return "bibliography_extraction"
    if step.startswith("normalizing_page_") or step in {"stored", "extracting", "normalizing_pages", "extracted"}:
        return "raw_text_extraction"
    if step in {"extracting_figures", "figures"}:
        return "visual_asset_extraction"
    if step in {"enriching", "enriched"}:
        return "summary_topics"
    if step in {"indexing", "indexed"}:
        return "text_chunk_encoding"
    if step == "cleaning_cache":
        return "cache_cleanup"
    return step


def job_step_at_least(job: ImportJob, step: str) -> bool:
    return IMPORT_STEP_ORDER.get(job.current_step, 0) >= IMPORT_STEP_ORDER[step]


def is_page_normalization_step(step: str | None) -> bool:
    return bool(step and step.startswith("normalizing_page_"))


def log_event(
    db: Session,
    *,
    job: ImportJob | None,
    document: Document | None,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        ProcessingEvent(
            import_job_id=job.id if job else None,
            document_id=document.id if document else None,
            level=level,
            event_type=event_type,
            message=message,
            payload=payload or {},
        )
    )


def sync_portfolio_version_processing_status(db: Session, document: Document, status: str) -> None:
    if document.document_kind != "portfolio_version":
        return
    db.query(PortfolioVersion).filter(PortfolioVersion.document_id == document.id).update(
        {PortfolioVersion.processing_status: status},
        synchronize_session=False,
    )


def checkpoint_job_step(db: Session, job: ImportJob, document: Document, step: str, message: str) -> None:
    if job.current_step != step:
        job.current_step = step
        log_event(db, job=job, document=document, event_type=step, message=message)
    job.locked_at = utc_now()
    db.commit()


def document_metadata(document: Document) -> dict[str, Any]:
    metadata = {
        "title": document.title,
        "authors": document.authors,
        "publication_year": document.publication_year,
        "journal": document.journal,
        "publisher": document.publisher,
        "doi": document.doi,
        "source_url": document.source_url,
    }
    return merge_citation_metadata(document_publication_citation_metadata(document), metadata)


def apply_document_citations(
    document: Document,
    metadata: dict[str, Any],
    *,
    reference_list: str | None = None,
    in_text: str | None = None,
    model: str | None,
    source: str,
) -> list[str]:
    citation_pair = validate_apa_citation_pair(metadata, reference_list=reference_list, in_text=in_text)
    document.apa_citation = citation_pair.reference_list
    document.apa_in_text_citation = citation_pair.in_text
    document.apa_citation_model = model
    document.apa_in_text_citation_model = model
    document.apa_citation_source = source
    document.apa_in_text_citation_source = source
    return citation_pair.validation_warnings


def apa_candidate_has_citation(apa_candidate: dict[str, Any] | None) -> bool:
    return bool(str((apa_candidate or {}).get("apa_citation") or "").strip() or str((apa_candidate or {}).get("apa_in_text_citation") or "").strip())


def apa_candidate_needs_review(apa_candidate: dict[str, Any] | None) -> bool:
    if not apa_candidate_has_citation(apa_candidate):
        return False
    if (apa_candidate or {}).get("needs_review_reasons"):
        return True
    confidence = (apa_candidate or {}).get("confidence")
    try:
        return confidence is not None and float(confidence) < 0.55
    except (TypeError, ValueError):
        return False


def apa_candidate_evidence(apa_candidate: dict[str, Any] | None) -> dict[str, Any]:
    apa_candidate = apa_candidate or {}
    return {
        "confidence": apa_candidate.get("confidence"),
        "citation_warnings": apa_candidate.get("citation_warnings") or [],
        "needs_review_reasons": apa_candidate.get("needs_review_reasons") or [],
        "returned_citation": apa_candidate_has_citation(apa_candidate),
        **(apa_candidate.get("_openai") or {}),
    }


def apply_apa_candidate_or_metadata_citations(
    document: Document,
    metadata: dict[str, Any],
    apa_candidate: dict[str, Any] | None,
    *,
    model: str | None,
    fallback_source: str,
) -> list[str]:
    has_candidate = apa_candidate_has_citation(apa_candidate)
    openai_model = ((apa_candidate or {}).get("_openai") or {}).get("model")
    return apply_document_citations(
        document,
        metadata,
        reference_list=(apa_candidate or {}).get("apa_citation") if has_candidate else None,
        in_text=(apa_candidate or {}).get("apa_in_text_citation") if has_candidate else None,
        model=openai_model or model,
        source="model" if has_candidate else fallback_source,
    )


def author_search_text(authors: list[dict[str, Any]] | None) -> str:
    return " ".join(
        " ".join(str(author.get(key) or "") for key in ("given", "family", "affiliation", "email")).strip()
        for author in authors or []
        if isinstance(author, dict)
    )


def figure_search_text(figures: list[Any]) -> str:
    return " ".join(
        " ".join(filter(None, [figure.figure_label, figure.caption, figure.gist])).strip()
        for figure in figures
        if figure
    )


def fill_missing_document_metadata(document: Document, metadata: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for field in ("title", "authors", "publication_year", "journal", "publisher", "doi", "source_url"):
        value = metadata.get(field)
        current = getattr(document, field)
        if _has_metadata_value(current) or not _has_metadata_value(value):
            continue
        setattr(document, field, value)
        changed.append(field)
    return changed


def _has_metadata_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def preferred_page_text(page: DocumentPage) -> str:
    text = page.normalized_text if page.normalized_text is not None else page.text or ""
    return sanitize_extracted_text(strip_figure_markers_from_text(text)).strip()


def document_reading_text(document: Document) -> str:
    return "\n\n".join(
        text
        for text in (preferred_page_text(page) for page in sorted(document.pages, key=lambda page: page.page_number))
        if text
    )


_SPACED_LETTER_ARTIFACT_RE = re.compile(r"(?:\b[A-Za-z]\s+){4,}[A-Za-z]\b")
_BROKEN_HYPHEN_ARTIFACT_RE = re.compile(r"[A-Za-z]-\s*\n\s*[a-z]")


def _page_text_source(page: DocumentPage) -> str:
    return (page.text_source or "").replace("_low_text", "").strip().lower() or "pdf"


def _page_cloud_normalization_reason(page: DocumentPage, text_override: str | None = None) -> str | None:
    text = sanitize_extracted_text(text_override if text_override is not None else page.text)
    if not text.strip():
        return None
    if page.low_text:
        return "low_text"
    if _page_text_source(page) == "marker":
        return None
    if len(_BROKEN_HYPHEN_ARTIFACT_RE.findall(text)) >= 2:
        return "hyphenated_wraps"
    if _SPACED_LETTER_ARTIFACT_RE.search(text):
        return "spaced_letters"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 16:
        short_lines = sum(1 for line in lines if len(line) <= 42 and not line.startswith("|"))
        if short_lines / len(lines) >= 0.58:
            return "fragmented_lines"
    return None


def _page_normalization_mode() -> str:
    mode = (get_settings().openai_page_normalization_mode or "auto").strip().lower()
    return mode if mode in {"auto", "always", "never"} else "auto"


def _local_page_normalization(text: str | None, *, source: str, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "normalized_text": normalize_extracted_text(text),
        "source": source,
        "confidence": 0.65,
        "notes": notes or [],
    }


def normalize_document_pages(
    document: Document,
    *,
    ai: Any | None = None,
    db: Session | None = None,
    job: ImportJob | None = None,
    resume_existing: bool = False,
    model: str | None = None,
    pdf_bytes: bytes | None = None,
    usage_context: OpenAIUsageContext | None = None,
    normalization_text_by_page_id: dict[str, str] | None = None,
    cloud_enabled: bool = True,
    auto_max_pages_override: int | None = None,
    protect_manual: bool = False,
) -> dict[str, Any]:
    ai = ai or get_ai_service()
    settings = get_settings()
    mode = _page_normalization_mode()
    auto_max_pages = max(
        0,
        settings.openai_page_normalization_auto_max_pages if auto_max_pages_override is None else auto_max_pages_override,
    )
    auto_cloud_pages = 0
    auto_reasons: dict[str, int] = {}
    auto_skipped_by_cap = 0
    source_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    changed_pages = 0
    failed_notes: list[str] = []
    pages = sorted(document.pages, key=lambda page: page.page_number)
    total_pages = len(pages)
    for index, page in enumerate(pages, start=1):
        page.text = sanitize_extracted_text(page.text)
        page.normalized_text = sanitize_extracted_text(page.normalized_text) or None
        if protect_manual and page.text_source == "manual":
            source_counts["manual_protected"] = source_counts.get("manual_protected", 0) + 1
            continue
        if resume_existing and page.normalized_text:
            source_counts["existing"] = source_counts.get("existing", 0) + 1
            continue
        if db and job:
            job.current_step = f"normalizing_page_{page.page_number}"
            job.locked_at = utc_now()
            log_event(
                db,
                job=job,
                document=document,
                event_type="normalizing_page",
                message=f"Normalizing page {index} of {total_pages}.",
                payload={"page_number": page.page_number, "page_index": index, "page_count": total_pages},
            )
            db.commit()
        before = sanitize_extracted_text(page.normalized_text)
        normalization_input = (
            sanitize_extracted_text(normalization_text_by_page_id.get(page.id))
            if normalization_text_by_page_id and page.id in normalization_text_by_page_id
            else sanitize_extracted_text(page.text)
        )
        auto_reason = _page_cloud_normalization_reason(page, normalization_input)
        if auto_reason:
            auto_reasons[auto_reason] = auto_reasons.get(auto_reason, 0) + 1
        if not cloud_enabled:
            result = _local_page_normalization(normalization_input, source="local_preset")
        elif mode == "never" or not settings.openai_normalize_page_text:
            result = _local_page_normalization(normalization_input, source="local")
        elif mode == "auto" and not auto_reason:
            result = _local_page_normalization(normalization_input, source="local_auto")
        elif mode == "auto" and auto_cloud_pages >= auto_max_pages:
            auto_skipped_by_cap += 1
            result = _local_page_normalization(
                normalization_input,
                source="local_auto_cap",
                notes=[f"OpenAI page normalization auto cap reached before page {page.page_number}."],
            )
        else:
            auto_cloud_pages += 1 if mode == "auto" else 0
            result = ai.normalize_page_text(
                document.original_filename,
                page.page_number,
                normalization_input,
                model=model,
                pdf_bytes=pdf_bytes if mode == "always" else None,
                usage_context=usage_context,
            )
        page.normalized_text = sanitize_extracted_text(result.get("normalized_text")) or None
        source = result.get("source") or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
        openai = result.get("_openai") or {}
        used_model = openai.get("model")
        if isinstance(used_model, str) and used_model:
            model_counts[used_model] = model_counts.get(used_model, 0) + 1
        if (page.normalized_text or "") != before:
            changed_pages += 1
        failed_notes.extend(note for note in result.get("notes") or [] if "failed" in note.lower())
        if db and job:
            job.locked_at = utc_now()
            db.commit()
    summary = {
        "pages": total_pages,
        "changed_pages": changed_pages,
        "mode": mode,
        "sources": source_counts,
        "cloud_enabled": cloud_enabled,
    }
    if mode == "auto":
        summary["auto_cloud_pages"] = auto_cloud_pages
        summary["auto_cloud_page_limit"] = auto_max_pages
        if auto_reasons:
            summary["auto_reasons"] = auto_reasons
        if auto_skipped_by_cap:
            summary["auto_skipped_by_cap"] = auto_skipped_by_cap
    if model_counts:
        summary["models"] = model_counts
    if failed_notes:
        summary["warnings"] = failed_notes[:5]
    return summary


def rebuild_document_text_chunks(db: Session, document: Document) -> str:
    reading_text = sanitize_extracted_text(document_reading_text(document))
    document.search_text = reading_text
    document.chunks.clear()
    db.flush()
    for chunk in split_text_into_chunks(reading_text):
        db.add(TextChunk(document_id=document.id, text=chunk, token_count=max(1, len(chunk) // 4)))
    return reading_text


def _prepared_source_pages(document: Document) -> tuple[str | None, list[dict[str, Any]]]:
    source_import = (document.metadata_evidence or {}).get("source_import")
    if not isinstance(source_import, dict):
        return None, []
    source_kind = str(source_import.get("kind") or "").strip().lower()
    if source_kind not in {"html", "text"}:
        return source_kind or None, []
    pages = source_import.get("extracted_pages")
    if not isinstance(pages, list):
        return source_kind, []
    return source_kind, [page for page in pages if isinstance(page, dict)]


def _compact_source_import_evidence(evidence: dict[str, Any], page_count: int) -> dict[str, Any]:
    source_import = evidence.get("source_import")
    if not isinstance(source_import, dict) or "extracted_pages" not in source_import:
        return evidence
    compacted = dict(source_import)
    compacted.pop("extracted_pages", None)
    compacted["extracted_page_count"] = page_count
    return {**evidence, "source_import": compacted}


def import_processing_preset_for_job(db: Session, job: ImportJob, document: Document) -> dict[str, Any]:
    evidence = document.metadata_evidence or {}
    preset = evidence.get("import_processing_preset")
    if isinstance(preset, dict):
        return preset
    shared_defaults = job.batch.shared_defaults if job.batch else {}
    if isinstance(shared_defaults, dict):
        preset = shared_defaults.get("processing_preset_snapshot")
        if isinstance(preset, dict):
            return preset
        preset_id = shared_defaults.get("processing_preset_id")
        if isinstance(preset_id, str) and preset_id.strip():
            return import_processing_snapshot(db, preset_id)
    return import_processing_snapshot(db)


def refresh_import_batch_progress(db: Session, batch: ImportBatch) -> None:
    db.flush()
    batch.completed_files = db.query(ImportJob).filter(
        ImportJob.batch_id == batch.id,
        ImportJob.status == "complete",
    ).count()
    batch.failed_files = db.query(ImportJob).filter(
        ImportJob.batch_id == batch.id,
        ImportJob.status == "failed",
    ).count()
    cleared_files = db.query(ImportJob).filter(
        ImportJob.batch_id == batch.id,
        ImportJob.status == "cleared",
    ).count()
    staged_files = db.query(ImportJob).filter(
        ImportJob.batch_id == batch.id,
        ImportJob.status == "staged",
    ).count()
    active_files = db.query(ImportJob).filter(
        ImportJob.batch_id == batch.id,
        ImportJob.status.in_(["queued", "running", "paused", "restored_paused"]),
    ).count()
    finished_files = batch.completed_files + batch.failed_files + cleared_files
    if finished_files >= batch.total_files:
        if cleared_files and batch.completed_files == 0 and batch.failed_files == 0:
            batch.status = "cleared"
        else:
            batch.status = "complete" if batch.failed_files == 0 else "complete_with_errors"
    elif active_files > 0 or (finished_files > 0 and not staged_files):
        batch.status = "running"
    elif staged_files > 0:
        batch.status = "staged"
    else:
        batch.status = "queued"
    if batch.status in {"complete", "complete_with_errors", "cleared"}:
        existing_events = db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "import_batch_complete").all()
        already_logged = any((event.payload or {}).get("batch_id") == batch.id for event in existing_events)
        if not already_logged:
            db.add(
                ProcessingEvent(
                    level="info" if batch.status == "complete" else "warning",
                    event_type="import_batch_complete",
                    message=f"Import batch {batch.label or batch.id} finished with status {batch.status}.",
                    payload={
                        "batch_id": batch.id,
                        "label": batch.label,
                        "status": batch.status,
                        "total_files": batch.total_files,
                        "completed_files": batch.completed_files,
                        "failed_files": batch.failed_files,
                        "cleared_files": cleared_files,
                    },
                )
            )


class DocumentProcessor:
    def process_job(self, db: Session, job: ImportJob) -> None:
        job_id = job.id
        document = job.document
        if not document:
            job.status = "failed"
            job.last_error = "Document record is missing."
            return
        document_id = document.id

        try:
            job.status = "running"
            job.attempts += 1
            job.locked_at = utc_now()
            document.processing_status = "running"
            sync_portfolio_version_processing_status(db, document, "running")
            log_event(db, job=job, document=document, event_type="started", message="Processing started.")
            db.commit()

            self._extract(db, job, document)
            self._extract_figures(db, job, document)
            self._enrich(db, job, document)
            self._index(db, job, document)
            self._cleanup_processing_cache(db, job, document)
            sync_import_usage_composition(db, document=document, job=job)

            job.current_step = "complete"
            job.status = "complete"
            job.locked_at = None
            document.processing_status = "ready"
            sync_portfolio_version_processing_status(db, document, "ready")
            batch = db.get(ImportBatch, job.batch_id)
            if batch:
                refresh_import_batch_progress(db, batch)
            log_event(db, job=job, document=document, event_type="complete", message="Processing complete.")
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ImportJob, job_id)
            document = db.get(Document, document_id)
            if not job:
                return
            job.status = "failed"
            job.locked_at = None
            job.last_error = str(exc)
            if document:
                document.processing_status = "failed"
                sync_portfolio_version_processing_status(db, document, "failed")
            batch = db.get(ImportBatch, job.batch_id)
            if batch:
                refresh_import_batch_progress(db, batch)
            if document:
                sync_import_usage_composition(db, document=document, job=job)
                record_import_erratum(
                    db,
                    document=document,
                    job=job,
                    stage_key=composition_stage_key_for_job_step(job.current_step),
                    message=str(exc),
                    metadata={"current_step": job.current_step, "attempts": job.attempts},
                )
            log_event(db, job=job, document=document, event_type="failed", message=str(exc), level="error")
            db.commit()

    def _extract(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "extracted"):
            return
        started_at, started_perf = stage_timer()
        resume_normalization = (job.current_step == "normalizing_pages" or is_page_normalization_step(job.current_step)) and bool(
            document.pages
        )
        raw_text_extractor = get_analysis_model(db, MODEL_RAW_TEXT_EXTRACTION)
        actual_extractor = "persisted_pages"
        fallback_reason = None
        if not resume_normalization:
            source_kind, source_pages = _prepared_source_pages(document)
            if source_kind in {"html", "text"} and source_pages:
                checkpoint_job_step(
                    db,
                    job,
                    document,
                    "extracting",
                    f"Preparing {source_kind.upper()} source text from imported document semantics.",
                )
                actual_extractor = f"{source_kind}_source_semantics"
                document.page_count = len(source_pages)
                document.pages.clear()
                db.flush()
                for raw_page in source_pages:
                    text = sanitize_extracted_text(str(raw_page.get("text") or ""))
                    page_number = int(raw_page.get("page_number") or len(document.pages) + 1)
                    document.pages.append(
                        DocumentPage(
                            document_id=document.id,
                            page_number=page_number,
                            text=text,
                            low_text=bool(raw_page.get("low_text")) or len(text) < get_settings().low_text_page_threshold,
                            text_source=str(raw_page.get("source") or actual_extractor),
                        )
                    )
                db.flush()
                checkpoint_job_step(db, job, document, "normalizing_pages", "Normalizing parsed source page text.")
            else:
                local_path = ensure_document_cache_file(db, document, source="import_retry")
                if not local_path or not local_path.exists():
                    raise RuntimeError("Local processing cache is missing. Re-upload or restore from GCS.")

                checkpoint_job_step(db, job, document, "extracting", f"Extracting PDF text with {raw_text_extractor}.")
                extracted = extract_pdf_text(local_path, extractor=raw_text_extractor)
                actual_extractor = extracted.source
                fallback_reason = extracted.fallback_reason
                if extracted.fallback_reason:
                    log_event(
                        db,
                        job=job,
                        document=document,
                        event_type="raw_extraction_fallback",
                        message=extracted.fallback_reason,
                        level="warning",
                        payload={"selected_extractor": raw_text_extractor, "actual_extractor": extracted.source},
                    )
                document.page_count = extracted.page_count
                document.pages.clear()
                db.flush()
                for page in extracted.pages:
                    document.pages.append(
                        DocumentPage(
                            document_id=document.id,
                            page_number=page.page_number,
                            text=sanitize_extracted_text(page.text),
                            low_text=page.low_text,
                            text_source=page.source if not page.low_text else f"{page.source}_low_text",
                        )
                    )
                db.flush()
                checkpoint_job_step(db, job, document, "normalizing_pages", "Normalizing extracted page text.")
        else:
            job.locked_at = utc_now()
            log_event(
                db,
                job=job,
                document=document,
                event_type="normalization_resumed",
                message="Resuming page text normalization from persisted page checkpoints.",
            )
            db.commit()
        preset_snapshot = import_processing_preset_for_job(db, job, document)
        second_pass_enabled = bool(preset_snapshot.get("second_pass_enabled", True))
        cleanup_text_by_page_id: dict[str, str] | None = None
        cleanup_evidence: dict[str, Any] | None = None
        cleanup_config = preset_snapshot.get("cleanup") if isinstance(preset_snapshot.get("cleanup"), dict) else {}
        if second_pass_enabled:
            cleanup_started_at, cleanup_started_perf = stage_timer()
            checkpoint_job_step(db, job, document, "cleaning_structure", "Cleaning document structure and boilerplate.")
            cleanup_result = clean_document_structure(document, preset_snapshot)
            raw_cleanup_text = cleanup_result.pop("cleaned_text_by_page_id", {})
            cleanup_text_by_page_id = raw_cleanup_text if isinstance(raw_cleanup_text, dict) else None
            cleanup_evidence = cleanup_result
            record_import_stage(
                db,
                document=document,
                job=job,
                stage_key="document_structure_cleanup",
                label="Document structure cleanup",
                method="deterministic",
                started_at=cleanup_started_at,
                duration_ms=elapsed_ms(cleanup_started_perf),
                metadata=cleanup_evidence,
            )
            log_event(
                db,
                job=job,
                document=document,
                event_type="document_structure_cleanup",
                message=f"Removed {cleanup_evidence.get('removed_boilerplate_count', 0)} boilerplate lines.",
                payload=cleanup_evidence,
            )
            db.commit()
            structured_tables_evidence = cleanup_evidence.get("structured_tables", {}) if cleanup_evidence else {}
            record_import_stage(
                db,
                document=document,
                job=job,
                stage_key="structured_tables",
                label="Structured tables",
                method="evidence_only",
                status="evidence_only",
                metadata=structured_tables_evidence if isinstance(structured_tables_evidence, dict) else {},
            )
        ocr_config = preset_snapshot.get("ocr") if isinstance(preset_snapshot.get("ocr"), dict) else {}
        low_text_pages = [page.page_number for page in document.pages if page.low_text]
        ocr_enabled = second_pass_enabled and bool(ocr_config.get("enabled", True))
        ocr_evidence = {
            "low_text_pages": low_text_pages,
            "eligible_pages": low_text_pages if ocr_enabled else [],
            "provider": str(ocr_config.get("provider") or "google_vision") if ocr_enabled else "none",
            "status": "pending_provider_integration" if ocr_enabled and low_text_pages else ("not_needed" if ocr_enabled else "disabled_by_preset"),
        }
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="ocr_fallback",
            label="OCR fallback",
            method="eligibility_audit",
            status=str(ocr_evidence["status"]),
            metadata=ocr_evidence,
        )
        ai = get_ai_service()
        pdf_path = metadata_cache_path(document)
        pdf_bytes = pdf_path.read_bytes() if pdf_path and pdf_path.exists() else None
        cloud_enabled = True
        auto_max_pages_override: int | None = None
        normalization_model = get_analysis_model(db, MODEL_PAGE_TEXT_NORMALIZATION)
        if second_pass_enabled:
            cloud_enabled = bool(cleanup_config.get("cloud_escalation", True))
            auto_max_pages_override = import_processing_cloud_page_cap(preset_snapshot, len(document.pages))
            if isinstance(cleanup_config.get("model"), str) and cleanup_config.get("model") != "local":
                normalization_model = str(cleanup_config["model"])
            checkpoint_job_step(db, job, document, "normalizing_pages", "Normalizing cleaned page text.")
        normalization_started_at, normalization_started_perf = stage_timer()
        normalization_summary = normalize_document_pages(
            document,
            ai=ai,
            db=db,
            job=job,
            resume_existing=resume_normalization,
            model=normalization_model,
            pdf_bytes=pdf_bytes,
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="page_text_normalization",
            ),
            normalization_text_by_page_id=cleanup_text_by_page_id,
            cloud_enabled=cloud_enabled,
            auto_max_pages_override=auto_max_pages_override,
        )
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="page_text_normalization",
            label="Page text normalization",
            method="local_first_auto" if cloud_enabled else "local_only",
            model=normalization_model if cloud_enabled else "local",
            started_at=normalization_started_at,
            duration_ms=elapsed_ms(normalization_started_perf),
            metadata=normalization_summary,
        )
        reading_text = rebuild_document_text_chunks(db, document)
        bibliography_config = preset_snapshot.get("bibliography") if isinstance(preset_snapshot.get("bibliography"), dict) else {}
        bibliography_evidence: dict[str, Any] = {"status": "disabled_by_preset"}
        if bool(bibliography_config.get("enabled", True)):
            bibliography_started_at, bibliography_started_perf = stage_timer()
            checkpoint_job_step(db, job, document, "extracting_bibliography", "Extracting source bibliography.")
            bibliography_visual_ocr = bibliography_visual_ocr_enabled(preset_snapshot)
            bibliography_pdf_path = (
                pdf_path
                if bool(bibliography_config.get("preserve_italics", True)) or bibliography_visual_ocr
                else None
            )
            bibliography_result = extract_document_bibliography(
                document,
                bibliography_pdf_path,
                visual_ocr=bibliography_visual_ocr,
            )
            bibliography_evidence = bibliography_result.get("evidence") or {}
            document.bibliography = bibliography_result.get("bibliography") or None
            record_import_stage(
                db,
                document=document,
                job=job,
                stage_key="bibliography_extraction",
                label="Bibliography extraction",
                method=str(bibliography_evidence.get("source") or "local"),
                started_at=bibliography_started_at,
                duration_ms=elapsed_ms(bibliography_started_perf),
                metadata=bibliography_evidence,
            )
            log_event(
                db,
                job=job,
                document=document,
                event_type="bibliography_extraction",
                message="Extracted source bibliography." if document.bibliography else "No source bibliography section found.",
                payload=bibliography_evidence,
            )
        evidence = _compact_source_import_evidence(dict(document.metadata_evidence or {}), document.page_count)
        document.metadata_evidence = {
            **evidence,
            "import_processing_preset": preset_snapshot,
            "raw_text_extraction": {
                "selected_extractor": raw_text_extractor,
                "actual_extractor": actual_extractor,
                "fallback_reason": fallback_reason,
            },
            **({"document_structure_cleanup": cleanup_evidence} if cleanup_evidence else {}),
            **({"structured_tables": cleanup_evidence.get("structured_tables")} if cleanup_evidence else {}),
            "page_text_normalization": normalization_summary,
            "ocr_fallback": ocr_evidence,
            "bibliography_extraction": bibliography_evidence,
        }
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="raw_text_extraction",
            label="Text extraction",
            method=actual_extractor,
            started_at=started_at,
            duration_ms=elapsed_ms(started_perf),
            metadata={
                "selected_extractor": raw_text_extractor,
                "actual_extractor": actual_extractor,
                "fallback_reason": fallback_reason,
                "import_processing_preset": {
                    "id": preset_snapshot.get("id"),
                    "name": preset_snapshot.get("name"),
                    "mode": preset_snapshot.get("mode"),
                    "second_pass_enabled": second_pass_enabled,
                },
                "document_structure_cleanup": cleanup_evidence,
                "ocr_fallback": ocr_evidence,
                "page_text_normalization": normalization_summary,
                "bibliography_extraction": bibliography_evidence,
            },
        )
        sync_import_usage_composition(db, document=document, job=job)
        job.current_step = "extracted"
        log_event(
            db,
            job=job,
            document=document,
            event_type="extracted",
            message=f"Extracted {document.page_count} pages.",
            payload={
                "low_text_pages": [page.page_number for page in document.pages if page.low_text],
                "readable_characters": len(reading_text),
                "import_processing_preset": {
                    "id": preset_snapshot.get("id"),
                    "name": preset_snapshot.get("name"),
                    "mode": preset_snapshot.get("mode"),
                },
                "page_text_normalization": normalization_summary,
            },
        )
        db.commit()

    def _extract_figures(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "figures"):
            return
        started_at, started_perf = stage_timer()
        local_path = ensure_document_cache_file(db, document, source="figure_extraction")
        if not local_path or not local_path.exists():
            raise RuntimeError("Local processing cache is missing. Re-upload or restore from GCS.")
        checkpoint_job_step(db, job, document, "extracting_figures", "Extracting embedded figures.")
        result = process_document_figures(db, document, local_path)
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="visual_asset_extraction",
            label="Visual asset extraction",
            method="pymupdf",
            started_at=started_at,
            duration_ms=elapsed_ms(started_perf),
            metadata=result,
        )
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="visual_asset_context",
            label="Visual asset context",
            method="local_page_context",
            metadata={
                "figures_with_context": result.get("figures_with_context", 0),
                "explicit_mentions": result.get("explicit_mentions", 0),
            },
        )
        job.current_step = "figures"
        log_event(
            db,
            job=job,
            document=document,
            event_type="figures_extracted",
            message=f"Extracted {result['figures']} figures.",
            payload=result,
        )
        db.commit()

    def _enrich(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "enriched"):
            return
        started_at, started_perf = stage_timer()
        checkpoint_job_step(db, job, document, "enriching", "Enriching metadata, citation, summary, and topics.")
        before = document_correction_snapshot(document)
        ai = get_ai_service()
        local_path = ensure_document_cache_file(db, document, source="metadata_enrichment")
        pdf_bytes = local_path.read_bytes() if local_path and local_path.exists() else None
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
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="summary_topics",
            ),
            prompt_cache_key=f"medusa-doc:{document.checksum_sha256}",
        )
        document.title = metadata.get("title") or document.title
        document.subtitle = metadata.get("subtitle")
        document.authors = metadata.get("authors") or []
        document.universities = metadata.get("universities") or []
        document.publication_year = metadata.get("publication_year")
        document.journal = metadata.get("journal")
        document.publisher = metadata.get("publisher")
        document.doi = metadata.get("doi")
        document.abstract = metadata.get("abstract")
        document.rich_summary = metadata.get("rich_summary")
        document.metadata_confidence = metadata.get("confidence")
        enrichment_generated_at = utc_now().isoformat()
        document.metadata_evidence = {
            **(document.metadata_evidence or {}),
            "ai": {
                "confidence": metadata.get("confidence"),
                "needs_review_reasons": metadata.get("needs_review_reasons") or [],
                "citation_warnings": metadata.get("citation_warnings") or [],
                "generated_at": enrichment_generated_at,
                "summary_generated_at": enrichment_generated_at if document.rich_summary else None,
                **(metadata.get("_openai") or {}),
            },
        }

        doi_resolution = local_doi_resolution_evidence(
            doi=document.doi,
            title=document.title,
            authors=document.authors,
            year=document.publication_year,
            text=document.search_text,
            bibliography=document.bibliography,
        )
        document.metadata_evidence["doi_source_resolution"] = doi_resolution
        local_doi_selection = doi_resolution.get("selected") if isinstance(doi_resolution.get("selected"), dict) else None
        if not document.doi and local_doi_selection and not doi_resolution.get("conflicts"):
            document.doi = local_doi_selection.get("doi")
        if not document.doi and not (doi_resolution.get("candidates") or document.title):
            document.doi = extract_doi_from_text(document.search_text)

        source_link_resolution = stable_source_link_evidence(
            title=document.title,
            authors=document.authors,
            year=document.publication_year,
            source_url=document.source_url,
            text=document.search_text,
            bibliography=document.bibliography,
        )
        document.metadata_evidence["source_link_resolution"] = source_link_resolution
        source_link_selection = (
            source_link_resolution.get("selected") if isinstance(source_link_resolution.get("selected"), dict) else None
        )
        if not document.source_url and source_link_selection:
            document.source_url = source_link_selection.get("source_url")

        crossref = crossref_lookup(document.doi, document.title, document.authors, document.publication_year)
        doi_discovery: dict[str, Any] | None = None
        if not crossref and not document.doi:
            doi_discovery = discover_doi_from_title(document.title, document.authors, document.publication_year)
            if doi_discovery:
                document.doi = doi_discovery["doi"]
                document.metadata_evidence["doi_discovery"] = doi_discovery
                document.metadata_evidence["doi_source_resolution"] = {
                    **doi_resolution,
                    "title_discovery": doi_discovery,
                    "conflicts": [*(doi_resolution.get("conflicts") or []), *(doi_discovery.get("conflicts") or [])],
                }
                if not document.source_url and doi_discovery.get("source_url"):
                    document.source_url = doi_discovery.get("source_url")
                crossref = crossref_lookup(document.doi, document.title, document.authors, document.publication_year)
        crossref_metadata: dict[str, Any] = {}
        if crossref:
            document.metadata_evidence["crossref"] = crossref
            crossref_metadata = crossref_to_citation_metadata(crossref)
            filled_fields = fill_missing_document_metadata(document, crossref_metadata)
            if filled_fields:
                document.metadata_evidence["crossref_filled_fields"] = filled_fields
        publication_result = refresh_document_publication_metadata(
            db,
            document,
            ai_publication=metadata.get("publication") if isinstance(metadata.get("publication"), dict) else None,
            crossref=crossref,
            model=model_preferences[MODEL_METADATA],
            source="import",
        )
        document.metadata_evidence["publication_metadata"] = {
            **publication_result,
            "generated_at": utc_now().isoformat(),
        }

        citation_metadata = merge_citation_metadata(crossref_metadata, document_metadata(document))
        if document.metadata_evidence.get("doi_source_resolution") or document.metadata_evidence.get("source_link_resolution"):
            citation_metadata["_resolution_evidence"] = {
                "doi_source_resolution": document.metadata_evidence.get("doi_source_resolution"),
                "source_link_resolution": document.metadata_evidence.get("source_link_resolution"),
            }
        citation_model = model_preferences[MODEL_APA_CITATION]
        apa_candidate = ai.generate_apa_citation_candidate(
            document.original_filename,
            document.search_text or "",
            citation_metadata,
            model=citation_model,
            crossref_candidates=[crossref] if crossref else None,
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="citation_refresh",
            ),
            prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:apa",
        )
        document.metadata_evidence["ai_apa"] = apa_candidate_evidence(apa_candidate)
        citation_validation_warnings = apply_apa_candidate_or_metadata_citations(
            document,
            citation_metadata,
            apa_candidate,
            model=citation_model,
            fallback_source="crossref" if crossref else "model",
        )
        if citation_validation_warnings:
            document.metadata_evidence["apa_validation_warnings"] = citation_validation_warnings
        else:
            document.metadata_evidence.pop("apa_validation_warnings", None)
        source_link_confidence = 0.0
        if isinstance(source_link_selection, dict):
            try:
                source_link_confidence = float(source_link_selection.get("confidence") or 0)
            except (TypeError, ValueError):
                source_link_confidence = 0.0
        trusted_source_link = bool(document.source_url and source_link_confidence >= 0.76)
        resolution_conflicts = bool(doi_resolution.get("conflicts") or (doi_discovery or {}).get("conflicts"))
        if (
            enough_metadata_for_verified_citation(citation_metadata)
            and (document.doi or crossref or trusted_source_link)
            and not resolution_conflicts
            and not apa_candidate_needs_review(apa_candidate)
        ):
            document.citation_status = "verified"
        else:
            document.citation_status = "needs_review"
            db.add(
                CitationCandidate(
                    document_id=document.id,
                    source="medusa-importer",
                    citation_text=document.apa_citation,
                    source_metadata=citation_metadata,
                    confidence=document.metadata_confidence,
                    status="needs_review",
                )
            )

        tag_governance = apply_import_tag_governance(
            db,
            document=document,
            topics=metadata.get("topics") or [],
            keywords=metadata.get("keywords") or [],
            source="import",
            job=job,
            ai=ai,
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="tag_governance",
            ),
        )

        record_document_version(
            db,
            document=document,
            change_note="Metadata enrichment",
            changed_fields=[
                "title",
                "subtitle",
                "authors",
                "universities",
                "publication_year",
                "publisher",
                "journal",
                "publication",
                "doi",
                "source_url",
                "abstract",
                "rich_summary",
                "bibliography",
                "apa_citation",
                "apa_in_text_citation",
                "citation_status",
                "tags",
            ],
            before=before,
            after=document_correction_snapshot(document),
            extra={"citation_metadata": citation_metadata},
        )
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="summary_topics",
            label="Metadata, summary, citation, and topics",
            provider="local",
            method="routed_document_intelligence",
            started_at=started_at,
            duration_ms=elapsed_ms(started_perf),
            metadata={
                "models": {
                    MODEL_METADATA: model_preferences[MODEL_METADATA],
                    MODEL_SUMMARY: model_preferences[MODEL_SUMMARY],
                    MODEL_APA_CITATION: model_preferences[MODEL_APA_CITATION],
                    MODEL_KEYWORDS_TOPICS: model_preferences[MODEL_KEYWORDS_TOPICS],
                },
                "citation_status": document.citation_status,
                "crossref_used": bool(crossref),
                "doi_discovery_source": doi_discovery.get("source") if doi_discovery else (local_doi_selection or {}).get("source"),
                "source_link_resolution": source_link_resolution,
                "publication_metadata": publication_result,
                "tag_governance": tag_governance,
            },
        )
        sync_import_usage_composition(db, document=document, job=job)
        job.current_step = "enriched"
        log_event(db, job=job, document=document, event_type="enriched", message="Metadata enrichment complete.")
        db.commit()

    def _index(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "indexed"):
            return
        started_at, started_perf = stage_timer()
        checkpoint_job_step(db, job, document, "indexing", "Indexing searchable text and embeddings.")
        ai = get_ai_service()
        encoding_model = get_analysis_model(db, MODEL_TEXT_CHUNK_ENCODING)
        embedding_errors: list[str] = []
        encoded_chunks = 0
        for chunk in document.chunks[:20]:
            if chunk.embedding is None:
                try:
                    chunk.embedding = ai.embed(
                        chunk.text,
                        model=encoding_model,
                        usage_context=OpenAIUsageContext(
                            document_id=document.id,
                            import_job_id=job.id,
                            source="import",
                            capability_key="text_chunk_encoding",
                        ),
                    )
                    if chunk.embedding is not None:
                        encoded_chunks += 1
                except Exception as exc:
                    embedding_errors.append(str(exc))
        document.search_text = sanitize_extracted_text(
            "\n\n".join(
                part
                for part in [
                    document.title,
                    author_search_text(document.authors),
                    document.abstract,
                    document.rich_summary,
                    document.bibliography,
                    document.search_text,
                    figure_search_text(document.figures),
                    " ".join(tag.name for tag in document.tags),
                ]
                if part
            )
        )
        evidence = dict(document.metadata_evidence or {})
        evidence["text_chunk_encoding"] = {
            "model": encoding_model,
            "encoded_chunks": encoded_chunks,
            "skipped_chunks": max(0, min(len(document.chunks), 20) - encoded_chunks),
        }
        if embedding_errors:
            evidence["text_chunk_encoding"]["errors"] = embedding_errors[:3]
        document.metadata_evidence = evidence
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="text_chunk_encoding",
            label="Search index and embeddings",
            method="embedding_index",
            model=encoding_model,
            started_at=started_at,
            duration_ms=elapsed_ms(started_perf),
            metadata=evidence["text_chunk_encoding"],
            status="warning" if embedding_errors else "complete",
            message="Embedding errors were recorded." if embedding_errors else None,
        )
        if embedding_errors:
            record_import_erratum(
                db,
                document=document,
                job=job,
                stage_key="text_chunk_encoding",
                message="; ".join(embedding_errors[:3]),
                level="warning",
                metadata={"model": encoding_model},
            )
        sync_import_usage_composition(db, document=document, job=job)
        job.current_step = "indexed"
        log_event(db, job=job, document=document, event_type="indexed", message="Search indexing complete.")
        db.commit()

    def _cleanup_processing_cache(self, db: Session, job: ImportJob, document: Document) -> None:
        started_at, started_perf = stage_timer()
        checkpoint_job_step(db, job, document, "cleaning_cache", "Cleaning temporary processing cache.")
        evidence = dict(document.metadata_evidence or {})
        cache_path = evidence.get("local_cache_path") or evidence.get("document_cache_path")
        if not cache_path:
            summary = enforce_document_cache_budget(db, keep_document_id=document.id)
            record_import_stage(
                db,
                document=document,
                job=job,
                stage_key="cache_cleanup",
                label="Cache cleanup",
                method="document_cache_budget",
                started_at=started_at,
                duration_ms=elapsed_ms(started_perf),
                metadata=summary,
            )
            log_event(
                db,
                job=job,
                document=document,
                event_type="cache_budget_checked",
                message="Document cache budget checked.",
                payload=summary,
            )
            return
        path = Path(str(cache_path)).expanduser()
        cache_root = (get_settings().data_dir / "processing-cache").resolve()
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            resolved = path.absolute()
        if cache_root not in resolved.parents:
            record_import_stage(
                db,
                document=document,
                job=job,
                stage_key="cache_cleanup",
                label="Cache cleanup",
                method="document_cache_budget",
                status="warning",
                started_at=started_at,
                duration_ms=elapsed_ms(started_perf),
                message="Processing cache path was outside the managed cache root.",
                metadata={"path": str(path)},
            )
            record_import_erratum(
                db,
                document=document,
                job=job,
                stage_key="cache_cleanup",
                message="Processing cache path was outside the managed cache root.",
                level="warning",
                metadata={"path": str(path)},
            )
            log_event(
                db,
                job=job,
                document=document,
                event_type="cache_cleanup_skipped",
                message="Processing cache path was outside the managed cache root.",
                level="warning",
                payload={"path": str(path)},
            )
            return
        if path.exists():
            mark_processing_cache_retained(document, path)
        summary = enforce_document_cache_budget(db, keep_document_id=document.id)
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="cache_cleanup",
            label="Cache cleanup",
            method="document_cache_budget",
            started_at=started_at,
            duration_ms=elapsed_ms(started_perf),
            metadata=summary,
        )
        log_event(
            db,
            job=job,
            document=document,
            event_type="cache_budget_checked",
            message="Document cache budget checked.",
            payload=summary,
        )
