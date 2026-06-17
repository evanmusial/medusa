from __future__ import annotations

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
from app.services.citations import format_apa_citation
from app.services.extraction import extract_pdf_text, split_text_into_chunks
from app.services.verifier import crossref_lookup, enough_metadata_for_verified_citation


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
        document = job.document
        if not document:
            job.status = "failed"
            job.last_error = "Document record is missing."
            return

        try:
            job.status = "running"
            job.attempts += 1
            job.locked_at = utc_now()
            document.processing_status = "running"
            log_event(db, job=job, document=document, event_type="started", message="Processing started.")
            db.commit()

            self._extract(db, job, document)
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
            job.status = "failed"
            job.locked_at = None
            job.last_error = str(exc)
            document.processing_status = "failed"
            log_event(db, job=job, document=document, event_type="failed", message=str(exc), level="error")
            db.commit()

    def _extract(self, db: Session, job: ImportJob, document: Document) -> None:
        if job.current_step in {"extracted", "enriched", "indexed", "complete"}:
            return
        local_path = document.metadata_evidence.get("local_cache_path")
        if not local_path or not Path(local_path).exists():
            raise RuntimeError("Local processing cache is missing. Re-upload or restore from GCS.")

        extracted = extract_pdf_text(Path(local_path))
        document.page_count = extracted.page_count
        document.search_text = extracted.full_text
        document.pages.clear()
        for page in extracted.pages:
            db.add(
                DocumentPage(
                    document_id=document.id,
                    page_number=page.page_number,
                    text=page.text,
                    low_text=page.low_text,
                    text_source="pdf" if not page.low_text else "pdf_low_text",
                )
            )
        document.chunks.clear()
        for chunk in split_text_into_chunks(extracted.full_text):
            db.add(TextChunk(document_id=document.id, text=chunk, token_count=max(1, len(chunk) // 4)))
        job.current_step = "extracted"
        log_event(
            db,
            job=job,
            document=document,
            event_type="extracted",
            message=f"Extracted {extracted.page_count} pages.",
            payload={"low_text_pages": [page.page_number for page in extracted.pages if page.low_text]},
        )
        db.commit()

    def _enrich(self, db: Session, job: ImportJob, document: Document) -> None:
        if job.current_step in {"enriched", "indexed", "complete"}:
            return
        ai = get_ai_service()
        metadata = ai.extract_metadata(document.original_filename, document.search_text or "")
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
            },
        }

        crossref = crossref_lookup(document.doi, document.title)
        if crossref:
            document.metadata_evidence["crossref"] = crossref

        citation_metadata = document_metadata(document)
        document.apa_citation = format_apa_citation(citation_metadata)
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
        if job.current_step in {"indexed", "complete"}:
            return
        ai = get_ai_service()
        for chunk in document.chunks[:20]:
            if chunk.embedding is None:
                chunk.embedding = ai.embed(chunk.text)
        document.search_text = "\n\n".join(
            part
            for part in [
                document.title,
                " ".join(a.get("family", "") for a in document.authors or []),
                document.abstract,
                document.rich_summary,
                document.search_text,
                " ".join(tag.name for tag in document.tags),
            ]
            if part
        )
        job.current_step = "indexed"
        log_event(db, job=job, document=document, event_type="indexed", message="Search indexing complete.")
        db.commit()

    def _cleanup_processing_cache(self, db: Session, job: ImportJob, document: Document) -> None:
        evidence = dict(document.metadata_evidence or {})
        cache_path = evidence.get("local_cache_path")
        if not cache_path:
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
            path.unlink()
        evidence.pop("local_cache_path", None)
        evidence["processing_cache"] = {"status": "deleted_after_success"}
        document.metadata_evidence = evidence
        log_event(db, job=job, document=document, event_type="cache_cleaned", message="Temporary processing cache deleted.")
