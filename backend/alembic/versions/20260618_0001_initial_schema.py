from __future__ import annotations

from alembic import op
from sqlalchemy import text

from app import models  # noqa: F401
from app.database import Base


revision = "20260618_0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_postgres_supporting_objects() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_documents_search_text_gin
            ON documents USING gin (to_tsvector('english', coalesce(search_text, '')))
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_documents_title_trgm
            ON documents USING gin (title gin_trgm_ops)
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_text_chunks_embedding
            ON text_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=bind)
    _create_postgres_supporting_objects()


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
