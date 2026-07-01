from __future__ import annotations

from difflib import SequenceMatcher
from html import unescape
import re
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse

import httpx

from app.config import get_settings
from app.services.citations import decode_html_entities

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
TRAILING_DOI_PUNCTUATION = ".,;:)]}>"
TITLE_TOKEN_STOPWORDS = {
    "about",
    "after",
    "among",
    "analysis",
    "based",
    "between",
    "from",
    "into",
    "model",
    "models",
    "paper",
    "study",
    "that",
    "their",
    "this",
    "through",
    "using",
    "with",
}
USER_AGENT = "Medusa local research library (mailto:admin@medusa.local)"
PROVIDER_CONFIDENCE_FLOOR = 0.84
STABLE_SOURCE_HOST_HINTS = {
    "acm.org",
    "arxiv.org",
    "ieee.org",
    "jstor.org",
    "nih.gov",
    "osf.io",
    "plos.org",
    "pubmed.ncbi.nlm.nih.gov",
    "researchgate.net",
    "sciencedirect.com",
    "semanticscholar.org",
    "springer.com",
    "tandfonline.com",
    "wiley.com",
}


def enough_metadata_for_verified_citation(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("title") and metadata.get("authors") and metadata.get("publication_year"))


def normalized_title_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    left_normalized = " ".join(decode_html_entities(left).lower().split())
    right_normalized = " ".join(decode_html_entities(right).lower().split())
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def normalize_doi(value: str | None) -> str | None:
    text = decode_html_entities(value)
    if not text:
        return None
    text = text.removeprefix("doi:").removeprefix("DOI:").strip()
    match = DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(0).rstrip(TRAILING_DOI_PUNCTUATION).lower()
    return doi or None


def extract_doi_from_text(text: str | None) -> str | None:
    return normalize_doi(text)


def discover_doi_from_title(
    title: str | None,
    authors: list[dict[str, Any]] | None = None,
    year: int | None = None,
) -> dict[str, Any] | None:
    clean_title = _search_title(title)
    if not clean_title:
        return None
    attempts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for source, resolver in (
        ("crossref_bibliographic", _crossref_bibliographic_doi),
        ("semantic_scholar_title", _semantic_scholar_title_doi),
        ("openalex_title", _openalex_title_doi),
        ("datacite_title", _datacite_title_doi),
        ("europe_pmc_title", _europe_pmc_title_doi),
        ("opencitations_meta_title", _opencitations_meta_title_doi),
        ("title_web_search", _title_web_search_doi),
    ):
        result = resolver(clean_title, authors, year)
        if result:
            candidates.append(result)
            attempts.append({"source": source, "status": "found", "doi": result.get("doi"), "confidence": result.get("confidence") or result.get("score")})
        else:
            attempts.append({"source": source, "status": "no_match"})
    selected = _select_doi_candidate(candidates, authors=authors, year=year)
    if not selected:
        return None
    selected["attempted_sources"] = attempts
    selected["candidates"] = _compact_candidate_list(candidates)
    selected["conflicts"] = _doi_conflicts(candidates, selected["doi"])
    if selected.get("doi"):
        selected["registration_agency"] = verify_doi_registration_agency(selected["doi"])
    return selected


def local_doi_resolution_evidence(
    *,
    doi: str | None,
    title: str | None,
    authors: list[dict[str, Any]] | None = None,
    year: int | None = None,
    text: str | None = None,
    bibliography: str | None = None,
) -> dict[str, Any]:
    """Collect DOI evidence available inside the document record without network calls."""
    candidates: list[dict[str, Any]] = []
    attempted_sources: list[dict[str, Any]] = []
    if normalized := normalize_doi(doi):
        candidate = {
            "source": "document_metadata",
            "doi": normalized,
            "confidence": 0.9,
            "score": 0.9,
            "matched_title": title,
        }
        candidates.append(candidate)
        attempted_sources.append({"source": "document_metadata", "status": "found", "doi": normalized, "confidence": 0.9})
    else:
        attempted_sources.append({"source": "document_metadata", "status": "no_match"})

    for source, body in (("extracted_text", text), ("bibliography", bibliography)):
        found = _document_text_doi_candidates(title, authors, year, body, source=source)
        candidates.extend(found)
        attempted_sources.append(
            {
                "source": source,
                "status": "found" if found else "no_match",
                "candidate_count": len(found),
            }
        )

    selected = _select_doi_candidate(candidates, authors=authors, year=year)
    return {
        "status": "found" if selected else "not_found",
        "selected": selected,
        "attempted_sources": attempted_sources,
        "candidates": _compact_candidate_list(candidates),
        "conflicts": _doi_conflicts(candidates, (selected or {}).get("doi")),
        "confidence": (selected or {}).get("confidence"),
    }


