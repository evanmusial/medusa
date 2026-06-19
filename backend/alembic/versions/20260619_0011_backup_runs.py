from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260619_0011"
down_revision = "20260619_0010"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("backup_runs"):
        return
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("phase", sa.String(length=80), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("hostname", sa.String(length=120), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("gcs_uri", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("source_kind", sa.String(length=40), nullable=True),
        sa.Column("source_filename", sa.String(length=512), nullable=True),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_local_path", sa.Text(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("safety_backup_id", sa.String(length=36), nullable=True),
        sa.Column("backup_metadata", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["safety_backup_id"], ["backup_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in ("kind", "reason", "status", "phase", "sha256"):
        op.create_index(f"ix_backup_runs_{column_name}", "backup_runs", [column_name])


def downgrade() -> None:
    if _has_table("backup_runs"):
        op.drop_table("backup_runs")
