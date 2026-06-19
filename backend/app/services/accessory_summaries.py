from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Document, DocumentAccessorySummary, utc_now
from app.services.ai import get_ai_service
from app.services.analysis_models import MODEL_ACCESSORY_SUMMARIES, default_model_for_task, normalize_model_id
from app.services.citations import decode_html_entities
from app.services.document_cache import ensure_document_pdf_bytes
from app.services.openai_usage import OpenAIUsageContext
from app.services.preferences import get_analysis_model
from app.services.processing import document_reading_text, log_event
from app.services.search import rebuild_document_search_text


def _normalize_prompt(value: str) -> str:
    prompt = " ".join((value or "").strip().split())
    if not prompt:
        raise ValueError("Accessory summary prompt is required.")
    return prompt[:4000]


def _normalize_title(value: str | None) -> str | None:
    title = " ".join((value or "").strip().split())
    return title[:240] or None


def create_accessory_summary(
    db: Session,
    document: Document,
    *,
    prompt: str,
    model: str | None = None,
    title: str | None = None,
) -> DocumentAccessorySummary:
    default_model = get_analysis_model(db, MODEL_ACCESSORY_SUMMARIES)
    summary = DocumentAccessorySummary(
        document_id=document.id,
        title=_normalize_title(title),
        prompt=_normalize_prompt(prompt),
        model=normalize_model_id(model, default_model),
        status="queued",
        attempts=0,
        evidence={"default_model": default_model},
    )
    db.add(summary)
    db.flush()
    log_event(
        db,
        job=None,
        document=document,
        event_type="accessory_summary_queued",
        message="Accessory summary queued.",
        payload={"accessory_summary_id": summary.id, "model": summary.model},
    )
    return summary


class AccessorySummaryProcessor:
    def process_summary(self, db: Session, summary: DocumentAccessorySummary) -> None:
        document = summary.document
        if not document or document.deleted_at:
            summary.status = "failed"
            summary.last_error = "Document record is missing."
            summary.locked_at = None
            return

        try:
            summary.status = "running"
            summary.attempts += 1
            summary.locked_at = utc_now()
            summary.last_error = None
            log_event(
                db,
                job=None,
                document=document,
                event_type="accessory_summary_started",
                message="Accessory summary started.",
                payload={"accessory_summary_id": summary.id, "model": summary.model},
            )
            db.commit()

            pdf_bytes = self._document_pdf_bytes(db, document)
            text = document_reading_text(document) or document.search_text or ""
            result = get_ai_service().generate_accessory_summary(
                document.original_filename,
                text,
                summary.prompt,
                model=summary.model or default_model_for_task(MODEL_ACCESSORY_SUMMARIES),
                pdf_bytes=pdf_bytes,
                usage_context=OpenAIUsageContext(
                    document_id=document.id,
                    source="accessory_summary",
                    capability_key=MODEL_ACCESSORY_SUMMARIES,
                ),
                prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:accessory:{summary.id}",
            )
            body = (decode_html_entities(result.get("summary")) or "").strip()
            if not body:
                raise RuntimeError("Accessory summary returned no body.")
            summary.summary = body
            if not summary.title:
                summary.title = _normalize_title(result.get("title"))
            summary.status = "complete"
            summary.completed_at = utc_now()
            summary.locked_at = None
            summary.evidence = {
                "confidence": result.get("confidence"),
                "needs_review_reasons": result.get("needs_review_reasons") or [],
                **(result.get("_openai") or {}),
            }
            document.search_text = rebuild_document_search_text(document)
            log_event(
                db,
                job=None,
                document=document,
                event_type="accessory_summary_complete",
                message="Accessory summary complete.",
                payload={"accessory_summary_id": summary.id, "model": summary.model},
            )
            db.commit()
        except Exception as exc:
            summary.status = "failed"
            summary.locked_at = None
            summary.last_error = str(exc)
            summary.evidence = {**(summary.evidence or {}), "error": str(exc)}
            log_event(
                db,
                job=None,
                document=document,
                event_type="accessory_summary_failed",
                message=str(exc),
                level="error",
                payload={"accessory_summary_id": summary.id, "model": summary.model},
            )
            db.commit()

    def _document_pdf_bytes(self, db: Session, document: Document) -> bytes | None:
        try:
            return ensure_document_pdf_bytes(db, document, source="accessory_summary")
        except Exception:
            return None