def stable_source_link_evidence(
    *,
    title: str | None,
    authors: list[dict[str, Any]] | None = None,
    year: int | None = None,
    source_url: str | None = None,
    text: str | None = None,
    bibliography: str | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    attempted_sources: list[dict[str, Any]] = []
    if source_url:
        candidate = _source_url_candidate(source_url, title, authors, year, context=title or "", source="document_metadata")
        if candidate:
            candidates.append(candidate)
            attempted_sources.append({"source": "document_metadata", "status": "found", "source_url": candidate["source_url"]})
        else:
            attempted_sources.append({"source": "document_metadata", "status": "rejected"})
    else:
        attempted_sources.append({"source": "document_metadata", "status": "no_match"})

    for source, body in (("extracted_text", text), ("bibliography", bibliography)):
        found = _source_url_candidates_from_text(title, authors, year, body, source=source)
        candidates.extend(found)
        attempted_sources.append(
            {
                "source": source,
                "status": "found" if found else "no_match",
                "candidate_count": len(found),
            }
        )

    selected = _select_source_url_candidate(candidates)
    return {
        "status": "found" if selected else "not_found",
        "selected": selected,
        "attempted_sources": attempted_sources,
        "candidates": _compact_source_candidate_list(candidates),
        "confidence": (selected or {}).get("confidence"),
    }


def verify_doi_registration_agency(doi: str | None) -> dict[str, Any] | None:
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    try:
        response = httpx.get(
            f"https://doi.org/doiRA/{quote(normalized, safe='')}",
            timeout=5,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {"doi": normalized, "status": "unavailable"}
    item = payload[0] if isinstance(payload, list) and payload else payload if isinstance(payload, dict) else {}
    return {
        "doi": normalized,
        "status": "verified" if item.get("RA") else "not_found",
        "registration_agency": item.get("RA"),
    }


def crossref_to_citation_metadata(crossref: dict[str, Any] | None) -> dict[str, Any]:
    if not crossref:
        return {}
    title = _first(crossref.get("title"))
    container = _first(crossref.get("container-title"))
    doi = crossref.get("DOI")
    source_url = (crossref.get("resource") or {}).get("primary", {}).get("URL") or crossref.get("URL")
    return {
        "title": decode_html_entities(title),
        "authors": [_crossref_author(author) for author in crossref.get("author") or []],
        "publication_year": _crossref_year(crossref),
        "journal": decode_html_entities(container),
        "publisher": decode_html_entities(crossref.get("publisher")),
        "doi": decode_html_entities(doi),
        "source_url": decode_html_entities(source_url),
        "type": crossref.get("type"),
        "volume": decode_html_entities(crossref.get("volume")),
        "issue": decode_html_entities(crossref.get("issue")),
        "page": decode_html_entities(crossref.get("page")),
        "article_number": decode_html_entities(crossref.get("article-number")),
    }


def crossref_lookup(
    doi: str | None,
    title: str | None,
    authors: list[dict[str, Any]] | None = None,
    year: int | None = None,
) -> dict[str, Any] | None:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        url = f"https://api.crossref.org/works/{quote(normalized_doi, safe='')}"
    elif title:
        url = "https://api.crossref.org/works"
    else:
        return None
    try:
        if normalized_doi:
            response = httpx.get(url, timeout=8)
        else:
            params: dict[str, str | int] = {"query.title": title, "rows": 5}
            first_family = _first_author_family(authors)
            if first_family:
                params["query.author"] = first_family
            if year:
                params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"
            response = httpx.get(url, params=params, timeout=8)
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message", {})
        if "items" in message:
            if not message["items"]:
                return None
            return _best_crossref_title_match(title, authors, year, message["items"])
        return message or None
    except Exception:
        return None


def _crossref_bibliographic_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.recommendations_enable_crossref:
        return None
    query = _bibliographic_query(title, authors, year)
    try:
        response = httpx.get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": query, "rows": 5},
            timeout=settings.recommendations_request_timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        response.raise_for_status()
        items = (response.json().get("message") or {}).get("items") or []
    except Exception:
        return None
    candidate = _best_crossref_title_match(title, authors, year, items)
    if not candidate:
        return None
    doi = normalize_doi(candidate.get("DOI"))
    if not doi:
        return None
    candidate_authors = [_crossref_author(author) for author in candidate.get("author") or []]
    score = _title_candidate_score(title, authors, year, _first(candidate.get("title")), candidate_authors, _crossref_year(candidate))
    confidence = _provider_confidence(score, base=0.89)
    return {
        "source": "crossref_bibliographic",
        "doi": doi,
        "query": query,
        "score": round(score, 4),
        "confidence": confidence,
        "matched_title": decode_html_entities(_first(candidate.get("title"))),
        "matched_year": _crossref_year(candidate),
        "matched_authors": [_author_display_name(author) for author in candidate_authors],
        "source_url": decode_html_entities((candidate.get("resource") or {}).get("primary", {}).get("URL") or candidate.get("URL")),
    }


def _semantic_scholar_title_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.recommendations_enable_semantic_scholar:
        return None
    headers = {"User-Agent": USER_AGENT}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    try:
        response = httpx.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": title,
                "fields": "title,year,authors,venue,externalIds,url",
                "limit": 5,
            },
            timeout=settings.recommendations_request_timeout_seconds,
            headers=headers,
            follow_redirects=True,
        )
        response.raise_for_status()
        papers = response.json().get("data") or []
    except Exception:
        return None

    best: tuple[float, dict[str, Any]] | None = None
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        doi = normalize_doi((paper.get("externalIds") or {}).get("DOI"))
        if not doi:
            continue
        candidate_authors = [
            {"name": author.get("name")}
            for author in paper.get("authors") or []
            if isinstance(author, dict) and author.get("name")
        ]
        score = _title_candidate_score(title, authors, year, paper.get("title"), candidate_authors, _int(paper.get("year")))
        threshold = 0.88 if (authors or year) else 0.92
        if score < threshold:
            continue
        confidence = _provider_confidence(score, base=0.87)
        evidence = {
            "source": "semantic_scholar_title",
            "doi": doi,
            "query": title,
            "score": round(score, 4),
            "confidence": confidence,
            "matched_title": decode_html_entities(paper.get("title")),
            "matched_year": _int(paper.get("year")),
            "matched_authors": [author.get("name") for author in paper.get("authors") or [] if isinstance(author, dict)],
            "source_url": decode_html_entities(paper.get("url")),
        }
        if best is None or score > best[0]:
            best = (score, evidence)
    return best[1] if best else None


