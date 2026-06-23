"""Increase composition cost precision.

Revision ID: 20260623_0018
Revises: 20260621_0017
Create Date: 2026-06-23 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260623_0018"
down_revision = "20260621_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document_composition_records") as batch_op:
        batch_op.alter_column(
            "amount_usd",
            existing_type=sa.Numeric(12, 6),
            type_=sa.Numeric(18, 12),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("document_composition_records") as batch_op:
        batch_op.alter_column(
            "amount_usd",
            existing_type=sa.Numeric(18, 12),
            type_=sa.Numeric(12, 6),
            existing_nullable=True,
        )
