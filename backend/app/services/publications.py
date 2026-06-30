from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, object_session

from app.config import get_settings
from app.models import Document, DocumentPublication, Publication, PublicationAlias, User, utc_now
from app.services.citations import decode_html_entities
from app.services.verifier import crossref_lookup, crossref_to_citation_metadata


PUBLICATION_VERIFIED_STATUS = "verified"
PUBLICATION_NEEDS_REVIEW_STATUS = "needs_review"
PUBLICATION_UNVERIFIED_STATUS = "unverified"
PUBLICATION_SOURCE_PRIORITY = {
    "crossref": 100,
    "openalex": 90,
    "semantic_scholar": 80,
    "google_books": 65,
    "open_library": 60,
    "manual": 55,
    "model": 40,
    "legacy": 25,
}


def normalize_publication_title(value: str | None) -> str:
    text = decode_html_entities(value or "").casefold()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_doi(value: str | None) -> str | None:
    text = decode_html_entities(value or "")
    if not text:
        return None
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().rstrip(".,;:)]}>")
    return text.lower() or None


def normalize_issn(value: str | None) -> str | None:
    text = re.sub(r"[^0-9Xx]", "", value or "")
    if len(text) != 8:
        return None
    return f"{text[:4]}-{text[4:].upper()}"


def normalize_isbn(value: str | None) -> str | None:
    text = re.sub(r"[^0-9Xx]", "", value or "")
    if len(text) not in {10, 13}:
        return None
    return text.upper()


