from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260620_0014"
down_revision = "20260620_0013"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("tag_aliases"):
        return
    op.create_table(
        "tag_aliases",
        sa.Column("alias_name", sa.String(length=120), nullable=False),
        sa.Column("target_tag_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alias_name"),
    )
    op.create_index("ix_tag_aliases_target_tag_id", "tag_aliases", ["target_tag_id"])


def downgrade() -> None:
    if _has_table("tag_aliases"):
        op.drop_table("tag_aliases")
