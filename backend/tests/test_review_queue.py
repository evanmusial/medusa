from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_accept_citation_candidate_updates_document_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import patch_citation_candidate
    from app.models import CitationCandidate, Document, DocumentVersion
    from app.schemas import CitationCandidatePatch

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Unverified Draft",
            original_filename="draft.pdf",
            checksum_sha256="c" * 64,
            citation_status="needs_review",
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        candidate = CitationCandidate(
            document_id=document.id,
            source="crossref",
            citation_text="Lovelace, A. (1843). Notes on the analytical engine.",
            source_metadata={
                "title": "Notes on the analytical engine",
                "authors": [{"given": "Ada", "family": "Lovelace"}],
                "publication_year": 1843,
                "doi": "10.0000/example",
            },
            status="needs_review",
        )
        db.add(candidate)
        db.commit()

        updated = patch_citation_candidate(
            candidate.id,
            CitationCandidatePatch(status="accepted", apply_to_document=True),
            object(),
            db,
        )
        db.refresh(document)
        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()

        assert updated.status == "accepted"
        assert document.title == "Notes on the analytical engine"
        assert document.citation_status == "verified"
        assert document.apa_citation == "Lovelace, A. (1843). Notes on the analytical engine."
        assert "Lovelace" in (document.search_text or "")
        assert version.change_note == "Accepted citation candidate"
        assert version.metadata_snapshot["candidate_id"] == candidate.id


def test_review_queue_exposes_document_title(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import review_queue
    from app.models import CitationCandidate, Document
    from app.schemas import CitationCandidateOut

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Balancing the insider and outsider threat",
            original_filename="balancing.pdf",
            checksum_sha256="d" * 64,
            citation_status="needs_review",
        )
        db.add(document)
        db.flush()
        db.add(
            CitationCandidate(
                document_id=document.id,
                source="medusa-importer",
                citation_text="Walton, R. (2006). Balancing the insider and outsider threat.",
                source_metadata={"title": "Balancing the insider and outsider threat"},
                status="needs_review",
            )
        )
        db.commit()

        candidates = review_queue(object(), db)
        payload = CitationCandidateOut.model_validate(candidates[0]).model_dump(by_alias=True)

        assert payload["document_title"] == "Balancing the insider and outsider threat"
        assert payload["metadata"]["title"] == "Balancing the insider and outsider threat"
