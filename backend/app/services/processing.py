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
    DocumentVersion,
    ImportBatch,
    ImportJob,
    ProcessingEvent,
    Tag,
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
from app.services.citations import decode_html_entities, format_apa_citation, merge_citation_metadata
from app.services.document_cache import (
    enforce_document_cache_budget,
    ensure_document_cache_file,
    mark_processing_cache_retained,
    metadata_cache_path,
)
from app.services.extraction import extract_pdf_text, normalize_extracted_text, sanitize_extracted_text, split_text_into_chunks
from app.services.figures import process_document_figures
from app.services.openai_usage import OpenAIUsageContext
from app.services.preferences import get_analysis_model, get_analysis_models
from app.services.verifier import crossref_lookup, crossref_to_citation_metadata, enough_metadata_for_verified_citation


IMPORT_STEP_ORDER = {
    "stored": 0,
    "extracting": 0,
    "normalizing_pages": 0,
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


def checkpoint_job_step(db: Session, job: ImportJob, document: Document, step: str, message: str) -> None:
    if job.current_step != step:
        job.current_step = step
        log_event(db, job=job, document=document, event_type=step, message=message)
    job.locked_at = utc_now()
    db.commit()


def get_or_create_tag(db: Session, name: str, kind: str = "keyword") -> Tag:
    normalized = name.strip().lower()
    tag = db.query(Tag).filter(Tag.name == normalized).one_or_none()
    if tag:
        return tag
    tag = Tag(name=normalized, kind=kind)
    db.add(tag)
    db.flush()
    return tag


def document_metadata(document: Document) -> dict[str, Any]:
    return {
        "title": document.title,
        "authors": document.authors,
        "publication_year": document.publication_year,
        "journal": document.journal,
        "publisher": document.publisher,
        "doi": document.doi,
        "source_url": document.source_url,
    }


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
    return sanitize_extracted_text(page.normalized_text or page.text or "").strip()


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


def _page_cloud_normalization_reason(page: DocumentPage) -> str | None:
    text = sanitize_extracted_text(page.text)
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
) -> dict[str, Any]:
    ai = ai or get_ai_service()
    settings = get_settings()
    mode = _page_normalization_mode()
    auto_max_pages = max(0, settings.openai_page_normalization_auto_max_pages)
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
        auto_reason = _page_cloud_normalization_reason(page)
        if auto_reason:
            auto_reasons[auto_reason] = auto_reasons.get(auto_reason, 0) + 1
        if mode == "never" or not settings.openai_normalize_page_text:
            result = _local_page_normalization(page.text, source="local")
        elif mode == "auto" and not auto_reason:
            result = _local_page_normalization(page.text, source="local_auto")
        elif mode == "auto" and auto_cloud_pages >= auto_max_pages:
            auto_skipped_by_cap += 1
            result = _local_page_normalization(
                page.text,
                source="local_auto_cap",
                notes=[f"OpenAI page normalization auto cap reached before page {page.page_number}."],
            )
        else:
            auto_cloud_pages += 1 if mode == "auto" else 0
            result = ai.normalize_page_text(
                document.original_filename,
                page.page_number,
                page.text,
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
    finished_files = batch.completed_files + batch.failed_files
    if finished_files >= batch.total_files:
        batch.status = "complete" if batch.failed_files == 0 else "complete_with_errors"
    elif finished_files > 0:
        batch.status = "running"
    else:
        batch.status = "queued"


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
            log_event(db, job=job, document=document, event_type="started", message="Processing started.")
            db.commit()

            self._extract(db, job, document)
            self._extract_figures(db, job, document)
            self._enrich(db, job, document)
            self._index(db, job, document)
            self._cleanup_processing_cache(db, job, document)

            job.current_step = "complete"
            job.status = "complete"
            job.locked_at = None
            document.processing_status = "ready"
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
            batch = db.get(ImportBatch, job.batch_id)
            if batch:
                refresh_import_batch_progress(db, batch)
            log_event(db, job=job, document=document, event_type="failed", message=str(exc), level="error")
            db.commit()

    def _extract(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "extracted"):
            return
        resume_normalization = (job.current_step == "normalizing_pages" or is_page_normalization_step(job.current_step)) and bool(
            document.pages
        )
        if not resume_normalization:
            local_path = ensure_document_cache_file(db, document, source="import_retry")
            if not local_path or not local_path.exists():
                raise RuntimeError("Local processing cache is missing. Re-upload or restore from GCS.")

            raw_text_extractor = get_analysis_model(db, MODEL_RAW_TEXT_EXTRACTION)
            checkpoint_job_step(db, job, document, "extracting", f"Extracting PDF text with {raw_text_extractor}.")
            extracted = extract_pdf_text(local_path, extractor=raw_text_extractor)
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
        ai = get_ai_service()
        pdf_path = metadata_cache_path(document)
        pdf_bytes = pdf_path.read_bytes() if pdf_path and pdf_path.exists() else None
        normalization_summary = normalize_document_pages(
            document,
            ai=ai,
            db=db,
            job=job,
            resume_existing=resume_normalization,
            model=get_analysis_model(db, MODEL_PAGE_TEXT_NORMALIZATION),
            pdf_bytes=pdf_bytes,
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="page_text_normalization",
            ),
        )
        reading_text = rebuild_document_text_chunks(db, document)
        document.metadata_evidence = {
            **(document.metadata_evidence or {}),
            "raw_text_extraction": {
                "selected_extractor": get_analysis_model(db, MODEL_RAW_TEXT_EXTRACTION),
                "actual_extractor": extracted.source if not resume_normalization else "persisted_pages",
                "fallback_reason": extracted.fallback_reason if not resume_normalization else None,
            },
            "page_text_normalization": normalization_summary,
        }
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
                "page_text_normalization": normalization_summary,
            },
        )
        db.commit()

    def _extract_figures(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "figures"):
            return
        local_path = ensure_document_cache_file(db, document, source="figure_extraction")
        if not local_path or not local_path.exists():
            raise RuntimeError("Local processing cache is missing. Re-upload or restore from GCS.")
        checkpoint_job_step(db, job, document, "extracting_figures", "Extracting embedded figures.")
        result = process_document_figures(db, document, local_path)
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
        checkpoint_job_step(db, job, document, "enriching", "Enriching metadata, citation, summary, and topics.")
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
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="summary_topics",
            ),
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
        document.metadata_evidence = {
            **(document.metadata_evidence or {}),
            "ai": {
                "confidence": metadata.get("confidence"),
                "needs_review_reasons": metadata.get("needs_review_reasons") or [],
                "citation_warnings": metadata.get("citation_warnings") or [],
                **(metadata.get("_openai") or {}),
            },
        }

        crossref = crossref_lookup(document.doi, document.title)
        crossref_metadata: dict[str, Any] = {}
        if crossref:
            document.metadata_evidence["crossref"] = crossref
            crossref_metadata = crossref_to_citation_metadata(crossref)
            filled_fields = fill_missing_document_metadata(document, crossref_metadata)
            if filled_fields:
                document.metadata_evidence["crossref_filled_fields"] = filled_fields

        citation_metadata = merge_citation_metadata(crossref_metadata, document_metadata(document))
        document.apa_citation = (
            format_apa_citation(citation_metadata)
            if crossref
            else decode_html_entities(metadata.get("apa_citation")) or format_apa_citation(citation_metadata)
        )
        if enough_metadata_for_verified_citation(citation_metadata) and (document.doi or crossref):
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

        for topic in metadata.get("topics") or []:
            tag = get_or_create_tag(db, topic, "topic")
            if tag not in document.tags:
                document.tags.append(tag)
        for keyword in metadata.get("keywords") or []:
            tag = get_or_create_tag(db, keyword, "keyword")
            if tag not in document.tags:
                document.tags.append(tag)

        db.add(
            DocumentVersion(
                document_id=document.id,
                version_number=len(document.versions) + 1,
                change_note="Metadata enrichment",
                metadata_snapshot=citation_metadata,
            )
        )
        job.current_step = "enriched"
        log_event(db, job=job, document=document, event_type="enriched", message="Metadata enrichment complete.")
        db.commit()

    def _index(self, db: Session, job: ImportJob, document: Document) -> None:
        if job_step_at_least(job, "indexed"):
            return
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
        job.current_step = "indexed"
        log_event(db, job=job, document=document, event_type="indexed", message="Search indexing complete.")
        db.commit()

    def _cleanup_processing_cache(self, db: Session, job: ImportJob, document: Document) -> None:
        checkpoint_job_step(db, job, document, "cleaning_cache", "Cleaning temporary processing cache.")
        evidence = dict(document.metadata_evidence or {})
        cache_path = evidence.get("local_cache_path") or evidence.get("document_cache_path")
        if not cache_path:
            summary = enforce_document_cache_budget(db, keep_document_id=document.id)
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
        log_event(
            db,
            job=job,
            document=document,
            event_type="cache_budget_checked",
            message="Document cache budget checked.",
            payload=summary,
        )
