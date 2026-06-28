from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    Document,
    Domain,
    PortfolioItem,
    ProjectItem,
    ReconAnswerVersion,
    ReconEvidence,
    ReconInquiry,
    ReconRun,
    SavedSearch,
    Tag,
    TextChunk,
    utc_now,
)
from app.services.ai import get_ai_service
from app.services.analysis_models import MODEL_RECON_INQUIRY, MODEL_TEXT_CHUNK_ENCODING, default_model_for_task, normalize_model_id
from app.services.document_visibility import filter_library_visible_documents
from app.services.openai_usage import OpenAIUsageContext
from app.services.preferences import get_analysis_model
from app.services.search import document_search_condition_and_rank


RECON_MODES = {"source_finder", "quick_answer", "broad_sweep", "exhaustive"}
RECON_SCOPE_TYPES = {"library", "documents", "domain", "project", "saved_search", "portfolio"}
MODE_EVIDENCE_LIMITS = {
    "source_finder": 16,
    "quick_answer": 18,
    "broad_sweep": 24,
    "exhaustive": 32,
}
MODE_MAX_PER_DOCUMENT = {
    "source_finder": 2,
    "quick_answer": 3,
    "broad_sweep": 2,
    "exhaustive": 4,
}
TOKEN_COST_PER_MILLION_FALLBACK = 5.0
QUESTION_TERM_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9-]{2,}")


@dataclass(frozen=True)
class ReconEvidenceCandidate:
    document: Document
    snippet: str
    score: float
    evidence_kind: str = "chunk"
    text_chunk: TextChunk | None = None
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] | None = None


def normalize_recon_mode(value: str | None) -> str:
    normalized = (value or "quick_answer").strip().lower().replace("-", "_")
    return normalized if normalized in RECON_MODES else "quick_answer"


def normalize_recon_scope_type(value: str | None) -> str:
    normalized = (value or "library").strip().lower().replace("-", "_")
    return normalized if normalized in RECON_SCOPE_TYPES else "library"


def normalize_recon_question(value: str | None) -> str:
    question = " ".join((value or "").strip().split())
    if not question:
        raise ValueError("Recon question is required.")
    return question[:6000]


def normalize_recon_title(title: str | None, question: str) -> str:
    candidate = " ".join((title or "").strip().split())
    if candidate:
        return candidate[:300]
    words = question.split()
    return " ".join(words[:12])[:300] or "Recon inquiry"


