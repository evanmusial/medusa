from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260618_0004"
down_revision = "20260618_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_document_id", sa.String(length=36), nullable=False),
        sa.Column("existing_document_id", sa.String(length=36), nullable=True),
        sa.Column("match_key", sa.String(length=900), nullable=False),
        sa.Column("title", sa.String(length=800), nullable=False),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("journal", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.String(length=160), nullable=False),
        sa.Column("source_relation", sa.String(length=120), nullable=True),
        sa.Column("external_id", sa.String(length=360), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("score", sa.Numeric(8, 3), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_document_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["existing_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["imported_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_document_id", "match_key", name="uq_document_recommendation_match"),
    )
    op.create_index("ix_document_recommendations_doi", "document_recommendations", ["doi"], unique=False)
    op.create_index(
        "ix_document_recommendations_existing_document_id",
        "document_recommendations",
        ["existing_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_recommendations_imported_document_id",
        "document_recommendations",
        ["imported_document_id"],
        unique=False,
    )
    op.create_index("ix_document_recommendations_status", "document_recommendations", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_recommendations_status", table_name="document_recommendations")
    op.drop_index("ix_document_recommendations_imported_document_id", table_name="document_recommendations")
    op.drop_index("ix_document_recommendations_existing_document_id", table_name="document_recommendations")
    op.drop_index("ix_document_recommendations_doi", table_name="document_recommendations")
    op.drop_table("document_recommendations")
