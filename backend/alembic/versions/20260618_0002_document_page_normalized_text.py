from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260618_0002"
down_revision = "20260618_0001"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("document_pages", "normalized_text"):
        op.add_column("document_pages", sa.Column("normalized_text", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("document_pages", "normalized_text"):
        op.drop_column("document_pages", "normalized_text")
