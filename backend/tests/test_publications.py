from datetime import timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


def make_session():
    from app import models  # noqa: F401
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session, engine


def make_document(**kwargs):
    from app.models import Document

    defaults = {
        "title": "Publication Target",
        "original_filename": "publication-target.pdf",
        "checksum_sha256": "p" * 64,
        "processing_status": "ready",
    }
    defaults.update(kwargs)
    return Document(**defaults)


def test_sqlite_metadata_creates_publication_tables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    _, engine = make_session()

    table_names = set(inspect(engine).get_table_names())
    assert {"publications", "publication_aliases", "document_publications"}.issubset(table_names)


def test_manual_publication_patch_separates_identity_and_appearance(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import DocumentPublication, Publication
    from app.services.publications import (
        apply_document_publication_patch,
        document_publication_citation_metadata,
        primary_document_publication,
        publication_search_text,
    )

    Session, _ = make_session()
    with Session() as db:
        document = make_document(publication_year=None)
        db.add(document)
        db.commit()

        changed = apply_document_publication_patch(
            db,
            document,
            {
                "title": "Journal of Useful Things",
                "type": "journal",
                "publisher": "Society for Useful Things",
                "issn_l": "12345678",
                "issns": ["1234-5678"],
                "volume": "12",
                "issue": "3",
                "article_number": "A45",
                "page_range": "45-67",
                "published_year": 2026,
            },
        )
        db.commit()

        link = primary_document_publication(document)
        publication = link.publication

        assert {"publication", "journal", "publisher", "publication_year"}.issubset(changed)
        assert db.query(Publication).count() == 1
        assert db.query(DocumentPublication).count() == 1
        assert publication.title == "Journal of Useful Things"
        assert publication.publication_type == "journal"
        assert publication.issn_l == "1234-5678"
        assert link.volume == "12"
        assert link.issue == "3"
        assert link.article_number == "A45"
        assert link.page_range == "45-67"
        assert document.journal == "Journal of Useful Things"
        assert document.publisher == "Society for Useful Things"
        assert document.publication_year == 2026

        citation_metadata = document_publication_citation_metadata(document)
        assert citation_metadata["journal"] == "Journal of Useful Things"
        assert citation_metadata["volume"] == "12"
        assert citation_metadata["issue"] == "3"
        assert citation_metadata["page"] == "45-67"
        assert citation_metadata["article_number"] == "A45"
        assert "Journal of Useful Things" in publication_search_text(document)
        assert "45-67" in publication_search_text(document)


def test_publication_matching_reuses_identity_by_issn(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Publication
    from app.services.publications import apply_document_publication_patch, primary_document_publication

    Session, _ = make_session()
    with Session() as db:
        first = make_document(title="First Article", checksum_sha256="1" * 64)
        second = make_document(title="Second Article", checksum_sha256="2" * 64)
        db.add_all([first, second])
        db.commit()

        for document, page_range in ((first, "1-10"), (second, "11-20")):
            apply_document_publication_patch(
                db,
                document,
                {
                    "title": "Journal of Useful Things",
                    "type": "journal",
                    "publisher": "Society for Useful Things",
                    "issn_l": "1234-5678",
                    "page_range": page_range,
                },
            )
        db.commit()

        first_link = primary_document_publication(first)
        second_link = primary_document_publication(second)
        assert db.query(Publication).count() == 1
        assert first_link.publication_id == second_link.publication_id
        assert first_link.page_range == "1-10"
        assert second_link.page_range == "11-20"


def test_legacy_journal_is_not_backfilled_until_explicit_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import DocumentPublication
    from app.services.publications import primary_document_publication, refresh_document_publication_metadata

    Session, _ = make_session()
    with Session() as db:
        document = make_document(
            journal="Legacy Journal",
            publisher="Legacy Publisher",
            publication_year=2024,
        )
        db.add(document)
        db.commit()

        assert primary_document_publication(document) is None
        assert db.query(DocumentPublication).count() == 0

        result = refresh_document_publication_metadata(db, document, source="concordance", force=True)
        db.commit()

        link = primary_document_publication(document)
        assert result["status"] == "updated"
        assert link.publication.title == "Legacy Journal"
        assert link.publication.publisher == "Legacy Publisher"
        assert link.source == "concordance"


def test_publication_metadata_is_not_in_default_concordance_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob
    from app.services.concordance import create_concordance_run

    Session, _ = make_session()
    with Session() as db:
        document = make_document(journal="Legacy Journal", publisher="Legacy Publisher")
        db.add(document)
        db.commit()

        run = create_concordance_run(db)
        queued_keys = {
            key
            for (key,) in db.query(ConcordanceJob.capability_key).filter(ConcordanceJob.run_id == run.id).all()
        }

        assert "publication_metadata" not in queued_keys


def test_verified_publication_is_not_overwritten_without_force(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import utc_now
    from app.services.publications import apply_document_publication_patch, apply_publication_candidate, primary_document_publication

    Session, _ = make_session()
    with Session() as db:
        document = make_document()
        db.add(document)
        db.commit()
        apply_document_publication_patch(
            db,
            document,
            {"title": "Verified Journal", "publisher": "Verified Publisher", "issn_l": "1111-1111"},
        )
        link = primary_document_publication(document)
        link.verification_status = "verified"
        link.verified_at = utc_now()
        db.commit()

        changed = apply_publication_candidate(
            db,
            document,
            {
                "publication": {
                    "title": "Conflicting Journal",
                    "publication_type": "journal",
                    "publisher": "Conflicting Publisher",
                    "issn_l": "2222-2222",
                },
                "appearance": {"source": "model", "confidence": 0.91},
            },
            source="concordance",
        )
        db.commit()

        assert changed == set()
        assert primary_document_publication(document).publication.title == "Verified Journal"
        assert document.journal == "Verified Journal"

        changed = apply_publication_candidate(
            db,
            document,
            {
                "publication": {
                    "title": "Conflicting Journal",
                    "publication_type": "journal",
                    "publisher": "Conflicting Publisher",
                    "issn_l": "2222-2222",
                },
                "appearance": {"source": "model", "confidence": 0.91},
            },
            source="concordance",
            force=True,
        )
        db.commit()

        assert "publication" in changed
        assert primary_document_publication(document).publication.title == "Conflicting Journal"
        assert document.journal == "Conflicting Journal"


def test_verify_publication_records_json_safe_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import verify_document_publication
    from app.models import DocumentVersion
    from app.services.publications import apply_document_publication_patch, primary_document_publication

    Session, _ = make_session()
    user = SimpleNamespace(id="user-1", email="editor@example.com")
    with Session() as db:
        document = make_document(title="Publication Verify", checksum_sha256="v" * 64)
        db.add(document)
        db.commit()

        apply_document_publication_patch(
            db,
            document,
            {
                "title": "Computers & Security",
                "type": "journal",
                "publisher": "Elsevier BV",
                "volume": "157",
                "article_number": "104606",
                "page_range": "104606",
                "appearance_type": "article",
            },
        )
        db.commit()

        updated = verify_document_publication(document.id, user, db)
        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()
        link = primary_document_publication(document)

        assert link.verification_status == "verified"
        assert link.verified_by == "editor@example.com"
        assert updated.publication["verification_status"] == "verified"
        assert isinstance(version.metadata_snapshot["after"]["publication"]["verified_at"], str)
        assert version.metadata_snapshot["after"]["publication"]["verified_by"] == "editor@example.com"


def test_publication_export_restore_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentPublication, Publication, utc_now
    from app.services.exports import build_metadata_export
    from app.services.publications import apply_document_publication_patch, primary_document_publication
    from app.services.restore import restore_metadata_export

    Session, _ = make_session()
    with Session() as db:
        document = make_document(title="Exported Article", checksum_sha256="e" * 64)
        db.add(document)
        db.commit()
        apply_document_publication_patch(
            db,
            document,
            {
                "title": "Exportable Journal",
                "type": "journal",
                "publisher": "Exportable Publisher",
                "issn_l": "2049-3630",
                "volume": "7",
                "issue": "2",
                "page_range": "100-112",
            },
        )
        link = primary_document_publication(document)
        link.verification_status = "verified"
        link.verified_at = utc_now()
        link.verified_by = "admin@medusa.local"
        db.commit()
        exported = build_metadata_export(db)

    RestoreSession, _ = make_session()
    with RestoreSession() as restored_db:
        result = restore_metadata_export(restored_db, exported, dry_run=False, preserve_ids=True)
        restored_db.commit()

        restored_document = restored_db.query(Document).one()
        restored_publication = restored_db.query(Publication).one()
        restored_link = restored_db.query(DocumentPublication).one()

        assert result["applied"] is True
        assert restored_publication.title == "Exportable Journal"
        assert restored_publication.issn_l == "2049-3630"
        assert restored_link.document_id == restored_document.id
        assert restored_link.publication_id == restored_publication.id
        assert restored_link.volume == "7"
        assert restored_link.issue == "2"
        assert restored_link.page_range == "100-112"
        assert restored_link.verification_status == "verified"
        assert restored_link.verified_at.tzinfo in (None, timezone.utc) or restored_link.verified_at.tzinfo is not None


def test_document_filter_supports_publication_id(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import apply_document_filters
    from app.models import Document
    from app.services.publications import apply_document_publication_patch, primary_document_publication

    Session, _ = make_session()
    with Session() as db:
        included = make_document(title="Included", checksum_sha256="i" * 64)
        excluded = make_document(title="Excluded", checksum_sha256="x" * 64)
        db.add_all([included, excluded])
        db.commit()
        apply_document_publication_patch(db, included, {"title": "Filtered Journal", "issn_l": "3333-3333"})
        apply_document_publication_patch(db, excluded, {"title": "Other Journal", "issn_l": "4444-4444"})
        db.commit()

        publication_id = primary_document_publication(included).publication_id
        query, rank = apply_document_filters(db.query(Document), db, publication_id=publication_id)

        assert rank is None
        assert [document.title for document in query.order_by(Document.title).all()] == ["Included"]
