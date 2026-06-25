from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_0019"
down_revision = "20260623_0018"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table("domain_tags"):
        op.create_table(
            "domain_tags",
            sa.Column("domain_id", sa.String(length=36), nullable=False),
            sa.Column("tag_id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("domain_id", "tag_id"),
        )
    if not _has_index("domain_tags", "ix_domain_tags_domain_id"):
        op.create_index("ix_domain_tags_domain_id", "domain_tags", ["domain_id"])
    if not _has_index("domain_tags", "ix_domain_tags_tag_id"):
        op.create_index("ix_domain_tags_tag_id", "domain_tags", ["tag_id"])


def downgrade() -> None:
    if _has_table("domain_tags"):
        if _has_index("domain_tags", "ix_domain_tags_tag_id"):
            op.drop_index("ix_domain_tags_tag_id", table_name="domain_tags")
        if _has_index("domain_tags", "ix_domain_tags_domain_id"):
            op.drop_index("ix_domain_tags_domain_id", table_name="domain_tags")
        op.drop_table("domain_tags")
