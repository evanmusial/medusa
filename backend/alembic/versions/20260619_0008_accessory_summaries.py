from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260619_0008"
down_revision = "20260619_0007"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("document_accessory_summaries"):
        return
    op.create_table(
        "document_accessory_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_accessory_summaries_document_id",
        "document_accessory_summaries",
        ["document_id"],
    )
    op.create_index(
        "ix_document_accessory_summaries_status",
        "document_accessory_summaries",
        ["status"],
    )


def downgrade() -> None:
    if _has_table("document_accessory_summaries"):
        op.drop_table("document_accessory_summaries")
