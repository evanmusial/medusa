from __future__ import annotations

from difflib import SequenceMatcher
from html import unescape
import re
from typing import Any
from urllib.parse import quote, quote_plus

import httpx

from app.config import get_settings
from app.services.citations import decode_html_entities

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
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
    return _semantic_scholar_title_doi(clean_title, authors, year) or _title_web_search_doi(clean_title, authors, year)


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
        evidence = {
            "source": "semantic_scholar_title",
            "doi": doi,
            "query": title,
            "score": round(score, 4),
            "matched_title": decode_html_entities(paper.get("title")),
            "matched_year": _int(paper.get("year")),
            "matched_authors": [author.get("name") for author in paper.get("authors") or [] if isinstance(author, dict)],
            "source_url": decode_html_entities(paper.get("url")),
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
        }
    )
    return best


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
