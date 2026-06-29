from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260629_0031"
down_revision = "20260629_0030"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("documents")
    if "locked_at" not in columns:
        op.add_column("documents", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    indexes = _index_names("documents")
    if "ix_documents_locked_at" not in indexes:
        op.create_index("ix_documents_locked_at", "documents", ["locked_at"])


def downgrade() -> None:
    columns = _column_names("documents")
    indexes = _index_names("documents")
    if "ix_documents_locked_at" in indexes:
        op.drop_index("ix_documents_locked_at", table_name="documents")
    if "locked_at" in columns:
        op.drop_column("documents", "locked_at")
