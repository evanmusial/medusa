from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260627_0024"
down_revision = "20260627_0023"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return column_name in {column["name"] for column in inspect(bind).get_columns(table_name)}


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()
    if not _has_column("documents", "document_kind"):
        op.add_column("documents", sa.Column("document_kind", sa.String(length=40), nullable=False, server_default="library"))
        op.create_index("ix_documents_document_kind", "documents", ["document_kind"])
        op.alter_column("documents", "document_kind", server_default=None)

    if "portfolio_items" not in tables:
        op.create_table(
            "portfolio_items",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=600), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("current_version_id", sa.String(length=36), nullable=True),
            sa.Column("project_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("domain_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("tag_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_portfolio_items_status", "portfolio_items", ["status"])
        op.create_index("ix_portfolio_items_current_version_id", "portfolio_items", ["current_version_id"])

    if "portfolio_versions" not in tables:
        op.create_table(
            "portfolio_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("portfolio_item_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("label", sa.String(length=240), nullable=True),
            sa.Column("upload_note", sa.Text(), nullable=True),
            sa.Column("source_filename", sa.String(length=512), nullable=False),
            sa.Column("source_content_type", sa.String(length=160), nullable=False),
            sa.Column("source_checksum_sha256", sa.String(length=64), nullable=False),
            sa.Column("source_checksum_md5", sa.String(length=32), nullable=True),
            sa.Column("source_storage_uri", sa.Text(), nullable=True),
            sa.Column("source_size_bytes", sa.Integer(), nullable=False),
            sa.Column("processing_status", sa.String(length=40), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["portfolio_item_id"], ["portfolio_items.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_id"),
            sa.UniqueConstraint("portfolio_item_id", "version_number", name="uq_portfolio_version_number"),
        )
        op.create_index("ix_portfolio_versions_portfolio_item_id", "portfolio_versions", ["portfolio_item_id"])
        op.create_index("ix_portfolio_versions_document_id", "portfolio_versions", ["document_id"])
        op.create_index("ix_portfolio_versions_source_checksum_sha256", "portfolio_versions", ["source_checksum_sha256"])
        op.create_index("ix_portfolio_versions_source_checksum_md5", "portfolio_versions", ["source_checksum_md5"])
        op.create_index("ix_portfolio_versions_processing_status", "portfolio_versions", ["processing_status"])

    if bind.dialect.name != "sqlite":
        existing_fks = {fk["name"] for fk in inspect(bind).get_foreign_keys("portfolio_items")}
        if "fk_portfolio_items_current_version_id" not in existing_fks:
            op.create_foreign_key(
                "fk_portfolio_items_current_version_id",
                "portfolio_items",
                "portfolio_versions",
                ["current_version_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if "portfolio_version_edges" not in tables:
        op.create_table(
            "portfolio_version_edges",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("parent_version_id", sa.String(length=36), nullable=False),
            sa.Column("child_version_id", sa.String(length=36), nullable=False),
            sa.Column("relation_type", sa.String(length=80), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["child_version_id"], ["portfolio_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["parent_version_id"], ["portfolio_versions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("parent_version_id", "child_version_id", "relation_type", name="uq_portfolio_version_edge"),
        )
        op.create_index("ix_portfolio_version_edges_parent_version_id", "portfolio_version_edges", ["parent_version_id"])
        op.create_index("ix_portfolio_version_edges_child_version_id", "portfolio_version_edges", ["child_version_id"])
        op.create_index("ix_portfolio_version_edges_relation_type", "portfolio_version_edges", ["relation_type"])

    if "portfolio_materials" not in tables:
        op.create_table(
            "portfolio_materials",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("portfolio_item_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=True),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=80), nullable=False),
            sa.Column("label", sa.String(length=240), nullable=True),
            sa.Column("required_for_assessment", sa.Boolean(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["portfolio_item_id"], ["portfolio_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["portfolio_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_id"),
        )
        op.create_index("ix_portfolio_materials_portfolio_item_id", "portfolio_materials", ["portfolio_item_id"])
        op.create_index("ix_portfolio_materials_version_id", "portfolio_materials", ["version_id"])
        op.create_index("ix_portfolio_materials_document_id", "portfolio_materials", ["document_id"])
        op.create_index("ix_portfolio_materials_role", "portfolio_materials", ["role"])

    if "portfolio_suggestions" not in tables:
        op.create_table(
            "portfolio_suggestions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("portfolio_item_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=True),
            sa.Column("library_document_id", sa.String(length=36), nullable=True),
            sa.Column("source_type", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=800), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("relation_family", sa.String(length=80), nullable=False),
            sa.Column("score", sa.Numeric(8, 3), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["library_document_id"], ["documents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["portfolio_item_id"], ["portfolio_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["portfolio_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("portfolio_item_id", "version_id", "library_document_id", "source_type", name="uq_portfolio_suggestion_source"),
        )
        op.create_index("ix_portfolio_suggestions_portfolio_item_id", "portfolio_suggestions", ["portfolio_item_id"])
        op.create_index("ix_portfolio_suggestions_version_id", "portfolio_suggestions", ["version_id"])
        op.create_index("ix_portfolio_suggestions_library_document_id", "portfolio_suggestions", ["library_document_id"])
        op.create_index("ix_portfolio_suggestions_source_type", "portfolio_suggestions", ["source_type"])
        op.create_index("ix_portfolio_suggestions_relation_family", "portfolio_suggestions", ["relation_family"])
        op.create_index("ix_portfolio_suggestions_status", "portfolio_suggestions", ["status"])

    if "portfolio_assessment_runs" not in tables:
        op.create_table(
            "portfolio_assessment_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("portfolio_item_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=True),
            sa.Column("mode", sa.String(length=80), nullable=False),
            sa.Column("model_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["portfolio_item_id"], ["portfolio_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["portfolio_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_portfolio_assessment_runs_portfolio_item_id", "portfolio_assessment_runs", ["portfolio_item_id"])
        op.create_index("ix_portfolio_assessment_runs_version_id", "portfolio_assessment_runs", ["version_id"])
        op.create_index("ix_portfolio_assessment_runs_mode", "portfolio_assessment_runs", ["mode"])
        op.create_index("ix_portfolio_assessment_runs_status", "portfolio_assessment_runs", ["status"])

    if "portfolio_assessment_findings" not in tables:
        op.create_table(
            "portfolio_assessment_findings",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("assessment_run_id", sa.String(length=36), nullable=False),
            sa.Column("category", sa.String(length=80), nullable=False),
            sa.Column("severity", sa.String(length=40), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["assessment_run_id"], ["portfolio_assessment_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_portfolio_assessment_findings_assessment_run_id", "portfolio_assessment_findings", ["assessment_run_id"])
        op.create_index("ix_portfolio_assessment_findings_category", "portfolio_assessment_findings", ["category"])
        op.create_index("ix_portfolio_assessment_findings_severity", "portfolio_assessment_findings", ["severity"])
        op.create_index("ix_portfolio_assessment_findings_status", "portfolio_assessment_findings", ["status"])

    if bind.dialect.name == "postgresql":
        bind.execute(text("DROP INDEX IF EXISTS ix_documents_library_ready_filters"))
        bind.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_library_ready_filters
                ON documents (read_status, priority, citation_status, duplicate_count)
                WHERE deleted_at IS NULL AND document_kind = 'library' AND processing_status IN ('ready', 'complete', 'completed', 'restored')
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in (
        "portfolio_assessment_findings",
        "portfolio_assessment_runs",
        "portfolio_suggestions",
        "portfolio_materials",
        "portfolio_version_edges",
    ):
        if table_name in _table_names():
            op.drop_table(table_name)
    if bind.dialect.name != "sqlite":
        existing_fks = {fk["name"] for fk in inspect(bind).get_foreign_keys("portfolio_items")}
        if "fk_portfolio_items_current_version_id" in existing_fks:
            op.drop_constraint("fk_portfolio_items_current_version_id", "portfolio_items", type_="foreignkey")
    if "portfolio_versions" in _table_names():
        op.drop_table("portfolio_versions")
    if "portfolio_items" in _table_names():
        op.drop_table("portfolio_items")
    if _has_column("documents", "document_kind"):
        op.drop_index("ix_documents_document_kind", table_name="documents")
        op.drop_column("documents", "document_kind")
    if bind.dialect.name == "postgresql":
        bind.execute(text("DROP INDEX IF EXISTS ix_documents_library_ready_filters"))
        bind.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_library_ready_filters
                ON documents (read_status, priority, citation_status, duplicate_count)
                WHERE deleted_at IS NULL AND processing_status IN ('ready', 'complete', 'completed', 'restored')
                """
            )
        )
