from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401

    get_settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_library_duplicate_scan_matches_case_insensitive_title_with_metadata(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_documents, scan_document_duplicates
    from app.models import Document

    with Session() as db:
        first = Document(
            title="Balancing the Insider and Outsider Threat",
            authors=[{"given": "A.", "family": "Researcher"}],
            publication_year=2024,
            original_filename="first.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        second = Document(
            title="balancing the insider and outsider threat",
            authors=[{"given": "Alex", "family": "Researcher"}],
            publication_year=2024,
            original_filename="second.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        unique = Document(
            title="Different Paper",
            original_filename="unique.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
        )
        db.add_all([first, second, unique])
        db.commit()

        scan = scan_document_duplicates(object(), db)
        duplicate_rows = list_documents(object(), db, duplicate_status="duplicates")
        unique_rows = list_documents(object(), db, duplicate_status="unique")

    assert scan.pair_count == 1
    assert scan.pairs[0].match_reasons[:3] == ["title", "authors", "publication_year"]
    assert {row.id for row in duplicate_rows} == {first.id, second.id}
    assert duplicate_rows[0].duplicate_count == 1
    assert {row.id for row in unique_rows} == {unique.id}


def test_duplicate_resolution_soft_deletes_unkept_document_with_history(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_documents, resolve_document_duplicate
    from app.models import Document, DocumentVersion
    from app.schemas import DuplicateResolveCreate

    with Session() as db:
        keep = Document(
            title="Shared Title",
            authors=[{"given": "A.", "family": "Researcher"}],
            original_filename="keep.pdf",
            checksum_sha256="d" * 64,
            processing_status="ready",
        )
        remove = Document(
            title="shared title",
            authors=[{"given": "A.", "family": "Researcher"}],
            original_filename="remove.pdf",
            checksum_sha256="e" * 64,
            processing_status="ready",
        )
        db.add_all([keep, remove])
        db.commit()

        result = resolve_document_duplicate(
            DuplicateResolveCreate(keep_document_id=keep.id, duplicate_document_id=remove.id),
            object(),
            db,
        )
        remaining = list_documents(object(), db)
        removed_version = db.query(DocumentVersion).filter(DocumentVersion.document_id == remove.id).one()

    assert result.status == "resolved"
    assert result.keep_document_id == keep.id
    assert remove.deleted_at is not None
    assert [row.id for row in remaining] == [keep.id]
    assert removed_version.change_note == "Duplicate resolution removed"
    assert removed_version.metadata_snapshot["kept_document_id"] == keep.id


def test_duplicate_dismissal_keeps_documents_and_removes_duplicate_labels(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import dismiss_document_duplicate, list_documents, scan_document_duplicates
    from app.models import Document, DocumentVersion
    from app.schemas import DuplicateDismissCreate

    with Session() as db:
        first = Document(
            title="Shared Title",
            authors=[{"given": "A.", "family": "Researcher"}],
            publication_year=2024,
            original_filename="first.pdf",
            checksum_sha256="f" * 64,
            processing_status="ready",
        )
        second = Document(
            title="shared title",
            authors=[{"given": "A.", "family": "Researcher"}],
            publication_year=2024,
            original_filename="second.pdf",
            checksum_sha256="0" * 64,
            processing_status="ready",
        )
        db.add_all([first, second])
        db.commit()

        assert scan_document_duplicates(object(), db).pair_count == 1

        result = dismiss_document_duplicate(
            DuplicateDismissCreate(left_document_id=first.id, right_document_id=second.id),
            object(),
            db,
        )
        scan = scan_document_duplicates(object(), db)
        all_rows = list_documents(object(), db)
        duplicate_rows = list_documents(object(), db, duplicate_status="duplicates")
        unique_rows = list_documents(object(), db, duplicate_status="unique")
        versions = db.query(DocumentVersion).filter(DocumentVersion.change_note == "Duplicate match dismissed").all()
        db.refresh(first)
        db.refresh(second)

    assert result.status == "dismissed"
    assert first.deleted_at is None
    assert second.deleted_at is None
    assert scan.pair_count == 0
    assert {row.duplicate_count for row in all_rows} == {0}
    assert duplicate_rows == []
    assert {row.id for row in unique_rows} == {first.id, second.id}
    assert second.id in {item["document_id"] for item in first.metadata_evidence["duplicate_false_positives"]}
    assert first.id in {item["document_id"] for item in second.metadata_evidence["duplicate_false_positives"]}
    assert len(versions) == 2