def _clean_text(value: Any, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    text = decode_html_entities(value)
    if not text:
        return None
    return text[:max_length] if max_length else text


def _first(values: Any) -> Any:
    if isinstance(values, list):
        return values[0] if values else None
    return values


def _int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _normalized_identifier_list(values: Any, normalizer) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    result: list[str] = []
    for value in raw_values:
        normalized = normalizer(str(value))
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def publication_type_from_crossref(kind: str | None) -> str | None:
    normalized = (kind or "").casefold()
    if "journal" in normalized:
        return "journal"
    if "book" in normalized or "monograph" in normalized or "reference" in normalized:
        return "book"
    if "proceedings" in normalized or "conference" in normalized:
        return "proceedings"
    if "report" in normalized:
        return "report"
    if normalized:
        return normalized.replace("-", "_")
    return None


def appearance_type_from_crossref(kind: str | None) -> str | None:
    normalized = (kind or "").casefold()
    if normalized in {"book-chapter", "book-section", "reference-entry"}:
        return "chapter"
    if normalized == "book":
        return "book"
    if "proceedings" in normalized:
        return "conference_paper"
    if "journal" in normalized:
        return "article"
    return normalized.replace("-", "_") if normalized else None


def _crossref_date(crossref: dict[str, Any]) -> str | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (crossref.get(key) or {}).get("date-parts") or []
        if parts and isinstance(parts[0], list):
            return "-".join(str(part) for part in parts[0] if part is not None) or None
    return None


def _crossref_year(crossref: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (crossref.get(key) or {}).get("date-parts") or []
        if parts and isinstance(parts[0], list) and parts[0]:
            return _int(parts[0][0])
    return None


def publication_candidate_from_crossref(crossref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not crossref:
        return None
    container = _clean_text(_first(crossref.get("container-title")), 600)
    title = container or _clean_text(_first(crossref.get("short-container-title")), 600)
    crossref_type = crossref.get("type")
    publication_type = publication_type_from_crossref(crossref_type)
    if not title and publication_type == "book":
        title = _clean_text(_first(crossref.get("title")), 600)
    if not title:
        return None
    issns = _normalized_identifier_list(crossref.get("ISSN") or [], normalize_issn)
    isbns = _normalized_identifier_list(crossref.get("ISBN") or [], normalize_isbn)
    identifiers = {
        "doi": normalize_doi(crossref.get("DOI")),
        "issn": issns,
        "issn_l": normalize_issn(crossref.get("ISSN-L")),
        "isbn": isbns,
    }
    identifiers = {key: value for key, value in identifiers.items() if value}
    return {
        "publication": {
            "title": title,
            "publication_type": publication_type,
            "publisher": _clean_text(crossref.get("publisher"), 300),
            "issn_l": normalize_issn(crossref.get("ISSN-L")),
            "issns": issns,
            "isbns": isbns,
            "doi": normalize_doi(crossref.get("container-title-doi") or (crossref.get("DOI") if publication_type == "book" else None)),
            "source_url": _clean_text((crossref.get("resource") or {}).get("primary", {}).get("URL") or crossref.get("URL")),
            "external_ids": {"crossref": crossref.get("DOI")} if crossref.get("DOI") else {},
            "metadata": {"crossref_type": crossref_type},
            "evidence": {"crossref": crossref},
        },
        "appearance": {
            "appearance_type": appearance_type_from_crossref(crossref_type),
            "volume": _clean_text(crossref.get("volume"), 80),
            "issue": _clean_text(crossref.get("issue"), 80),
            "article_number": _clean_text(crossref.get("article-number"), 120),
            "page_range": _clean_text(crossref.get("page"), 120),
            "published_date": _crossref_date(crossref),
            "published_year": _crossref_year(crossref),
            "source_url": _clean_text((crossref.get("resource") or {}).get("primary", {}).get("URL") or crossref.get("URL")),
            "identifiers": identifiers,
            "confidence": 0.94,
            "source": "crossref",
            "evidence": {"crossref_work_type": crossref_type, "container_title": title},
        },
    }


def publication_candidate_from_ai(publication: dict[str, Any] | None, *, model: str | None = None) -> dict[str, Any] | None:
    if not isinstance(publication, dict):
        return None
    identifiers = publication.get("identifiers") if isinstance(publication.get("identifiers"), dict) else {}
    title = _clean_text(publication.get("title") or publication.get("publication_title"), 600)
    if not title:
        return None
    issns = _normalized_identifier_list(identifiers.get("issn") or publication.get("issn") or [], normalize_issn)
    isbns = _normalized_identifier_list(identifiers.get("isbn") or publication.get("isbn") or [], normalize_isbn)
    evidence = publication.get("evidence") if isinstance(publication.get("evidence"), dict) else {}
    source_url = _clean_text(publication.get("source_url") or identifiers.get("url"))
    confidence = _float(publication.get("confidence"))
    if confidence is None:
        confidence = 0.45
    return {
        "publication": {
            "title": title,
            "publication_type": _clean_text(publication.get("type") or publication.get("publication_type"), 60),
            "publisher": _clean_text(publication.get("publisher"), 300),
            "imprint": _clean_text(publication.get("imprint"), 300),
            "issn_l": normalize_issn(identifiers.get("issn_l") or publication.get("issn_l")),
            "issns": issns,
            "isbns": isbns,
            "doi": normalize_doi(identifiers.get("doi") or publication.get("doi")),
            "source_url": source_url,
            "external_ids": {
                key: value
                for key, value in {
                    "openalex": identifiers.get("openalex"),
                    "semantic_scholar": identifiers.get("semantic_scholar"),
                    "crossref": identifiers.get("crossref"),
                }.items()
                if value
            },
            "metadata": {"model": model} if model else {},
            "evidence": evidence,
        },
        "appearance": {
            "appearance_type": _clean_text(publication.get("appearance_type"), 80),
            "volume": _clean_text(publication.get("volume"), 80),
            "issue": _clean_text(publication.get("issue"), 80),
            "article_number": _clean_text(publication.get("article_number"), 120),
            "page_range": _clean_text(publication.get("page_range") or publication.get("pages"), 120),
            "published_date": _clean_text(publication.get("published_date"), 80),
            "published_year": _int(publication.get("published_year")),
            "edition": _clean_text(publication.get("edition"), 160),
            "chapter": _clean_text(publication.get("chapter"), 240),
            "section": _clean_text(publication.get("section"), 240),
            "series_title": _clean_text(publication.get("series_title"), 600),
            "event_name": _clean_text(publication.get("event_name"), 600),
            "source_url": source_url,
            "identifiers": {key: value for key, value in {"doi": normalize_doi(identifiers.get("doi")), "issn": issns, "isbn": isbns}.items() if value},
            "confidence": confidence,
            "source": "model",
            "model": model,
            "evidence": evidence,
        },
    }


def _candidate_from_recommendation(candidate: Any) -> dict[str, Any] | None:
    journal = _clean_text(getattr(candidate, "journal", None), 600)
    if not journal:
        return None
    provider = _clean_text(getattr(candidate, "provider", None), 80) or "provider"
    raw_metadata = getattr(candidate, "raw_metadata", None) or {}
    publication: dict[str, Any] = {
        "title": journal,
        "publication_type": "journal",
        "source_url": _clean_text(getattr(candidate, "source_url", None)),
        "external_ids": {},
        "metadata": {},
        "evidence": {"provider": provider, "raw_metadata": raw_metadata},
    }
    raw_work = raw_metadata.get("work") if isinstance(raw_metadata, dict) else None
    if provider == "openalex" and isinstance(raw_work, dict):
        source = ((raw_work.get("primary_location") or {}).get("source") or {})
        publication["external_ids"] = {"openalex_source": source.get("id")} if source.get("id") else {}
        publication["issn_l"] = normalize_issn(source.get("issn_l"))
        publication["issns"] = _normalized_identifier_list(source.get("issn") or [], normalize_issn)
        publication["source_url"] = source.get("homepage_url") or publication["source_url"]
    return {
        "publication": publication,
        "appearance": {
            "appearance_type": "article",
            "published_year": getattr(candidate, "publication_year", None),
            "source_url": _clean_text(getattr(candidate, "source_url", None)),
            "identifiers": {"doi": normalize_doi(getattr(candidate, "doi", None))} if normalize_doi(getattr(candidate, "doi", None)) else {},
            "confidence": 0.82 if provider in {"openalex", "semantic_scholar"} else 0.76,
            "source": provider,
            "evidence": {"provider": provider},
        },
    }


def _merge_candidate(base: dict[str, Any], fallback: dict[str, Any] | None) -> dict[str, Any]:
    if not fallback:
        return base
    merged = {"publication": dict(base.get("publication") or {}), "appearance": dict(base.get("appearance") or {})}
    for section in ("publication", "appearance"):
        for key, value in (fallback.get(section) or {}).items():
            if value in (None, "", [], {}):
                continue
            current = merged[section].get(key)
            if current in (None, "", [], {}):
                merged[section][key] = value
            elif key in {"evidence", "metadata", "external_ids", "identifiers"} and isinstance(current, dict) and isinstance(value, dict):
                merged[section][key] = {**value, **current}
            elif key in {"issns", "isbns"} and isinstance(current, list) and isinstance(value, list):
                merged[section][key] = _unique([*current, *value])
    return merged


def _candidate_priority(candidate: dict[str, Any]) -> tuple[int, float]:
    appearance = candidate.get("appearance") or {}
    source = str(appearance.get("source") or "").strip()
    confidence = _float(appearance.get("confidence")) or 0.0
    return PUBLICATION_SOURCE_PRIORITY.get(source, 0), confidence


def _http_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        with httpx.Client(timeout=settings.recommendations_request_timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _open_library_candidates(title: str | None, isbns: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for isbn in isbns[:2]:
        data = _http_json(f"https://openlibrary.org/isbn/{quote(isbn)}.json")
        if not data:
            continue
        candidate = _open_library_book_candidate(data)
        if candidate:
            candidates.append(candidate)
    if title and not candidates:
        data = _http_json("https://openlibrary.org/search.json", params={"title": title, "limit": 3})
        for doc in (data or {}).get("docs") or []:
            candidate = _open_library_book_candidate(doc)
            if candidate:
                candidates.append(candidate)
    return candidates


def _open_library_book_candidate(data: dict[str, Any]) -> dict[str, Any] | None:
    title = _clean_text(data.get("title"), 600)
    if not title:
        return None
    isbns = _normalized_identifier_list(data.get("isbn") or data.get("isbn_13") or data.get("isbn_10") or [], normalize_isbn)
    publishers = data.get("publishers") or data.get("publisher") or []
    publisher = _clean_text(_first(publishers), 300)
    year = _int(data.get("first_publish_year") or str(data.get("publish_date") or "")[:4])
    return {
        "publication": {
            "title": title,
            "publication_type": "book",
            "publisher": publisher,
            "isbns": isbns,
            "source_url": f"https://openlibrary.org{data.get('key')}" if data.get("key") else None,
            "external_ids": {"open_library": data.get("key")} if data.get("key") else {},
            "evidence": {"open_library": data},
        },
        "appearance": {
            "appearance_type": "book",
            "published_year": year,
            "identifiers": {"isbn": isbns} if isbns else {},
            "confidence": 0.66,
            "source": "open_library",
            "evidence": {"provider": "open_library"},
        },
    }


def _google_books_candidates(title: str | None, isbns: list[str]) -> list[dict[str, Any]]:
    queries = [f"isbn:{isbn}" for isbn in isbns[:2]]
    if title and not queries:
        queries.append(f"intitle:{title}")
    candidates: list[dict[str, Any]] = []
    for query in queries:
        data = _http_json("https://www.googleapis.com/books/v1/volumes", params={"q": query, "maxResults": 3})
        for item in (data or {}).get("items") or []:
            candidate = _google_books_candidate(item)
            if candidate:
                candidates.append(candidate)
    return candidates


def _google_books_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    info = item.get("volumeInfo") or {}
    title = _clean_text(info.get("title"), 600)
    if not title:
        return None
    identifiers = info.get("industryIdentifiers") or []
    isbns = _normalized_identifier_list([identifier.get("identifier") for identifier in identifiers], normalize_isbn)
    published_year = _int(str(info.get("publishedDate") or "")[:4])
    return {
        "publication": {
            "title": title,
            "publication_type": "book",
            "publisher": _clean_text(info.get("publisher"), 300),
            "isbns": isbns,
            "source_url": _clean_text(info.get("infoLink") or item.get("selfLink")),
            "external_ids": {"google_books": item.get("id")} if item.get("id") else {},
            "evidence": {"google_books": item},
        },
        "appearance": {
            "appearance_type": "book",
            "published_year": published_year,
            "identifiers": {"isbn": isbns} if isbns else {},
            "confidence": 0.7,
            "source": "google_books",
            "evidence": {"provider": "google_books"},
        },
    }


def _candidate_identifiers(candidate: dict[str, Any]) -> dict[str, Any]:
    publication = candidate.get("publication") or {}
    appearance = candidate.get("appearance") or {}
    identifiers = dict(appearance.get("identifiers") or {})
    if publication.get("doi"):
        identifiers.setdefault("container_doi", publication.get("doi"))
    if publication.get("issn_l"):
        identifiers.setdefault("issn_l", publication.get("issn_l"))
    if publication.get("issns"):
        identifiers.setdefault("issn", publication.get("issns"))
    if publication.get("isbns"):
        identifiers.setdefault("isbn", publication.get("isbns"))
    return {key: value for key, value in identifiers.items() if value not in (None, "", [], {})}


def find_matching_publication(db: Session, candidate: dict[str, Any]) -> Publication | None:
    publication = candidate.get("publication") or {}
    external_ids = publication.get("external_ids") if isinstance(publication.get("external_ids"), dict) else {}
    for key, value in external_ids.items():
        if not value:
            continue
        for row in db.query(Publication).all():
            if str((row.external_ids or {}).get(key) or "") == str(value):
                return row
    doi = normalize_doi(publication.get("doi"))
    if doi:
        row = db.query(Publication).filter(func.lower(Publication.doi) == doi).one_or_none()
        if row:
            return row
    issn_l = normalize_issn(publication.get("issn_l"))
    if issn_l:
        row = db.query(Publication).filter(Publication.issn_l == issn_l).one_or_none()
        if row:
            return row
    for isbn in _normalized_identifier_list(publication.get("isbns") or [], normalize_isbn):
        for row in db.query(Publication).all():
            if isbn in (row.isbns or []):
                return row
    for issn in _normalized_identifier_list(publication.get("issns") or [], normalize_issn):
        for row in db.query(Publication).all():
            if issn in (row.issns or []):
                return row
    normalized_title = normalize_publication_title(publication.get("title"))
    if normalized_title:
        query = db.query(Publication).filter(Publication.normalized_title == normalized_title)
        publication_type = _clean_text(publication.get("publication_type"), 60)
        if publication_type:
            query = query.filter(or_(Publication.publication_type == publication_type, Publication.publication_type.is_(None)))
        publisher = normalize_publication_title(publication.get("publisher"))
        rows = query.all()
        if publisher:
            for row in rows:
                if normalize_publication_title(row.publisher) == publisher:
                    return row
        if rows:
            return rows[0]
        alias = db.query(PublicationAlias).filter(PublicationAlias.normalized_alias == normalized_title).first()
        if alias:
            return alias.publication
    return None


def upsert_publication(db: Session, candidate: dict[str, Any]) -> Publication:
    payload = candidate.get("publication") or {}
    source = str((candidate.get("appearance") or {}).get("source") or "").strip()
    force_fields = source == "manual"
    title = _clean_text(payload.get("title"), 600)
    if not title:
        raise ValueError("Publication title is required")
    publication = find_matching_publication(db, candidate)
    if not publication:
        publication = Publication(title=title, normalized_title=normalize_publication_title(title))
        db.add(publication)
    if force_fields or not publication.title:
        publication.title = title
    publication.normalized_title = normalize_publication_title(publication.title or title)
    for field in ("publication_type", "publisher", "imprint", "source_url"):
        value = _clean_text(payload.get(field), 600 if field == "source_url" else 300)
        if value and (force_fields or not getattr(publication, field)):
            setattr(publication, field, value)
    doi = normalize_doi(payload.get("doi"))
    if doi and (force_fields or not publication.doi):
        publication.doi = doi
    issn_l = normalize_issn(payload.get("issn_l"))
    if issn_l and (force_fields or not publication.issn_l):
        publication.issn_l = issn_l
    publication.issns = _unique([*(publication.issns or []), *_normalized_identifier_list(payload.get("issns") or [], normalize_issn)])
    publication.isbns = _unique([*(publication.isbns or []), *_normalized_identifier_list(payload.get("isbns") or [], normalize_isbn)])
    if isinstance(payload.get("external_ids"), dict):
        publication.external_ids = {**(publication.external_ids or {}), **payload["external_ids"]}
    if isinstance(payload.get("metadata"), dict):
        publication.publication_metadata = {**(publication.publication_metadata or {}), **payload["metadata"]}
    if isinstance(payload.get("evidence"), dict):
        publication.evidence = {**(publication.evidence or {}), **payload["evidence"]}
    db.flush()
    if title and title != publication.title:
        normalized_alias = normalize_publication_title(title)
        if normalized_alias:
            existing_alias = (
                db.query(PublicationAlias)
                .filter(PublicationAlias.publication_id == publication.id, PublicationAlias.normalized_alias == normalized_alias)
                .one_or_none()
            )
            if not existing_alias:
                db.add(PublicationAlias(publication_id=publication.id, alias=title, normalized_alias=normalized_alias, source="metadata"))
    return publication


def primary_document_publication(document: Document | None) -> DocumentPublication | None:
    if not document:
        return None
    for link in document.publication_links or []:
        if link.role == "primary":
            return link
    if document.publication_links:
        return document.publication_links[0]
    db = object_session(document)
    if db and document.id:
        return (
            db.query(DocumentPublication)
            .filter(DocumentPublication.document_id == document.id, DocumentPublication.role == "primary")
            .one_or_none()
        )
    return None


def document_publication_is_verified(document: Document) -> bool:
    link = primary_document_publication(document)
    return bool(link and link.verification_status == PUBLICATION_VERIFIED_STATUS and link.verified_at)


def clear_document_publication_verification(document: Document) -> bool:
    link = primary_document_publication(document)
    if not link or link.verification_status != PUBLICATION_VERIFIED_STATUS:
        return False
    link.verification_status = PUBLICATION_NEEDS_REVIEW_STATUS
    link.verified_at = None
    link.verified_by = None
    link.verified_by_user_id = None
    return True


def mark_document_publication_verified(document: Document, user: User) -> bool:
    link = primary_document_publication(document)
    if not link or not link.publication:
        return False
    link.verification_status = PUBLICATION_VERIFIED_STATUS
    link.verified_at = utc_now()
    link.verified_by = user.email
    link.verified_by_user_id = user.id
    return True


def apply_publication_candidate(
    db: Session,
    document: Document,
    candidate: dict[str, Any],
    *,
    source: str,
    force: bool = False,
) -> set[str]:
    if document_publication_is_verified(document) and not force:
        return set()
    publication = upsert_publication(db, candidate)
    appearance = dict(candidate.get("appearance") or {})
    link = primary_document_publication(document)
    conflict: dict[str, Any] | None = None
    if not link:
        link = DocumentPublication(document=document, publication=publication, role="primary")
        db.add(link)
    elif link.publication_id != publication.id:
        conflict = {
            "previous_publication_id": link.publication_id,
            "previous_title": link.publication.title if link.publication else link.title_snapshot,
            "replacement_publication_id": publication.id,
            "replacement_title": publication.title,
        }
        link.publication = publication

    changed: set[str] = {"publication"}
    link.title_snapshot = publication.title
    link.publisher_snapshot = publication.publisher
    for field in (
        "appearance_type",
        "volume",
        "issue",
        "article_number",
        "page_range",
        "published_date",
        "published_year",
        "edition",
        "chapter",
        "section",
        "series_title",
        "event_name",
        "source_url",
        "model",
    ):
        value = appearance.get(field)
        if value not in (None, "", [], {}) and (force or getattr(link, field) in (None, "", [], {})):
            setattr(link, field, value)
    if appearance.get("confidence") is not None:
        link.confidence = appearance.get("confidence")
    link.source = source or appearance.get("source") or link.source
    link.identifiers = {**(link.identifiers or {}), **_candidate_identifiers(candidate)}
    evidence = dict(link.evidence or {})
    if conflict:
        evidence.setdefault("conflicts", []).append(conflict)
    if isinstance(appearance.get("evidence"), dict):
        evidence[appearance.get("source") or source or "metadata"] = appearance["evidence"]
    link.evidence = evidence
    if link.verification_status != PUBLICATION_VERIFIED_STATUS:
        link.verification_status = PUBLICATION_NEEDS_REVIEW_STATUS if conflict else PUBLICATION_UNVERIFIED_STATUS

    if document.journal != publication.title:
        document.journal = publication.title
        changed.add("journal")
    if publication.publisher and document.publisher != publication.publisher:
        document.publisher = publication.publisher
        changed.add("publisher")
    if link.published_year and document.publication_year in (None, 0):
        document.publication_year = link.published_year
        changed.add("publication_year")
    if link.source_url and not document.source_url:
        document.source_url = link.source_url
        changed.add("source_url")
    return changed


def apply_document_publication_patch(db: Session, document: Document, payload: dict[str, Any]) -> set[str]:
    if payload.get("clear"):
        link = primary_document_publication(document)
        if link:
            db.delete(link)
            document.journal = None
            document.publisher = None
            return {"publication", "journal", "publisher"}
        return set()
    existing = primary_document_publication(document)
    title = _clean_text(payload.get("title") or payload.get("publication_title") or (existing.publication.title if existing and existing.publication else None), 600)
    if not title:
        return set()
    identifiers = payload.get("identifiers") if isinstance(payload.get("identifiers"), dict) else {}
    publication_payload = {
        "title": title,
        "publication_type": _clean_text(payload.get("type") or payload.get("publication_type"), 60)
        or (existing.publication.publication_type if existing and existing.publication else None),
        "publisher": _clean_text(payload.get("publisher"), 300),
        "imprint": _clean_text(payload.get("imprint"), 300),
        "issn_l": normalize_issn(payload.get("issn_l") or identifiers.get("issn_l")),
        "issns": _normalized_identifier_list(payload.get("issns") or identifiers.get("issn") or [], normalize_issn),
        "isbns": _normalized_identifier_list(payload.get("isbns") or identifiers.get("isbn") or [], normalize_isbn),
        "doi": normalize_doi(payload.get("doi") or identifiers.get("doi")),
        "source_url": _clean_text(payload.get("source_url")),
        "external_ids": payload.get("external_ids") if isinstance(payload.get("external_ids"), dict) else {},
        "metadata": {"manual_notes": _clean_text(payload.get("notes"))} if payload.get("notes") else {},
        "evidence": {"manual": {"updated_at": utc_now().isoformat()}},
    }
    appearance_payload = {
        "appearance_type": _clean_text(payload.get("appearance_type"), 80),
        "volume": _clean_text(payload.get("volume"), 80),
        "issue": _clean_text(payload.get("issue"), 80),
        "article_number": _clean_text(payload.get("article_number"), 120),
        "page_range": _clean_text(payload.get("page_range"), 120),
        "published_date": _clean_text(payload.get("published_date"), 80),
        "published_year": _int(payload.get("published_year")),
        "edition": _clean_text(payload.get("edition"), 160),
        "chapter": _clean_text(payload.get("chapter"), 240),
        "section": _clean_text(payload.get("section"), 240),
        "series_title": _clean_text(payload.get("series_title"), 600),
        "event_name": _clean_text(payload.get("event_name"), 600),
        "source_url": _clean_text(payload.get("source_url")),
        "identifiers": {
            key: value
            for key, value in {
                "doi": normalize_doi(payload.get("doi") or identifiers.get("doi")),
                "issn_l": normalize_issn(payload.get("issn_l") or identifiers.get("issn_l")),
                "issn": _normalized_identifier_list(payload.get("issns") or identifiers.get("issn") or [], normalize_issn),
                "isbn": _normalized_identifier_list(payload.get("isbns") or identifiers.get("isbn") or [], normalize_isbn),
            }.items()
            if value
        },
        "confidence": 1.0,
        "source": "manual",
        "evidence": {"manual": {"updated_at": utc_now().isoformat()}},
    }
    return apply_publication_candidate(
        db,
        document,
        {"publication": publication_payload, "appearance": appearance_payload},
        source="manual",
        force=True,
    )


def lookup_publication_candidates(
    document: Document,
    *,
    crossref: dict[str, Any] | None = None,
    ai_publication: dict[str, Any] | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if crossref:
        candidate = publication_candidate_from_crossref(crossref)
        if candidate:
            candidates.append(candidate)
    if document.doi:
        try:
            from app.services.recommendations import resolve_doi_metadata_candidate

            doi_candidate = resolve_doi_metadata_candidate(document.doi, title=document.title, source_url=document.source_url)
            provider_candidate = _candidate_from_recommendation(doi_candidate)
            if provider_candidate:
                candidates.append(provider_candidate)
        except Exception:
            pass
    ai_candidate = publication_candidate_from_ai(ai_publication, model=model)
    if ai_candidate:
        candidates.append(ai_candidate)
        publication = ai_candidate.get("publication") or {}
        title = publication.get("title")
        isbns = _normalized_identifier_list(publication.get("isbns") or [], normalize_isbn)
        candidates.extend(_google_books_candidates(title, isbns))
        candidates.extend(_open_library_candidates(title, isbns))
    return candidates


def refresh_document_publication_metadata(
    db: Session,
    document: Document,
    *,
    ai_publication: dict[str, Any] | None = None,
    crossref: dict[str, Any] | None = None,
    model: str | None = None,
    source: str = "concordance",
    force: bool = False,
) -> dict[str, Any]:
    if document_publication_is_verified(document) and not force:
        return {"status": "skipped_verified", "publication_id": primary_document_publication(document).publication_id}
    evidence_crossref = crossref
    if not evidence_crossref and document.doi:
        evidence_crossref = crossref_lookup(document.doi, document.title, document.authors, document.publication_year)
    candidates = lookup_publication_candidates(document, crossref=evidence_crossref, ai_publication=ai_publication, model=model)
    if not candidates:
        legacy_candidate = publication_candidate_from_document_metadata(document)
        if legacy_candidate:
            candidates.append(legacy_candidate)
    if not candidates:
        return {"status": "not_found", "candidate_count": 0}
    provider_candidates = [candidate for candidate in candidates if (candidate.get("appearance") or {}).get("source") != "model"]
    model_candidate = next((candidate for candidate in candidates if (candidate.get("appearance") or {}).get("source") == "model"), None)
    base = sorted(provider_candidates or candidates, key=_candidate_priority, reverse=True)[0]
    merged = _merge_candidate(base, model_candidate)
    changed_fields = apply_publication_candidate(db, document, merged, source=source or (merged.get("appearance") or {}).get("source"), force=force)
    link = primary_document_publication(document)
    return {
        "status": "updated" if changed_fields else "unchanged",
        "candidate_count": len(candidates),
        "candidate_sources": [str((candidate.get("appearance") or {}).get("source") or "") for candidate in candidates],
        "publication_id": link.publication_id if link else None,
        "publication_title": link.publication.title if link and link.publication else None,
        "changed_fields": sorted(changed_fields),
    }


def document_publication_citation_metadata(document: Document) -> dict[str, Any]:
    link = primary_document_publication(document)
    if not link:
        return {}
    publication = link.publication
    metadata = {
        "journal": publication.title if publication else link.title_snapshot,
        "publisher": publication.publisher if publication else link.publisher_snapshot,
        "volume": link.volume,
        "issue": link.issue,
        "page": link.page_range,
        "pages": link.page_range,
        "article_number": link.article_number,
        "source_url": link.source_url or (publication.source_url if publication else None),
        "type": link.appearance_type or (publication.publication_type if publication else None),
        "edition": link.edition,
        "chapter": link.chapter,
        "series_title": link.series_title,
        "event_name": link.event_name,
    }
    return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}


def publication_search_text(document: Document) -> str:
    link = primary_document_publication(document)
    if not link:
        return ""
    publication = link.publication
    identifiers = link.identifiers or {}
    parts = [
        publication.title if publication else link.title_snapshot,
        publication.publisher if publication else link.publisher_snapshot,
        publication.publication_type if publication else None,
        publication.issn_l if publication else None,
        " ".join(publication.issns or []) if publication else None,
        " ".join(publication.isbns or []) if publication else None,
        link.volume,
        link.issue,
        link.article_number,
        link.page_range,
        link.edition,
        link.chapter,
        link.section,
        link.series_title,
        link.event_name,
        " ".join(str(value) for value in identifiers.values() if value),
    ]
    return "\n".join(str(part) for part in parts if part)


def publication_to_dict(link: DocumentPublication | None) -> dict[str, Any] | None:
    if not link or not link.publication:
        return None
    publication = link.publication
    return {
        "id": link.id,
        "publication_id": publication.id,
        "role": link.role,
        "title": publication.title,
        "type": publication.publication_type,
        "publisher": publication.publisher,
        "imprint": publication.imprint,
        "issn_l": publication.issn_l,
        "issns": publication.issns or [],
        "isbns": publication.isbns or [],
        "doi": publication.doi,
        "source_url": link.source_url or publication.source_url,
        "external_ids": publication.external_ids or {},
        "appearance_type": link.appearance_type,
        "volume": link.volume,
        "issue": link.issue,
        "article_number": link.article_number,
        "page_range": link.page_range,
        "published_date": link.published_date,
        "published_year": link.published_year,
        "edition": link.edition,
        "chapter": link.chapter,
        "section": link.section,
        "series_title": link.series_title,
        "event_name": link.event_name,
        "identifiers": link.identifiers or {},
        "confidence": float(link.confidence) if link.confidence is not None else None,
        "source": link.source,
        "model": link.model,
        "verification_status": link.verification_status,
        "verified_at": link.verified_at,
        "verified_by": link.verified_by,
        "evidence": link.evidence or {},
    }


def publication_candidate_from_document_metadata(document: Document) -> dict[str, Any] | None:
    if not (document.journal or document.publisher):
        return None
    title = document.journal or document.publisher
    return {
        "publication": {
            "title": title,
            "publication_type": "unknown",
            "publisher": document.publisher,
            "source_url": document.source_url,
            "evidence": {"legacy": {"journal": document.journal, "publisher": document.publisher}},
        },
        "appearance": {
            "published_year": document.publication_year,
            "source_url": document.source_url,
            "confidence": 0.25,
            "source": "legacy",
            "evidence": {"legacy": True},
        },
    }


def crossref_document_metadata(document: Document) -> dict[str, Any]:
    crossref = crossref_lookup(document.doi, document.title, document.authors, document.publication_year) if document.doi else None
    return crossref_to_citation_metadata(crossref) if crossref else {}
