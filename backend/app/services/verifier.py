from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.services.citations import decode_html_entities

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
TRAILING_DOI_PUNCTUATION = ".,;:)]}>"


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


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


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
