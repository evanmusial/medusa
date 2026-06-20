from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260620_0015"
down_revision = "20260620_0014"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if _has_table("tags"):
        if not _has_column("tags", "status"):
            op.add_column("tags", sa.Column("status", sa.String(length=40), nullable=False, server_default="canonical"))
            op.create_index("ix_tags_status", "tags", ["status"])
        if not _has_column("tags", "definition"):
            op.add_column("tags", sa.Column("definition", sa.Text(), nullable=True))
        if not _has_column("tags", "use_guidance"):
            op.add_column("tags", sa.Column("use_guidance", sa.Text(), nullable=True))
        if not _has_column("tags", "avoid_guidance"):
            op.add_column("tags", sa.Column("avoid_guidance", sa.Text(), nullable=True))
        if not _has_column("tags", "metadata"):
            op.add_column("tags", sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    if not _has_table("tag_relationships"):
        op.create_table(
            "tag_relationships",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_tag_id", sa.String(length=36), nullable=False),
            sa.Column("target_tag_id", sa.String(length=36), nullable=False),
            sa.Column("relationship_type", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["source_tag_id"], ["tags.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_tag_id"], ["tags.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_tag_id", "target_tag_id", "relationship_type", name="uq_tag_relationship"),
        )
        op.create_index("ix_tag_relationships_source_tag_id", "tag_relationships", ["source_tag_id"])
        op.create_index("ix_tag_relationships_target_tag_id", "tag_relationships", ["target_tag_id"])
        op.create_index("ix_tag_relationships_relationship_type", "tag_relationships", ["relationship_type"])
        op.create_index("ix_tag_relationships_status", "tag_relationships", ["status"])

    if not _has_table("document_tag_assessments"):
        op.create_table(
            "document_tag_assessments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("tag_id", sa.String(length=36), nullable=True),
            sa.Column("import_job_id", sa.String(length=36), nullable=True),
            sa.Column("concordance_job_id", sa.String(length=36), nullable=True),
            sa.Column("candidate_name", sa.String(length=120), nullable=False),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("decision", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("relevance_score", sa.Numeric(4, 3), nullable=False),
            sa.Column("library_fit_score", sa.Numeric(4, 3), nullable=False),
            sa.Column("novelty_score", sa.Numeric(4, 3), nullable=False),
            sa.Column("overall_score", sa.Numeric(4, 3), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["concordance_job_id"], ["concordance_jobs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_document_tag_assessments_document_id", "document_tag_assessments", ["document_id"])
        op.create_index("ix_document_tag_assessments_tag_id", "document_tag_assessments", ["tag_id"])
        op.create_index("ix_document_tag_assessments_import_job_id", "document_tag_assessments", ["import_job_id"])
        op.create_index("ix_document_tag_assessments_concordance_job_id", "document_tag_assessments", ["concordance_job_id"])
        op.create_index("ix_document_tag_assessments_candidate_name", "document_tag_assessments", ["candidate_name"])
        op.create_index("ix_document_tag_assessments_source", "document_tag_assessments", ["source"])
        op.create_index("ix_document_tag_assessments_decision", "document_tag_assessments", ["decision"])
        op.create_index("ix_document_tag_assessments_status", "document_tag_assessments", ["status"])


def downgrade() -> None:
    if _has_table("document_tag_assessments"):
        op.drop_table("document_tag_assessments")
    if _has_table("tag_relationships"):
        op.drop_table("tag_relationships")
    if _has_table("tags"):
        for column in ("metadata", "avoid_guidance", "use_guidance", "definition", "status"):
            if _has_column("tags", column):
                if column == "status":
                    op.drop_index("ix_tags_status", table_name="tags")
                op.drop_column("tags", column)
