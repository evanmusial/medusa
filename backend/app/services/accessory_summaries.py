from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentAccessorySummary, DocumentRecommendation, utc_now
from app.services.ai import get_ai_service
from app.services.analysis_models import MODEL_ACCESSORY_SUMMARIES, default_model_for_task, normalize_model_id
from app.services.citations import decode_html_entities
from app.services.document_cache import ensure_document_pdf_bytes
from app.services.openai_usage import OpenAIUsageContext
from app.services.preferences import get_analysis_model
from app.services.processing import document_reading_text, log_event
from app.services.recommendations import (
    document_has_recommendation_inputs,
    doi_url,
    list_document_recommendations,
    normalize_doi,
    refresh_document_recommendations,
)
from app.services.search import rebuild_document_search_text


SOURCE_FINDER_ACTION_TERMS = {
    "find",
    "locate",
    "recommend",
    "suggest",
    "identify",
    "show",
    "give",
    "list",
}
SOURCE_FINDER_OBJECT_TERMS = {
    "article",
    "articles",
    "citation",
    "citations",
    "literature",
    "paper",
    "papers",
    "reading",
    "reference",
    "references",
    "source",
    "sources",
    "study",
    "studies",
}
SOURCE_FINDER_PHRASES = {
    "more sources",
    "more papers",
    "papers like",
    "sources like",
    "similar papers",
    "similar sources",
    "related papers",
    "related sources",
    "recent papers",
    "recent sources",
    "newer papers",
    "newer sources",
    "reading list",
    "continued reading",
}
SOURCE_FINDER_REFRESH_TERMS = {"recent", "more recent", "newer", "latest", "current", "new"}
SOURCE_FINDER_STOPWORDS = {
    "about",
    "also",
    "analysis",
    "especially",
    "find",
    "from",
    "give",
    "identify",
    "like",
    "list",
    "locate",
    "more",
    "paper",
    "papers",
    "recent",
    "recommend",
    "research",
    "show",
    "similar",
    "source",
    "sources",
    "study",
    "studies",
    "suggest",
    "that",
    "this",
    "with",
}


def _normalize_prompt(value: str) -> str:
    prompt = " ".join((value or "").strip().split())
    if not prompt:
        raise ValueError("Inquest question is required.")
    return prompt[:4000]


def _normalize_title(value: str | None) -> str | None:
    title = " ".join((value or "").strip().split())
    return title[:240] or None


def _is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in message or "deadline" in message


def _normalized_terms(value: str | None) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()


def _is_source_finder_prompt(prompt: str) -> bool:
    text = " ".join(_normalized_terms(prompt))
    if not text:
        return False
    if any(phrase in text for phrase in SOURCE_FINDER_PHRASES):
        return True
    terms = set(text.split())
    return bool(terms & SOURCE_FINDER_ACTION_TERMS and terms & SOURCE_FINDER_OBJECT_TERMS)


def _source_finder_needs_refresh(prompt: str) -> bool:
    text = " ".join(_normalized_terms(prompt))
    return any(term in text for term in SOURCE_FINDER_REFRESH_TERMS)


def _source_finder_prompt_terms(prompt: str) -> set[str]:
    return {
        term
        for term in _normalized_terms(prompt)
        if len(term) >= 4 and term not in SOURCE_FINDER_STOPWORDS and not term.isdigit()
    }


def _recommendation_text(row: DocumentRecommendation) -> str:
    chips = " ".join(row.reason_chips or [])
    return " ".join(
        part
        for part in [
            row.title,
            row.description,
            row.journal,
            row.source_relation,
            row.source_provider,
            row.relation_family,
            chips,
        ]
        if part
    )


def _recommendation_rank(document: Document, prompt: str, row: DocumentRecommendation, prompt_terms: set[str]) -> float:
    try:
        score = float(row.score or 0)
    except (TypeError, ValueError):
        score = 0.0
    text_terms = set(_normalized_terms(_recommendation_text(row)))
    matched_terms = prompt_terms & text_terms
    score += min(1.2, len(matched_terms) * 0.18)
    if row.has_pdf:
        score += 0.16
    if normalize_doi(row.doi):
        score += 0.12
    if row.source_url:
        score += 0.08
    if row.known_status == "new":
        score += 0.1

    prompt_text = " ".join(_normalized_terms(prompt))
    if any(term in prompt_text for term in SOURCE_FINDER_REFRESH_TERMS):
        if document.publication_year and row.publication_year and row.publication_year > document.publication_year:
            score += min(1.0, (row.publication_year - document.publication_year) * 0.08)
        elif row.relation_family == "newer":
            score += 0.35
    if any(term in prompt_text for term in ["behavioral", "behavioural", "profile", "actor", "actors", "psychosocial"]):
        if row.relation_family == "methods":
            score += 0.25
        if matched_terms:
            score += 0.25
    return score


