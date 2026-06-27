from __future__ import annotations

import json
from typing import Any

from sqlalchemy import String, func, literal_column, or_
from sqlalchemy.orm import Session

from app.models import Document
from app.services.extraction import sanitize_extracted_text
from app.services.formulas import formula_capture_search_text
from app.services.processing import author_search_text, document_reading_text, figure_search_text


def _attribute_value_text(value: dict[str, Any]) -> str:
    if "value" in value:
        return str(value["value"])
    return json.dumps(value, sort_keys=True)


def accessory_summary_search_text(document: Document) -> str:
    return "\n\n".join(
        part
        for summary in sorted(document.accessory_summaries, key=lambda item: (item.created_at, item.id))
        if summary.status == "complete" and summary.summary
        for part in [summary.title, summary.prompt, summary.summary]
        if part
    )


def rebuild_document_search_text(document: Document) -> str:
    page_text = document_reading_text(document)
    notes = "\n\n".join(note.body for note in document.notes if not note.deleted_at)
    annotations = "\n\n".join(annotation.body or "" for annotation in document.annotations if not annotation.deleted_at)
    attributes = "\n\n".join(
        f"{value.definition.name}: {_attribute_value_text(value.value)}" for value in document.attributes if value.definition
    )
    return sanitize_extracted_text(
        "\n\n".join(
            part
            for part in [
                document.title,
                author_search_text(document.authors),
                document.abstract,
                document.rich_summary,
                document.bibliography,
                document.apa_citation,
                document.apa_in_text_citation,
                page_text,
                formula_capture_search_text(document),
                figure_search_text(document.figures),
                accessory_summary_search_text(document),
                notes,
                annotations,
                attributes,
                " ".join(tag.name for tag in document.tags),
                " ".join(domain.name for domain in document.domains),
            ]
            if part
        )
    )


def document_search_condition_and_rank(db: Session, term: str):
    cleaned = term.strip()
    if not cleaned:
        return None, None
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        empty = literal_column("''", type_=String())
        space = literal_column("' '", type_=String())
        search_document = (
            func.coalesce(Document.title, empty)
            + space
            + func.coalesce(Document.search_text, empty)
            + space
            + func.coalesce(Document.apa_citation, empty)
            + space
            + func.coalesce(Document.apa_in_text_citation, empty)
        )
        vector = func.to_tsvector(
            literal_column("'english'"),
            search_document,
        )
        query = func.websearch_to_tsquery(literal_column("'english'"), cleaned)
        title_like = f"%{cleaned}%"
        return or_(vector.op("@@")(query), Document.title.ilike(title_like)), func.ts_rank_cd(vector, query)

    like = f"%{cleaned}%"
    return (
        or_(
            Document.title.ilike(like),
            Document.search_text.ilike(like),
            Document.apa_citation.ilike(like),
            Document.apa_in_text_citation.ilike(like),
        ),
        None,
    )
