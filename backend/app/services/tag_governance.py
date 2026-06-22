from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models import Document, DocumentTagAssessment, ImportJob, Tag, TagRelationship
from app.services.document_visibility import document_is_library_visible
from app.services.openai_usage import OpenAIUsageContext
from app.services.tags import (
    TAG_STATUS_BLOCKED,
    TAG_STATUS_CANDIDATE,
    TAG_STATUS_CANONICAL,
    TAG_STATUS_RETIRED,
    get_or_create_tag,
    normalize_tag_name,
    resolve_tag_alias,
)


TAG_IMPORT_MAX_ATTACHMENTS = 5
TAG_IMPORT_MAX_NEW_CANDIDATES = 1
TAG_IMPORT_EXISTING_RELEVANCE_THRESHOLD = 0.42
TAG_IMPORT_EXISTING_OVERALL_THRESHOLD = 0.50
TAG_IMPORT_CLOSE_MATCH_REUSE_THRESHOLD = 0.68
TAG_IMPORT_NEAR_EXISTING_BLOCK_THRESHOLD = 0.56
TAG_IMPORT_NEW_RELEVANCE_THRESHOLD = 0.62
TAG_IMPORT_NOVELTY_THRESHOLD = 0.55
TAG_IMPORT_NEW_OVERALL_THRESHOLD = 0.70
TAG_IMPORT_COVERED_BY_THRESHOLD = 0.74
TAG_IMPORT_EMBEDDING_CANDIDATE_LIMIT = 6
TAG_IMPORT_EMBEDDING_NEIGHBOR_LIMIT = 16
TAG_HEALTH_SINGLETON_THRESHOLD = 1
TAG_HEALTH_OVERBROAD_DOCUMENT_COUNT = 25
TAG_RELATIONSHIP_TYPES = {"covered_by", "broader", "narrower", "related", "cluster_peer"}
TAG_STATUSES = {TAG_STATUS_CANONICAL, TAG_STATUS_CANDIDATE, TAG_STATUS_RETIRED, TAG_STATUS_BLOCKED}

_SPLIT_RE = re.compile(r"\s+(?:and|or)\s+|[,;/]+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TAG_STOPWORDS = {
    "a",
    "an",
    "and",
    "approach",
    "article",
    "based",
    "case",
    "document",
    "for",
    "in",
    "into",
    "miscellaneous",
    "of",
    "on",
    "paper",
    "research",
    "study",
    "the",
    "to",
    "using",
    "with",
}
_LOW_VALUE_TAG_NAMES = {
    "case study",
    "literature review",
    "miscellaneous",
    "overview",
    "review",
    "survey",
}
_LOW_VALUE_SINGLE_TOKEN_TAGS = {
    "analysis",
    "approach",
    "article",
    "case",
    "data",
    "document",
    "framework",
    "method",
    "model",
    "overview",
    "paper",
    "research",
    "review",
    "study",
    "survey",
    "system",
    "technique",
}


@dataclass
class TagScoreDecision:
    candidate_name: str
    source_bucket: str
    decision: str
    status: str
    relevance_score: float
    library_fit_score: float
    novelty_score: float
    overall_score: float
    rationale: str
    target_tag: Tag | None = None
    target_name: str | None = None
    covered_by_tag: Tag | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_governance_status(status: str | None, *, default: str = TAG_STATUS_CANONICAL) -> str:
    normalized = normalize_tag_name(status or "")
    return normalized if normalized in TAG_STATUSES else default


def normalize_relationship_type(relationship_type: str | None) -> str:
    normalized = normalize_tag_name(relationship_type or "").replace(" ", "_")
    if normalized not in TAG_RELATIONSHIP_TYPES:
        raise ValueError("Unsupported tag relationship type")
    return normalized


def candidate_tag_names(topics: list[str] | None, keywords: list[str] | None) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source_bucket, values in (("topic", topics or []), ("keyword", keywords or [])):
        for raw_value in values:
            for name in _expand_tag_candidate(str(raw_value or "")):
                normalized = normalize_tag_name(name)
                if not _useful_candidate_name(normalized) or normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append((normalized, source_bucket))
    return candidates


