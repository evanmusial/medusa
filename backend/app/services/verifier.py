from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import httpx


def enough_metadata_for_verified_citation(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("title") and metadata.get("authors") and metadata.get("publication_year"))


def normalized_title_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    left_normalized = " ".join(left.lower().split())
    right_normalized = " ".join(right.lower().split())
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def crossref_to_citation_metadata(crossref: dict[str, Any] | None) -> dict[str, Any]:
    if not crossref:
        return {}
    title = _first(crossref.get("title"))
    container = _first(crossref.get("container-title"))
    doi = crossref.get("DOI")
    source_url = (crossref.get("resource") or {}).get("primary", {}).get("URL") or crossref.get("URL")
    return {
        "title": title,
        "authors": [_crossref_author(author) for author in crossref.get("author") or []],
        "publication_year": _crossref_year(crossref),
        "journal": container,
        "publisher": crossref.get("publisher"),
        "doi": doi,
        "source_url": source_url,
        "type": crossref.get("type"),
        "volume": crossref.get("volume"),
        "issue": crossref.get("issue"),
        "page": crossref.get("page"),
        "article_number": crossref.get("article-number"),
    }


def crossref_lookup(doi: str | None, title: str | None) -> dict[str, Any] | None:
    if doi:
        url = f"https://api.crossref.org/works/{doi.strip().removeprefix('https://doi.org/')}"
    elif title:
        url = "https://api.crossref.org/works"
    else:
        return None
    try:
        if doi:
            response = httpx.get(url, timeout=8)
        else:
            response = httpx.get(url, params={"query.title": title, "rows": 1}, timeout=8)
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message", {})
        if "items" in message:
            if not message["items"]:
                return None
            candidate = message["items"][0]
            candidate_title = (candidate.get("title") or [None])[0]
            if normalized_title_similarity(title, candidate_title) < 0.82:
                return None
            return candidate
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
    given = str(author.get("given") or "").strip()
    family = str(author.get("family") or "").strip()
    if family and not given and len(family.split()) > 1:
        parts = family.split()
        given = " ".join(parts[:-1])
        family = parts[-1]
    return {"given": given, "family": family, "affiliation": None}