def question_terms(question: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in QUESTION_TERM_RE.findall(question.lower()):
        term = raw.strip("-")
        if len(term) < 3 or term in seen or term in {"about", "that", "with", "from", "this", "have", "show", "need", "source", "paper", "papers"}:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= 32:
            break
    return terms


def document_recon_text(document: Document, *, max_chars: int = 120_000) -> str:
    page_text = "\n\n".join(page.normalized_text or page.text or "" for page in sorted(document.pages, key=lambda item: item.page_number))
    chunk_text = "\n\n".join(chunk.text for chunk in sorted(document.chunks, key=lambda item: (item.page_start or 0, item.id))[:40])
    parts = [
        document.title,
        document.abstract,
        document.rich_summary,
        document.bibliography,
        document.apa_citation,
        document.search_text,
        page_text or chunk_text,
    ]
    return "\n\n".join(part for part in parts if part)[:max_chars]


def _base_document_query(db: Session, scope_type: str):
    query = db.query(Document).options(
        selectinload(Document.chunks),
        selectinload(Document.pages),
        selectinload(Document.tags),
        selectinload(Document.domains),
    )
    if scope_type == "portfolio":
        return query.filter(Document.deleted_at.is_(None))
    return filter_library_visible_documents(query)


def _scope_ids(scope: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = scope.get(key)
        if isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
        elif isinstance(raw, list):
            for item in raw:
                if item is None:
                    continue
                value = str(item).strip()
                if value:
                    values.append(value)
    return list(dict.fromkeys(values))


def _apply_saved_search_filters(query, filters: dict[str, Any]):
    tag_ids = _scope_ids(filters, "tag_id", "tag_ids", "tags")
    if tag_ids:
        query = query.filter(Document.tags.any(Tag.id.in_(tag_ids)))
    domain_ids = _scope_ids(filters, "domain_id", "domain_ids", "domains")
    if domain_ids:
        query = query.filter(Document.domains.any(Domain.id.in_(domain_ids)))
    priority = filters.get("priority")
    if isinstance(priority, str) and priority:
        query = query.filter(Document.priority == priority)
    read_status = filters.get("read_status")
    if isinstance(read_status, str) and read_status:
        query = query.filter(Document.read_status == read_status)
    citation_status = filters.get("citation_status")
    if isinstance(citation_status, str) and citation_status:
        query = query.filter(Document.citation_status == citation_status)
    return query


def resolve_recon_documents(db: Session, *, scope_type: str, scope: dict[str, Any] | None = None) -> list[Document]:
    scope = scope or {}
    scope_type = normalize_recon_scope_type(scope_type)
    query = _base_document_query(db, scope_type)

    if scope_type == "documents":
        document_ids = _scope_ids(scope, "document_id", "document_ids", "selected_document_ids")
        if not document_ids:
            return []
        query = query.filter(Document.id.in_(document_ids))
    elif scope_type == "domain":
        domain_ids = _scope_ids(scope, "domain_id", "domain_ids")
        if not domain_ids:
            return []
        query = query.filter(Document.domains.any(Domain.id.in_(domain_ids)))
    elif scope_type == "project":
        project_ids = _scope_ids(scope, "project_id", "project_ids")
        if not project_ids:
            return []
        document_ids = [
            row[0]
            for row in db.query(ProjectItem.document_id)
            .filter(ProjectItem.project_id.in_(project_ids))
            .distinct()
            .all()
        ]
        if not document_ids:
            return []
        query = query.filter(Document.id.in_(document_ids))
    elif scope_type == "saved_search":
        saved_search_id = scope.get("saved_search_id") or scope.get("id")
        saved_search = db.get(SavedSearch, str(saved_search_id)) if saved_search_id else None
        if not saved_search or saved_search.deleted_at:
            return []
        query = _apply_saved_search_filters(query, saved_search.filters or {})
        if saved_search.query:
            condition, rank = document_search_condition_and_rank(db, saved_search.query)
            if condition is not None:
                query = query.filter(condition)
                if rank is not None:
                    query = query.order_by(rank.desc())
    elif scope_type == "portfolio":
        portfolio_item_ids = _scope_ids(scope, "portfolio_item_id", "portfolio_item_ids")
        if not portfolio_item_ids:
            return []
        item = (
            db.query(PortfolioItem)
            .options(
                joinedload(PortfolioItem.current_version),
                selectinload(PortfolioItem.versions),
                selectinload(PortfolioItem.materials),
            )
            .filter(PortfolioItem.id.in_(portfolio_item_ids), PortfolioItem.deleted_at.is_(None))
            .all()
        )
        document_ids: list[str] = []
        for portfolio_item in item:
            document_ids.extend(version.document_id for version in portfolio_item.versions)
            document_ids.extend(material.document_id for material in portfolio_item.materials if not material.deleted_at)
        if not document_ids:
            return []
        query = query.filter(Document.id.in_(list(dict.fromkeys(document_ids))))

    return query.order_by(Document.updated_at.desc(), Document.title).all()


def _lexical_score(text_value: str, terms: list[str]) -> float:
    if not text_value or not terms:
        return 0.0
    haystack = text_value.lower()
    score = 0.0
    for term in terms:
        count = haystack.count(term)
        if count:
            score += 1.0 + math.log(count + 1, 2)
    return score


def _best_snippet(text_value: str, terms: list[str], *, max_chars: int = 950) -> str:
    normalized = " ".join((text_value or "").split())
    if len(normalized) <= max_chars:
        return normalized
    lower = normalized.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - max_chars // 4)
    end = min(len(normalized), start + max_chars)
    snippet = normalized[start:end].strip()
    if start > 0:
        snippet = f"... {snippet}"
    if end < len(normalized):
        snippet = f"{snippet} ..."
    return snippet


def _document_metadata_score(document: Document, terms: list[str]) -> float:
    metadata_text = " ".join(
        part
        for part in [
            document.title,
            document.abstract,
            document.rich_summary,
            document.bibliography,
            document.apa_citation,
            " ".join(tag.name for tag in document.tags),
            " ".join(domain.name for domain in document.domains),
        ]
        if part
    )
    score = _lexical_score(metadata_text, terms) * 1.35
    if document.doi:
        score += 0.4
    if document.citation_status == "verified":
        score += 0.25
    return score


def _embedding_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8g}" for value in embedding) + "]"


