from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260629_0030"
down_revision = "20260628_0029"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "portfolio_audit_events" not in tables:
        op.create_table(
            "portfolio_audit_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("portfolio_item_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=True),
            sa.Column("material_id", sa.String(length=36), nullable=True),
            sa.Column("assessment_run_id", sa.String(length=36), nullable=True),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("subject_type", sa.String(length=80), nullable=True),
            sa.Column("subject_id", sa.String(length=80), nullable=True),
            sa.Column("actor_type", sa.String(length=80), nullable=False),
            sa.Column("actor_id", sa.String(length=120), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("canonical_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("payload_sha256", sa.String(length=64), nullable=False),
            sa.Column("previous_event_hash", sa.String(length=64), nullable=True),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("signature_public_key_id", sa.String(length=96), nullable=False),
            sa.Column("signature_algorithm", sa.String(length=40), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["assessment_run_id"], ["portfolio_assessment_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["material_id"], ["portfolio_materials.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["portfolio_item_id"], ["portfolio_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["portfolio_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_hash"),
            sa.UniqueConstraint("portfolio_item_id", "sequence", name="uq_portfolio_audit_event_sequence"),
        )
        op.create_index("ix_portfolio_audit_events_portfolio_item_id", "portfolio_audit_events", ["portfolio_item_id"])
        op.create_index("ix_portfolio_audit_events_version_id", "portfolio_audit_events", ["version_id"])
        op.create_index("ix_portfolio_audit_events_material_id", "portfolio_audit_events", ["material_id"])
        op.create_index("ix_portfolio_audit_events_assessment_run_id", "portfolio_audit_events", ["assessment_run_id"])
        op.create_index("ix_portfolio_audit_events_event_type", "portfolio_audit_events", ["event_type"])
        op.create_index("ix_portfolio_audit_events_subject_type", "portfolio_audit_events", ["subject_type"])
        op.create_index("ix_portfolio_audit_events_subject_id", "portfolio_audit_events", ["subject_id"])
        op.create_index("ix_portfolio_audit_events_payload_sha256", "portfolio_audit_events", ["payload_sha256"])
        op.create_index("ix_portfolio_audit_events_event_hash", "portfolio_audit_events", ["event_hash"])
        op.create_index("ix_portfolio_audit_events_signature_public_key_id", "portfolio_audit_events", ["signature_public_key_id"])
        op.create_index("ix_portfolio_audit_events_item_hash", "portfolio_audit_events", ["portfolio_item_id", "event_hash"])

    if "portfolio_audit_anchors" not in tables:
        op.create_table(
            "portfolio_audit_anchors",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("portfolio_item_id", sa.String(length=36), nullable=False),
            sa.Column("root_event_id", sa.String(length=36), nullable=True),
            sa.Column("start_sequence", sa.Integer(), nullable=True),
            sa.Column("end_sequence", sa.Integer(), nullable=True),
            sa.Column("root_hash", sa.String(length=64), nullable=False),
            sa.Column("tsa_url", sa.Text(), nullable=True),
            sa.Column("tsa_policy_oid", sa.String(length=160), nullable=True),
            sa.Column("tsa_serial_number", sa.String(length=240), nullable=True),
            sa.Column("tsa_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("request_sha256", sa.String(length=64), nullable=True),
            sa.Column("response_der_base64", sa.Text(), nullable=True),
            sa.Column("verification_status", sa.String(length=40), nullable=False),
            sa.Column("verification_error", sa.Text(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["portfolio_item_id"], ["portfolio_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["root_event_id"], ["portfolio_audit_events.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_portfolio_audit_anchors_portfolio_item_id", "portfolio_audit_anchors", ["portfolio_item_id"])
        op.create_index("ix_portfolio_audit_anchors_root_event_id", "portfolio_audit_anchors", ["root_event_id"])
        op.create_index("ix_portfolio_audit_anchors_end_sequence", "portfolio_audit_anchors", ["end_sequence"])
        op.create_index("ix_portfolio_audit_anchors_root_hash", "portfolio_audit_anchors", ["root_hash"])
        op.create_index("ix_portfolio_audit_anchors_tsa_time", "portfolio_audit_anchors", ["tsa_time"])
        op.create_index("ix_portfolio_audit_anchors_verification_status", "portfolio_audit_anchors", ["verification_status"])
        op.create_index(
            "ix_portfolio_audit_anchors_item_range",
            "portfolio_audit_anchors",
            ["portfolio_item_id", "start_sequence", "end_sequence"],
        )


def downgrade() -> None:
    tables = _table_names()
    if "portfolio_audit_anchors" in tables:
        op.drop_table("portfolio_audit_anchors")
    if "portfolio_audit_events" in tables:
        op.drop_table("portfolio_audit_events")
