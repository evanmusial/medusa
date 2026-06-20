from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_document_cache_budget_prunes_completed_document_copies(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.database import Base
    from app.models import Document
    from app.services.document_cache import document_cache_path, enforce_document_cache_budget, register_document_cache
    from app.services.preferences import update_app_preferences

    get_settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="a" * 64)
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="b" * 64)
        db.add_all([first, second])
        db.flush()
        first_path = document_cache_path(first.id)
        second_path = document_cache_path(second.id)
        first_path.write_bytes(b"a" * 16)
        second_path.write_bytes(b"b" * 16)
        register_document_cache(first, first_path, source="test")
        register_document_cache(second, second_path, source="test")
        update_app_preferences(db, document_cache_size_mb=0)

        summary = enforce_document_cache_budget(db)

        assert summary["deleted_files"] == 2
        assert not first_path.exists()
        assert not second_path.exists()
        assert first.metadata_evidence["document_cache"]["status"] == "pruned"
        assert second.metadata_evidence["document_cache"]["status"] == "pruned"


def test_current_document_cache_usage_reports_nearest_mb(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.services.document_cache import current_document_cache_usage, document_cache_root

    get_settings.cache_clear()
    root = document_cache_root()
    (root / "first.pdf").write_bytes(b"a" * (1024 * 1024))
    (root / "nested").mkdir()
    (root / "nested" / "second.bin").write_bytes(b"b" * (512 * 1024))

    usage = current_document_cache_usage()

    assert usage["current_size_bytes"] == 1572864
    assert usage["current_size_mb"] == 2
    assert usage["file_count"] == 2
