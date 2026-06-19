from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260619_0007"
down_revision = "20260618_0006"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("openai_usage_records"):
        return
    op.create_table(
        "openai_usage_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("import_job_id", sa.String(length=36), nullable=True),
        sa.Column("concordance_run_id", sa.String(length=36), nullable=True),
        sa.Column("concordance_job_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("capability_key", sa.String(length=120), nullable=True),
        sa.Column("task_key", sa.String(length=120), nullable=False),
        sa.Column("operation", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("endpoint", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("request_id", sa.String(length=160), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("used_pdf_file", sa.Boolean(), nullable=False),
        sa.Column("input_file_bytes", sa.Integer(), nullable=False),
        sa.Column("input_text_characters", sa.Integer(), nullable=False),
        sa.Column("output_text_characters", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("usage_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["concordance_job_id"], ["concordance_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["concordance_run_id"], ["concordance_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in (
        "document_id",
        "import_job_id",
        "concordance_run_id",
        "concordance_job_id",
        "source",
        "capability_key",
        "task_key",
        "operation",
        "model",
        "status",
        "request_id",
    ):
        op.create_index(f"ix_openai_usage_records_{column_name}", "openai_usage_records", [column_name])


def downgrade() -> None:
    if _has_table("openai_usage_records"):
        op.drop_table("openai_usage_records")
