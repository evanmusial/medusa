from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260630_0032"
down_revision = "20260629_0031"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    tables = _table_names()
    if "publications" not in tables:
        op.create_table(
            "publications",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=600), nullable=False),
            sa.Column("normalized_title", sa.String(length=600), nullable=False),
            sa.Column("publication_type", sa.String(length=60), nullable=True),
            sa.Column("publisher", sa.String(length=300), nullable=True),
            sa.Column("imprint", sa.String(length=300), nullable=True),
            sa.Column("issn_l", sa.String(length=32), nullable=True),
            sa.Column("issns", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("isbns", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("doi", sa.String(length=256), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("external_ids", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = _index_names("publications")
    for name, columns in {
        "ix_publications_normalized_title": ["normalized_title"],
        "ix_publications_publication_type": ["publication_type"],
        "ix_publications_issn_l": ["issn_l"],
        "ix_publications_doi": ["doi"],
        "ix_publications_normalized_title_type": ["normalized_title", "publication_type"],
    }.items():
        if name not in indexes:
            op.create_index(name, "publications", columns)

    tables = _table_names()
    if "publication_aliases" not in tables:
        op.create_table(
            "publication_aliases",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("publication_id", sa.String(length=36), nullable=False),
            sa.Column("alias", sa.String(length=600), nullable=False),
            sa.Column("normalized_alias", sa.String(length=600), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("publication_id", "normalized_alias", name="uq_publication_alias_normalized"),
        )
    indexes = _index_names("publication_aliases")
    for name, columns in {
        "ix_publication_aliases_publication_id": ["publication_id"],
        "ix_publication_aliases_normalized_alias": ["normalized_alias"],
    }.items():
        if name not in indexes:
            op.create_index(name, "publication_aliases", columns)

    tables = _table_names()
    if "document_publications" not in tables:
        op.create_table(
            "document_publications",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("publication_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False),
            sa.Column("appearance_type", sa.String(length=80), nullable=True),
            sa.Column("title_snapshot", sa.String(length=600), nullable=True),
            sa.Column("publisher_snapshot", sa.String(length=300), nullable=True),
            sa.Column("volume", sa.String(length=80), nullable=True),
            sa.Column("issue", sa.String(length=80), nullable=True),
            sa.Column("article_number", sa.String(length=120), nullable=True),
            sa.Column("page_range", sa.String(length=120), nullable=True),
            sa.Column("published_date", sa.String(length=80), nullable=True),
            sa.Column("published_year", sa.Integer(), nullable=True),
            sa.Column("edition", sa.String(length=160), nullable=True),
            sa.Column("chapter", sa.String(length=240), nullable=True),
            sa.Column("section", sa.String(length=240), nullable=True),
            sa.Column("series_title", sa.String(length=600), nullable=True),
            sa.Column("event_name", sa.String(length=600), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("identifiers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=True),
            sa.Column("model", sa.String(length=160), nullable=True),
            sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="needs_review"),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_by", sa.String(length=320), nullable=True),
            sa.Column("verified_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_id", "role", name="uq_document_publication_role"),
        )
    indexes = _index_names("document_publications")
    for name, columns in {
        "ix_document_publications_document_id": ["document_id"],
        "ix_document_publications_publication_id": ["publication_id"],
        "ix_document_publications_role": ["role"],
        "ix_document_publications_appearance_type": ["appearance_type"],
        "ix_document_publications_source": ["source"],
        "ix_document_publications_verification_status": ["verification_status"],
        "ix_document_publications_document_role": ["document_id", "role"],
        "ix_document_publications_publication_role": ["publication_id", "role"],
    }.items():
        if name not in indexes:
            op.create_index(name, "document_publications", columns)


def downgrade() -> None:
    for table_name in ("document_publications", "publication_aliases", "publications"):
        if table_name in _table_names():
            op.drop_table(table_name)
