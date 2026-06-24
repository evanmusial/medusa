from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import Document, DocumentRecommendation, DoiStash, ImportBatch, ImportJob, ProcessingEvent, utc_now
from app.services.document_cache import document_cache_path, document_cache_root, register_document_cache
from app.services.document_visibility import LIBRARY_VISIBLE_DOCUMENT_STATUSES, filter_library_visible_documents, library_visible_document_filter
from app.services.processing import refresh_import_batch_progress
from app.services.storage import get_storage_service
from app.services.verifier import normalized_title_similarity


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
TRAILING_DOI_PUNCTUATION = ".,;:)]}>"
REFERENCE_ENTRY_MARKER_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s+")
REFERENCE_QUOTED_TITLE_RE = re.compile(r"[\"“]([^\"”]{8,300})[\"”]")
REFERENCE_MARKDOWN_TITLE_RE = re.compile(r"(?<!\*)\*([^*\n]{8,300})\*(?!\*)")
REFERENCE_APA_TITLE_RE = re.compile(r"\(\s*(?:19|20)\d{2}[a-z]?\s*\)\.\s+(.+?)(?:\.\s+|$)")
REFERENCE_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
REFERENCE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")
OPENALEX_WORK_RE = re.compile(r"W\d+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ARXIV_ABS_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#]+)", re.IGNORECASE)
ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?|\d{4}\.\d{4,5}(?:v\d+)?)$", re.IGNORECASE)
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
PDF_PROVIDER_PRIORITY = {
    "unpaywall": 90,
    "arxiv": 85,
    "semantic_scholar": 70,
    "openalex": 60,
    "crossref": 45,
}
RECOMMENDATION_V2_METADATA_KEY = "recommendations_v2"
RECOMMENDATION_VIEWS = {"discover", "known", "all"}
RECOMMENDATION_FAMILIES = {
    "diverse",
    "closest",
    "newer",
    "foundational",
    "methods",
    "contrasting",
    "open_pdf",
    "reference_material",
}
RECOMMENDATION_IMPORT_KNOWN_STATUSES = {"staged", "queued", "running", "failed", "restored_paused"}
RECOMMENDATION_FAMILY_LABELS = {
    "closest": "Closest",
    "newer": "Newer",
    "foundational": "Foundational",
    "methods": "Methods",
    "contrasting": "Contrasting",
    "open_pdf": "Open PDF",
    "reference_material": "Reference material",
    "diverse": "Diverse set",
}
RECOMMENDATION_KNOWN_LABELS = {
    "new": "Outside library",
    "in_library": "In library",
    "active_import": "Queued import",
    "stashed": "Stashed",
}
METHOD_TERMS = {
    "approach",
    "algorithm",
    "classification",
    "dataset",
    "framework",
    "measurement",
    "method",
    "methodology",
    "model",
    "protocol",
    "technique",
}
CONTRAST_TERMS = {"challenge", "contrary", "contrast", "critique", "critical", "debate", "limitation", "opposing"}
REFERENCE_MATERIAL_TERMS = {"book", "chapter", "dataset", "handbook", "manual", "policy", "report", "standard", "survey"}


@dataclass
class RecommendationCandidate:
    title: str
    provider: str
    relation: str | None = None
    doi: str | None = None
    authors: list[dict[str, Any]] = field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    description: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    pdf_url: str | None = None
    score: float | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def match_key(self) -> str:
        return recommendation_match_key(self.doi, self.title)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    text = unquote(str(value)).strip()
    parsed = urlparse(text)
    if parsed.netloc and parsed.path:
        text = parsed.path.lstrip("/")
    text = text.removeprefix("doi:").removeprefix("DOI:").strip()
    match = DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(0).rstrip(TRAILING_DOI_PUNCTUATION).lower()
    return doi or None


def doi_url(doi: str | None) -> str | None:
    normalized = normalize_doi(doi)
    return f"https://doi.org/{normalized}" if normalized else None


