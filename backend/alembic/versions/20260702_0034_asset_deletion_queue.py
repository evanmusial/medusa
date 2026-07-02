"""Add deferred asset deletion queue."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260702_0034"
down_revision = "20260630_0033"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "asset_deletion_queue" in _table_names():
        return
    op.create_table(
        "asset_deletion_queue",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("cdn_url_path", sa.Text(), nullable=True),
        sa.Column("cdn_invalidation_path", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("storage_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_deletion_queue_status", "asset_deletion_queue", ["status"])
    op.create_index("ix_asset_deletion_queue_source_kind", "asset_deletion_queue", ["source_kind"])
    op.create_index("ix_asset_deletion_queue_source_id", "asset_deletion_queue", ["source_id"])
    op.create_index("ix_asset_deletion_queue_document_id", "asset_deletion_queue", ["document_id"])


def downgrade() -> None:
    if "asset_deletion_queue" in _table_names():
        op.drop_table("asset_deletion_queue")
