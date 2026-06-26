from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_0021"
down_revision = "20260625_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "two_factor_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "two_factor_secret" not in columns:
        op.add_column("users", sa.Column("two_factor_secret", sa.String(length=80), nullable=True))
    if "two_factor_confirmed_at" not in columns:
        op.add_column("users", sa.Column("two_factor_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    if "two_factor_last_used_step" not in columns:
        op.add_column("users", sa.Column("two_factor_last_used_step", sa.Integer(), nullable=True))
    if "two_factor_recovery_hashes" not in columns:
        op.add_column(
            "users",
            sa.Column("two_factor_recovery_hashes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    for column_name in (
        "two_factor_recovery_hashes",
        "two_factor_last_used_step",
        "two_factor_confirmed_at",
        "two_factor_secret",
        "two_factor_enabled",
    ):
        if column_name in columns:
            op.drop_column("users", column_name)