def _rank_source_finder_rows(
    document: Document,
    prompt: str,
    rows: list[DocumentRecommendation],
    *,
    limit: int = 12,
) -> list[DocumentRecommendation]:
    prompt_terms = _source_finder_prompt_terms(prompt)
    candidates = [row for row in rows if row.status != "stale" and row.title]
    ranked = sorted(
        candidates,
        key=lambda row: (
            -_recommendation_rank(document, prompt, row, prompt_terms),
            -(row.publication_year or 0),
            row.title.lower(),
        ),
    )
    return ranked[:limit]


def _format_recommendation_authors(authors: list[dict[str, Any]] | None) -> str | None:
    names: list[str] = []
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        if author.get("family") and author.get("given"):
            names.append(f"{author['family']}, {str(author['given']).strip()[:1]}.")
        elif author.get("family") or author.get("name") or author.get("full_name"):
            names.append(str(author.get("family") or author.get("name") or author.get("full_name")))
    if not names:
        return None
    if len(names) <= 3:
        return ", ".join(names)
    return f"{', '.join(names[:3])}, et al."


def _format_recommendation_links(row: DocumentRecommendation) -> str:
    links: list[str] = []
    doi_link = doi_url(row.doi)
    if doi_link:
        links.append(f"[DOI]({doi_link})")
    if row.source_url and row.source_url != doi_link:
        links.append(f"[source]({row.source_url})")
    if row.pdf_url:
        links.append(f"[open PDF]({row.pdf_url})")
    return "; ".join(links)


def _source_fit_reason(row: DocumentRecommendation, prompt_terms: set[str]) -> str:
    matched = sorted((prompt_terms & set(_normalized_terms(_recommendation_text(row)))) - SOURCE_FINDER_STOPWORDS)
    chips = [chip for chip in row.reason_chips if chip]
    reasons: list[str] = []
    if row.relation_family:
        reasons.append(row.relation_family.replace("_", " "))
    if matched:
        reasons.append("matches " + ", ".join(matched[:4]))
    for chip in chips:
        if chip.lower() not in {reason.lower() for reason in reasons}:
            reasons.append(chip)
        if len(reasons) >= 4:
            break
    return "; ".join(reasons) if reasons else "related recommendation evidence"


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
        message="Inquest queued.",
        payload={"accessory_summary_id": summary.id, "model": summary.model},
    )
    return summary