def _semantic_chunk_scores(db: Session, question: str, document_ids: list[str], *, limit: int) -> tuple[dict[str, float], dict[str, Any]]:
    metadata: dict[str, Any] = {"semantic_attempted": False, "semantic_available": False}
    if not document_ids or not db.bind or db.bind.dialect.name != "postgresql":
        return {}, metadata
    try:
        embedding = get_ai_service().embed(
            question,
            model=get_analysis_model(db, MODEL_TEXT_CHUNK_ENCODING),
            usage_context=OpenAIUsageContext(source="recon", capability_key=MODEL_TEXT_CHUNK_ENCODING),
        )
    except Exception as exc:
        metadata.update({"semantic_attempted": True, "semantic_error": str(exc)[:300]})
        return {}, metadata
    if not embedding:
        metadata.update({"semantic_attempted": True})
        return {}, metadata
    statement = text(
        """
        SELECT id, 1 - (embedding <=> CAST(:embedding AS vector)) AS vector_score
        FROM text_chunks
        WHERE document_id IN :document_ids
          AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
        """
    ).bindparams(bindparam("document_ids", expanding=True))
    try:
        with db.begin_nested():
            rows = list(
                db.execute(
                    statement,
                    {
                        "document_ids": document_ids,
                        "embedding": _embedding_literal(embedding),
                        "limit": limit,
                    },
                ).mappings()
            )
    except Exception as exc:
        metadata.update({"semantic_attempted": True, "semantic_error": str(exc)[:300]})
        return {}, metadata
    scores = {str(row["id"]): float(row["vector_score"] or 0.0) for row in rows}
    metadata.update({"semantic_attempted": True, "semantic_available": bool(scores), "semantic_score_count": len(scores)})
    return scores, metadata


def retrieve_recon_evidence(
    db: Session,
    *,
    question: str,
    scope_type: str = "library",
    scope: dict[str, Any] | None = None,
    mode: str = "quick_answer",
    exclude_document_ids: set[str] | None = None,
) -> tuple[list[ReconEvidenceCandidate], list[Document]]:
    mode = normalize_recon_mode(mode)
    terms = question_terms(question)
    documents = [
        document
        for document in resolve_recon_documents(db, scope_type=scope_type, scope=scope)
        if document.id not in (exclude_document_ids or set())
    ]
    if not documents:
        return [], []

    semantic_scores, semantic_metadata = _semantic_chunk_scores(
        db,
        question,
        [document.id for document in documents],
        limit=max(MODE_EVIDENCE_LIMITS[mode] * 8, 48),
    )
    candidates: list[ReconEvidenceCandidate] = []
    for document in documents:
        metadata_score = _document_metadata_score(document, terms)
        chunks = sorted(document.chunks, key=lambda chunk: (chunk.page_start or 0, chunk.id))
        if chunks:
            for chunk in chunks[:80]:
                vector_score = semantic_scores.get(chunk.id)
                score = metadata_score + _lexical_score(chunk.text, terms)
                if vector_score is not None:
                    score += max(0.0, vector_score) * 4.0
                if score <= 0 and mode not in {"broad_sweep", "exhaustive"}:
                    continue
                candidates.append(
                    ReconEvidenceCandidate(
                        document=document,
                        text_chunk=chunk,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        snippet=_best_snippet(chunk.text, terms),
                        score=round(score, 4),
                        metadata={
                            "score_basis": "hybrid_vector_lexical_chunk_metadata" if vector_score is not None else "lexical_chunk_metadata",
                            "vector_score": round(vector_score, 4) if vector_score is not None else None,
                            **semantic_metadata,
                            "doi": document.doi,
                            "citation_status": document.citation_status,
                        },
                    )
                )
        else:
            text_value = document_recon_text(document, max_chars=40_000)
            score = metadata_score + _lexical_score(text_value, terms)
            if score > 0 or mode in {"broad_sweep", "exhaustive"}:
                candidates.append(
                    ReconEvidenceCandidate(
                        document=document,
                        snippet=_best_snippet(text_value, terms),
                        score=round(score, 4),
                        evidence_kind="document",
                        metadata={
                            "score_basis": "lexical_document_metadata",
                            "doi": document.doi,
                            "citation_status": document.citation_status,
                        },
                    )
                )

    if not candidates:
        fallback_documents = sorted(
            documents,
            key=lambda document: (_document_metadata_score(document, terms), document.updated_at),
            reverse=True,
        )[: MODE_EVIDENCE_LIMITS[mode]]
        for document in fallback_documents:
            text_value = document_recon_text(document, max_chars=40_000)
            candidates.append(
                ReconEvidenceCandidate(
                    document=document,
                    snippet=_best_snippet(text_value, terms),
                    score=round(_document_metadata_score(document, terms), 4),
                    evidence_kind="document",
                    metadata={"score_basis": "fallback_document_metadata"},
                )
            )

    per_document: dict[str, int] = {}
    ranked: list[ReconEvidenceCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.score, item.document.updated_at), reverse=True):
        count = per_document.get(candidate.document.id, 0)
        if count >= MODE_MAX_PER_DOCUMENT[mode]:
            continue
        per_document[candidate.document.id] = count + 1
        ranked.append(candidate)
        if len(ranked) >= MODE_EVIDENCE_LIMITS[mode]:
            break
    return ranked, documents


