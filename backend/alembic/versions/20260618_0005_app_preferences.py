from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260618_0005"
down_revision = "20260618_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_preferences",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_preferences")
