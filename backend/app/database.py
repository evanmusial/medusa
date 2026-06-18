from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy import create_engine

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def is_postgres() -> bool:
    return settings.database_url.startswith("postgresql")


def create_schema_from_metadata() -> None:
    if is_postgres():
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    if is_postgres():
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_documents_search_text_gin
                    ON documents USING gin (to_tsvector('english', coalesce(search_text, '')))
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_documents_title_trgm
                    ON documents USING gin (title gin_trgm_ops)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_text_chunks_embedding
                    ON text_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
                    """
                )
            )


def run_migrations() -> None:
    try:
        from alembic import command
        from alembic.config import Config
    except ModuleNotFoundError as exc:
        if exc.name == "alembic":
            create_schema_from_metadata()
            return
        raise

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def init_db() -> None:
    from app import models  # noqa: F401

    if is_postgres():
        run_migrations()
        return
    create_schema_from_metadata()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
