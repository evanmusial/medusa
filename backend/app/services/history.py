from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Document, DocumentPage, DocumentVersion
from app.services.publications import publication_to_dict, primary_document_publication


def _figure_snapshot(document: Document) -> list[dict[str, Any]]:
    return [
        {
            "id": figure.id,
            "page_number": figure.page_number,
            "figure_label": figure.figure_label,
            "caption": figure.caption,
            "gist": figure.gist,
            "asset_uri": figure.asset_uri,
            "geometry": figure.geometry,
        }
        for figure in sorted(document.figures, key=lambda item: (item.page_number or 0, item.figure_label or "", item.id))
    ]


def document_correction_snapshot(document: Document) -> dict[str, Any]:
    return {
        "title": document.title,
        "subtitle": document.subtitle,
        "authors": document.authors,
        "universities": document.universities,
        "publication_year": document.publication_year,
        "publisher": document.publisher,
        "journal": document.journal,
        "doi": document.doi,
        "source_url": document.source_url,
        "abstract": document.abstract,
        "rich_summary": document.rich_summary,
        "bibliography": document.bibliography,
        "apa_citation": document.apa_citation,
        "apa_citation_model": document.apa_citation_model,
        "apa_citation_source": document.apa_citation_source,
        "apa_in_text_citation": document.apa_in_text_citation,
        "apa_in_text_citation_model": document.apa_in_text_citation_model,
        "apa_in_text_citation_source": document.apa_in_text_citation_source,
        "citation_status": document.citation_status,
        "metadata_confidence": float(document.metadata_confidence) if document.metadata_confidence is not None else None,
        "metadata_evidence": document.metadata_evidence,
        "publication": publication_to_dict(primary_document_publication(document)),
        "read_status": document.read_status,
        "priority": document.priority,
        "tags": [tag.name for tag in document.tags],
        "domains": [domain.id for domain in document.domains],
        "attributes": {value.definition.name: value.value for value in document.attributes if value.definition},
        "figures": _figure_snapshot(document),
    }


def document_page_snapshot(page: DocumentPage) -> dict[str, Any]:
    return {
        "id": page.id,
        "page_number": page.page_number,
        "text": page.text,
        "normalized_text": page.normalized_text,
        "text_source": page.text_source,
        "low_text": page.low_text,
        "image_uri": page.image_uri,
    }


def next_document_version_number(db: Session, document_id: str) -> int:
    return (
        db.query(func.max(DocumentVersion.version_number))
        .filter(DocumentVersion.document_id == document_id)
        .scalar()
        or 0
    ) + 1


def record_document_version(
    db: Session,
    *,
    document: Document,
    change_note: str,
    changed_fields: list[str] | set[str],
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> DocumentVersion:
    snapshot: dict[str, Any] = {
        "changed_fields": sorted(changed_fields),
    }
    if before is not None:
        snapshot["before"] = before
    if after is not None:
        snapshot["after"] = after
    if extra:
        snapshot.update(extra)
    version = DocumentVersion(
        document_id=document.id,
        version_number=next_document_version_number(db, document.id),
        change_note=change_note,
        metadata_snapshot=snapshot,
    )
    db.add(version)
    return version


def changed_snapshot_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
