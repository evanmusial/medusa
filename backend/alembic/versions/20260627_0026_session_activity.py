"""track session activity for maintenance idle gates

Revision ID: 20260627_0026
Revises: 20260627_0025
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260627_0026"
down_revision = "20260627_0025"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if not _has_column("sessions", "last_seen_at"):
        op.add_column("sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_index("sessions", "ix_sessions_last_seen_at"):
        op.create_index("ix_sessions_last_seen_at", "sessions", ["last_seen_at"])


def downgrade() -> None:
    if _has_index("sessions", "ix_sessions_last_seen_at"):
        op.drop_index("ix_sessions_last_seen_at", table_name="sessions")
    if _has_column("sessions", "last_seen_at"):
        op.drop_column("sessions", "last_seen_at")
