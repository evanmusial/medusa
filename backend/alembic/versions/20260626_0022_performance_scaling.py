from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260626_0022"
down_revision = "20260626_0021"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return column_name in {column["name"] for column in inspect(bind).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column("documents", "duplicate_count"):
        op.add_column("documents", sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"))
    if not _has_column("documents", "duplicate_reasons"):
        op.add_column("documents", sa.Column("duplicate_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    if not _has_column("documents", "duplicate_checked_at"):
        op.add_column("documents", sa.Column("duplicate_checked_at", sa.DateTime(timezone=True), nullable=True))

    indexes = _index_names("documents")
    if "ix_documents_duplicate_count" not in indexes:
        op.create_index("ix_documents_duplicate_count", "documents", ["duplicate_count"])

    if bind.dialect.name == "postgresql":
        bind.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_full_text_gin
                ON documents USING gin (
                  to_tsvector(
                    'english',
                    coalesce(title, '') || ' ' ||
                    coalesce(search_text, '') || ' ' ||
                    coalesce(apa_citation, '') || ' ' ||
                    coalesce(apa_in_text_citation, '')
                  )
                )
                """
            )
        )
        bind.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_library_ready_filters
                ON documents (read_status, priority, citation_status, duplicate_count)
                WHERE deleted_at IS NULL AND processing_status IN ('ready', 'complete', 'completed', 'restored')
                """
            )
        )
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_document_tags_tag_id ON document_tags (tag_id)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_document_domains_domain_id ON document_domains (domain_id)"))
    else:
        indexes = _index_names("document_tags")
        if "ix_document_tags_tag_id" not in indexes:
            op.create_index("ix_document_tags_tag_id", "document_tags", ["tag_id"])
        indexes = _index_names("document_domains")
        if "ix_document_domains_domain_id" not in indexes:
            op.create_index("ix_document_domains_domain_id", "document_domains", ["domain_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(text("DROP INDEX IF EXISTS ix_document_domains_domain_id"))
        bind.execute(text("DROP INDEX IF EXISTS ix_document_tags_tag_id"))
        bind.execute(text("DROP INDEX IF EXISTS ix_documents_library_ready_filters"))
        bind.execute(text("DROP INDEX IF EXISTS ix_documents_full_text_gin"))
    else:
        indexes = _index_names("document_domains")
        if "ix_document_domains_domain_id" in indexes:
            op.drop_index("ix_document_domains_domain_id", table_name="document_domains")
        indexes = _index_names("document_tags")
        if "ix_document_tags_tag_id" in indexes:
            op.drop_index("ix_document_tags_tag_id", table_name="document_tags")
    indexes = _index_names("documents")
    if "ix_documents_duplicate_count" in indexes:
        op.drop_index("ix_documents_duplicate_count", table_name="documents")
    if _has_column("documents", "duplicate_checked_at"):
        op.drop_column("documents", "duplicate_checked_at")
    if _has_column("documents", "duplicate_reasons"):
        op.drop_column("documents", "duplicate_reasons")
    if _has_column("documents", "duplicate_count"):
        op.drop_column("documents", "duplicate_count")