def normalize_title_key(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", unescape(value).lower()).strip()


def recommendation_match_key(doi: str | None, title: str | None) -> str:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    normalized_title = normalize_title_key(title)
    return f"title:{normalized_title[:840]}" if normalized_title else "title:untitled"


def list_document_recommendations(
    db: Session,
    document: Document,
    *,
    hide_existing: bool = False,
    view: str | None = None,
    family: str | None = None,
) -> list[DocumentRecommendation]:
    rows = (
        db.query(DocumentRecommendation)
        .options(
            joinedload(DocumentRecommendation.existing_document),
            joinedload(DocumentRecommendation.imported_document),
        )
        .filter(DocumentRecommendation.source_document_id == document.id)
        .order_by(
            DocumentRecommendation.score.desc().nullslast(),
            DocumentRecommendation.publication_year.desc().nullslast(),
            DocumentRecommendation.title,
        )
        .all()
    )
    mark_recommendation_discovery_state(db, rows, source_document=document)
    effective_view = _recommendation_view(view, hide_existing=hide_existing)
    effective_family = _recommendation_family(family)
    rows = _rank_recommendations(document, rows, effective_family)
    return _filter_recommendations(rows, view=effective_view, family=effective_family)


def _recommendation_view(value: str | None, *, hide_existing: bool) -> str:
    if value in RECOMMENDATION_VIEWS:
        return value
    return "discover" if hide_existing else "all"


def _recommendation_family(value: str | None) -> str:
    return value if value in RECOMMENDATION_FAMILIES else "diverse"


def _filter_recommendations(
    rows: list[DocumentRecommendation],
    *,
    view: str,
    family: str,
) -> list[DocumentRecommendation]:
    filtered = rows
    if view == "discover":
        filtered = [row for row in filtered if row.known_status == "new"]
    elif view == "known":
        filtered = [row for row in filtered if row.known_status != "new"]
    if family == "open_pdf":
        filtered = [row for row in filtered if row.has_pdf]
    elif family != "diverse":
        filtered = [row for row in filtered if row.relation_family == family]
    return filtered


def _rank_recommendations(
    source_document: Document,
    rows: list[DocumentRecommendation],
    family: str,
) -> list[DocumentRecommendation]:
    if family != "diverse":
        ranked = sorted(rows, key=lambda row: _recommendation_sort_key(source_document, row))
        for index, row in enumerate(ranked):
            _write_recommendation_v2_metadata(
                row,
                {"diversity_score": round(max(0.0, 1.0 - index * 0.02), 3)},
            )
        return ranked

    remaining = list(rows)
    selected: list[DocumentRecommendation] = []
    seen_authors: set[str] = set()
    seen_decades: set[int] = set()
    seen_journals: set[str] = set()
    seen_families: set[str] = set()
    seen_providers: set[str] = set()
    while remaining:
        best = max(
            remaining,
            key=lambda row: _diversity_rank_score(
                source_document,
                row,
                seen_authors=seen_authors,
                seen_decades=seen_decades,
                seen_journals=seen_journals,
                seen_families=seen_families,
                seen_providers=seen_providers,
            ),
        )
        score = _diversity_rank_score(
            source_document,
            best,
            seen_authors=seen_authors,
            seen_decades=seen_decades,
            seen_journals=seen_journals,
            seen_families=seen_families,
            seen_providers=seen_providers,
        )
        _write_recommendation_v2_metadata(best, {"diversity_score": round(score, 3)})
        selected.append(best)
        remaining.remove(best)
        seen_authors.update(_author_families(best.authors))
        if best.publication_year:
            seen_decades.add((best.publication_year // 10) * 10)
        if best.journal:
            seen_journals.add(normalize_title_key(best.journal))
        seen_families.add(best.relation_family)
        seen_providers.update(_provider_tokens(best.source_provider))
    return selected


def _recommendation_sort_key(source_document: Document, row: DocumentRecommendation) -> tuple[int, float, int, str]:
    known_penalty = 0 if row.known_status == "new" else 1
    return (
        known_penalty,
        -_base_recommendation_score(source_document, row),
        -(row.publication_year or 0),
        normalize_title_key(row.title),
    )


def _diversity_rank_score(
    source_document: Document,
    row: DocumentRecommendation,
    *,
    seen_authors: set[str],
    seen_decades: set[int],
    seen_journals: set[str],
    seen_families: set[str],
    seen_providers: set[str],
) -> float:
    score = _base_recommendation_score(source_document, row)
    authors = _author_families(row.authors)
    if authors and seen_authors.isdisjoint(authors):
        score += 0.34
    elif authors:
        score -= 0.12
    if row.publication_year:
        decade = (row.publication_year // 10) * 10
        score += 0.18 if decade not in seen_decades else -0.06
    journal_key = normalize_title_key(row.journal)
    if journal_key:
        score += 0.16 if journal_key not in seen_journals else -0.06
    if row.relation_family not in seen_families:
        score += 0.24
    providers = _provider_tokens(row.source_provider)
    if providers and seen_providers.isdisjoint(providers):
        score += 0.08
    return score


def _base_recommendation_score(source_document: Document, row: DocumentRecommendation) -> float:
    try:
        score = float(row.score or 0)
    except (TypeError, ValueError):
        score = 0.0
    if row.has_pdf:
        score += 0.18
    if normalize_doi(row.doi):
        score += 0.12
    if row.source_url:
        score += 0.05
    family = row.relation_family
    if family == "closest":
        score += 0.18
    elif family in {"methods", "contrasting", "reference_material"}:
        score += 0.12
    elif family == "newer" and row.publication_year and source_document.publication_year:
        score += min(0.18, max(0, row.publication_year - source_document.publication_year) * 0.02)
    elif family == "foundational" and row.publication_year and source_document.publication_year:
        score += min(0.16, max(0, source_document.publication_year - row.publication_year) * 0.01)
    return score


def refresh_document_recommendations(db: Session, document: Document, *, limit: int | None = None) -> list[DocumentRecommendation]:
    settings = get_settings()
    limit = limit or settings.recommendations_max_results_per_source
    candidates: dict[str, RecommendationCandidate] = {}
    errors: dict[str, str] = {}

    for provider, fetcher in _enabled_fetchers():
        try:
            for candidate in fetcher(document, limit):
                if not candidate.title.strip():
                    continue
                _merge_candidate(candidates, candidate)
        except Exception as exc:
            errors[provider] = str(exc)

    bibliography_candidates = bibliography_reference_candidates(document, limit)
    for candidate in bibliography_candidates:
        if not candidate.title.strip():
            continue
        _merge_candidate(candidates, candidate)

    for provider, enricher in _enabled_enrichers():
        try:
            for candidate in enricher(list(candidates.values()), limit):
                if not candidate.title.strip():
                    continue
                _merge_candidate(candidates, candidate)
        except Exception as exc:
            errors[provider] = str(exc)

    seen_keys = set(candidates)
    for candidate in candidates.values():
        row = (
            db.query(DocumentRecommendation)
            .filter(
                DocumentRecommendation.source_document_id == document.id,
                DocumentRecommendation.match_key == candidate.match_key,
            )
            .one_or_none()
        )
        if not row:
            row = DocumentRecommendation(
                source_document_id=document.id,
                match_key=candidate.match_key,
                title=candidate.title[:800],
                source_provider=candidate.provider,
                raw_metadata={},
            )
            db.add(row)
        _apply_candidate(row, candidate)

    stale_query = db.query(DocumentRecommendation).filter(
        DocumentRecommendation.source_document_id == document.id,
        DocumentRecommendation.status == "candidate",
    )
    if seen_keys:
        stale_query = stale_query.filter(~DocumentRecommendation.match_key.in_(seen_keys))
    stale_rows = stale_query.all()
    for stale in stale_rows:
        stale.status = "stale"

    db.flush()
    rows = list_document_recommendations(db, document)
    db.add(
        ProcessingEvent(
            document_id=document.id,
            level="warning" if errors else "info",
            event_type="recommendations_refreshed",
            message=f"Recommendation refresh found {len(rows)} related papers.",
            payload={
                "candidate_count": len(candidates),
                "bibliography_reference_count": len(bibliography_candidates),
                "providers": sorted({row.source_provider for row in rows}),
                "errors": errors,
            },
        )
    )
    return rows


def bibliography_reference_candidates(document: Document, limit: int) -> list[RecommendationCandidate]:
    entries = _bibliography_reference_entries(document.bibliography, limit=limit)
    candidates: list[RecommendationCandidate] = []
    source_doi = normalize_doi(document.doi)
    source_title_key = normalize_title_key(document.title)
    for index, entry in enumerate(entries, start=1):
        candidate = _bibliography_entry_to_candidate(entry, index)
        if not candidate:
            continue
        if source_doi and normalize_doi(candidate.doi) == source_doi:
            continue
        if not normalize_doi(candidate.doi) and normalize_title_key(candidate.title) == source_title_key:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def _bibliography_reference_entries(text: str | None, *, limit: int) -> list[str]:
    normalized = unescape(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n+", normalized) if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs[:limit]

    entries: list[str] = []
    current: list[str] = []
    for line in [line.strip() for line in normalized.splitlines() if line.strip()]:
        if REFERENCE_ENTRY_MARKER_RE.match(line) and current:
            entries.append(" ".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append(" ".join(current).strip())
    return [entry for entry in entries if entry][:limit]


def _bibliography_entry_to_candidate(entry: str, index: int) -> RecommendationCandidate | None:
    raw_reference = " ".join(entry.split())
    if not raw_reference:
        return None
    doi = normalize_doi(raw_reference)
    title = _reference_title(raw_reference)
    if not title and doi:
        title = doi
    if not title:
        return None
    source_url = doi_url(doi) or _first_reference_url(raw_reference)
    return RecommendationCandidate(
        title=title[:800],
        provider="bibliography",
        relation="bibliography_reference",
        doi=doi,
        publication_year=_reference_year(raw_reference),
        source_url=source_url,
        score=max(0.3, 0.78 - index * 0.004),
        raw_metadata={
            "provider": "bibliography",
            "relation": "bibliography_reference",
            "reference_index": index,
            "raw_reference": raw_reference[:2400],
            "doi": doi,
            "source_url": source_url,
            "parsed_title": title,
        },
    )


def _reference_title(entry: str) -> str | None:
    clean = REFERENCE_ENTRY_MARKER_RE.sub("", entry).strip()
    for pattern in (REFERENCE_QUOTED_TITLE_RE, REFERENCE_APA_TITLE_RE, REFERENCE_MARKDOWN_TITLE_RE):
        match = pattern.search(clean)
        if match:
            title = _clean_reference_title(match.group(1))
            if title:
                return title
    return None


def _clean_reference_title(value: str | None) -> str | None:
    title = unescape(value or "")
    title = re.sub(r"\s+", " ", title.replace("*", "")).strip(" .,:;\"'“”")
    if len(title) < 8:
        return None
    if DOI_RE.search(title) or REFERENCE_URL_RE.search(title):
        return None
    return title


def _reference_year(entry: str) -> int | None:
    if match := REFERENCE_YEAR_RE.search(entry):
        return int(match.group(1))
    return None


def _first_reference_url(entry: str) -> str | None:
    if match := REFERENCE_URL_RE.search(entry):
        return match.group(0).rstrip(TRAILING_DOI_PUNCTUATION)
    return None


def queue_recommendation_imports(
    db: Session,
    source_document: Document,
    recommendations: list[DocumentRecommendation],
    *,
    skip_existing: bool = True,
) -> dict[str, Any]:
    now = utc_now()
    batch = ImportBatch(
        label=f"Recommendations: {source_document.title[:180]}",
        total_files=len(recommendations),
        shared_defaults={
            "source": "recommendations",
            "source_document_id": source_document.id,
            "source_document_title": source_document.title,
            "skip_existing": skip_existing,
        },
    )
    db.add(batch)
    db.flush()

    counts = {
        "queued_count": 0,
        "skipped_existing_count": 0,
        "unavailable_count": 0,
        "failed_count": 0,
    }
    document_cache_root()
    storage = get_storage_service()

    mark_recommendation_discovery_state(db, recommendations, source_document=source_document)
    for recommendation in recommendations:
        if skip_existing and recommendation.known_status != "new":
            _add_recommendation_skip_event(
                db,
                batch=batch,
                recommendation=recommendation,
                step=recommendation.known_status,
                reason=recommendation.hidden_reason or "Recommendation already matches a known Medusa item.",
            )
            counts["skipped_existing_count"] += 1
            continue
        if not recommendation.pdf_url:
            _add_recommendation_skip_event(
                db,
                batch=batch,
                recommendation=recommendation,
                step="download_unavailable",
                reason="No open PDF URL was available from recommendation sources.",
            )
            counts["unavailable_count"] += 1
            continue
        try:
            data, content_type = _download_pdf(recommendation.pdf_url)
            checksum = hashlib.sha256(data).hexdigest()
            duplicate = _first_active_checksum_match(db, checksum)
            if skip_existing and duplicate:
                recommendation.existing_document_id = duplicate.id
                _add_recommendation_skip_event(
                    db,
                    batch=batch,
                    recommendation=recommendation,
                    step="checksum_duplicate",
                    reason="Downloaded PDF matched an existing Medusa checksum.",
                    matched_document_id=duplicate.id,
                )
                counts["skipped_existing_count"] += 1
                continue

            filename = _recommendation_filename(recommendation)
            document = Document(
                title=recommendation.title,
                authors=recommendation.authors or [],
                publication_year=recommendation.publication_year,
                journal=recommendation.journal,
                doi=recommendation.doi,
                source_url=recommendation.source_url or doi_url(recommendation.doi),
                abstract=recommendation.description,
                original_filename=filename,
                content_type=content_type,
                checksum_sha256=checksum,
                priority=source_document.priority,
                read_status="unread",
            )
            db.add(document)
            db.flush()

            key = f"documents/{checksum[:2]}/{checksum}/{document.id}/{filename}"
            stored = storage.put_bytes(key, data, content_type)
            cache_path = document_cache_path(document.id)
            cache_path.write_bytes(data)
            document.gcs_uri = stored.uri
            document.storage_status = stored.backend
            document.processing_status = "queued"
            document.metadata_evidence = {
                "file_size_bytes": len(data),
                "local_cache_path": str(cache_path),
                "document_cache_path": str(cache_path),
                "recommendation_import": {
                    "source_document_id": source_document.id,
                    "source_document_title": source_document.title,
                    "recommendation_id": recommendation.id,
                    "provider": recommendation.source_provider,
                    "relation": recommendation.source_relation,
                    "source_url": recommendation.source_url,
                    "pdf_url": recommendation.pdf_url,
                    "downloaded_at": now.isoformat(),
                },
            }
            register_document_cache(document, cache_path, source="recommendation")
            job = ImportJob(batch_id=batch.id, document_id=document.id, status="queued", current_step="stored")
            db.add(job)
            recommendation.imported_document_id = document.id
            recommendation.existing_document_id = document.id
            recommendation.status = "import_queued"
            counts["queued_count"] += 1
        except Exception as exc:
            _add_recommendation_skip_event(
                db,
                batch=batch,
                recommendation=recommendation,
                step="download_failed",
                reason=str(exc),
                level="error",
                status="failed",
            )
            recommendation.status = "download_failed"
            counts["failed_count"] += 1

    refresh_import_batch_progress(db, batch)
    return {"batch_id": batch.id, **counts}


def resolve_open_pdf_candidate_for_doi(
    doi: str,
    *,
    title: str | None = None,
    source_url: str | None = None,
    source_provider: str | None = None,
) -> RecommendationCandidate | None:
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    candidates: dict[str, RecommendationCandidate] = {}
    _merge_candidate(
        candidates,
        RecommendationCandidate(
            title=title or normalized,
            provider=source_provider or "doi_stash",
            relation="doi_lookup",
            doi=normalized,
            source_url=source_url or doi_url(normalized),
            raw_metadata={"provider": source_provider or "doi_stash", "relation": "doi_lookup", "doi": normalized},
        ),
    )
    for resolver in (_fetch_openalex_doi_candidate, _fetch_semantic_scholar_doi_candidate, _fetch_crossref_doi_candidate):
        try:
            if candidate := resolver(normalized):
                _merge_candidate(candidates, candidate)
        except Exception:
            continue
    for _name, enricher in _enabled_enrichers():
        try:
            for candidate in enricher(list(candidates.values()), 1):
                _merge_candidate(candidates, candidate)
        except Exception:
            continue
    pdf_candidates = [candidate for candidate in candidates.values() if candidate.pdf_url]
    if not pdf_candidates:
        return None
    return sorted(pdf_candidates, key=_candidate_pdf_priority, reverse=True)[0]


def queue_doi_stash_open_pdf_import(db: Session, stash: DoiStash) -> dict[str, Any]:
    now = utc_now()
    batch = ImportBatch(
        label=f"Stash DOI: {stash.doi}",
        total_files=1,
        shared_defaults={
            "source": "doi_stash_doi_import",
            "doi_stash_id": stash.id,
            "doi": stash.doi,
        },
    )
    db.add(batch)
    db.flush()

    counts = {
        "queued_count": 0,
        "skipped_existing_count": 0,
        "unavailable_count": 0,
        "failed_count": 0,
    }
    candidate = resolve_open_pdf_candidate_for_doi(
        stash.doi,
        title=stash.title,
        source_url=stash.source_url,
        source_provider=stash.source_provider,
    )
    if not candidate or not candidate.pdf_url:
        message = "No open PDF URL was available from DOI resolvers."
        _add_doi_stash_import_event(
            db,
            batch=batch,
            stash=stash,
            step="download_unavailable",
            reason=message,
        )
        _remember_doi_stash_import_attempt(stash, status="unavailable", message=message, candidate=candidate, now=now)
        refresh_import_batch_progress(db, batch)
        counts["unavailable_count"] = 1
        return {"batch_id": batch.id, "message": message, **counts}

    _remember_doi_stash_import_attempt(stash, status="resolving", message=None, candidate=candidate, now=now)
    try:
        data, content_type = _download_pdf(candidate.pdf_url)
        checksum = hashlib.sha256(data).hexdigest()
        filename = _candidate_filename(candidate)
        duplicate = _first_active_checksum_match(db, checksum)
        if duplicate:
            job = _add_doi_stash_import_event(
                db,
                batch=batch,
                stash=stash,
                step="checksum_duplicate",
                reason="Downloaded PDF matched an existing Medusa checksum.",
                candidate=candidate,
                document_id=duplicate.id,
            )
            stash.imported_document_id = duplicate.id
            stash.import_job_id = job.id
            stash.status = "imported"
            stash.uploaded_filename = filename
            stash.imported_at = now
            _remember_doi_stash_import_attempt(stash, status="duplicate", message=None, candidate=candidate, now=now)
            refresh_import_batch_progress(db, batch)
            counts["skipped_existing_count"] = 1
            return {"batch_id": batch.id, "message": "Downloaded PDF matched an existing Medusa document.", **counts}

        source_document = stash.source_document
        document = Document(
            title=candidate.title or stash.title or stash.doi,
            authors=candidate.authors or [],
            publication_year=candidate.publication_year,
            journal=candidate.journal,
            doi=normalize_doi(candidate.doi) or stash.doi,
            source_url=candidate.source_url or stash.source_url or doi_url(stash.doi),
            abstract=candidate.description,
            original_filename=filename,
            content_type=content_type,
            checksum_sha256=checksum,
            priority=source_document.priority if source_document else "normal",
            read_status="unread",
        )
        db.add(document)
        db.flush()

        storage = get_storage_service()
        key = f"documents/{checksum[:2]}/{checksum}/{document.id}/{filename}"
        stored = storage.put_bytes(key, data, content_type)
        cache_path = document_cache_path(document.id)
        cache_path.write_bytes(data)
        document.gcs_uri = stored.uri
        document.storage_status = stored.backend
        document.processing_status = "queued"
        document.metadata_evidence = {
            "file_size_bytes": len(data),
            "local_cache_path": str(cache_path),
            "document_cache_path": str(cache_path),
            "doi_stash_import": {
                "id": stash.id,
                "doi": stash.doi,
                "title": stash.title,
                "source_url": stash.source_url,
                "source_provider": stash.source_provider,
                "recommendation_id": stash.recommendation_id,
                "source_document_id": stash.source_document_id,
                "resolver_provider": candidate.provider,
                "resolver_relation": candidate.relation,
                "resolver_source_url": candidate.source_url,
                "resolver_pdf_url": candidate.pdf_url,
                "downloaded_at": now.isoformat(),
            },
        }
        register_document_cache(document, cache_path, source="doi_stash_doi_import")
        job = ImportJob(batch_id=batch.id, document_id=document.id, status="queued", current_step="stored")
        db.add(job)
        db.flush()
        stash.imported_document_id = document.id
        stash.import_job_id = job.id
        stash.status = "import_queued"
        stash.uploaded_filename = filename
        _remember_doi_stash_import_attempt(stash, status="queued", message=None, candidate=candidate, now=now)
        refresh_import_batch_progress(db, batch)
        counts["queued_count"] = 1
        return {"batch_id": batch.id, "message": "Queued DOI import.", **counts}
    except Exception as exc:
        message = str(exc)
        job = _add_doi_stash_import_event(
            db,
            batch=batch,
            stash=stash,
            step="download_failed",
            reason=message,
            level="error",
            status="failed",
            candidate=candidate,
        )
        stash.import_job_id = job.id
        stash.status = "import_failed"
        _remember_doi_stash_import_attempt(stash, status="failed", message=message, candidate=candidate, now=now)
        refresh_import_batch_progress(db, batch)
        counts["failed_count"] = 1
        return {"batch_id": batch.id, "message": message, **counts}


def _enabled_fetchers():
    settings = get_settings()
    if settings.recommendations_enable_openalex:
        yield "openalex", fetch_openalex_recommendations
    if settings.recommendations_enable_semantic_scholar:
        yield "semantic_scholar", fetch_semantic_scholar_recommendations
    if settings.recommendations_enable_crossref:
        yield "crossref", fetch_crossref_recommendations


def _enabled_enrichers():
    settings = get_settings()
    if settings.recommendations_enable_unpaywall:
        yield "unpaywall", enrich_unpaywall_recommendations
    if settings.recommendations_enable_arxiv:
        yield "arxiv", enrich_arxiv_recommendations


def _fetch_openalex_doi_candidate(doi: str) -> RecommendationCandidate | None:
    settings = get_settings()
    if not settings.recommendations_enable_openalex:
        return None
    with _client() as client:
        response = client.get(f"https://api.openalex.org/works/{quote(f'https://doi.org/{doi}', safe=':/')}", params=_params())
        response.raise_for_status()
        return _openalex_work_to_candidate(response.json(), "doi_lookup")


def _fetch_semantic_scholar_doi_candidate(doi: str) -> RecommendationCandidate | None:
    settings = get_settings()
    if not settings.recommendations_enable_semantic_scholar:
        return None
    headers = {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {}
    fields = "paperId,title,abstract,venue,year,externalIds,openAccessPdf,url,authors"
    with httpx.Client(
        timeout=settings.recommendations_request_timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = client.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}",
            params={"fields": fields},
        )
        response.raise_for_status()
        return _semantic_scholar_paper_to_candidate(response.json(), "doi_lookup")


def _fetch_crossref_doi_candidate(doi: str) -> RecommendationCandidate | None:
    settings = get_settings()
    if not settings.recommendations_enable_crossref:
        return None
    with _client() as client:
        response = client.get(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        response.raise_for_status()
        return _crossref_work_to_candidate(response.json().get("message") or {}, "doi_lookup")


def _client() -> httpx.Client:
    settings = get_settings()
    headers = {"User-Agent": "Medusa local research library (mailto:admin@medusa.local)"}
    return httpx.Client(
        timeout=settings.recommendations_request_timeout_seconds,
        follow_redirects=True,
        headers=headers,
    )


def _params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    params = dict(extra or {})
    mailto = settings.openalex_mailto or settings.admin_email
    if mailto:
        params["mailto"] = mailto
    return params


def fetch_openalex_recommendations(document: Document, limit: int) -> list[RecommendationCandidate]:
    doi = normalize_doi(document.doi)
    if not doi:
        return []
    with _client() as client:
        work_url = f"https://api.openalex.org/works/{quote(f'https://doi.org/{doi}', safe=':/')}"
        work_response = client.get(work_url, params=_params())
        work_response.raise_for_status()
        work = work_response.json()
        relation_by_id: dict[str, str] = {}
        for raw_id in work.get("related_works") or []:
            if work_id := _openalex_work_id(raw_id):
                relation_by_id.setdefault(work_id, "related")
        for raw_id in work.get("referenced_works") or []:
            if work_id := _openalex_work_id(raw_id):
                relation_by_id.setdefault(work_id, "referenced")

        candidates: list[RecommendationCandidate] = []
        for chunk in _chunks(list(relation_by_id)[: max(limit * 2, limit)], 50):
            response = client.get(
                "https://api.openalex.org/works",
                params=_params({"filter": f"openalex_id:{'|'.join(chunk)}", "per-page": str(len(chunk))}),
            )
            response.raise_for_status()
            for item in response.json().get("results") or []:
                work_id = _openalex_work_id(item.get("id") or "")
                candidate = _openalex_work_to_candidate(item, relation_by_id.get(work_id, "related"))
                if candidate:
                    candidates.append(candidate)
                if len(candidates) >= limit:
                    return candidates
        return candidates[:limit]


def fetch_semantic_scholar_recommendations(document: Document, limit: int) -> list[RecommendationCandidate]:
    doi = normalize_doi(document.doi)
    if not doi:
        return []
    settings = get_settings()
    headers = {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {}
    fields = (
        "paperId,title,abstract,venue,year,externalIds,openAccessPdf,url,authors,"
        "references.paperId,references.title,references.abstract,references.venue,references.year,"
        "references.externalIds,references.openAccessPdf,references.url,references.authors,"
        "citations.paperId,citations.title,citations.abstract,citations.venue,citations.year,"
        "citations.externalIds,citations.openAccessPdf,citations.url,citations.authors"
    )
    candidates: list[RecommendationCandidate] = []
    with httpx.Client(
        timeout=settings.recommendations_request_timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        paper_response = client.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}",
            params={"fields": fields},
        )
        paper_response.raise_for_status()
        paper = paper_response.json()
        paper_id = paper.get("paperId")
        if paper_id:
            try:
                rec_response = client.post(
                    "https://api.semanticscholar.org/recommendations/v1/papers",
                    params={"fields": "paperId,title,abstract,venue,year,externalIds,openAccessPdf,url,authors"},
                    json={"positivePaperIds": [paper_id]},
                )
                rec_response.raise_for_status()
                for item in rec_response.json().get("recommendedPapers") or []:
                    if candidate := _semantic_scholar_paper_to_candidate(item, "recommended"):
                        candidates.append(candidate)
                    if len(candidates) >= limit:
                        return candidates
            except Exception:
                pass
        for relation, items in (("reference", paper.get("references") or []), ("citation", paper.get("citations") or [])):
            for item in items:
                if candidate := _semantic_scholar_paper_to_candidate(item, relation):
                    candidates.append(candidate)
                if len(candidates) >= limit:
                    return candidates
    return candidates[:limit]


def fetch_crossref_recommendations(document: Document, limit: int) -> list[RecommendationCandidate]:
    doi = normalize_doi(document.doi)
    if not doi:
        return []
    candidates: list[RecommendationCandidate] = []
    with _client() as client:
        response = client.get(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        response.raise_for_status()
        message = response.json().get("message") or {}
        for reference in message.get("reference") or []:
            reference_doi = normalize_doi(reference.get("DOI") or reference.get("doi"))
            if reference_doi:
                try:
                    ref_response = client.get(f"https://api.crossref.org/works/{quote(reference_doi, safe='')}")
                    ref_response.raise_for_status()
                    ref_message = ref_response.json().get("message") or {}
                    if candidate := _crossref_work_to_candidate(ref_message, "reference"):
                        candidates.append(candidate)
                except Exception:
                    if candidate := _crossref_reference_to_candidate(reference):
                        candidates.append(candidate)
            elif candidate := _crossref_reference_to_candidate(reference):
                candidates.append(candidate)
            if len(candidates) >= limit:
                return candidates
    return candidates[:limit]


def enrich_unpaywall_recommendations(
    candidates: list[RecommendationCandidate],
    _limit: int,
) -> list[RecommendationCandidate]:
    email = _unpaywall_contact_email()
    if not email:
        return []
    doi_candidates = [candidate for candidate in candidates if normalize_doi(candidate.doi)]
    if not doi_candidates:
        return []
    enriched: list[RecommendationCandidate] = []
    with _client() as client:
        for candidate in doi_candidates:
            doi = normalize_doi(candidate.doi)
            if not doi:
                continue
            response = client.get(f"https://api.unpaywall.org/v2/{quote(doi, safe='')}", params={"email": email})
            if response.status_code == 404:
                continue
            response.raise_for_status()
            if unpaywall_candidate := _unpaywall_work_to_candidate(candidate, response.json()):
                enriched.append(unpaywall_candidate)
    return enriched


def enrich_arxiv_recommendations(
    candidates: list[RecommendationCandidate],
    _limit: int,
) -> list[RecommendationCandidate]:
    settings = get_settings()
    enriched: list[RecommendationCandidate] = []
    direct_keys: set[str] = set()
    for candidate in candidates:
        if candidate.pdf_url:
            continue
        arxiv_id = _arxiv_id_from_candidate(candidate)
        if not arxiv_id:
            continue
        direct_keys.add(candidate.match_key)
        enriched.append(_arxiv_id_candidate(candidate, arxiv_id, relation="metadata_id"))

    lookup_limit = max(0, settings.recommendations_arxiv_title_lookups)
    if lookup_limit <= 0:
        return enriched
    title_candidates = [
        candidate
        for candidate in candidates
        if not candidate.pdf_url and candidate.match_key not in direct_keys and _arxiv_query_phrase(candidate.title)
    ][:lookup_limit]
    if not title_candidates:
        return enriched
    with _client() as client:
        enriched.extend(_fetch_arxiv_title_matches(client, title_candidates))
    return enriched


def _merge_candidate(candidates: dict[str, RecommendationCandidate], candidate: RecommendationCandidate) -> None:
    key = candidate.match_key
    existing = candidates.get(key)
    if not existing:
        candidates[key] = candidate
        return
    existing_pdf_priority = _candidate_pdf_priority(existing)
    candidate_pdf_priority = _candidate_pdf_priority(candidate)
    providers = unique_join(existing.provider, candidate.provider)
    relations = unique_join(existing.relation, candidate.relation)
    existing.provider = providers
    existing.relation = relations
    for attr in ("doi", "journal", "description", "external_id", "source_url", "publication_year"):
        if getattr(existing, attr) in (None, "", []):
            setattr(existing, attr, getattr(candidate, attr))
    if candidate.pdf_url and (not existing.pdf_url or candidate_pdf_priority > existing_pdf_priority):
        existing.pdf_url = candidate.pdf_url
    if not existing.authors and candidate.authors:
        existing.authors = candidate.authors
    if candidate.score is not None:
        existing.score = max(existing.score or 0, candidate.score)
    existing.raw_metadata = {
        "sources": [*(existing.raw_metadata.get("sources") or [existing.raw_metadata]), candidate.raw_metadata],
    }


def unique_join(left: str | None, right: str | None) -> str:
    parts = []
    for value in (left, right):
        for part in str(value or "").split(","):
            stripped = part.strip()
            if stripped and stripped not in parts:
                parts.append(stripped)
    return ", ".join(parts)


def _candidate_pdf_priority(candidate: RecommendationCandidate) -> int:
    if not candidate.pdf_url:
        return 0
    priority = 1
    for provider in str(candidate.provider or "").split(","):
        priority = max(priority, PDF_PROVIDER_PRIORITY.get(provider.strip(), 1))
    return priority


def _unpaywall_contact_email() -> str | None:
    settings = get_settings()
    for value in (settings.unpaywall_email, settings.openalex_mailto, settings.admin_email):
        email = (value or "").strip()
        if EMAIL_RE.fullmatch(email) and not email.lower().endswith(".local"):
            return email
    return None


def _unpaywall_work_to_candidate(
    source: RecommendationCandidate,
    work: dict[str, Any],
) -> RecommendationCandidate | None:
    location = _unpaywall_best_location(work)
    pdf_url = _unpaywall_pdf_url(location, work)
    if not pdf_url:
        return None
    title = unescape(work.get("title") or source.title).strip()
    if not title:
        return None
    return RecommendationCandidate(
        title=title,
        provider="unpaywall",
        relation="open_access",
        doi=normalize_doi(work.get("doi") or source.doi),
        authors=_unpaywall_authors(work) or source.authors,
        publication_year=_int(work.get("year")) or source.publication_year,
        journal=unescape(work.get("journal_name") or "") or source.journal,
        description=source.description,
        external_id=normalize_doi(work.get("doi") or source.doi),
        source_url=(location or {}).get("url") or work.get("doi_url") or source.source_url,
        pdf_url=pdf_url,
        score=source.score,
        raw_metadata={
            "provider": "unpaywall",
            "relation": "open_access",
            "is_oa": work.get("is_oa"),
            "oa_status": work.get("oa_status"),
            "best_oa_location": location,
            "doi": work.get("doi"),
            "title": work.get("title"),
            "year": work.get("year"),
            "journal_name": work.get("journal_name"),
        },
    )


def _unpaywall_best_location(work: dict[str, Any]) -> dict[str, Any] | None:
    best = work.get("best_oa_location")
    if isinstance(best, dict) and (best.get("url_for_pdf") or best.get("url")):
        return best
    for location in work.get("oa_locations") or []:
        if isinstance(location, dict) and (location.get("url_for_pdf") or location.get("url")):
            return location
    return None


def _unpaywall_pdf_url(location: dict[str, Any] | None, work: dict[str, Any]) -> str | None:
    if isinstance(location, dict) and location.get("url_for_pdf"):
        return location["url_for_pdf"]
    for item in work.get("oa_locations") or []:
        if isinstance(item, dict) and item.get("url_for_pdf"):
            return item["url_for_pdf"]
    return None


def _unpaywall_authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    authors = []
    for author in work.get("z_authors") or []:
        given = unescape(author.get("given") or "")
        family = unescape(author.get("family") or "")
        name = unescape(author.get("name") or "")
        if not family and name:
            parts = name.split()
            given = " ".join(parts[:-1])
            family = parts[-1] if parts else name
        if given or family:
            authors.append({"given": given, "family": family, "affiliation": None})
    return authors


def _arxiv_id_from_candidate(candidate: RecommendationCandidate) -> str | None:
    for value in _candidate_raw_values(candidate.raw_metadata):
        if arxiv_id := _normalize_arxiv_id(value):
            return arxiv_id
    if arxiv_id := _normalize_arxiv_id(candidate.external_id):
        return arxiv_id
    if arxiv_id := _normalize_arxiv_id(candidate.source_url):
        return arxiv_id
    if arxiv_id := _normalize_arxiv_id(candidate.pdf_url):
        return arxiv_id
    return None


def _candidate_raw_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"arxiv", "arxiv_id"} and isinstance(child, str):
                values.append(child)
            elif str(key).lower() in {"externalids", "ids"} and isinstance(child, dict):
                values.extend(str(item) for subkey, item in child.items() if str(subkey).lower() == "arxiv")
            values.extend(_candidate_raw_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_candidate_raw_values(child))
    elif isinstance(value, str) and ("arxiv" in value.lower() or ARXIV_ID_RE.match(value.strip())):
        values.append(value)
    return values


def _normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if match := ARXIV_ABS_RE.search(text):
        text = match.group(1)
    text = text.removesuffix(".pdf").strip("/")
    match = ARXIV_ID_RE.match(text)
    return match.group(1) if match else None


def _arxiv_id_candidate(source: RecommendationCandidate, arxiv_id: str, *, relation: str) -> RecommendationCandidate:
    clean_id = _normalize_arxiv_id(arxiv_id) or arxiv_id
    return RecommendationCandidate(
        title=source.title,
        provider="arxiv",
        relation=relation,
        doi=source.doi,
        authors=source.authors,
        publication_year=source.publication_year,
        journal=source.journal,
        description=source.description,
        external_id=f"arXiv:{clean_id}",
        source_url=f"https://arxiv.org/abs/{clean_id}",
        pdf_url=f"https://arxiv.org/pdf/{clean_id}",
        score=source.score,
        raw_metadata={"provider": "arxiv", "relation": relation, "arxiv_id": clean_id},
    )


def _fetch_arxiv_title_matches(
    client: httpx.Client,
    candidates: list[RecommendationCandidate],
) -> list[RecommendationCandidate]:
    query_parts = [f'ti:"{phrase}"' for candidate in candidates if (phrase := _arxiv_query_phrase(candidate.title))]
    if not query_parts:
        return []
    search_query = f"({' OR '.join(query_parts)})" if len(query_parts) > 1 else query_parts[0]
    response = client.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": search_query,
            "start": "0",
            "max_results": str(max(len(candidates) * 3, 12)),
            "sortBy": "relevance",
            "sortOrder": "descending",
        },
    )
    response.raise_for_status()
    entries = _parse_arxiv_feed(response.text)
    if not entries:
        return []
    enriched: list[RecommendationCandidate] = []
    for candidate in candidates:
        match = _best_arxiv_entry(candidate, entries)
        if match:
            enriched.append(_arxiv_entry_to_candidate(candidate, match))
    return enriched


def _arxiv_query_phrase(title: str | None) -> str:
    text = " ".join(unescape(title or "").replace('"', " ").split())
    return text[:180]


def _parse_arxiv_feed(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    entries: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        title = " ".join((entry.findtext("atom:title", default="", namespaces=ARXIV_NS) or "").split())
        arxiv_id = _normalize_arxiv_id(entry.findtext("atom:id", default="", namespaces=ARXIV_NS))
        if not title or not arxiv_id:
            continue
        links = []
        pdf_url = None
        source_url = f"https://arxiv.org/abs/{arxiv_id}"
        for link in entry.findall("atom:link", ARXIV_NS):
            href = link.attrib.get("href")
            if not href:
                continue
            links.append(dict(link.attrib))
            link_type = str(link.attrib.get("type") or "").lower()
            link_title = str(link.attrib.get("title") or "").lower()
            if link_title == "pdf" or "pdf" in link_type:
                pdf_url = href
            elif link.attrib.get("rel") == "alternate":
                source_url = href
        entries.append(
            {
                "title": title,
                "arxiv_id": arxiv_id,
                "doi": entry.findtext("arxiv:doi", default=None, namespaces=ARXIV_NS),
                "journal_ref": entry.findtext("arxiv:journal_ref", default=None, namespaces=ARXIV_NS),
                "summary": " ".join((entry.findtext("atom:summary", default="", namespaces=ARXIV_NS) or "").split()),
                "published": entry.findtext("atom:published", default=None, namespaces=ARXIV_NS),
                "authors": [
                    {"given": " ".join(name.split()[:-1]), "family": name.split()[-1], "affiliation": None}
                    for author in entry.findall("atom:author", ARXIV_NS)
                    if (name := " ".join((author.findtext("atom:name", default="", namespaces=ARXIV_NS) or "").split()))
                    and name.split()
                ],
                "source_url": source_url,
                "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                "links": links,
            }
        )
    return entries


def _best_arxiv_entry(candidate: RecommendationCandidate, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    best_score = 0.0
    best_entry: dict[str, Any] | None = None
    candidate_doi = normalize_doi(candidate.doi)
    for entry in entries:
        entry_doi = normalize_doi(entry.get("doi"))
        if candidate_doi and entry_doi == candidate_doi:
            return entry
        score = normalized_title_similarity(candidate.title, entry.get("title") or "")
        if score > best_score:
            best_score = score
            best_entry = entry
    return best_entry if best_score >= 0.94 else None


def _arxiv_entry_to_candidate(
    source: RecommendationCandidate,
    entry: dict[str, Any],
) -> RecommendationCandidate:
    year = None
    published = entry.get("published")
    if isinstance(published, str) and len(published) >= 4 and published[:4].isdigit():
        year = int(published[:4])
    return RecommendationCandidate(
        title=entry.get("title") or source.title,
        provider="arxiv",
        relation="title_match",
        doi=normalize_doi(entry.get("doi")) or source.doi,
        authors=entry.get("authors") or source.authors,
        publication_year=year or source.publication_year,
        journal=entry.get("journal_ref") or source.journal,
        description=entry.get("summary") or source.description,
        external_id=f"arXiv:{entry.get('arxiv_id')}",
        source_url=entry.get("source_url"),
        pdf_url=entry.get("pdf_url"),
        score=source.score,
        raw_metadata={"provider": "arxiv", "relation": "title_match", "entry": entry},
    )


def _apply_candidate(row: DocumentRecommendation, candidate: RecommendationCandidate) -> None:
    previous_metadata = row.raw_metadata if isinstance(row.raw_metadata, dict) else {}
    previous_v2 = previous_metadata.get(RECOMMENDATION_V2_METADATA_KEY)
    row.match_key = candidate.match_key
    row.title = candidate.title[:800]
    row.doi = normalize_doi(candidate.doi)
    row.authors = candidate.authors or []
    row.publication_year = candidate.publication_year
    row.journal = candidate.journal[:300] if candidate.journal else None
    row.description = candidate.description
    row.source_provider = candidate.provider[:160]
    row.source_relation = candidate.relation[:120] if candidate.relation else None
    row.external_id = candidate.external_id[:360] if candidate.external_id else None
    row.source_url = candidate.source_url or doi_url(candidate.doi)
    row.pdf_url = candidate.pdf_url
    row.score = candidate.score
    row.status = "candidate" if row.status in {"stale", "download_failed"} else row.status or "candidate"
    row.raw_metadata = candidate.raw_metadata or {}
    if isinstance(previous_v2, dict):
        row.raw_metadata[RECOMMENDATION_V2_METADATA_KEY] = previous_v2
    row.last_seen_at = utc_now()


def mark_existing_library_matches(db: Session, recommendations: list[DocumentRecommendation], *, source_document_id: str) -> None:
    source_document = db.get(Document, source_document_id)
    if source_document:
        mark_recommendation_discovery_state(db, recommendations, source_document=source_document)


def mark_recommendation_discovery_state(
    db: Session,
    recommendations: list[DocumentRecommendation],
    *,
    source_document: Document,
) -> None:
    if not recommendations:
        return
    visible_documents = filter_library_visible_documents(db.query(Document)).filter(Document.id != source_document.id).all()
    active_import_documents = (
        db.query(Document)
        .filter(
            Document.deleted_at.is_(None),
            Document.id != source_document.id,
            Document.processing_status.in_(RECOMMENDATION_IMPORT_KNOWN_STATUSES),
        )
        .all()
    )
    active_stashes = db.query(DoiStash).filter(DoiStash.deleted_at.is_(None), DoiStash.status != "removed").all()
    stash_by_doi = {normalize_doi(stash.doi): stash for stash in active_stashes if normalize_doi(stash.doi)}

    for recommendation in recommendations:
        library_match, library_basis = _best_document_match(visible_documents, recommendation)
        active_match, active_basis = _best_document_match(active_import_documents, recommendation)
        imported_document = recommendation.imported_document
        if recommendation.imported_document_id and not imported_document:
            imported_document = db.get(Document, recommendation.imported_document_id)
        stash_match = stash_by_doi.get(normalize_doi(recommendation.doi))

        known_status = "new"
        hidden_reason = None
        match_basis = library_basis
        matched_document_id = library_match.id if library_match else None
        matched_document_title = library_match.title if library_match else None

        if imported_document and imported_document.deleted_at is None:
            if imported_document.processing_status in LIBRARY_VISIBLE_DOCUMENT_STATUSES:
                known_status = "in_library"
                hidden_reason = "Already imported from a recommendation."
                matched_document_id = imported_document.id
                matched_document_title = imported_document.title
                match_basis = match_basis or "recommendation_import"
                recommendation.existing_document_id = imported_document.id
            elif imported_document.processing_status in RECOMMENDATION_IMPORT_KNOWN_STATUSES:
                known_status = "active_import"
                hidden_reason = "Already queued or staged for import."
                matched_document_id = imported_document.id
                matched_document_title = imported_document.title
                match_basis = "recommendation_import"
                recommendation.existing_document_id = None
        elif library_match:
            known_status = "in_library"
            hidden_reason = f"Matched existing library document by {library_basis.replace('_', ' ')}."
            recommendation.existing_document_id = library_match.id
        elif active_match:
            known_status = "active_import"
            hidden_reason = f"Matched an active import by {active_basis.replace('_', ' ')}."
            match_basis = active_basis
            matched_document_id = active_match.id
            matched_document_title = active_match.title
            recommendation.existing_document_id = None
        elif stash_match:
            known_status = "stashed"
            hidden_reason = "Already saved to DOI Stashes."
            match_basis = "doi_stash"
            recommendation.existing_document_id = None
        else:
            recommendation.existing_document_id = None

        relation_family = _classify_relation_family(source_document, recommendation)
        _write_recommendation_v2_metadata(
            recommendation,
            {
                "relation_family": relation_family,
                "known_status": known_status,
                "hidden_reason": hidden_reason,
                "match_basis": match_basis,
                "matched_document_id": matched_document_id,
                "matched_document_title": matched_document_title,
                "doi_stash_id": stash_match.id if stash_match else None,
                "reason_chips": _recommendation_reason_chips(recommendation, relation_family, known_status),
                "evidence": _recommendation_v2_evidence(
                    recommendation,
                    relation_family=relation_family,
                    known_status=known_status,
                    hidden_reason=hidden_reason,
                    match_basis=match_basis,
                    matched_document_id=matched_document_id,
                ),
            },
        )


def _write_recommendation_v2_metadata(row: DocumentRecommendation, updates: dict[str, Any]) -> None:
    metadata = dict(row.raw_metadata or {})
    v2_metadata = metadata.get(RECOMMENDATION_V2_METADATA_KEY)
    if not isinstance(v2_metadata, dict):
        v2_metadata = {}
    v2_metadata.update(updates)
    metadata[RECOMMENDATION_V2_METADATA_KEY] = v2_metadata
    row.raw_metadata = metadata


def _best_document_match(documents: list[Document], recommendation: DocumentRecommendation) -> tuple[Document | None, str | None]:
    recommendation_doi = normalize_doi(recommendation.doi)
    if recommendation_doi:
        for document in documents:
            if normalize_doi(document.doi) == recommendation_doi:
                return document, "doi"
    best_document: Document | None = None
    best_basis: str | None = None
    best_score = 0.0
    for document in documents:
        basis, score = _strong_metadata_match_basis(document, recommendation)
        if basis and score > best_score:
            best_document = document
            best_basis = basis
            best_score = score
    return best_document, best_basis


def _strong_metadata_match_basis(document: Document, recommendation: DocumentRecommendation) -> tuple[str | None, float]:
    if not recommendation.title:
        return None, 0.0
    title_score = normalized_title_similarity(document.title, recommendation.title)
    if title_score < 0.94:
        return None, title_score
    supports: list[str] = []
    if _publication_year_matches(document.publication_year, recommendation.publication_year):
        supports.append("year")
    if not _author_families(document.authors).isdisjoint(_author_families(recommendation.authors)):
        supports.append("author")
    if title_score >= 0.985:
        return ("title" if not supports else f"title_{'_'.join(supports)}"), title_score
    if title_score >= 0.96 and supports:
        return f"title_{'_'.join(supports)}", title_score
    if len(supports) >= 2:
        return f"title_{'_'.join(supports)}", title_score
    return None, title_score


def _publication_year_matches(left: int | None, right: int | None) -> bool:
    return bool(left and right and abs(left - right) <= 1)


def _author_families(authors: list[dict[str, Any]] | None) -> set[str]:
    families: set[str] = set()
    for author in authors or []:
        value = None
        if isinstance(author, dict):
            value = author.get("family") or author.get("name")
            if not value and (author.get("given") or author.get("full_name")):
                value = author.get("full_name") or author.get("given")
        elif isinstance(author, str):
            value = author
        if not value:
            continue
        cleaned = normalize_title_key(str(value)).split()
        if cleaned:
            families.add(cleaned[-1])
    return families


def _provider_tokens(value: str | None) -> set[str]:
    return {token.strip().lower() for token in (value or "").split(",") if token.strip()}


def _classify_relation_family(source_document: Document, recommendation: DocumentRecommendation) -> str:
    relation_text = normalize_title_key(recommendation.source_relation)
    title_text = normalize_title_key(recommendation.title)
    description_text = normalize_title_key(recommendation.description)
    journal_text = normalize_title_key(recommendation.journal)
    metadata = recommendation.raw_metadata if isinstance(recommendation.raw_metadata, dict) else {}
    type_text = normalize_title_key(str(metadata.get("type") or metadata.get("work_type") or ""))
    combined = " ".join([relation_text, title_text, description_text, journal_text, type_text])
    terms = set(combined.split())

    if terms & CONTRAST_TERMS:
        return "contrasting"
    if terms & METHOD_TERMS:
        return "methods"
    if terms & REFERENCE_MATERIAL_TERMS:
        return "reference_material"
    if source_document.publication_year and recommendation.publication_year:
        if recommendation.publication_year > source_document.publication_year:
            return "newer"
        if recommendation.publication_year < source_document.publication_year and (
            "reference" in terms or "referenced" in terms or recommendation.publication_year <= source_document.publication_year - 3
        ):
            return "foundational"
    if "reference" in terms or "referenced" in terms:
        return "foundational"
    if "open" in terms and "access" in terms and recommendation.has_pdf:
        return "open_pdf"
    return "closest"


def _recommendation_reason_chips(
    recommendation: DocumentRecommendation,
    relation_family: str,
    known_status: str,
) -> list[str]:
    chips = [
        RECOMMENDATION_KNOWN_LABELS.get(known_status, known_status.replace("_", " ").title()),
        RECOMMENDATION_FAMILY_LABELS.get(relation_family, relation_family.replace("_", " ").title()),
    ]
    relation_chip = _relation_reason_chip(recommendation.source_relation)
    if relation_chip:
        chips.append(relation_chip)
    if recommendation.has_pdf:
        chips.append("Open PDF")
    if normalize_doi(recommendation.doi):
        chips.append("DOI")
    for provider in _provider_tokens(recommendation.source_provider):
        if provider in {"unpaywall", "arxiv"}:
            chips.append(provider.replace("_", " ").title())
    return _unique_reason_chips(chips)


def _relation_reason_chip(relation: str | None) -> str | None:
    relation_key = normalize_title_key(relation)
    if not relation_key:
        return None
    if "referenced" in relation_key or "reference" in relation_key:
        return "Cited by source"
    if "cited by" in relation_key or "citing" in relation_key:
        return "Cites source"
    if "open access" in relation_key:
        return "Open access evidence"
    if "title match" in relation_key:
        return "Title match"
    if "recommended" in relation_key:
        return "Recommended"
    if "related" in relation_key:
        return "Related work"
    return relation.replace("_", " ").strip().title() if relation else None


def _unique_reason_chips(values: list[str]) -> list[str]:
    chips: list[str] = []
    seen: set[str] = set()
    for value in values:
        chip = " ".join(str(value).split())
        key = chip.lower()
        if chip and key not in seen:
            chips.append(chip)
            seen.add(key)
    return chips[:7]


def _recommendation_v2_evidence(
    recommendation: DocumentRecommendation,
    *,
    relation_family: str,
    known_status: str,
    hidden_reason: str | None,
    match_basis: str | None,
    matched_document_id: str | None,
) -> dict[str, Any]:
    return {
        "provider": recommendation.source_provider,
        "relation": recommendation.source_relation,
        "relation_family": relation_family,
        "doi": normalize_doi(recommendation.doi),
        "source_url": recommendation.source_url,
        "pdf_url": recommendation.pdf_url,
        "abstract_snippet": recommendation.description[:420] if recommendation.description else None,
        "known_status": known_status,
        "duplicate_suppression_reason": hidden_reason,
        "match_basis": match_basis,
        "matched_document_id": matched_document_id,
        "open_pdf_evidence": bool(recommendation.pdf_url),
    }


def _best_title_match(documents: list[Document], title: str) -> Document | None:
    best: tuple[float, Document | None] = (0.0, None)
    for document in documents:
        score = normalized_title_similarity(document.title, title)
        if score > best[0]:
            best = (score, document)
    return best[1] if best[0] >= 0.94 else None


def _first_active_checksum_match(db: Session, checksum: str) -> Document | None:
    return (
        db.query(Document)
        .filter(library_visible_document_filter(), Document.checksum_sha256 == checksum)
        .order_by(Document.created_at.desc(), Document.id)
        .first()
    )


def _download_pdf(url: str) -> tuple[bytes, str]:
    settings = get_settings()
    response = httpx.get(
        url,
        timeout=settings.recommendation_download_timeout_seconds,
        follow_redirects=True,
        headers={
            "User-Agent": "Medusa local research library (mailto:admin@medusa.local)",
            "Accept": "application/pdf, application/octet-stream;q=0.9, */*;q=0.2",
        },
    )
    response.raise_for_status()
    data = response.content
    max_bytes = settings.recommendation_download_max_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise RuntimeError(f"PDF is larger than the configured {settings.recommendation_download_max_mb} MB limit.")
    content_type = response.headers.get("content-type", "application/pdf").split(";")[0].strip() or "application/pdf"
    if "pdf" not in content_type.lower() and not data.startswith(b"%PDF"):
        raise RuntimeError("Downloaded content was not a PDF.")
    return data, "application/pdf"


def _recommendation_filename(recommendation: DocumentRecommendation) -> str:
    base = recommendation.doi or recommendation.title or recommendation.id
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._")[:96]
    return f"{slug or recommendation.id}.pdf"


def _candidate_filename(candidate: RecommendationCandidate) -> str:
    base = candidate.doi or candidate.title or candidate.external_id or "doi-import"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._")[:96]
    return f"{slug or 'doi-import'}.pdf"


def _remember_doi_stash_import_attempt(
    stash: DoiStash,
    *,
    status: str,
    message: str | None,
    candidate: RecommendationCandidate | None,
    now,
) -> None:
    metadata = dict(stash.stash_metadata or {})
    metadata["last_doi_import"] = {
        "status": status,
        "message": message,
        "attempted_at": now.isoformat(),
        "provider": candidate.provider if candidate else None,
        "relation": candidate.relation if candidate else None,
        "source_url": candidate.source_url if candidate else None,
        "pdf_url": candidate.pdf_url if candidate else None,
    }
    stash.stash_metadata = metadata


def _add_doi_stash_import_event(
    db: Session,
    *,
    batch: ImportBatch,
    stash: DoiStash,
    step: str,
    reason: str,
    level: str = "warning",
    status: str = "complete",
    candidate: RecommendationCandidate | None = None,
    document_id: str | None = None,
) -> ImportJob:
    job = ImportJob(
        batch_id=batch.id,
        document_id=document_id,
        status=status,
        current_step=step,
        last_error=reason if status == "failed" else None,
    )
    db.add(job)
    db.flush()
    db.add(
        ProcessingEvent(
            import_job_id=job.id,
            document_id=document_id,
            level=level,
            event_type=step,
            message=reason,
            payload={
                "doi_stash_id": stash.id,
                "doi": stash.doi,
                "title": stash.title,
                "source_url": stash.source_url,
                "source_provider": stash.source_provider,
                "resolver_provider": candidate.provider if candidate else None,
                "resolver_relation": candidate.relation if candidate else None,
                "resolver_source_url": candidate.source_url if candidate else None,
                "pdf_url": candidate.pdf_url if candidate else None,
                "matched_document_id": document_id,
            },
        )
    )
    return job


def _add_recommendation_skip_event(
    db: Session,
    *,
    batch: ImportBatch,
    recommendation: DocumentRecommendation,
    step: str,
    reason: str,
    level: str = "warning",
    status: str = "complete",
    matched_document_id: str | None = None,
) -> None:
    job = ImportJob(
        batch_id=batch.id,
        document_id=matched_document_id,
        status=status,
        current_step=step,
        last_error=reason if status == "failed" else None,
    )
    db.add(job)
    db.flush()
    db.add(
        ProcessingEvent(
            import_job_id=job.id,
            document_id=matched_document_id,
            level=level,
            event_type=step,
            message=reason,
            payload={
                "recommendation_id": recommendation.id,
                "title": recommendation.title,
                "doi": recommendation.doi,
                "pdf_url": recommendation.pdf_url,
                "matched_document_id": matched_document_id,
            },
        )
    )


def _openalex_work_id(value: str | None) -> str | None:
    if not value:
        return None
    match = OPENALEX_WORK_RE.search(value)
    return match.group(0) if match else None


def _openalex_work_to_candidate(work: dict[str, Any], relation: str) -> RecommendationCandidate | None:
    title = unescape(work.get("display_name") or "").strip()
    if not title:
        return None
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    best_pdf = _openalex_pdf_url(work)
    return RecommendationCandidate(
        title=title,
        provider="openalex",
        relation=relation,
        doi=normalize_doi(work.get("doi")),
        authors=_openalex_authors(work),
        publication_year=_int(work.get("publication_year")),
        journal=unescape(source.get("display_name") or "") or None,
        description=_openalex_abstract(work.get("abstract_inverted_index")),
        external_id=_openalex_work_id(work.get("id")),
        source_url=primary_location.get("landing_page_url") or doi_url(work.get("doi")) or work.get("id"),
        pdf_url=best_pdf,
        score=_float(work.get("cited_by_count")),
        raw_metadata={"provider": "openalex", "relation": relation, "work": work},
    )


def _openalex_authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name") or ""
        if not name:
            continue
        parts = name.split()
        authors.append(
            {
                "given": " ".join(parts[:-1]) if len(parts) > 1 else "",
                "family": parts[-1] if parts else name,
                "affiliation": None,
            }
        )
    return authors


def _openalex_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not isinstance(index, dict):
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            if isinstance(position, int):
                words.append((position, word))
    return " ".join(word for _, word in sorted(words)) or None


def _openalex_pdf_url(work: dict[str, Any]) -> str | None:
    primary_location = work.get("primary_location") or {}
    if primary_location.get("pdf_url"):
        return primary_location["pdf_url"]
    for location in work.get("locations") or []:
        if location.get("pdf_url"):
            return location["pdf_url"]
    return None


def _semantic_scholar_paper_to_candidate(paper: dict[str, Any], relation: str) -> RecommendationCandidate | None:
    title = unescape(paper.get("title") or "").strip()
    if not title:
        return None
    external_ids = paper.get("externalIds") or {}
    open_pdf = paper.get("openAccessPdf") or {}
    return RecommendationCandidate(
        title=title,
        provider="semantic_scholar",
        relation=relation,
        doi=normalize_doi(external_ids.get("DOI")),
        authors=_semantic_scholar_authors(paper),
        publication_year=_int(paper.get("year")),
        journal=unescape(paper.get("venue") or "") or None,
        description=unescape(paper.get("abstract") or "") or None,
        external_id=paper.get("paperId"),
        source_url=paper.get("url") or doi_url(external_ids.get("DOI")),
        pdf_url=open_pdf.get("url"),
        raw_metadata={"provider": "semantic_scholar", "relation": relation, "paper": paper},
    )


def _semantic_scholar_authors(paper: dict[str, Any]) -> list[dict[str, Any]]:
    authors = []
    for author in paper.get("authors") or []:
        name = author.get("name") or ""
        parts = name.split()
        if parts:
            authors.append({"given": " ".join(parts[:-1]), "family": parts[-1], "affiliation": None})
    return authors


def _crossref_work_to_candidate(work: dict[str, Any], relation: str) -> RecommendationCandidate | None:
    title = _first(work.get("title"))
    if not title:
        return None
    return RecommendationCandidate(
        title=unescape(title),
        provider="crossref",
        relation=relation,
        doi=normalize_doi(work.get("DOI")),
        authors=_crossref_authors(work),
        publication_year=_crossref_year(work),
        journal=unescape(_first(work.get("container-title")) or "") or None,
        description=_strip_html(work.get("abstract")),
        external_id=work.get("DOI"),
        source_url=(work.get("resource") or {}).get("primary", {}).get("URL") or work.get("URL") or doi_url(work.get("DOI")),
        pdf_url=_crossref_pdf_url(work),
        score=_float(work.get("is-referenced-by-count")),
        raw_metadata={"provider": "crossref", "relation": relation, "work": work},
    )


def _crossref_reference_to_candidate(reference: dict[str, Any]) -> RecommendationCandidate | None:
    title = reference.get("article-title") or reference.get("unstructured")
    if not title:
        return None
    return RecommendationCandidate(
        title=unescape(title),
        provider="crossref",
        relation="reference",
        doi=normalize_doi(reference.get("DOI") or reference.get("doi")),
        publication_year=_int(reference.get("year")),
        journal=unescape(reference.get("journal-title") or "") or None,
        source_url=doi_url(reference.get("DOI") or reference.get("doi")),
        raw_metadata={"provider": "crossref", "relation": "reference", "reference": reference},
    )


def _crossref_authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    authors = []
    for author in work.get("author") or []:
        authors.append(
            {
                "given": unescape(author.get("given") or ""),
                "family": unescape(author.get("family") or ""),
                "affiliation": None,
            }
        )
    return authors


def _crossref_year(work: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        date_parts = (work.get(key) or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            return _int(date_parts[0][0])
    return None


def _crossref_pdf_url(work: dict[str, Any]) -> str | None:
    for item in work.get("link") or []:
        content_type = str(item.get("content-type") or "").lower()
        url = item.get("URL")
        if url and "pdf" in content_type:
            return url
    return None


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split()) or None


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, (float, int)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
