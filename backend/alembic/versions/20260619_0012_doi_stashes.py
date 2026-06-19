from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260619_0012"
down_revision = "20260619_0011"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("doi_stashes"):
        return
    op.create_table(
        "doi_stashes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("doi", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=800), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.String(length=160), nullable=True),
        sa.Column("source_document_id", sa.String(length=36), nullable=True),
        sa.Column("recommendation_id", sa.String(length=36), nullable=True),
        sa.Column("imported_document_id", sa.String(length=36), nullable=True),
        sa.Column("import_job_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("uploaded_filename", sa.String(length=512), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["imported_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["document_recommendations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doi", name="uq_doi_stashes_doi"),
    )
    for column_name in (
        "doi",
        "source_document_id",
        "recommendation_id",
        "imported_document_id",
        "import_job_id",
        "status",
    ):
        op.create_index(f"ix_doi_stashes_{column_name}", "doi_stashes", [column_name])


def downgrade() -> None:
    if _has_table("doi_stashes"):
        op.drop_table("doi_stashes")
