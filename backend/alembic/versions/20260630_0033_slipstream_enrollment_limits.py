"""Add Slipstream enrollment limits."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260630_0033"
down_revision = "20260630_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slipstream_enrollments", sa.Column("capabilities", sa.JSON(), nullable=True))
    op.add_column("slipstream_enrollments", sa.Column("max_capacity", sa.Integer(), nullable=True))
    op.execute("UPDATE slipstream_enrollments SET capabilities = '[\"import_preprocess\"]' WHERE capabilities IS NULL")
    op.execute("UPDATE slipstream_enrollments SET max_capacity = 1 WHERE max_capacity IS NULL")
    op.alter_column("slipstream_enrollments", "capabilities", nullable=False)
    op.alter_column("slipstream_enrollments", "max_capacity", nullable=False)


def downgrade() -> None:
    op.drop_column("slipstream_enrollments", "max_capacity")
    op.drop_column("slipstream_enrollments", "capabilities")
