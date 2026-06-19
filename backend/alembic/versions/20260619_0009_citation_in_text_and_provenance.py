from __future__ import annotations

import json
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260619_0009"
down_revision = "20260619_0008"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return value


def _family(author: Any) -> str:
    if isinstance(author, dict):
        return str(author.get("family") or "").strip()
    text_value = str(author or "").strip()
    if not text_value:
        return ""
    return text_value.split(",")[0].split()[-1]


def _in_text_citation(title: str | None, authors: Any, year: Any) -> str:
    families = [family for author in (_decode_json(authors) or []) if (family := _family(author))]
    year_text = str(year or "n.d.").strip() or "n.d."
    if not families:
        words = str(title or "Untitled work").strip().rstrip(".?!").split()
        short_title = " ".join(words[:4]) if words else "Untitled work"
        return f'("{short_title}", {year_text})'
    if len(families) == 1:
        author_text = families[0]
    elif len(families) == 2:
        author_text = f"{families[0]} & {families[1]}"
    else:
        author_text = f"{families[0]} et al."
    return f"({author_text}, {year_text})"


def upgrade() -> None:
    columns = [
        ("apa_citation_model", sa.String(length=160)),
        ("apa_citation_source", sa.String(length=40)),
        ("apa_in_text_citation", sa.Text()),
        ("apa_in_text_citation_model", sa.String(length=160)),
        ("apa_in_text_citation_source", sa.String(length=40)),
    ]
    for name, column_type in columns:
        if not _has_column("documents", name):
            op.add_column("documents", sa.Column(name, column_type, nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT id, title, authors, publication_year, apa_citation
            FROM documents
            WHERE apa_citation IS NOT NULL AND trim(apa_citation) != ''
            """
        )
    ).mappings()
    for row in rows:
        bind.execute(
            text(
                """
                UPDATE documents
                SET apa_citation_model = COALESCE(apa_citation_model, :model),
                    apa_citation_source = COALESCE(apa_citation_source, :source),
                    apa_in_text_citation = COALESCE(apa_in_text_citation, :in_text),
                    apa_in_text_citation_model = COALESCE(apa_in_text_citation_model, :model),
                    apa_in_text_citation_source = COALESCE(apa_in_text_citation_source, :source)
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "model": "gpt-5.5",
                "source": "model",
                "in_text": _in_text_citation(row["title"], row["authors"], row["publication_year"]),
            },
        )


def downgrade() -> None:
    for name in [
        "apa_in_text_citation_source",
        "apa_in_text_citation_model",
        "apa_in_text_citation",
        "apa_citation_source",
        "apa_citation_model",
    ]:
        if _has_column("documents", name):
            op.drop_column("documents", name)
