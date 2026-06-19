from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260618_0006"
down_revision = "20260618_0005"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("figures", "geometry"):
        op.add_column("figures", sa.Column("geometry", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        op.alter_column("figures", "geometry", server_default=None)


def downgrade() -> None:
    if _has_column("figures", "geometry"):
        op.drop_column("figures", "geometry")
