from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260627_0023"
down_revision = "20260626_0022"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("cache_revisions"):
        return
    op.create_table(
        "cache_revisions",
        sa.Column("family", sa.String(length=80), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    if _has_table("cache_revisions"):
        op.drop_table("cache_revisions")