def estimate_recon_run(
    db: Session,
    *,
    question: str,
    scope_type: str,
    scope: dict[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    mode = normalize_recon_mode(mode)
    documents = resolve_recon_documents(db, scope_type=scope_type, scope=scope)
    token_sum = sum(sum(chunk.token_count or max(1, len(chunk.text) // 4) for chunk in document.chunks[:80]) for document in documents)
    if mode == "source_finder":
        estimated_tokens = 2500 + min(token_sum, 6000)
    elif mode == "quick_answer":
        estimated_tokens = 3500 + min(token_sum, 16000)
    elif mode == "broad_sweep":
        estimated_tokens = 4000 + max(len(documents) * 500, min(token_sum, 80_000))
    else:
        estimated_tokens = 5000 + max(token_sum, len(documents) * 1000)
    warnings: list[str] = []
    if not documents:
        warnings.append("Scope resolves to no documents.")
    if mode in {"broad_sweep", "exhaustive"}:
        warnings.append("This V1 run records a retrieval-backed answer; deeper per-document worker passes are planned.")
    return {
        "mode": mode,
        "scope_type": normalize_recon_scope_type(scope_type),
        "resolved_document_count": len(documents),
        "estimated_evidence_count": min(MODE_EVIDENCE_LIMITS[mode], max(0, len(documents) * MODE_MAX_PER_DOCUMENT[mode])),
        "estimated_input_tokens": estimated_tokens,
        "estimated_cost_usd": round((estimated_tokens / 1_000_000) * TOKEN_COST_PER_MILLION_FALLBACK, 4),
        "warnings": warnings,
    }


def create_recon_inquiry(
    db: Session,
    *,
    title: str | None,
    question: str,
    instructions: str | None = None,
    scope_type: str = "library",
    scope: dict[str, Any] | None = None,
    default_mode: str = "quick_answer",
    model: str | None = None,
) -> ReconInquiry:
    normalized_question = normalize_recon_question(question)
    default_model = get_analysis_model(db, MODEL_RECON_INQUIRY)
    inquiry = ReconInquiry(
        title=normalize_recon_title(title, normalized_question),
        question=normalized_question,
        instructions=(instructions or "").strip()[:6000] or None,
        scope_type=normalize_recon_scope_type(scope_type),
        scope=scope or {},
        default_mode=normalize_recon_mode(default_mode),
        model=normalize_model_id(model, default_model) if model else default_model,
        status="draft",
        inquiry_metadata={"default_model": default_model},
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return inquiry


def update_recon_inquiry(db: Session, inquiry: ReconInquiry, updates: dict[str, Any]) -> ReconInquiry:
    if "question" in updates and updates["question"] is not None:
        inquiry.question = normalize_recon_question(updates["question"])
    if "title" in updates and updates["title"] is not None:
        inquiry.title = normalize_recon_title(updates["title"], inquiry.question)
    if "instructions" in updates:
        inquiry.instructions = (updates.get("instructions") or "").strip()[:6000] or None
    if "scope_type" in updates and updates["scope_type"] is not None:
        inquiry.scope_type = normalize_recon_scope_type(updates["scope_type"])
    if "scope" in updates and updates["scope"] is not None:
        inquiry.scope = updates["scope"] or {}
    if "default_mode" in updates and updates["default_mode"] is not None:
        inquiry.default_mode = normalize_recon_mode(updates["default_mode"])
    if "model" in updates and updates["model"] is not None:
        inquiry.model = normalize_model_id(updates["model"], get_analysis_model(db, MODEL_RECON_INQUIRY))
    if "status" in updates and updates["status"] is not None:
        status = str(updates["status"]).strip().lower()[:40]
        if status:
            inquiry.status = status
    db.commit()
    db.refresh(inquiry)
    return inquiry


def _evidence_payload(rank: int, evidence: ReconEvidenceCandidate) -> dict[str, Any]:
    label = f"R{rank}"
    document = evidence.document
    citation = document.apa_citation or document.title
    return {
        "label": label,
        "document_id": document.id,
        "title": document.title,
        "citation": citation,
        "doi": document.doi,
        "page_start": evidence.page_start,
        "page_end": evidence.page_end,
        "score": evidence.score,
        "snippet": evidence.snippet,
    }


def _local_source_answer(question: str, evidence_rows: list[ReconEvidence]) -> tuple[str, list[str], float]:
    if not evidence_rows:
        return (
            "No Library evidence matched this Recon inquiry. Broaden the scope or run a broader sweep after more documents are indexed.",
            ["No matching evidence was retrieved."],
            0.2,
        )
    lines = [
        "Recon searched the selected corpus and ranked the strongest retrieved evidence. It did not read every scoped document in full."
    ]
    for index, evidence in enumerate(evidence_rows[:10], start=1):
        page_bits = []
        if evidence.page_start:
            page_bits.append(f"p. {evidence.page_start}" if evidence.page_start == evidence.page_end else f"pp. {evidence.page_start}-{evidence.page_end}")
        page = f" ({', '.join(page_bits)})" if page_bits else ""
        lines.append(f"[R{index}] {evidence.document_title or 'Untitled document'}{page}: {evidence.snippet}")
    return "\n\n".join(lines), ["This is a retrieval-backed source-finding answer, not a full-document sweep."], 0.72


def _fallback_synthesis(question: str, evidence_rows: list[ReconEvidence], *, mode: str) -> tuple[str, list[str], float]:
    answer, limitations, confidence = _local_source_answer(question, evidence_rows)
    if mode != "source_finder":
        answer = (
            f"Question: {question}\n\n"
            f"{answer}\n\n"
            "Synthesis note: The strongest retrieved evidence should be treated as source support candidates. "
            "Use Broad Sweep or Exhaustive when negative coverage or full-document review matters."
        )
        limitations = [*limitations, "AI synthesis was unavailable, so Medusa returned a local evidence summary."]
        confidence = min(confidence, 0.62)
    return answer, limitations, confidence


def run_recon_inquiry(
    db: Session,
    inquiry: ReconInquiry,
    *,
    mode: str | None = None,
    model: str | None = None,
) -> ReconRun:
    selected_mode = normalize_recon_mode(mode or inquiry.default_mode)
    selected_model = normalize_model_id(model, inquiry.model or default_model_for_task(MODEL_RECON_INQUIRY))
    estimate = estimate_recon_run(
        db,
        question=inquiry.question,
        scope_type=inquiry.scope_type,
        scope=inquiry.scope,
        mode=selected_mode,
    )
    run = ReconRun(
        inquiry_id=inquiry.id,
        mode=selected_mode,
        model=selected_model,
        status="running",
        progress=5,
        estimated_input_tokens=estimate["estimated_input_tokens"],
        estimated_cost_usd=estimate["estimated_cost_usd"],
        scope_snapshot={
            "scope_type": inquiry.scope_type,
            "scope": inquiry.scope,
            "question": inquiry.question,
            "instructions": inquiry.instructions,
        },
        run_metadata={"estimate": estimate},
        started_at=utc_now(),
    )
    db.add(run)
    inquiry.status = "running"
    db.commit()
    db.refresh(run)

    try:
        candidates, documents = retrieve_recon_evidence(
            db,
            question=inquiry.question,
            scope_type=inquiry.scope_type,
            scope=inquiry.scope,
            mode=selected_mode,
        )
        run.resolved_document_count = len(documents)
        run.progress = 45
        db.flush()
        evidence_rows: list[ReconEvidence] = []
        for index, candidate in enumerate(candidates, start=1):
            row = ReconEvidence(
                run_id=run.id,
                document_id=candidate.document.id,
                text_chunk_id=candidate.text_chunk.id if candidate.text_chunk else None,
                page_start=candidate.page_start,
                page_end=candidate.page_end,
                evidence_kind=candidate.evidence_kind,
                rank=index,
                score=candidate.score,
                document_title=candidate.document.title,
                snippet=candidate.snippet,
                citation_text=candidate.document.apa_citation,
                relevance_label="supporting" if candidate.score > 0 else "low_signal",
                evidence_metadata={**(candidate.metadata or {}), "label": f"R{index}"},
            )
            db.add(row)
            evidence_rows.append(row)
        run.evidence_count = len(evidence_rows)
        run.progress = 70
        db.flush()

        answer: str
        limitations: list[str]
        confidence: float
        answer_metadata: dict[str, Any] = {"method": "local_evidence_summary"}
        if selected_mode == "source_finder":
            answer, limitations, confidence = _local_source_answer(inquiry.question, evidence_rows)
        elif not evidence_rows:
            answer, limitations, confidence = _fallback_synthesis(inquiry.question, evidence_rows, mode=selected_mode)
            answer_metadata = {"method": "local_no_evidence"}
        else:
            try:
                result = get_ai_service().generate_recon_answer(
                    inquiry.question,
                    [_evidence_payload(index, candidate) for index, candidate in enumerate(candidates, start=1)],
                    instructions=inquiry.instructions,
                    mode=selected_mode,
                    model=selected_model,
                    usage_context=OpenAIUsageContext(source="recon", capability_key=MODEL_RECON_INQUIRY),
                )
                answer = str(result.get("answer") or "").strip()
                if not answer:
                    raise RuntimeError("Recon synthesis returned no answer.")
                limitations = [str(item) for item in result.get("limitations") or [] if str(item).strip()]
                confidence = float(result.get("confidence") or 0.72)
                answer_metadata = {"method": "ai_synthesis", **(result.get("_openai") or {})}
                if selected_mode in {"broad_sweep", "exhaustive"}:
                    limitations.append("This V1 run uses retrieval-backed synthesis; deeper per-document passes are planned.")
            except Exception as exc:
                answer, limitations, confidence = _fallback_synthesis(inquiry.question, evidence_rows, mode=selected_mode)
                answer_metadata = {"method": "local_fallback", "fallback_reason": str(exc)}

        answer_version = ReconAnswerVersion(
            run_id=run.id,
            answer=answer,
            confidence=confidence,
            limitations=limitations,
            answer_metadata=answer_metadata,
        )
        db.add(answer_version)
        run.answer_summary = answer[:600]
        run.status = "complete"
        run.progress = 100
        run.completed_at = utc_now()
        run.run_metadata = {
            **(run.run_metadata or {}),
            "mode_semantics": (
                "source_finder_ranked_sources"
                if selected_mode == "source_finder"
                else "retrieval_synthesis_v1"
            ),
        }
        inquiry.status = "complete"
        db.commit()
    except Exception as exc:
        run.status = "failed"
        run.last_error = str(exc)
        run.completed_at = utc_now()
        inquiry.status = "failed"
        db.commit()
    return (
        db.query(ReconRun)
        .options(selectinload(ReconRun.evidence), selectinload(ReconRun.answers))
        .filter(ReconRun.id == run.id)
        .one()
    )


def cancel_recon_run(db: Session, run: ReconRun) -> ReconRun:
    if run.status in {"queued", "running"}:
        run.status = "cancelled"
        run.progress = 100
        run.cancelled_at = utc_now()
        run.completed_at = run.completed_at or run.cancelled_at
        if run.inquiry:
            run.inquiry.status = "cancelled"
        db.commit()
        db.refresh(run)
    return run
