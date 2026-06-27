"""add slipstream remote processing tables

Revision ID: 20260627_0025
Revises: 20260627_0024
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260627_0025"
down_revision = "20260627_0024"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()

    if "slipstream_clients" not in tables:
        op.create_table(
            "slipstream_clients",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("public_key", sa.Text(), nullable=False),
            sa.Column("version", sa.String(length=120), nullable=True),
            sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
            sa.Column("last_check_in_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_nonce", sa.String(length=160), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_slipstream_clients_status", "slipstream_clients", ["status"])

    if "slipstream_enrollments" not in tables:
        op.create_table(
            "slipstream_enrollments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("label", sa.String(length=160), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("client_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["client_id"], ["slipstream_clients.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_slipstream_enrollments_token_hash"),
        )
        op.create_index("ix_slipstream_enrollments_status", "slipstream_enrollments", ["status"])
        op.create_index("ix_slipstream_enrollments_token_hash", "slipstream_enrollments", ["token_hash"])

    if "slipstream_leases" not in tables:
        op.create_table(
            "slipstream_leases",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("client_id", sa.String(length=36), nullable=True),
            sa.Column("worker_kind", sa.String(length=40), nullable=False, server_default="slipstream"),
            sa.Column("job_type", sa.String(length=40), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
            sa.Column("lease_token_hash", sa.String(length=128), nullable=False),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("result_idempotency_key", sa.String(length=120), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["client_id"], ["slipstream_clients.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_slipstream_leases_client_id", "slipstream_leases", ["client_id"])
        op.create_index("ix_slipstream_leases_job_type", "slipstream_leases", ["job_type"])
        op.create_index("ix_slipstream_leases_job_id", "slipstream_leases", ["job_id"])
        op.create_index("ix_slipstream_leases_status", "slipstream_leases", ["status"])
        op.create_index("ix_slipstream_leases_worker_kind", "slipstream_leases", ["worker_kind"])
        op.create_index("ix_slipstream_leases_lease_token_hash", "slipstream_leases", ["lease_token_hash"])
        if bind.dialect.name == "postgresql":
            bind.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_slipstream_active_job_lease
                    ON slipstream_leases (job_type, job_id)
                    WHERE status = 'active'
                    """
                )
            )
        elif bind.dialect.name == "sqlite":
            bind.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_slipstream_active_job_lease
                    ON slipstream_leases (job_type, job_id)
                    WHERE status = 'active'
                    """
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "slipstream_leases" in _table_names():
        bind.execute(text("DROP INDEX IF EXISTS uq_slipstream_active_job_lease"))
        op.drop_table("slipstream_leases")
    if "slipstream_enrollments" in _table_names():
        op.drop_table("slipstream_enrollments")
    if "slipstream_clients" in _table_names():
        op.drop_table("slipstream_clients")
