from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion
from app.services.document_visibility import filter_library_visible_documents


REASON_LABELS = {
    "sha256": "SHA-256",
    "md5": "MD5",
    "doi": "DOI",
    "title": "title",
    "authors": "authors",
    "publication_year": "year",
    "journal": "journal",
    "publisher": "publisher",
    "source_url": "source URL",
    "page_count": "page count",
}
REASON_ORDER = ["sha256", "md5", "doi", "title", "authors", "publication_year", "journal", "publisher", "source_url", "page_count"]


@dataclass(frozen=True)
class DuplicateProfile:
    id: str | None
    title: str
    authors: list[dict[str, Any]] = field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    publisher: str | None = None
    doi: str | None = None
    source_url: str | None = None
    original_filename: str | None = None
    page_count: int | None = None
    sha256_fingerprints: frozenset[str] = field(default_factory=frozenset)
    md5_fingerprints: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class DuplicateMatch:
    document: Document
    match_reasons: list[str]
    match_score: int

    @property
    def match_basis(self) -> str:
        return match_basis(self.match_reasons)


def normalize_duplicate_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_duplicate_title(value: str | None) -> str:
    text = normalize_duplicate_text(value)
    text = re.sub(r"^(a|an|the)\s+", "", text)
    return text


def normalize_duplicate_doi(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text.strip(" .")


def normalize_duplicate_url(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    return text.rstrip("/")


def _fingerprint(value: Any, length: int) -> str | None:
    text = str(value or "").strip().lower()
    if len(text) == length and re.fullmatch(r"[a-f0-9]+", text):
        return text
    return None


def document_sha256_fingerprints(document: Document) -> set[str]:
    evidence = document.metadata_evidence or {}
    source_import = evidence.get("source_import") if isinstance(evidence.get("source_import"), dict) else {}
    mezzanine = source_import.get("mezzanine") if isinstance(source_import.get("mezzanine"), dict) else {}
    values = {
        _fingerprint(document.checksum_sha256, 64),
        _fingerprint(source_import.get("source_checksum_sha256"), 64),
        _fingerprint(source_import.get("stored_checksum_sha256"), 64),
        _fingerprint(mezzanine.get("checksum_sha256"), 64),
    }
    return {value for value in values if value}


def document_md5_fingerprints(document: Document) -> set[str]:
    evidence = document.metadata_evidence or {}
    source_import = evidence.get("source_import") if isinstance(evidence.get("source_import"), dict) else {}
    mezzanine = source_import.get("mezzanine") if isinstance(source_import.get("mezzanine"), dict) else {}
    values = {
        _fingerprint(document.checksum_md5, 32),
        _fingerprint(source_import.get("source_checksum_md5"), 32),
        _fingerprint(source_import.get("stored_checksum_md5"), 32),
        _fingerprint(mezzanine.get("checksum_md5"), 32),
    }
    return {value for value in values if value}


def author_family_keys(authors: list[dict[str, Any]] | None) -> set[str]:
    keys: set[str] = set()
    for author in authors or []:
        family = normalize_duplicate_text(str(author.get("family") or ""))
        given = normalize_duplicate_text(str(author.get("given") or ""))
        literal = normalize_duplicate_text(str(author.get("name") or author.get("display") or ""))
        if family:
            keys.add(family)
        elif literal:
            keys.add(literal.split(" ")[-1])
        elif given:
            keys.add(given)
    return {key for key in keys if key}


def document_duplicate_profile(document: Document) -> DuplicateProfile:
    return DuplicateProfile(
        id=document.id,
        title=document.title,
        authors=document.authors or [],
        publication_year=document.publication_year,
        journal=document.journal,
        publisher=document.publisher,
        doi=document.doi,
        source_url=document.source_url,
        original_filename=document.original_filename,
        page_count=document.page_count,
        sha256_fingerprints=frozenset(document_sha256_fingerprints(document)),
        md5_fingerprints=frozenset(document_md5_fingerprints(document)),
    )


def import_duplicate_profile(
    *,
    title: str,
    original_filename: str | None = None,
    source_checksum_sha256: str | None = None,
    stored_checksum_sha256: str | None = None,
    source_checksum_md5: str | None = None,
    stored_checksum_md5: str | None = None,
    page_count: int | None = None,
    doi: str | None = None,
    authors: list[dict[str, Any]] | None = None,
    publication_year: int | None = None,
    journal: str | None = None,
    publisher: str | None = None,
    source_url: str | None = None,
) -> DuplicateProfile:
    return DuplicateProfile(
        id=None,
        title=title,
        authors=authors or [],
        publication_year=publication_year,
        journal=journal,
        publisher=publisher,
        doi=doi,
        source_url=source_url,
        original_filename=original_filename,
        page_count=page_count,
        sha256_fingerprints=frozenset(
            value for value in (_fingerprint(source_checksum_sha256, 64), _fingerprint(stored_checksum_sha256, 64)) if value
        ),
        md5_fingerprints=frozenset(
            value for value in (_fingerprint(source_checksum_md5, 32), _fingerprint(stored_checksum_md5, 32)) if value
        ),
    )


def duplicate_match_reasons(left: DuplicateProfile, right: DuplicateProfile) -> list[str]:
    if left.id and right.id and left.id == right.id:
        return []
    reasons: set[str] = set()
    if left.sha256_fingerprints and right.sha256_fingerprints and left.sha256_fingerprints.intersection(right.sha256_fingerprints):
        reasons.add("sha256")
    if left.md5_fingerprints and right.md5_fingerprints and left.md5_fingerprints.intersection(right.md5_fingerprints):
        reasons.add("md5")

    left_doi = normalize_duplicate_doi(left.doi)
    right_doi = normalize_duplicate_doi(right.doi)
    if left_doi and right_doi and left_doi == right_doi:
        reasons.add("doi")

    left_title = normalize_duplicate_title(left.title)
    right_title = normalize_duplicate_title(right.title)
    if left_title and right_title and left_title == right_title:
        reasons.add("title")
        left_authors = author_family_keys(left.authors)
        right_authors = author_family_keys(right.authors)
        if left_authors and right_authors and left_authors.intersection(right_authors):
            reasons.add("authors")
        if left.publication_year and right.publication_year and left.publication_year == right.publication_year:
            reasons.add("publication_year")
        if normalize_duplicate_text(left.journal) and normalize_duplicate_text(left.journal) == normalize_duplicate_text(right.journal):
            reasons.add("journal")
        if normalize_duplicate_text(left.publisher) and normalize_duplicate_text(left.publisher) == normalize_duplicate_text(right.publisher):
            reasons.add("publisher")
        if normalize_duplicate_url(left.source_url) and normalize_duplicate_url(left.source_url) == normalize_duplicate_url(right.source_url):
            reasons.add("source_url")
        if left.page_count and right.page_count and abs(int(left.page_count) - int(right.page_count)) <= 1:
            reasons.add("page_count")

    return [reason for reason in REASON_ORDER if reason in reasons]


def duplicate_match_score(reasons: list[str]) -> int:
    reason_set = set(reasons)
    if "sha256" in reason_set:
        return 100
    if "md5" in reason_set:
        return 98
    if "doi" in reason_set and "title" in reason_set:
        return 94
    if "doi" in reason_set:
        return 88
    if "title" in reason_set:
        supporting = len(reason_set.intersection({"authors", "publication_year", "journal", "publisher", "source_url", "page_count"}))
        return 68 + min(18, supporting * 6)
    return 0


def is_duplicate_match(reasons: list[str]) -> bool:
    return duplicate_match_score(reasons) >= 60


def match_basis(reasons: list[str]) -> str:
    labels = [REASON_LABELS.get(reason, reason.replace("_", " ")) for reason in reasons]
    return " + ".join(labels)


def duplicate_matches_by_document(db: Session, *, documents: list[Document] | None = None) -> dict[str, list[DuplicateMatch]]:
    visible_documents = documents or filter_library_visible_documents(db.query(Document)).all()
    profiles = {document.id: document_duplicate_profile(document) for document in visible_documents}
    matches: dict[str, list[DuplicateMatch]] = {document.id: [] for document in visible_documents}
    for index, left_document in enumerate(visible_documents):
        left_profile = profiles[left_document.id]
        for right_document in visible_documents[index + 1 :]:
            reasons = duplicate_match_reasons(left_profile, profiles[right_document.id])
            if not is_duplicate_match(reasons):
                continue
            score = duplicate_match_score(reasons)
            matches[left_document.id].append(DuplicateMatch(document=right_document, match_reasons=reasons, match_score=score))
            matches[right_document.id].append(DuplicateMatch(document=left_document, match_reasons=reasons, match_score=score))
    for document_matches in matches.values():
        document_matches.sort(key=lambda item: (-item.match_score, item.document.created_at, item.document.id))
    return matches


def duplicate_document_id_set(db: Session) -> set[str]:
    return {document_id for document_id, matches in duplicate_matches_by_document(db).items() if matches}


def active_duplicate_matches_for_profile(
    db: Session,
    profile: DuplicateProfile,
    *,
    statuses: tuple[str, ...],
) -> list[DuplicateMatch]:
    candidates = (
        db.query(Document)
        .filter(Document.deleted_at.is_(None), Document.processing_status.in_(statuses))
        .order_by(Document.created_at.desc(), Document.id)
        .all()
    )
    matches: list[DuplicateMatch] = []
    for document in candidates:
        reasons = duplicate_match_reasons(profile, document_duplicate_profile(document))
        if is_duplicate_match(reasons):
            matches.append(DuplicateMatch(document=document, match_reasons=reasons, match_score=duplicate_match_score(reasons)))
    matches.sort(key=lambda item: (-item.match_score, item.document.created_at, item.document.id))
    return matches


def duplicate_document_version_stats(db: Session, document_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not document_ids:
        return {}
    rows = (
        db.query(DocumentVersion.document_id, DocumentVersion.created_at)
        .filter(DocumentVersion.document_id.in_(document_ids))
        .order_by(DocumentVersion.created_at.asc())
        .all()
    )
    stats: dict[str, dict[str, Any]] = {document_id: {"version_count": 0, "latest_version_at": None} for document_id in document_ids}
    for document_id, created_at in rows:
        row = stats.setdefault(document_id, {"version_count": 0, "latest_version_at": None})
        row["version_count"] += 1
        latest = row.get("latest_version_at")
        if latest is None or (isinstance(created_at, datetime) and created_at > latest):
            row["latest_version_at"] = created_at
    return stats
