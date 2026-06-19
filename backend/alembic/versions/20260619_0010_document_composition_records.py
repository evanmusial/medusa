from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260619_0010"
down_revision = "20260619_0009"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("document_composition_records"):
        return
    op.create_table(
        "document_composition_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("import_job_id", sa.String(length=36), nullable=True),
        sa.Column("usage_record_id", sa.String(length=36), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("record_kind", sa.String(length=40), nullable=False),
        sa.Column("stage_key", sa.String(length=120), nullable=False),
        sa.Column("stage_label", sa.String(length=180), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("method", sa.String(length=160), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["usage_record_id"], ["openai_usage_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usage_record_id", name="uq_document_composition_usage_record"),
    )
    for column_name in (
        "document_id",
        "import_job_id",
        "usage_record_id",
        "record_kind",
        "stage_key",
        "provider",
        "model",
        "status",
    ):
        op.create_index(f"ix_document_composition_records_{column_name}", "document_composition_records", [column_name])


def downgrade() -> None:
    if _has_table("document_composition_records"):
        op.drop_table("document_composition_records")