class AccessorySummaryProcessor:
    def process_summary(
        self,
        db: Session,
        summary: DocumentAccessorySummary,
        *,
        timeout_seconds: float | None = None,
        defer_timeouts: bool = False,
    ) -> None:
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
                message="Inquest started.",
                payload={"accessory_summary_id": summary.id, "model": summary.model},
            )
            db.commit()

            result = self._generate_summary(db, document, summary, timeout_seconds=timeout_seconds)
            self._complete_summary(db, document, summary, result)
            log_event(
                db,
                job=None,
                document=document,
                event_type="accessory_summary_complete",
                message="Inquest complete.",
                payload={"accessory_summary_id": summary.id, "model": summary.model},
            )
            db.commit()
        except Exception as exc:
            if defer_timeouts and _is_timeout_error(exc):
                summary.status = "queued"
                summary.locked_at = None
                summary.last_error = None
                summary.evidence = {
                    **(summary.evidence or {}),
                    "inline_deferred": True,
                    "inline_deferred_at": utc_now().isoformat(),
                    "inline_timeout_seconds": timeout_seconds,
                    "inline_defer_reason": str(exc),
                }
                log_event(
                    db,
                    job=None,
                    document=document,
                    event_type="accessory_summary_deferred",
                    message="Inquest deferred to worker after inline timeout.",
                    payload={"accessory_summary_id": summary.id, "model": summary.model},
                )
                db.commit()
                return
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

    def _generate_summary(
        self,
        db: Session,
        document: Document,
        summary: DocumentAccessorySummary,
        *,
        timeout_seconds: float | None = None,
    ) -> dict:
        if _is_source_finder_prompt(summary.prompt):
            return self._generate_source_finder_summary(db, document, summary, timeout_seconds=timeout_seconds)

        pdf_bytes = self._document_pdf_bytes(db, document)
        text = document_reading_text(document) or document.search_text or ""
        return get_ai_service().generate_accessory_summary(
            document.original_filename,
            text,
            summary.prompt,
            model=summary.model or default_model_for_task(MODEL_ACCESSORY_SUMMARIES),
            pdf_bytes=pdf_bytes,
            timeout_seconds=timeout_seconds,
            usage_context=OpenAIUsageContext(
                document_id=document.id,
                source="accessory_summary",
                capability_key=MODEL_ACCESSORY_SUMMARIES,
            ),
            prompt_cache_key=f"medusa-doc:{document.checksum_sha256}:accessory:{summary.id}",
        )

    def _generate_source_finder_summary(
        self,
        db: Session,
        document: Document,
        summary: DocumentAccessorySummary,
        *,
        timeout_seconds: float | None = None,
    ) -> dict:
        cached_rows = list_document_recommendations(db, document, view="discover")
        if timeout_seconds is not None and (_source_finder_needs_refresh(summary.prompt) or not cached_rows):
            raise TimeoutError("Source-finding Inquest deferred so related-paper discovery can refresh.")

        refreshed = False
        if timeout_seconds is None and document_has_recommendation_inputs(document):
            refresh_document_recommendations(db, document, limit=20)
            refreshed = True

        rows = list_document_recommendations(db, document, view="discover")
        if not rows:
            rows = list_document_recommendations(db, document, view="all")
        selected = _rank_source_finder_rows(document, summary.prompt, rows)
        prompt_terms = _source_finder_prompt_terms(summary.prompt)
        if not selected:
            reason = (
                "Medusa could not find recommendation candidates for this document. The document may need a title, "
                "DOI, extracted bibliography, summary, tags, or domains before related-paper discovery can produce "
                "source leads."
            )
            if document.processing_status != "ready":
                reason = "Medusa can find related sources after this document finishes processing."
            return {
                "title": "Source leads",
                "summary": reason,
                "confidence": 0.25,
                "needs_review_reasons": ["No recommendation candidates were available."],
                "_source_finder": {
                    "refreshed_recommendations": refreshed,
                    "recommendation_ids": [],
                    "recommendation_count": 0,
                },
            }

        lines = [
            "I found these source leads from Medusa's related-paper discovery instead of inferring a reading list from the document text alone.",
            "",
        ]
        for index, row in enumerate(selected, start=1):
            authors = _format_recommendation_authors(row.authors)
            metadata = " / ".join(str(part) for part in [authors, row.publication_year, row.journal] if part)
            prefix = f"{index}. **{row.title.strip()}**"
            line = f"{prefix} ({metadata})." if metadata else f"{prefix}."
            links = _format_recommendation_links(row)
            if links:
                line = f"{line} {links}."
            line = f"{line} Fit: {_source_fit_reason(row, prompt_terms)}."
            lines.append(line)
        if refreshed:
            lines.append("")
            lines.append("The list was refreshed from the configured recommendation providers and local bibliography/context evidence.")
        return {
            "title": "Source leads",
            "summary": "\n".join(lines),
            "confidence": 0.78,
            "needs_review_reasons": [],
            "_source_finder": {
                "refreshed_recommendations": refreshed,
                "recommendation_ids": [row.id for row in selected],
                "recommendation_count": len(selected),
            },
        }

    def _complete_summary(
        self,
        db: Session,
        document: Document,
        summary: DocumentAccessorySummary,
        result: dict,
    ) -> None:
        body = (decode_html_entities(result.get("summary")) or "").strip()
        if not body:
            raise RuntimeError("Inquest returned no answer.")
        summary.summary = body
        if not summary.title:
            summary.title = _normalize_title(result.get("title"))
        summary.status = "complete"
        summary.completed_at = utc_now()
        summary.locked_at = None
        prior_evidence = {key: value for key, value in (summary.evidence or {}).items() if key != "error"}
        summary.evidence = {
            **prior_evidence,
            "confidence": result.get("confidence"),
            "needs_review_reasons": result.get("needs_review_reasons") or [],
            **(result.get("_openai") or {}),
        }
        if result.get("_source_finder"):
            summary.evidence["source_finder"] = result["_source_finder"]
        document.search_text = rebuild_document_search_text(document)
