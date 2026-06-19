from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import Document, DocumentRecommendation, ImportBatch, ImportJob, ProcessingEvent, utc_now
from app.services.document_cache import document_cache_path, document_cache_root, register_document_cache
from app.services.processing import refresh_import_batch_progress
from app.services.storage import get_storage_service
from app.services.verifier import normalized_title_similarity


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
TRAILING_DOI_PUNCTUATION = ".,;:)]}>"
OPENALEX_WORK_RE = re.compile(r"W\d+")


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


def list_document_recommendations(db: Session, document: Document, *, hide_existing: bool = False) -> list[DocumentRecommendation]:
    rows = (
        db.query(DocumentRecommendation)
        .options(
            joinedload(DocumentRecommendation.existing_document),
            joinedload(DocumentRecommendation.imported_document),
        )
        .filter(DocumentRecommendation.source_document_id == document.id)
        .order_by(
        DocumentRecommendation.existing_document_id.isnot(None),
        DocumentRecommendation.score.desc().nullslast(),
        DocumentRecommendation.publication_year.desc().nullslast(),
        DocumentRecommendation.title,
        )
        .all()
    )
    mark_existing_library_matches(db, rows, source_document_id=document.id)
    if hide_existing:
        return [row for row in rows if not row.existing_document_id and not row.imported_document_id]
    return rows


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
                "providers": sorted({row.source_provider for row in rows}),
                "errors": errors,
            },
        )
    )
    return rows


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

    mark_existing_library_matches(db, recommendations, source_document_id=source_document.id)
    for recommendation in recommendations:
        if skip_existing and (recommendation.existing_document_id or recommendation.imported_document_id):
            _add_recommendation_skip_event(
                db,
                batch=batch,
                recommendation=recommendation,
                step="already_in_library",
                reason="Recommendation already matches a Medusa document.",
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


def _enabled_fetchers():
    settings = get_settings()
    if settings.recommendations_enable_openalex:
        yield "openalex", fetch_openalex_recommendations
    if settings.recommendations_enable_semantic_scholar:
        yield "semantic_scholar", fetch_semantic_scholar_recommendations
    if settings.recommendations_enable_crossref:
        yield "crossref", fetch_crossref_recommendations


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


def _merge_candidate(candidates: dict[str, RecommendationCandidate], candidate: RecommendationCandidate) -> None:
    key = candidate.match_key
    existing = candidates.get(key)
    if not existing:
        candidates[key] = candidate
        return
    providers = unique_join(existing.provider, candidate.provider)
    relations = unique_join(existing.relation, candidate.relation)
    existing.provider = providers
    existing.relation = relations
    for attr in ("doi", "journal", "description", "external_id", "source_url", "pdf_url", "publication_year"):
        if getattr(existing, attr) in (None, "", []):
            setattr(existing, attr, getattr(candidate, attr))
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


def _apply_candidate(row: DocumentRecommendation, candidate: RecommendationCandidate) -> None:
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
    row.status = "candidate" if row.status == "stale" else row.status or "candidate"
    row.raw_metadata = candidate.raw_metadata or {}
    row.last_seen_at = utc_now()


def mark_existing_library_matches(db: Session, recommendations: list[DocumentRecommendation], *, source_document_id: str) -> None:
    if not recommendations:
        return
    documents = db.query(Document).filter(Document.deleted_at.is_(None), Document.id != source_document_id).all()
    doi_map = {normalize_doi(document.doi): document for document in documents if normalize_doi(document.doi)}
    for recommendation in recommendations:
        match = doi_map.get(normalize_doi(recommendation.doi))
        if not match and recommendation.title:
            match = _best_title_match(documents, recommendation.title)
        recommendation.existing_document_id = recommendation.imported_document_id or (match.id if match else None)


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
        .filter(Document.deleted_at.is_(None), Document.checksum_sha256 == checksum)
        .order_by(Document.created_at.desc(), Document.id)
        .first()
    )


def _download_pdf(url: str) -> tuple[bytes, str]:
    settings = get_settings()
    response = httpx.get(url, timeout=settings.recommendation_download_timeout_seconds, follow_redirects=True)
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
    job = ImportJob(batch_id=batch.id, document_id=matched_document_id, status=status, current_step=step)
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
