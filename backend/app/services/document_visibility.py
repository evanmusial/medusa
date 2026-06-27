from __future__ import annotations

from sqlalchemy import and_

from app.models import Document


LIBRARY_VISIBLE_DOCUMENT_STATUSES = ("ready", "complete", "completed", "restored")
LIBRARY_DOCUMENT_KIND = "library"


def document_is_library_visible(document: Document | None) -> bool:
    return bool(
        document
        and document.deleted_at is None
        and getattr(document, "document_kind", LIBRARY_DOCUMENT_KIND) == LIBRARY_DOCUMENT_KIND
        and document.processing_status in LIBRARY_VISIBLE_DOCUMENT_STATUSES
    )


def library_visible_document_filter():
    return and_(
        Document.deleted_at.is_(None),
        Document.document_kind == LIBRARY_DOCUMENT_KIND,
        Document.processing_status.in_(LIBRARY_VISIBLE_DOCUMENT_STATUSES),
    )


def filter_library_visible_documents(query):
    return query.filter(library_visible_document_filter())
