from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260621_0016"
down_revision = "20260620_0015"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("model_pricing_records"):
        return
    op.create_table(
        "model_pricing_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("price_basis", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("input_usd_per_million", sa.Numeric(12, 6), nullable=True),
        sa.Column("cached_input_usd_per_million", sa.Numeric(12, 6), nullable=True),
        sa.Column("output_usd_per_million", sa.Numeric(12, 6), nullable=True),
        sa.Column("input_over_200k_usd_per_million", sa.Numeric(12, 6), nullable=True),
        sa.Column("cached_input_over_200k_usd_per_million", sa.Numeric(12, 6), nullable=True),
        sa.Column("output_over_200k_usd_per_million", sa.Numeric(12, 6), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model", "price_basis", "observed_at", name="uq_model_pricing_observation"),
    )
    op.create_index("ix_model_pricing_records_provider", "model_pricing_records", ["provider"])
    op.create_index("ix_model_pricing_records_model", "model_pricing_records", ["model"])
    op.create_index("ix_model_pricing_records_price_basis", "model_pricing_records", ["price_basis"])
    op.create_index("ix_model_pricing_records_observed_at", "model_pricing_records", ["observed_at"])
    op.create_index("ix_model_pricing_records_last_checked_at", "model_pricing_records", ["last_checked_at"])
    op.create_index("ix_model_pricing_records_superseded_at", "model_pricing_records", ["superseded_at"])


def downgrade() -> None:
    if _has_table("model_pricing_records"):
        op.drop_table("model_pricing_records")
