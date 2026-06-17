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
