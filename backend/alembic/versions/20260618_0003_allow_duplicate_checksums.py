from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260618_0003"
down_revision = "20260618_0002"
branch_labels = None
depends_on = None


def _index_is_unique(indexes: list[dict], name: str) -> bool:
    for index in indexes:
        if index["name"] == name:
            return bool(index.get("unique"))
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = inspector.get_indexes("documents")
    if _index_is_unique(indexes, "ix_documents_checksum_sha256"):
        op.drop_index("ix_documents_checksum_sha256", table_name="documents")
    if bind.dialect.name == "postgresql":
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_checksum_sha256 ON documents (checksum_sha256)"))
    elif not any(index["name"] == "ix_documents_checksum_sha256" for index in inspector.get_indexes("documents")):
        op.create_index("ix_documents_checksum_sha256", "documents", ["checksum_sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_checksum_sha256", table_name="documents")
    op.create_index("ix_documents_checksum_sha256", "documents", ["checksum_sha256"], unique=True)
