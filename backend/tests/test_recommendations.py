from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_normalize_doi_accepts_urls_and_sci_hub_style_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services.recommendations import normalize_doi

    assert normalize_doi("https://doi.org/10.1109/SPW.2013.35") == "10.1109/spw.2013.35"
    assert normalize_doi("https://sci-hub.red/10.1016/j.cose.2020.101908") == "10.1016/j.cose.2020.101908"
    assert normalize_doi("doi:10.1145/1234567.7654321.") == "10.1145/1234567.7654321"


def test_refresh_recommendations_caches_and_marks_existing_match(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document
    from app.services import recommendations as service
    from app.services.recommendations import RecommendationCandidate, refresh_document_recommendations

    Session = make_session()
    with Session() as db:
        source = Document(
            title="Seed Paper",
            doi="10.1000/seed",
            original_filename="seed.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        existing = Document(
            title="Existing Related Paper",
            doi="10.1000/existing",
            original_filename="existing.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        db.add_all([source, existing])
        db.commit()

        def fake_fetcher(_document, _limit):
            return [
                RecommendationCandidate(
                    title="Existing Related Paper",
                    doi="10.1000/existing",
                    provider="test",
                    relation="related",
                    journal="Journal",
                    description="A short abstract.",
                    pdf_url="https://example.test/existing.pdf",
                )
            ]

        monkeypatch.setattr(service, "_enabled_fetchers", lambda: [("test", fake_fetcher)])
        rows = refresh_document_recommendations(db, source)
        db.commit()

        assert len(rows) == 1
        assert rows[0].doi == "10.1000/existing"
        assert rows[0].existing_document_id == existing.id
        assert rows[0].has_pdf is True


def test_queue_recommendation_imports_reuses_import_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentRecommendation, ImportJob
    from app.services import recommendations as service
    from app.services.recommendations import queue_recommendation_imports

    class FakeStorage:
        def put_bytes(self, key, data, content_type):
            class Stored:
                uri = str(tmp_path / key)
                backend = "local"

            assert data.startswith(b"%PDF")
            assert content_type == "application/pdf"
            return Stored()

    Session = make_session()
    with Session() as db:
        source = Document(
            title="Seed Paper",
            doi="10.1000/seed",
            original_filename="seed.pdf",
            checksum_sha256="c" * 64,
            priority="high",
            processing_status="ready",
        )
        db.add(source)
        db.flush()
        recommendation = DocumentRecommendation(
            source_document_id=source.id,
            match_key="doi:10.1000/new",
            title="New Related Paper",
            doi="10.1000/new",
            source_provider="test",
            pdf_url="https://example.test/new.pdf",
            raw_metadata={},
        )
        db.add(recommendation)
        db.commit()

        monkeypatch.setattr(service, "_download_pdf", lambda _url: (b"%PDF-1.4 related", "application/pdf"))
        monkeypatch.setattr(service, "get_storage_service", lambda: FakeStorage())

        result = queue_recommendation_imports(db, source, [recommendation])
        db.commit()

        jobs = db.query(ImportJob).all()
        db.refresh(recommendation)

        assert result["queued_count"] == 1
        assert jobs[0].status == "queued"
        assert jobs[0].document.priority == "high"
        assert jobs[0].document.doi == "10.1000/new"
        assert recommendation.imported_document_id == jobs[0].document_id
