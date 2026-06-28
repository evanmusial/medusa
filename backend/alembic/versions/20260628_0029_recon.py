from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260628_0029"
down_revision = "20260627_0028"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "recon_inquiries" not in tables:
        op.create_table(
            "recon_inquiries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column("scope_type", sa.String(length=40), nullable=False),
            sa.Column("scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("default_mode", sa.String(length=40), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recon_inquiries_scope_type", "recon_inquiries", ["scope_type"])
        op.create_index("ix_recon_inquiries_default_mode", "recon_inquiries", ["default_mode"])
        op.create_index("ix_recon_inquiries_status", "recon_inquiries", ["status"])

    if "recon_runs" not in tables:
        op.create_table(
            "recon_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("inquiry_id", sa.String(length=36), nullable=False),
            sa.Column("mode", sa.String(length=40), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("resolved_document_count", sa.Integer(), nullable=False),
            sa.Column("evidence_count", sa.Integer(), nullable=False),
            sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
            sa.Column("estimated_cost_usd", sa.Numeric(10, 4), nullable=True),
            sa.Column("answer_summary", sa.Text(), nullable=True),
            sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["inquiry_id"], ["recon_inquiries.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recon_runs_inquiry_id", "recon_runs", ["inquiry_id"])
        op.create_index("ix_recon_runs_mode", "recon_runs", ["mode"])
        op.create_index("ix_recon_runs_status", "recon_runs", ["status"])

    if "recon_evidence" not in tables:
        op.create_table(
            "recon_evidence",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=True),
            sa.Column("text_chunk_id", sa.String(length=36), nullable=True),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("evidence_kind", sa.String(length=40), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("score", sa.Numeric(8, 4), nullable=True),
            sa.Column("document_title", sa.String(length=600), nullable=True),
            sa.Column("snippet", sa.Text(), nullable=False),
            sa.Column("citation_text", sa.Text(), nullable=True),
            sa.Column("relevance_label", sa.String(length=40), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["run_id"], ["recon_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["text_chunk_id"], ["text_chunks.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recon_evidence_run_id", "recon_evidence", ["run_id"])
        op.create_index("ix_recon_evidence_document_id", "recon_evidence", ["document_id"])
        op.create_index("ix_recon_evidence_text_chunk_id", "recon_evidence", ["text_chunk_id"])
        op.create_index("ix_recon_evidence_evidence_kind", "recon_evidence", ["evidence_kind"])
        op.create_index("ix_recon_evidence_relevance_label", "recon_evidence", ["relevance_label"])

    if "recon_answer_versions" not in tables:
        op.create_table(
            "recon_answer_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("limitations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["recon_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_recon_answer_versions_run_id", "recon_answer_versions", ["run_id"])


def downgrade() -> None:
    tables = _table_names()
    if "recon_answer_versions" in tables:
        op.drop_table("recon_answer_versions")
    if "recon_evidence" in tables:
        op.drop_table("recon_evidence")
    if "recon_runs" in tables:
        op.drop_table("recon_runs")
    if "recon_inquiries" in tables:
        op.drop_table("recon_inquiries")
