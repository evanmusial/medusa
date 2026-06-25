from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260625_0020"
down_revision = "20260625_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "checksum_md5" not in columns:
        op.add_column("documents", sa.Column("checksum_md5", sa.String(length=32), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("documents")}
    if "ix_documents_checksum_md5" not in indexes:
        if bind.dialect.name == "postgresql":
            bind.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_checksum_md5 ON documents (checksum_md5)"))
        else:
            op.create_index("ix_documents_checksum_md5", "documents", ["checksum_md5"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_checksum_md5", table_name="documents")
    op.drop_column("documents", "checksum_md5")
