"""increase composition status length

Revision ID: 20260627_0027
Revises: 20260627_0026
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260627_0027"
down_revision = "20260627_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document_composition_records") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=40),
            type_=sa.String(length=120),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("document_composition_records") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=120),
            type_=sa.String(length=40),
            existing_nullable=False,
        )