def apply_import_tag_governance(
    db: Session,
    *,
    document: Document,
    topics: list[str] | None,
    keywords: list[str] | None,
    source: str = "import",
    job: ImportJob | None = None,
    concordance_job_id: str | None = None,
    ai: Any | None = None,
    usage_context: OpenAIUsageContext | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    candidates = candidate_tag_names(topics, keywords)
    decisions = score_tag_candidates(
        db,
        document=document,
        candidates=candidates,
        source=source,
        ai=ai,
        usage_context=usage_context,
    )

    replaced_tag_names = sorted(tag.name for tag in document.tags) if replace_existing else []
    if replace_existing:
        document.tags.clear()

    attached = 0
    new_candidates = 0
    covered_by = 0
    selected_target_ids: set[str] = {tag.id for tag in document.tags}
    assessments: list[dict[str, Any]] = []
    for decision in decisions:
        tag = decision.target_tag
        should_attach = decision.status == "attached"
        selection_skip_reason: str | None = None
        if should_attach:
            if attached >= TAG_IMPORT_MAX_ATTACHMENTS:
                should_attach = False
                selection_skip_reason = "max_attachments"
            elif decision.decision == "new_candidate":
                if new_candidates >= TAG_IMPORT_MAX_NEW_CANDIDATES:
                    should_attach = False
                    selection_skip_reason = "max_new_candidates"
                else:
                    tag = get_or_create_tag(
                        db,
                        decision.target_name or decision.candidate_name,
                        status_if_new=TAG_STATUS_CANDIDATE,
                        metadata_if_new={
                            "created_by": source,
                            "created_from_candidate": decision.candidate_name,
                            "governance_note": "New concept accepted by import-time tag scoring.",
                        },
                    )
                    if tag.id in selected_target_ids:
                        should_attach = False
                        selection_skip_reason = "duplicate_target"
                    else:
                        new_candidates += 1
            elif tag and tag.id in selected_target_ids:
                should_attach = False
                selection_skip_reason = "duplicate_target"
            elif not tag:
                should_attach = False
                selection_skip_reason = "missing_target"
        status = decision.status if should_attach else "not_attached"
        if selection_skip_reason:
            decision.metadata["selection_skip_reason"] = selection_skip_reason
        if should_attach and tag:
            document.tags.append(tag)
            selected_target_ids.add(tag.id)
            attached += 1
        if decision.decision == "covered_by" and should_attach:
            covered_by += 1
        assessment = DocumentTagAssessment(
            document_id=document.id,
            tag_id=tag.id if tag else None,
            import_job_id=job.id if job else None,
            concordance_job_id=concordance_job_id,
            candidate_name=decision.candidate_name,
            source=source,
            decision=decision.decision,
            status=status,
            relevance_score=round_score(decision.relevance_score),
            library_fit_score=round_score(decision.library_fit_score),
            novelty_score=round_score(decision.novelty_score),
            overall_score=round_score(decision.overall_score),
            rationale=decision.rationale,
            assessment_metadata={
                **decision.metadata,
                "source_bucket": decision.source_bucket,
                "target_name": tag.name if tag else decision.target_name,
                "scoring_contract": "aggressive_existing_first_ranked_cap_v2",
            },
        )
        db.add(assessment)
        assessments.append(
            {
                "candidate_name": decision.candidate_name,
                "target_name": tag.name if tag else decision.target_name,
                "decision": decision.decision,
                "status": status,
                "selection_skip_reason": selection_skip_reason,
                "relevance_score": round_score(decision.relevance_score),
                "library_fit_score": round_score(decision.library_fit_score),
                "novelty_score": round_score(decision.novelty_score),
                "overall_score": round_score(decision.overall_score),
            }
        )

    summary = {
        "method": "embedding_similarity_hybrid_library_cluster_scoring",
        "source": source,
        "candidate_count": len(candidates),
        "attached_count": attached,
        "new_candidate_count": new_candidates,
        "covered_by_count": covered_by,
        "max_attachments": TAG_IMPORT_MAX_ATTACHMENTS,
        "max_new_candidates": TAG_IMPORT_MAX_NEW_CANDIDATES,
        "selection_policy": "ranked_existing_first_total_cap_new_cap",
        "score_axes": ["document_relevance", "library_fit", "novelty_value"],
        "replace_existing": replace_existing,
        "replaced_tag_count": len(replaced_tag_names),
        "replaced_tags": replaced_tag_names,
        "decisions": assessments[:20],
    }
    evidence = dict(document.metadata_evidence or {})
    evidence_key = "tag_governance" if source == "import" else f"{source}_tag_governance"
    evidence[evidence_key] = summary
    document.metadata_evidence = evidence
    return summary


def score_tag_candidates(
    db: Session,
    *,
    document: Document,
    candidates: list[tuple[str, str]],
    source: str,
    ai: Any | None = None,
    usage_context: OpenAIUsageContext | None = None,
) -> list[TagScoreDecision]:
    existing_tags = (
        db.query(Tag)
        .options(selectinload(Tag.incoming_relationships), selectinload(Tag.outgoing_relationships))
        .order_by(Tag.name)
        .all()
    )
    active_tags = [tag for tag in existing_tags if normalize_governance_status(tag.status) not in {TAG_STATUS_RETIRED, TAG_STATUS_BLOCKED}]
    document_context = _document_scoring_context(document)
    decisions: list[TagScoreDecision] = []
    embedding_budget = TAG_IMPORT_EMBEDDING_CANDIDATE_LIMIT

    for candidate_name, source_bucket in candidates:
        alias_target = resolve_tag_alias(db, candidate_name)
        relevance = _document_relevance(candidate_name, source_bucket, document_context)
        low_value_reason = _low_value_candidate_reason(candidate_name)
        if alias_target and normalize_governance_status(alias_target.status) not in {TAG_STATUS_RETIRED, TAG_STATUS_BLOCKED}:
            if low_value_reason and not (alias_target.definition or alias_target.use_guidance):
                decisions.append(
                    TagScoreDecision(
                        candidate_name=candidate_name,
                        source_bucket=source_bucket,
                        decision="low_value",
                        status="not_attached",
                        relevance_score=relevance,
                        library_fit_score=0.0,
                        novelty_score=0.0,
                        overall_score=0.0,
                        rationale=low_value_reason,
                        target_tag=alias_target,
                        metadata={"alias_memory": True, "low_value": True},
                    )
                )
                continue
            decisions.append(
                TagScoreDecision(
                    candidate_name=candidate_name,
                    source_bucket=source_bucket,
                    decision="existing_alias",
                    status="attached",
                    relevance_score=relevance,
                    library_fit_score=1.0,
                    novelty_score=0.05,
                    overall_score=_overall_existing_score(relevance, 1.0, 0.05),
                    rationale=f'Reused existing tag "{alias_target.name}" through merge alias memory.',
                    target_tag=alias_target,
                    metadata={"alias_memory": True},
                )
            )
            continue

        best_tag, similarity, similarity_evidence = _best_existing_tag(
            db,
            candidate_name,
            active_tags,
            ai=ai if embedding_budget > 0 else None,
            usage_context=usage_context,
        )
        if similarity_evidence.get("embedding_attempted"):
            embedding_budget -= 1
        library_fit = _library_fit(best_tag, similarity)
        novelty = _novelty_value(similarity, best_tag)
        covered = best_tag is not None and _covered_by_existing(candidate_name, best_tag, similarity)
        exact_existing = best_tag is not None and normalize_tag_name(best_tag.name) == candidate_name
        blocked_match = _blocked_or_retired_match(candidate_name, existing_tags)
        existing_overall = _overall_existing_score(relevance, library_fit, novelty)
        new_overall = _overall_new_score(relevance, novelty)

        if blocked_match:
            decisions.append(
                TagScoreDecision(
                    candidate_name=candidate_name,
                    source_bucket=source_bucket,
                    decision="blocked_or_retired",
                    status="not_attached",
                    relevance_score=relevance,
                    library_fit_score=0.0,
                    novelty_score=0.0,
                    overall_score=0.0,
                    rationale=f'The matching tag "{blocked_match.name}" is {blocked_match.status}.',
                    target_tag=blocked_match,
                    metadata={"matched_status": blocked_match.status},
                )
            )
            continue

        if low_value_reason and not (best_tag and exact_existing and (best_tag.definition or best_tag.use_guidance)):
            decisions.append(
                TagScoreDecision(
                    candidate_name=candidate_name,
                    source_bucket=source_bucket,
                    decision="low_value",
                    status="not_attached",
                    relevance_score=relevance,
                    library_fit_score=library_fit,
                    novelty_score=novelty,
                    overall_score=0.0,
                    rationale=low_value_reason,
                    target_tag=best_tag,
                    metadata={**similarity_evidence, "nearest_existing_tag": best_tag.name if best_tag else None, "low_value": True},
                )
            )
            continue

        if (
            best_tag
            and (exact_existing or covered or similarity >= TAG_IMPORT_CLOSE_MATCH_REUSE_THRESHOLD)
            and relevance >= TAG_IMPORT_EXISTING_RELEVANCE_THRESHOLD
            and existing_overall >= TAG_IMPORT_EXISTING_OVERALL_THRESHOLD
        ):
            if exact_existing:
                decision = "existing_exact"
            elif covered:
                decision = "covered_by"
            else:
                decision = "existing_close_match"
            decisions.append(
                TagScoreDecision(
                    candidate_name=candidate_name,
                    source_bucket=source_bucket,
                    decision=decision,
                    status="attached",
                    relevance_score=relevance,
                    library_fit_score=library_fit,
                    novelty_score=novelty,
                    overall_score=existing_overall,
                    rationale=(
                        f'Reused existing tag "{best_tag.name}" because it semantically covers this candidate.'
                        if decision == "covered_by"
                        else (
                            f'Reused existing tag "{best_tag.name}" because it is the closest high-similarity library match.'
                            if decision == "existing_close_match"
                            else f'Reused existing tag "{best_tag.name}".'
                        )
                    ),
                    target_tag=best_tag,
                    covered_by_tag=best_tag if decision == "covered_by" else None,
                    metadata=similarity_evidence,
                )
            )
            continue

        if best_tag and similarity >= TAG_IMPORT_NEAR_EXISTING_BLOCK_THRESHOLD:
            decisions.append(
                TagScoreDecision(
                    candidate_name=candidate_name,
                    source_bucket=source_bucket,
                    decision="near_existing_not_attached",
                    status="not_attached",
                    relevance_score=relevance,
                    library_fit_score=library_fit,
                    novelty_score=novelty,
                    overall_score=existing_overall,
                    rationale=f'Skipped new tag because existing tag "{best_tag.name}" is close enough to review or reuse instead.',
                    target_tag=best_tag,
                    metadata={**similarity_evidence, "nearest_existing_tag": best_tag.name, "near_existing_block": True},
                )
            )
            continue

        if (
            relevance >= TAG_IMPORT_NEW_RELEVANCE_THRESHOLD
            and novelty >= TAG_IMPORT_NOVELTY_THRESHOLD
            and new_overall >= TAG_IMPORT_NEW_OVERALL_THRESHOLD
        ):
            decisions.append(
                TagScoreDecision(
                    candidate_name=candidate_name,
                    source_bucket=source_bucket,
                    decision="new_candidate",
                    status="attached",
                    relevance_score=relevance,
                    library_fit_score=library_fit,
                    novelty_score=novelty,
                    overall_score=new_overall,
                    rationale="Created a candidate tag because the document supports the concept and no existing tag covered it well.",
                    target_name=candidate_name,
                    metadata={**similarity_evidence, "nearest_existing_tag": best_tag.name if best_tag else None},
                )
            )
            continue

        decisions.append(
            TagScoreDecision(
                candidate_name=candidate_name,
                source_bucket=source_bucket,
                decision="low_score",
                status="not_attached",
                relevance_score=relevance,
                library_fit_score=library_fit,
                novelty_score=novelty,
                overall_score=max(existing_overall, new_overall),
                rationale="Skipped because the concept was not strong enough for this document or was too weakly distinguished from existing tags.",
                target_tag=best_tag,
                metadata={**similarity_evidence, "nearest_existing_tag": best_tag.name if best_tag else None},
            )
        )

    return sorted(
        decisions,
        key=lambda decision: (
            1 if decision.status == "attached" else 0,
            _decision_priority(decision),
            decision.overall_score,
            decision.relevance_score,
            decision.candidate_name,
        ),
        reverse=True,
    )


def _decision_priority(decision: TagScoreDecision) -> int:
    return {
        "existing_exact": 5,
        "existing_alias": 5,
        "covered_by": 4,
        "existing_close_match": 4,
        "new_candidate": 3,
        "near_existing_not_attached": 2,
        "low_score": 1,
        "low_value": 0,
        "blocked_or_retired": 0,
    }.get(decision.decision, 0)


def tag_health_summary(db: Session, tag_rows: list[Tag]) -> dict[str, Any]:
    tag_ids = [tag.id for tag in tag_rows]
    if not tag_ids:
        return {
            "candidate_tags": 0,
            "retired_tags": 0,
            "blocked_tags": 0,
            "singletons": 0,
            "weak_assignments": 0,
            "relationships": 0,
        }
    counts = {tag.id: _visible_document_count(tag) for tag in tag_rows}
    weak_assignments = (
        db.query(DocumentTagAssessment)
        .filter(
            DocumentTagAssessment.tag_id.in_(tag_ids),
            DocumentTagAssessment.status == "attached",
            DocumentTagAssessment.overall_score < 0.50,
        )
        .count()
    )
    relationships = (
        db.query(TagRelationship)
        .filter(TagRelationship.source_tag_id.in_(tag_ids) | TagRelationship.target_tag_id.in_(tag_ids))
        .count()
    )
    return {
        "candidate_tags": sum(1 for tag in tag_rows if tag.status == TAG_STATUS_CANDIDATE),
        "retired_tags": sum(1 for tag in tag_rows if tag.status == TAG_STATUS_RETIRED),
        "blocked_tags": sum(1 for tag in tag_rows if tag.status == TAG_STATUS_BLOCKED),
        "singletons": sum(1 for tag in tag_rows if counts.get(tag.id, 0) <= TAG_HEALTH_SINGLETON_THRESHOLD),
        "weak_assignments": weak_assignments,
        "relationships": relationships,
    }


def relationship_review_suggestions(db: Session, tag_rows: list[Tag], *, limit: int = 30) -> list[dict[str, Any]]:
    tag_rows = sorted(tag_rows, key=lambda tag: tag.name)
    suggestions: list[dict[str, Any]] = []
    existing_relationships = {
        (relationship.source_tag_id, relationship.target_tag_id, relationship.relationship_type)
        for relationship in db.query(TagRelationship).all()
    }
    for source in tag_rows:
        source_tokens = _tokens(source.name)
        if len(source_tokens) < 2:
            continue
        candidates: list[tuple[float, Tag, str]] = []
        for target in tag_rows:
            if source.id == target.id:
                continue
            target_tokens = _tokens(target.name)
            if not target_tokens or len(target_tokens) > len(source_tokens):
                continue
            relationship_type = "covered_by" if _starts_with_tokens(source_tokens, target_tokens) else "cluster_peer"
            if (source.id, target.id, relationship_type) in existing_relationships:
                continue
            similarity = hybrid_tag_similarity(source.name, target.name)
            if relationship_type == "covered_by" and similarity >= 0.58:
                candidates.append((similarity + 0.12, target, relationship_type))
            elif relationship_type == "cluster_peer" and similarity >= 0.72:
                candidates.append((similarity, target, relationship_type))
        if not candidates:
            continue
        score, target, relationship_type = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        suggestions.append(
            {
                "id": f"relationship:{relationship_type}:{source.id}:{target.id}",
                "source_tag": source,
                "target_tag": target,
                "relationship_type": relationship_type,
                "confidence": min(0.95, score),
                "rationale": (
                    f'"{target.name}" appears to cover the more specific "{source.name}" without requiring a merge.'
                    if relationship_type == "covered_by"
                    else "These tags are semantically close enough to review as a cluster relationship."
                ),
            }
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def status_review_suggestions(db: Session, tag_rows: list[Tag], *, limit: int = 30) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    tag_ids = [tag.id for tag in tag_rows]
    scores_by_tag = _attached_scores_by_tag(db, tag_ids)
    for tag in sorted(tag_rows, key=lambda value: (value.status != TAG_STATUS_CANDIDATE, value.name)):
        status = normalize_governance_status(tag.status)
        if status in {TAG_STATUS_RETIRED, TAG_STATUS_BLOCKED}:
            continue
        scores = scores_by_tag.get(tag.id, [])
        document_count = _visible_document_count(tag)
        average_score = sum(scores) / len(scores) if scores else 0
        low_value_reason = _low_value_candidate_reason(tag.name)
        peer_tag, peer_similarity = _best_peer_tag(tag, tag_rows)
        if document_count == 0:
            suggestions.append(
                {
                    "id": f"status:retired:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_RETIRED,
                    "confidence": 0.84 if status == TAG_STATUS_CANDIDATE else 0.8,
                    "rationale": "This tag has no active document assignments; retiring it keeps it out of future import matching without deleting history.",
                }
            )
        elif status == TAG_STATUS_CANDIDATE and document_count >= 2 and average_score >= 0.58:
            suggestions.append(
                {
                    "id": f"status:canonical:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_CANONICAL,
                    "confidence": min(0.95, max(0.62, average_score)),
                    "rationale": "This candidate tag has repeated attached use and enough score evidence to promote.",
                }
            )
        elif status == TAG_STATUS_CANDIDATE and document_count <= 1 and low_value_reason:
            suggestions.append(
                {
                    "id": f"status:retired:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_RETIRED,
                    "confidence": 0.72,
                    "rationale": low_value_reason,
                }
            )
        elif status == TAG_STATUS_CANDIDATE and document_count <= 1 and scores and max(scores) < 0.55:
            suggestions.append(
                {
                    "id": f"status:retired:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_RETIRED,
                    "confidence": 0.66,
                    "rationale": "This candidate tag has weak single-document score evidence and may be better retired after review.",
                }
            )
        elif status == TAG_STATUS_CANDIDATE and document_count <= 1 and not scores:
            suggestions.append(
                {
                    "id": f"status:retired:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_RETIRED,
                    "confidence": 0.56,
                    "rationale": "This one-document candidate tag has no import-governance evidence; retire it unless it represents a concept you want to keep available for future imports.",
                }
            )
        elif status == TAG_STATUS_CANONICAL and document_count <= 1 and low_value_reason:
            suggestions.append(
                {
                    "id": f"status:retired:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_RETIRED,
                    "confidence": 0.72,
                    "rationale": low_value_reason,
                }
            )
        elif status == TAG_STATUS_CANONICAL and document_count <= 1 and peer_tag and peer_similarity >= 0.72:
            suggestions.append(
                {
                    "id": f"status:retired:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_RETIRED,
                    "confidence": min(0.9, peer_similarity),
                    "rationale": f'This singleton canonical tag is very close to "{peer_tag.name}" and should be retired after the assignment is merged or pruned.',
                }
            )
        elif status == TAG_STATUS_CANONICAL and document_count <= 1:
            suggestions.append(
                {
                    "id": f"status:candidate:{tag.id}",
                    "tag": tag,
                    "suggested_status": TAG_STATUS_CANDIDATE,
                    "confidence": 0.58 if not scores else 0.54,
                    "rationale": (
                        "This singleton canonical tag has no import-governance evidence; downgrade it to candidate until it proves durable value."
                        if not scores
                        else "This canonical tag is still used by only one document; downgrade it to candidate until repeated use proves it belongs in the durable taxonomy."
                    ),
                }
            )
        if len(suggestions) >= limit:
            break
    return suggestions


def pruning_review_suggestions(db: Session, tag_rows: list[Tag], *, limit: int = 30) -> list[dict[str, Any]]:
    tag_ids = [tag.id for tag in tag_rows]
    if not tag_ids:
        return []
    scores_by_tag = _attached_scores_by_tag(db, tag_ids)
    rows = (
        db.query(DocumentTagAssessment)
        .filter(
            DocumentTagAssessment.tag_id.in_(tag_ids),
            DocumentTagAssessment.status == "attached",
            DocumentTagAssessment.overall_score < 0.50,
        )
        .options(selectinload(DocumentTagAssessment.document), selectinload(DocumentTagAssessment.tag))
        .order_by(DocumentTagAssessment.overall_score.asc(), DocumentTagAssessment.created_at.desc())
        .limit(limit * 3)
        .all()
    )
    suggestions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not document_is_library_visible(row.document) or not row.tag:
            continue
        key = (row.document_id, row.tag_id or "")
        if key in seen or row.tag not in row.document.tags:
            continue
        seen.add(key)
        suggestions.append(
            {
                "id": f"prune:{row.document_id}:{row.tag_id}",
                "document_id": row.document_id,
                "document_title": row.document.title,
                "tag": row.tag,
                "confidence": min(0.9, max(0.52, 1.0 - float(row.overall_score or 0))),
                "relevance_score": float(row.relevance_score or 0),
                "library_fit_score": float(row.library_fit_score or 0),
                "novelty_score": float(row.novelty_score or 0),
                "overall_score": float(row.overall_score or 0),
                "rationale": row.rationale or "This document-tag assignment scored weakly during tag governance.",
            }
        )
        if len(suggestions) >= limit:
            break
    if len(suggestions) < limit:
        for tag in sorted(tag_rows, key=lambda value: value.name):
            visible_documents = _visible_documents(tag)
            if len(visible_documents) != 1:
                continue
            document = visible_documents[0]
            key = (document.id, tag.id)
            if key in seen or tag not in document.tags:
                continue
            low_value_reason = _low_value_candidate_reason(tag.name)
            peer_tag, peer_similarity = _best_peer_tag(tag, tag_rows)
            scores = scores_by_tag.get(tag.id, [])
            average_score = sum(scores) / len(scores) if scores else 0
            if not low_value_reason and not (peer_tag and peer_similarity >= 0.72) and scores and average_score >= 0.58:
                continue
            seen.add(key)
            if low_value_reason:
                rationale = low_value_reason
                confidence = 0.7
                relevance_score = 0.22
                library_fit_score = 0.14
                novelty_score = 0.08
                overall_score = 0.22
            elif peer_tag and peer_similarity >= 0.72:
                rationale = f'This singleton assignment is close to existing tag "{peer_tag.name}" and may not add retrieval value.'
                confidence = min(0.86, peer_similarity)
                relevance_score = 0.36
                library_fit_score = round_score(peer_similarity)
                novelty_score = 0.18
                overall_score = 0.36
            elif scores:
                rationale = "This singleton assignment has limited score evidence and has not proven reusable library value."
                confidence = 0.56
                relevance_score = round_score(average_score)
                library_fit_score = 0.32
                novelty_score = 0.28
                overall_score = round_score(min(average_score, 0.5))
            else:
                rationale = "This one-document tag assignment predates import-governance scoring; prune it if it does not add real retrieval value for this document."
                confidence = 0.52
                relevance_score = 0.34
                library_fit_score = 0.2
                novelty_score = 0.22
                overall_score = 0.34
            suggestions.append(
                {
                    "id": f"prune:{document.id}:{tag.id}",
                    "document_id": document.id,
                    "document_title": document.title,
                    "tag": tag,
                    "confidence": confidence,
                    "relevance_score": relevance_score,
                    "library_fit_score": library_fit_score,
                    "novelty_score": novelty_score,
                    "overall_score": overall_score,
                    "rationale": rationale,
                }
            )
            if len(suggestions) >= limit:
                break
    return suggestions


def _visible_documents(tag: Tag) -> list[Document]:
    return [document for document in tag.documents if document_is_library_visible(document)]


def _visible_document_count(tag: Tag) -> int:
    return len(_visible_documents(tag))


def _attached_scores_by_tag(db: Session, tag_ids: list[str]) -> dict[str, list[float]]:
    if not tag_ids:
        return {}
    rows = (
        db.query(DocumentTagAssessment)
        .filter(DocumentTagAssessment.tag_id.in_(tag_ids), DocumentTagAssessment.status == "attached")
        .all()
    )
    scores_by_tag: dict[str, list[float]] = {}
    for row in rows:
        if row.tag_id:
            scores_by_tag.setdefault(row.tag_id, []).append(float(row.overall_score or 0))
    return scores_by_tag


def _best_peer_tag(tag: Tag, tag_rows: list[Tag]) -> tuple[Tag | None, float]:
    candidates = [
        (hybrid_tag_similarity(tag.name, other.name), other)
        for other in tag_rows
        if other.id != tag.id and normalize_governance_status(other.status) not in {TAG_STATUS_RETIRED, TAG_STATUS_BLOCKED}
    ]
    if not candidates:
        return None, 0.0
    score, peer = sorted(
        candidates,
        key=lambda item: (item[0], _visible_document_count(item[1]), item[1].status == TAG_STATUS_CANONICAL, item[1].name),
        reverse=True,
    )[0]
    return peer, round_score(score)


def round_score(value: float | int | None) -> float:
    return round(min(1.0, max(0.0, float(value or 0))), 3)


def hybrid_tag_similarity(left: str, right: str, *, embedding_similarity: float | None = None) -> float:
    left_normalized = normalize_tag_name(left)
    right_normalized = normalize_tag_name(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    left_tokens = set(_tokens(left_normalized))
    right_tokens = set(_tokens(right_normalized))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    containment = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    lexical = (0.45 * overlap) + (0.35 * containment) + (0.20 * sequence)
    if embedding_similarity is None:
        return round_score(lexical)
    return round_score((0.55 * lexical) + (0.45 * embedding_similarity))


def _expand_tag_candidate(value: str) -> list[str]:
    normalized = normalize_tag_name(value)
    if not normalized:
        return []
    parts = [part for part in (normalize_tag_name(part) for part in _SPLIT_RE.split(normalized)) if part]
    return [normalized, *[part for part in parts if part != normalized]]


def _useful_candidate_name(name: str) -> bool:
    tokens = _tokens(name)
    if not tokens or len(tokens) > 6:
        return False
    return any(token not in _TAG_STOPWORDS for token in tokens)


def _document_scoring_context(document: Document) -> dict[str, str]:
    title = normalize_tag_name(" ".join(part for part in [document.title, document.subtitle] if part))
    abstract_summary = normalize_tag_name(" ".join(part for part in [document.abstract, document.rich_summary] if part))
    body = normalize_tag_name(document.search_text or "")
    existing_tags = normalize_tag_name(" ".join(tag.name for tag in document.tags))
    return {
        "title": title,
        "abstract_summary": abstract_summary,
        "body": body,
        "existing_tags": existing_tags,
        "all": normalize_tag_name(" ".join(part for part in [title, abstract_summary, body, existing_tags] if part)),
    }


def _document_relevance(candidate_name: str, source_bucket: str, document_context: dict[str, str]) -> float:
    tokens = _tokens(candidate_name)
    if not tokens:
        return 0.0
    all_text = document_context.get("all", "")
    title = document_context.get("title", "")
    abstract_summary = document_context.get("abstract_summary", "")
    body = document_context.get("body", "")
    existing_tags = document_context.get("existing_tags", "")
    token_hits = sum(1 for token in tokens if token in all_text)
    base = 0.34 if source_bucket == "topic" else 0.30
    if candidate_name in title:
        base += 0.42
    elif candidate_name in abstract_summary:
        base += 0.36
    elif candidate_name in body:
        base += 0.33
    elif token_hits:
        base += 0.28 * (token_hits / len(tokens))
    if candidate_name in existing_tags:
        base += 0.08
    if len(tokens) == 1:
        base -= 0.10
    if len(tokens) >= 5:
        base -= 0.10
    if any(token in _TAG_STOPWORDS for token in tokens) and len(tokens) <= 2:
        base -= 0.04
    return round_score(base)


def _low_value_candidate_reason(name: str) -> str | None:
    normalized = normalize_tag_name(name)
    tokens = _tokens(normalized)
    if not tokens:
        return "Skipped because the candidate tag is blank after normalization."
    if normalized in _LOW_VALUE_TAG_NAMES:
        return f'Skipped low-value tag "{normalized}" because it describes document form rather than a durable research concept.'
    if len(tokens) == 1 and tokens[0] in _LOW_VALUE_SINGLE_TOKEN_TAGS:
        return f'Skipped low-value one-word tag "{normalized}" because it is too broad to improve retrieval.'
    meaningful_tokens = [token for token in tokens if token not in _TAG_STOPWORDS and token not in _LOW_VALUE_SINGLE_TOKEN_TAGS]
    if len(tokens) <= 3 and not meaningful_tokens:
        return f'Skipped low-value tag "{normalized}" because its words are too generic for taxonomy growth.'
    return None


def _best_existing_tag(
    db: Session,
    candidate_name: str,
    active_tags: list[Tag],
    *,
    ai: Any | None,
    usage_context: OpenAIUsageContext | None,
) -> tuple[Tag | None, float, dict[str, Any]]:
    if not active_tags:
        return None, 0.0, {"similarity_method": "none"}
    lexical_ranked = sorted(
        ((hybrid_tag_similarity(candidate_name, tag.name), tag) for tag in active_tags),
        key=lambda item: item[0],
        reverse=True,
    )
    top = lexical_ranked[:TAG_IMPORT_EMBEDDING_NEIGHBOR_LIMIT]
    embedding_evidence: dict[str, Any] = {
        "similarity_method": "hybrid_lexical",
        "lexical_similarity": round_score(top[0][0]) if top else 0.0,
    }
    if ai is not None and top:
        candidate_embedding = _safe_embed(ai, f"Research library tag candidate: {candidate_name}", usage_context)
        if candidate_embedding:
            embedding_evidence["embedding_attempted"] = True
            best: tuple[float, Tag, float | None] | None = None
            for lexical_score, tag in top:
                tag_embedding = _tag_embedding(db, tag, ai, usage_context)
                embedding_similarity = _cosine_similarity(candidate_embedding, tag_embedding) if tag_embedding else None
                hybrid_score = hybrid_tag_similarity(candidate_name, tag.name, embedding_similarity=embedding_similarity)
                if best is None or hybrid_score > best[0]:
                    best = (hybrid_score, tag, embedding_similarity)
            if best:
                embedding_evidence.update(
                    {
                        "similarity_method": "hybrid_embedding_lexical",
                        "embedding_similarity": round_score(best[2]) if best[2] is not None else None,
                        "lexical_similarity": round_score(hybrid_tag_similarity(candidate_name, best[1].name)),
                    }
                )
                return best[1], round_score(best[0]), embedding_evidence
    if top:
        return top[0][1], round_score(top[0][0]), embedding_evidence
    return None, 0.0, embedding_evidence


def _tag_embedding(db: Session, tag: Tag, ai: Any, usage_context: OpenAIUsageContext | None) -> list[float] | None:
    metadata = dict(tag.governance_metadata or {})
    embedding = metadata.get("embedding")
    if isinstance(embedding, list) and embedding:
        return [float(value) for value in embedding if isinstance(value, (int, float))]
    text = f"Research library tag: {tag.name}"
    if tag.definition:
        text += f"\nDefinition: {tag.definition}"
    if tag.use_guidance:
        text += f"\nUse when: {tag.use_guidance}"
    embedding = _safe_embed(ai, text, usage_context)
    if not embedding:
        return None
    metadata["embedding"] = embedding
    metadata["embedding_source"] = "tag_governance"
    tag.governance_metadata = metadata
    db.flush()
    return embedding


def _safe_embed(ai: Any, text: str, usage_context: OpenAIUsageContext | None) -> list[float] | None:
    try:
        return ai.embed(text, usage_context=usage_context)
    except Exception:
        return None


def _library_fit(tag: Tag | None, similarity: float) -> float:
    if tag is None:
        return 0.0
    status = normalize_governance_status(tag.status)
    status_boost = 0.10 if status == TAG_STATUS_CANONICAL else 0.02
    count_boost = min(0.12, math.log1p(len([document for document in tag.documents if document_is_library_visible(document)])) / 30)
    definition_boost = 0.04 if tag.definition else 0.0
    return round_score((0.78 * similarity) + status_boost + count_boost + definition_boost)


def _novelty_value(similarity: float, tag: Tag | None) -> float:
    if tag is None:
        return 0.92
    return round_score(1.0 - (0.88 * similarity))


def _covered_by_existing(candidate_name: str, tag: Tag, similarity: float) -> bool:
    if similarity >= TAG_IMPORT_COVERED_BY_THRESHOLD:
        return True
    candidate_tokens = _tokens(candidate_name)
    tag_tokens = _tokens(tag.name)
    if not candidate_tokens or not tag_tokens:
        return False
    return _starts_with_tokens(candidate_tokens, tag_tokens) and len(candidate_tokens) > len(tag_tokens)


def _blocked_or_retired_match(candidate_name: str, tags: list[Tag]) -> Tag | None:
    for tag in tags:
        if normalize_tag_name(tag.name) == candidate_name and normalize_governance_status(tag.status) in {TAG_STATUS_RETIRED, TAG_STATUS_BLOCKED}:
            return tag
    return None


def _overall_existing_score(relevance: float, library_fit: float, novelty: float) -> float:
    return round_score((0.48 * relevance) + (0.42 * library_fit) + (0.10 * novelty))


def _overall_new_score(relevance: float, novelty: float) -> float:
    return round_score((0.64 * relevance) + (0.36 * novelty))


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_tag_name(value))


def _starts_with_tokens(source_tokens: list[str], target_tokens: list[str]) -> bool:
    return len(source_tokens) > len(target_tokens) and source_tokens[: len(target_tokens)] == target_tokens


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float | None:
    if not left or not right:
        return None
    size = min(len(left), len(right))
    if not size:
        return None
    dot = sum(float(left[index]) * float(right[index]) for index in range(size))
    left_norm = math.sqrt(sum(float(left[index]) ** 2 for index in range(size)))
    right_norm = math.sqrt(sum(float(right[index]) ** 2 for index in range(size)))
    if not left_norm or not right_norm:
        return None
    return round_score((dot / (left_norm * right_norm) + 1) / 2)