def _openalex_title_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.recommendations_enable_openalex:
        return None
    params: dict[str, Any] = {"search": title, "per-page": 5}
    if settings.openalex_mailto or settings.admin_email:
        params["mailto"] = settings.openalex_mailto or settings.admin_email
    try:
        response = httpx.get(
            "https://api.openalex.org/works",
            params=params,
            timeout=settings.recommendations_request_timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        response.raise_for_status()
        works = response.json().get("results") or []
    except Exception:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for work in works:
        if not isinstance(work, dict):
            continue
        doi = normalize_doi(work.get("doi"))
        if not doi:
            continue
        candidate_authors = _openalex_authors(work)
        score = _title_candidate_score(title, authors, year, work.get("display_name"), candidate_authors, _int(work.get("publication_year")))
        if score < (0.87 if (authors or year) else 0.9):
            continue
        source_url = _openalex_source_url(work) or work.get("id")
        evidence = {
            "source": "openalex_title",
            "doi": doi,
            "query": title,
            "score": round(score, 4),
            "confidence": _provider_confidence(score, base=0.86),
            "matched_title": decode_html_entities(work.get("display_name")),
            "matched_year": _int(work.get("publication_year")),
            "matched_authors": [_author_display_name(author) for author in candidate_authors],
            "source_url": decode_html_entities(source_url),
            "openalex_id": work.get("id"),
        }
        if best is None or score > best[0]:
            best = (score, evidence)
    return best[1] if best else None


def _datacite_title_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    try:
        response = httpx.get(
            "https://api.datacite.org/dois",
            params={"query": title, "page[size]": 5},
            timeout=get_settings().recommendations_request_timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        response.raise_for_status()
        items = response.json().get("data") or []
    except Exception:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for item in items:
        attrs = item.get("attributes") if isinstance(item, dict) else None
        if not isinstance(attrs, dict):
            continue
        doi = normalize_doi(attrs.get("doi") or item.get("id"))
        candidate_title = _datacite_title(attrs)
        if not doi or not candidate_title:
            continue
        candidate_authors = _datacite_authors(attrs)
        score = _title_candidate_score(title, authors, year, candidate_title, candidate_authors, _int(attrs.get("publicationYear")))
        if score < (0.86 if (authors or year) else 0.9):
            continue
        evidence = {
            "source": "datacite_title",
            "doi": doi,
            "query": title,
            "score": round(score, 4),
            "confidence": _provider_confidence(score, base=0.84),
            "matched_title": decode_html_entities(candidate_title),
            "matched_year": _int(attrs.get("publicationYear")),
            "matched_authors": [_author_display_name(author) for author in candidate_authors],
            "source_url": decode_html_entities(attrs.get("url")),
        }
        if best is None or score > best[0]:
            best = (score, evidence)
    return best[1] if best else None


def _europe_pmc_title_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    query = f'TITLE:"{title}"'
    if year:
        query += f" AND PUB_YEAR:{year}"
    try:
        response = httpx.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "format": "json", "pageSize": 5},
            timeout=get_settings().recommendations_request_timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        response.raise_for_status()
        items = ((response.json().get("resultList") or {}).get("result")) or []
    except Exception:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        doi = normalize_doi(item.get("doi"))
        if not doi:
            continue
        candidate_authors = _split_author_string(item.get("authorString"))
        score = _title_candidate_score(title, authors, year, item.get("title"), candidate_authors, _int(item.get("pubYear")))
        if score < (0.86 if (authors or year) else 0.9):
            continue
        evidence = {
            "source": "europe_pmc_title",
            "doi": doi,
            "query": query,
            "score": round(score, 4),
            "confidence": _provider_confidence(score, base=0.84),
            "matched_title": decode_html_entities(item.get("title")),
            "matched_year": _int(item.get("pubYear")),
            "matched_authors": [_author_display_name(author) for author in candidate_authors],
            "source_url": decode_html_entities(_europe_pmc_source_url(item)),
        }
        if best is None or score > best[0]:
            best = (score, evidence)
    return best[1] if best else None


def _opencitations_meta_title_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    try:
        response = httpx.get(
            f"https://opencitations.net/meta/api/v1/metadata/title/{quote(title, safe='')}",
            timeout=get_settings().recommendations_request_timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    items = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    best: tuple[float, dict[str, Any]] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        doi = normalize_doi(item.get("doi"))
        candidate_title = item.get("title")
        if not doi or not candidate_title:
            continue
        candidate_authors = _split_author_string(item.get("author"))
        candidate_year = _int(str(item.get("pub_date") or "")[:4])
        score = _title_candidate_score(title, authors, year, candidate_title, candidate_authors, candidate_year)
        if score < (0.86 if (authors or year) else 0.9):
            continue
        evidence = {
            "source": "opencitations_meta_title",
            "doi": doi,
            "query": title,
            "score": round(score, 4),
            "confidence": _provider_confidence(score, base=0.82),
            "matched_title": decode_html_entities(candidate_title),
            "matched_year": candidate_year,
            "matched_authors": [_author_display_name(author) for author in candidate_authors],
            "source_url": decode_html_entities(item.get("url")),
        }
        if best is None or score > best[0]:
            best = (score, evidence)
    return best[1] if best else None


def _title_web_search_doi(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.citation_title_web_search:
        return None
    query = f'"{title}" DOI'
    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        response = httpx.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=settings.citation_title_web_search_timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception:
        return None
    text = _plain_search_text(response.text)
    candidates = _web_doi_candidates(title, authors, year, text)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["score"], reverse=True)
    best = candidates[0]
    best.update(
        {
            "source": "title_web_search",
            "query": query,
            "search_url": search_url,
            "confidence": _provider_confidence(best.get("score"), base=0.8),
        }
    )
    return best


def _bibliographic_query(title: str, authors: list[dict[str, Any]] | None, year: int | None) -> str:
    parts = [title]
    first_author = _first_author_family(authors)
    if first_author:
        parts.append(first_author)
    if year:
        parts.append(str(year))
    return " ".join(part for part in parts if part)


def _provider_confidence(score: Any, *, base: float) -> float:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = base
    confidence = base + max(0.0, min(numeric, 1.0) - 0.82) * 0.45
    return round(max(0.0, min(confidence, 0.98)), 4)


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("confidence") if candidate.get("confidence") is not None else candidate.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _select_doi_candidate(
    candidates: list[dict[str, Any]],
    *,
    authors: list[dict[str, Any]] | None,
    year: int | None,
) -> dict[str, Any] | None:
    by_doi: dict[str, dict[str, Any]] = {}
    source_names: dict[str, set[str]] = {}
    for candidate in candidates:
        doi = normalize_doi(candidate.get("doi"))
        if not doi:
            continue
        normalized = {**candidate, "doi": doi}
        source_names.setdefault(doi, set()).add(str(candidate.get("source") or "unknown"))
        current = by_doi.get(doi)
        if current is None or _candidate_confidence(normalized) > _candidate_confidence(current):
            by_doi[doi] = normalized
    if not by_doi:
        return None
    ranked = sorted(by_doi.values(), key=_candidate_confidence, reverse=True)
    selected = dict(ranked[0])
    selected["sources"] = sorted(source_names.get(selected["doi"], set()))
    selected["confidence"] = _candidate_confidence(selected)
    if len(selected["sources"]) >= 2:
        selected["confidence"] = round(min(0.99, selected["confidence"] + 0.04), 4)
    threshold = 0.84 if (authors or year) else 0.88
    return selected if selected["confidence"] >= threshold else None


def _doi_conflicts(candidates: list[dict[str, Any]], selected_doi: str | None) -> list[dict[str, Any]]:
    selected = normalize_doi(selected_doi)
    conflicts: list[dict[str, Any]] = []
    selected_confidence = 0.0
    for candidate in candidates:
        if normalize_doi(candidate.get("doi")) == selected:
            selected_confidence = max(selected_confidence, _candidate_confidence(candidate))
    for candidate in candidates:
        doi = normalize_doi(candidate.get("doi"))
        if not doi or doi == selected:
            continue
        confidence = _candidate_confidence(candidate)
        if confidence >= max(PROVIDER_CONFIDENCE_FLOOR, selected_confidence - 0.05):
            conflicts.append(
                {
                    "doi": doi,
                    "source": candidate.get("source"),
                    "confidence": confidence,
                    "matched_title": candidate.get("matched_title"),
                    "source_url": candidate.get("source_url"),
                }
            )
    return conflicts


def _compact_candidate_list(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for candidate in candidates:
        doi = normalize_doi(candidate.get("doi"))
        if not doi:
            continue
        compacted.append(
            {
                "doi": doi,
                "source": candidate.get("source"),
                "confidence": _candidate_confidence(candidate),
                "score": candidate.get("score"),
                "matched_title": candidate.get("matched_title"),
                "matched_year": candidate.get("matched_year"),
                "source_url": candidate.get("source_url"),
            }
        )
    compacted.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    return compacted[:12]


def _compact_source_candidate_list(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = [
        {
            "source_url": candidate.get("source_url"),
            "source": candidate.get("source"),
            "confidence": candidate.get("confidence"),
            "matched_context": candidate.get("matched_context"),
        }
        for candidate in candidates
        if candidate.get("source_url")
    ]
    compacted.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    return compacted[:12]


def _document_text_doi_candidates(
    title: str | None,
    authors: list[dict[str, Any]] | None,
    year: int | None,
    text: str | None,
    *,
    source: str,
) -> list[dict[str, Any]]:
    clean_title = _search_title(title)
    if not text or not clean_title:
        return []
    found: dict[str, dict[str, Any]] = {}
    for match in DOI_RE.finditer(text[:200_000]):
        doi = normalize_doi(match.group(0))
        if not doi:
            continue
        start = max(0, match.start() - 1200)
        end = min(len(text), match.end() + 1200)
        context = text[start:end]
        support = _title_token_support(clean_title, context)
        exact_title = _normalized_title(clean_title) in _normalized_title(context)
        has_author = _context_has_author(context, authors)
        has_year = bool(year and re.search(rf"\b{re.escape(str(year))}\b", context))
        if source == "bibliography" and not (exact_title or support >= 0.82):
            continue
        if source == "extracted_text" and not (exact_title or support >= 0.55 or (has_author and has_year)):
            continue
        score = 0.7 + min(support, 1.0) * 0.16
        if exact_title:
            score += 0.08
        if has_author:
            score += 0.04
        if has_year:
            score += 0.03
        if match.start() < 8000:
            score += 0.03
        candidate = {
            "source": source,
            "doi": doi,
            "score": round(score, 4),
            "confidence": round(min(score, 0.96), 4),
            "title_support": round(support, 4),
            "matched_context": context[:700],
            "matched_title": title,
            "matched_year": year if has_year else None,
        }
        current = found.get(doi)
        if current is None or _candidate_confidence(candidate) > _candidate_confidence(current):
            found[doi] = candidate
    return list(found.values())


def _source_url_candidates_from_text(
    title: str | None,
    authors: list[dict[str, Any]] | None,
    year: int | None,
    text: str | None,
    *,
    source: str,
) -> list[dict[str, Any]]:
    if not text:
        return []
    candidates: list[dict[str, Any]] = []
    for match in URL_RE.finditer(text[:200_000]):
        url = match.group(0).rstrip(TRAILING_DOI_PUNCTUATION)
        if "doi.org/" in url.lower():
            continue
        start = max(0, match.start() - 800)
        end = min(len(text), match.end() + 800)
        context = text[start:end]
        candidate = _source_url_candidate(url, title, authors, year, context=context, source=source)
        if candidate:
            candidates.append(candidate)
    return candidates


def _source_url_candidate(
    url: str | None,
    title: str | None,
    authors: list[dict[str, Any]] | None,
    year: int | None,
    *,
    context: str,
    source: str,
) -> dict[str, Any] | None:
    clean_url = _clean_source_url(url)
    if not clean_url:
        return None
    parsed = urlparse(clean_url)
    if parsed.scheme != "https":
        return None
    host = parsed.netloc.lower()
    if any(blocked in host for blocked in ("duckduckgo.", "google.", "bing.", "yahoo.")):
        return None
    support = _title_token_support(title or "", context or clean_url)
    has_author = _context_has_author(context, authors)
    has_year = bool(year and re.search(rf"\b{re.escape(str(year))}\b", context or clean_url))
    score = 0.56
    if clean_url.lower().split("?")[0].endswith(".pdf"):
        score += 0.22
    if "arxiv.org/abs/" in clean_url.lower() or "arxiv.org/pdf/" in clean_url.lower():
        score += 0.2
    if any(hint in host for hint in STABLE_SOURCE_HOST_HINTS):
        score += 0.1
    score += min(support, 1.0) * 0.12
    if has_author:
        score += 0.03
    if has_year:
        score += 0.03
    if score < 0.66:
        return None
    return {
        "source": source,
        "source_url": clean_url,
        "confidence": round(min(score, 0.95), 4),
        "matched_context": (context or "")[:500],
    }


def _select_source_url_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        url = candidate.get("source_url")
        if not url:
            continue
        current = deduped.get(url)
        if current is None or float(candidate.get("confidence") or 0) > float(current.get("confidence") or 0):
            deduped[url] = candidate
    ranked = sorted(deduped.values(), key=lambda item: float(item.get("confidence") or 0), reverse=True)
    return ranked[0] if ranked and float(ranked[0].get("confidence") or 0) >= 0.66 else None


def _clean_source_url(url: str | None) -> str | None:
    text = decode_html_entities(url).strip().rstrip(TRAILING_DOI_PUNCTUATION)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.netloc == "duckduckgo.com" and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            text = unquote(target[0])
    return text if text.startswith("https://") else None


def _openalex_authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = decode_html_entities((author or {}).get("display_name"))
        if name:
            authors.append(_name_to_author(name))
    return authors


def _openalex_source_url(work: dict[str, Any]) -> str | None:
    primary = work.get("primary_location") or {}
    if primary.get("landing_page_url"):
        return primary.get("landing_page_url")
    if primary.get("pdf_url"):
        return primary.get("pdf_url")
    for location in work.get("locations") or []:
        if location.get("landing_page_url"):
            return location.get("landing_page_url")
        if location.get("pdf_url"):
            return location.get("pdf_url")
    return None


def _datacite_title(attrs: dict[str, Any]) -> str | None:
    for item in attrs.get("titles") or []:
        if isinstance(item, dict) and item.get("title"):
            return decode_html_entities(item.get("title"))
    return None


def _datacite_authors(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []
    for creator in attrs.get("creators") or []:
        if not isinstance(creator, dict):
            continue
        name = creator.get("name")
        if not name:
            continue
        authors.append(
            {
                "given": decode_html_entities(creator.get("givenName")),
                "family": decode_html_entities(creator.get("familyName") or name),
                "affiliation": None,
            }
        )
    return authors


def _europe_pmc_source_url(item: dict[str, Any]) -> str | None:
    full_text_urls = ((item.get("fullTextUrlList") or {}).get("fullTextUrl")) or []
    for full_text in full_text_urls:
        if isinstance(full_text, dict) and full_text.get("url"):
            return full_text.get("url")
    if item.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{item['pmid']}/"
    return None


def _split_author_string(value: Any) -> list[dict[str, Any]]:
    text = decode_html_entities(value)
    if not text:
        return []
    pieces = re.split(r"\s*(?:;|,\s+and\s+|\s+and\s+)\s*", text)
    return [_name_to_author(piece) for piece in pieces if piece.strip()][:20]


def _name_to_author(name: str) -> dict[str, Any]:
    parts = decode_html_entities(name).strip().split()
    if not parts:
        return {"given": "", "family": "", "affiliation": None}
    return {
        "given": " ".join(parts[:-1]) if len(parts) > 1 else "",
        "family": parts[-1],
        "affiliation": None,
    }


def _author_display_name(author: dict[str, Any]) -> str:
    return " ".join(str(author.get(key) or "").strip() for key in ("given", "family")).strip() or str(author.get("name") or "").strip()


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _search_title(title: str | None) -> str | None:
    text = " ".join(decode_html_entities(title).replace('"', " ").split())
    return text[:240] if len(text) >= 8 else None


def _plain_search_text(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _web_doi_candidates(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
    text: str,
) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for match in DOI_RE.finditer(text):
        doi = normalize_doi(match.group(0))
        if not doi:
            continue
        start = max(0, match.start() - 900)
        end = min(len(text), match.end() + 900)
        context = text[start:end]
        support = _title_token_support(title, context)
        exact_title = _normalized_title(title) in _normalized_title(context)
        if not exact_title and support < 0.72:
            continue
        context_year = year if year and re.search(rf"\b{re.escape(str(year))}\b", context) else None
        score = 0.88 + min(support, 1.0) * 0.1
        if exact_title:
            score += 0.08
        if context_year:
            score += 0.03
        if authors and _context_has_author(context, authors):
            score += 0.03
        if "doi" in context.lower():
            score += 0.02
        evidence = {
            "doi": doi,
            "score": round(score, 4),
            "title_support": round(support, 4),
            "matched_context": context[:500],
        }
        current = found.get(doi)
        if current is None or evidence["score"] > current["score"]:
            found[doi] = evidence
    return list(found.values())


def _normalized_title(value: str | None) -> str:
    return " ".join(decode_html_entities(value).lower().split())


def _title_tokens(title: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", decode_html_entities(title).lower())
    return [token for token in tokens if len(token) >= 4 and token not in TITLE_TOKEN_STOPWORDS]


def _title_token_support(title: str, context: str) -> float:
    tokens = _title_tokens(title)
    if not tokens:
        return 0.0
    context_text = decode_html_entities(context).lower()
    matched = sum(1 for token in tokens if token in context_text)
    return matched / len(tokens)


def _context_has_author(context: str, authors: list[dict[str, Any]] | None) -> bool:
    context_text = decode_html_entities(context).lower()
    for family in _author_families(authors):
        if family and family in context_text:
            return True
    return False


def _title_candidate_score(
    title: str,
    authors: list[dict[str, Any]] | None,
    year: int | None,
    candidate_title: str | None,
    candidate_authors: list[dict[str, Any]] | None,
    candidate_year: int | None,
) -> float:
    score = normalized_title_similarity(title, candidate_title)
    if year and candidate_year:
        score += 0.06 if year == candidate_year else -0.08
    expected_authors = _author_families(authors)
    found_authors = _author_families(candidate_authors)
    if expected_authors and found_authors:
        score += 0.04 if expected_authors & found_authors else -0.04
    return score


def _int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _crossref_year(crossref: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        date_parts = (crossref.get(key) or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            year = date_parts[0][0]
            if isinstance(year, int):
                return year
            if isinstance(year, str) and year.isdigit():
                return int(year)
    return None


def _crossref_author(author: dict[str, Any]) -> dict[str, Any]:
    given = decode_html_entities(author.get("given"))
    family = decode_html_entities(author.get("family"))
    if family and not given and len(family.split()) > 1:
        parts = family.split()
        given = " ".join(parts[:-1])
        family = parts[-1]
    return {"given": given, "family": family, "affiliation": None}


def _first_author_family(authors: list[dict[str, Any]] | None) -> str | None:
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        family = decode_html_entities(author.get("family") or author.get("last") or author.get("name"))
        if family:
            return family.split()[-1]
    return None


def _author_families(authors: list[dict[str, Any]] | None) -> set[str]:
    families: set[str] = set()
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        family = decode_html_entities(author.get("family") or author.get("last") or author.get("name")).lower()
        if family:
            families.add(family.split()[-1])
    return families


def _best_crossref_title_match(
    title: str | None,
    authors: list[dict[str, Any]] | None,
    year: int | None,
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    expected_authors = _author_families(authors)
    best: tuple[float, dict[str, Any]] | None = None
    for candidate in items:
        candidate_title = _first(candidate.get("title"))
        title_score = normalized_title_similarity(title, candidate_title)
        if title_score < 0.82:
            continue
        score = title_score
        candidate_year = _crossref_year(candidate)
        if year and candidate_year:
            score += 0.08 if candidate_year == year else -0.08
        candidate_authors = _author_families([_crossref_author(author) for author in candidate.get("author") or []])
        if expected_authors and candidate_authors:
            score += 0.06 if expected_authors & candidate_authors else -0.04
        if best is None or score > best[0]:
            best = (score, candidate)
    if not best:
        return None
    threshold = 0.86 if (authors or year) else 0.82
    return best[1] if best[0] >= threshold else None
