import asyncio
import hashlib

import pytest
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


def test_refresh_recommendations_uses_stored_bibliography_references(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document
    from app.services import recommendations as service
    from app.services.recommendations import refresh_document_recommendations

    Session = make_session()
    with Session() as db:
        source = Document(
            title="Seed Paper",
            doi="10.1000/seed",
            original_filename="seed.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
            bibliography=(
                '[1] A. Author, "Known Reference Paper," Journal of References, 2018.\n\n'
                "[2] Smith, A. (2020). Unheld bibliography source. Research Press. https://example.test/source"
            ),
        )
        existing = Document(
            title="Known Reference Paper",
            original_filename="known.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        db.add_all([source, existing])
        db.commit()

        monkeypatch.setattr(service, "_enabled_fetchers", lambda: [])
        monkeypatch.setattr(service, "_enabled_enrichers", lambda: [])

        rows = refresh_document_recommendations(db, source)
        db.commit()

        by_title = {row.title: row for row in rows}
        known = by_title["Known Reference Paper"]
        unheld = by_title["Unheld bibliography source"]
        assert known.source_provider == "bibliography"
        assert known.source_relation == "bibliography_reference"
        assert known.existing_document_id == existing.id
        assert known.known_status == "in_library"
        assert known.relation_family == "foundational"
        assert known.raw_metadata["recommendations_v2"]["evidence"]["provider"] == "bibliography"
        assert unheld.source_url == "https://example.test/source"


def test_refresh_recommendations_route_allows_bibliography_without_doi(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import refresh_recommendations
    from app.models import Document
    from app.services import recommendations as service

    Session = make_session()
    with Session() as db:
        source = Document(
            title="Bibliography Only Paper",
            original_filename="source.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
            bibliography="Smith, A. (2020). Bibliography seeded paper. Research Press.",
        )
        blocked = Document(
            title="No Related Inputs",
            original_filename="blocked.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        db.add_all([source, blocked])
        db.commit()

        monkeypatch.setattr(service, "_enabled_fetchers", lambda: [])
        monkeypatch.setattr(service, "_enabled_enrichers", lambda: [])

        result = refresh_recommendations(source.id, object(), db)

        assert result.recommendation_count == 1
        assert result.recommendations[0].source_provider == "bibliography"
        with pytest.raises(HTTPException) as exc:
            refresh_recommendations(blocked.id, object(), db)
        assert exc.value.status_code == 400


def test_bibliography_reference_entries_split_one_source_per_line(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services.recommendations import _bibliography_reference_entries

    entries = _bibliography_reference_entries(
        "Smith, A. (2024). A careful source. Journal.\n"
        "Jones, B. (2023). Another source. Press.",
        limit=10,
    )

    assert entries == [
        "Smith, A. (2024). A careful source. Journal.",
        "Jones, B. (2023). Another source. Press.",
    ]

    initial_entries = _bibliography_reference_entries(
        "P. Barrett and P. Rolland, The meta-analytic correlation between two Big Five factors, 2012.\n"
        "D.M. Cappelli, A. Moore, and R. Trzeciak, The CERT Guide to Insider Threats, 2012.",
        limit=10,
    )

    assert initial_entries == [
        "P. Barrett and P. Rolland, The meta-analytic correlation between two Big Five factors, 2012.",
        "D.M. Cappelli, A. Moore, and R. Trzeciak, The CERT Guide to Insider Threats, 2012.",
    ]


def test_recommendations_v2_filters_known_items_and_relation_families(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentRecommendation, DoiStash
    from app.services.recommendations import list_document_recommendations

    Session = make_session()
    with Session() as db:
        source = Document(
            title="Seed Paper",
            doi="10.1000/seed",
            original_filename="seed.pdf",
            checksum_sha256="a" * 64,
            publication_year=2020,
            processing_status="ready",
        )
        existing = Document(
            title="Existing Related Paper",
            doi="10.1000/existing",
            original_filename="existing.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        queued = Document(
            title="Queued Related Paper",
            doi="10.1000/queued",
            original_filename="queued.pdf",
            checksum_sha256="c" * 64,
            processing_status="queued",
        )
        db.add_all([source, existing, queued])
        db.flush()
        rows = [
            DocumentRecommendation(
                source_document_id=source.id,
                match_key="doi:10.1000/new",
                title="A Method Framework for Seed Paper",
                doi="10.1000/new",
                source_provider="semantic_scholar",
                source_relation="recommended",
                publication_year=2024,
                description="A method framework for analyzing the seed topic.",
                pdf_url="https://example.test/new.pdf",
                raw_metadata={},
            ),
            DocumentRecommendation(
                source_document_id=source.id,
                match_key="doi:10.1000/existing",
                title="Existing Related Paper",
                doi="10.1000/existing",
                source_provider="openalex",
                source_relation="related",
                raw_metadata={},
            ),
            DocumentRecommendation(
                source_document_id=source.id,
                match_key="doi:10.1000/queued",
                title="Queued Related Paper",
                doi="10.1000/queued",
                source_provider="openalex",
                source_relation="related",
                raw_metadata={},
            ),
            DocumentRecommendation(
                source_document_id=source.id,
                match_key="doi:10.1000/stashed",
                title="Stashed Related Paper",
                doi="10.1000/stashed",
                source_provider="crossref",
                source_relation="reference",
                raw_metadata={},
            ),
        ]
        db.add_all(rows)
        db.add(DoiStash(doi="10.1000/stashed", title="Stashed Related Paper", status="active", stash_metadata={}))
        db.commit()

        discover = list_document_recommendations(db, source, view="discover")
        known = list_document_recommendations(db, source, view="known")
        methods = list_document_recommendations(db, source, view="discover", family="methods")

        assert [row.doi for row in discover] == ["10.1000/new"]
        assert discover[0].known_status == "new"
        assert discover[0].relation_family == "methods"
        assert "Methods" in discover[0].reason_chips
        assert discover[0].raw_metadata["recommendations_v2"]["evidence"]["open_pdf_evidence"] is True
        assert [row.doi for row in methods] == ["10.1000/new"]
        assert {row.known_status for row in known} == {"in_library", "active_import", "stashed"}
        assert all(row.hidden_reason for row in known)


def test_refresh_recommendations_enriches_pdf_availability_and_resets_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.models import Document, DocumentRecommendation
    from app.services import recommendations as service
    from app.services.recommendations import RecommendationCandidate, refresh_document_recommendations

    get_settings.cache_clear()
    Session = make_session()
    with Session() as db:
        source = Document(
            title="Seed Paper",
            doi="10.1000/seed",
            original_filename="seed.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        db.add(source)
        db.flush()
        stale_failure = DocumentRecommendation(
            source_document_id=source.id,
            match_key="doi:10.1000/related",
            title="Related Paper",
            doi="10.1000/related",
            source_provider="crossref",
            pdf_url="https://publisher.test/blocked.pdf",
            status="download_failed",
            raw_metadata={},
        )
        db.add(stale_failure)
        db.commit()

        def fake_fetcher(_document, _limit):
            return [
                RecommendationCandidate(
                    title="Related Paper",
                    doi="10.1000/related",
                    provider="crossref",
                    relation="reference",
                    pdf_url="https://publisher.test/blocked.pdf",
                    raw_metadata={"provider": "crossref"},
                )
            ]

        def fake_enricher(_candidates, _limit):
            return [
                RecommendationCandidate(
                    title="Related Paper",
                    doi="10.1000/related",
                    provider="unpaywall",
                    relation="open_access",
                    pdf_url="https://repository.test/related.pdf",
                    raw_metadata={"provider": "unpaywall"},
                )
            ]

        monkeypatch.setattr(service, "_enabled_fetchers", lambda: [("crossref", fake_fetcher)])
        monkeypatch.setattr(service, "_enabled_enrichers", lambda: [("unpaywall", fake_enricher)])

        rows = refresh_document_recommendations(db, source)
        db.commit()

        assert len(rows) == 1
        assert rows[0].source_provider == "crossref, unpaywall"
        assert rows[0].source_relation == "reference, open_access"
        assert rows[0].pdf_url == "https://repository.test/related.pdf"
        assert rows[0].status == "candidate"
        assert rows[0].scholar_url.startswith("https://scholar.google.com/scholar?q=10.1000")


def test_unpaywall_candidate_uses_best_oa_pdf():
    from app.services.recommendations import RecommendationCandidate, _unpaywall_work_to_candidate

    source = RecommendationCandidate(title="Open Article", doi="10.1000/open", provider="crossref")
    candidate = _unpaywall_work_to_candidate(
        source,
        {
            "doi": "10.1000/open",
            "title": "Open Article",
            "year": 2024,
            "journal_name": "Repository Journal",
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {
                "url": "https://repository.test/open",
                "url_for_pdf": "https://repository.test/open.pdf",
            },
            "z_authors": [{"given": "Ada", "family": "Lovelace"}],
        },
    )

    assert candidate is not None
    assert candidate.provider == "unpaywall"
    assert candidate.pdf_url == "https://repository.test/open.pdf"
    assert candidate.source_url == "https://repository.test/open"
    assert candidate.authors[0]["family"] == "Lovelace"


def test_arxiv_enrichment_uses_metadata_id(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.services.recommendations import RecommendationCandidate, enrich_arxiv_recommendations

    get_settings.cache_clear()
    candidate = RecommendationCandidate(
        title="Preprint Article",
        doi="10.1000/preprint",
        provider="semantic_scholar",
        raw_metadata={"paper": {"externalIds": {"ArXiv": "2402.04607"}}},
    )

    rows = enrich_arxiv_recommendations([candidate], 40)

    assert len(rows) == 1
    assert rows[0].provider == "arxiv"
    assert rows[0].source_url == "https://arxiv.org/abs/2402.04607"
    assert rows[0].pdf_url == "https://arxiv.org/pdf/2402.04607"


def test_arxiv_feed_parser_matches_titles():
    from app.services.recommendations import (
        RecommendationCandidate,
        _arxiv_entry_to_candidate,
        _best_arxiv_entry,
        _parse_arxiv_feed,
    )

    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2402.04607v1</id>
        <title>Google Scholar is manipulatable</title>
        <summary>A compact abstract.</summary>
        <published>2024-02-07T06:08:23Z</published>
        <author><name>Hazem Ibrahim</name></author>
        <arxiv:doi>10.48550/arXiv.2402.04607</arxiv:doi>
        <link href="http://arxiv.org/abs/2402.04607v1" rel="alternate" type="text/html"/>
        <link title="pdf" href="http://arxiv.org/pdf/2402.04607v1" rel="related" type="application/pdf"/>
      </entry>
    </feed>
    """
    entries = _parse_arxiv_feed(feed)
    match = _best_arxiv_entry(RecommendationCandidate(title="Google Scholar is manipulatable", provider="test"), entries)

    assert match is not None
    candidate = _arxiv_entry_to_candidate(RecommendationCandidate(title="Google Scholar is manipulatable", provider="test"), match)
    assert candidate.external_id == "arXiv:2402.04607v1"
    assert candidate.publication_year == 2024
    assert candidate.pdf_url == "http://arxiv.org/pdf/2402.04607v1"


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


def test_queue_recommendation_imports_skips_stashed_recommendations(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentRecommendation, DoiStash, ImportJob
    from app.services import recommendations as service
    from app.services.recommendations import queue_recommendation_imports

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
            match_key="doi:10.1000/stashed",
            title="Stashed Related Paper",
            doi="10.1000/stashed",
            source_provider="test",
            pdf_url="https://example.test/stashed.pdf",
            raw_metadata={},
        )
        stash = DoiStash(doi="10.1000/stashed", title="Stashed Related Paper", status="active", stash_metadata={})
        db.add_all([recommendation, stash])
        db.commit()

        monkeypatch.setattr(service, "_download_pdf", lambda _url: (_ for _ in ()).throw(AssertionError("downloaded known item")))

        result = queue_recommendation_imports(db, source, [recommendation])
        db.commit()

        job = db.query(ImportJob).one()
        db.refresh(recommendation)

        assert result["queued_count"] == 0
        assert result["skipped_existing_count"] == 1
        assert job.current_step == "stashed"
        assert recommendation.known_status == "stashed"


def test_queue_recommendation_imports_records_download_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentRecommendation, ImportJob, ProcessingEvent
    from app.services import recommendations as service
    from app.services.recommendations import queue_recommendation_imports

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
            match_key="doi:10.1000/blocked",
            title="Blocked Related Paper",
            doi="10.1000/blocked",
            source_provider="test",
            pdf_url="https://example.test/blocked.pdf",
            raw_metadata={},
        )
        db.add(recommendation)
        db.commit()

        monkeypatch.setattr(service, "_download_pdf", lambda _url: (_ for _ in ()).throw(RuntimeError("403 Forbidden")))

        result = queue_recommendation_imports(db, source, [recommendation])
        db.commit()

        job = db.query(ImportJob).one()
        event = db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "download_failed").one()
        db.refresh(recommendation)

        assert result["failed_count"] == 1
        assert job.status == "failed"
        assert job.current_step == "download_failed"
        assert job.document_id is None
        assert job.last_error == "403 Forbidden"
        assert event.payload["title"] == "Blocked Related Paper"
        assert recommendation.status == "download_failed"


def test_doi_stash_status_tracks_import_job(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import doi_stash_out, sync_doi_stash_import_status
    from app.models import Document, DoiStash, ImportBatch, ImportJob

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Queued Paper",
            doi="10.1000/stashed",
            original_filename="queued.pdf",
            checksum_sha256="d" * 64,
            processing_status="queued",
        )
        batch = ImportBatch(label="Stash: 10.1000/stashed", total_files=1, shared_defaults={})
        db.add_all([document, batch])
        db.flush()
        job = ImportJob(
            batch_id=batch.id,
            document_id=document.id,
            status="complete",
            current_step="complete",
        )
        stash = DoiStash(
            doi="10.1000/stashed",
            title="Queued Paper",
            imported_document_id=document.id,
            import_job=job,
            status="import_queued",
            stash_metadata={},
        )
        db.add_all([job, stash])
        db.commit()

        assert sync_doi_stash_import_status(stash) is True
        rendered = doi_stash_out(stash)

        assert stash.status == "imported"
        assert stash.imported_at is not None
        assert rendered.import_job_status == "complete"
        assert rendered.imported_document_title == "Queued Paper"


def test_doi_stash_library_match_marks_imported_for_removal(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import doi_stash_out, sync_doi_stash_library_matches
    from app.models import Document, DoiStash

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Imported Elsewhere",
            doi="https://doi.org/10.1000/stashed",
            original_filename="imported.pdf",
            checksum_sha256="e" * 64,
            processing_status="ready",
        )
        stash = DoiStash(doi="10.1000/stashed", title="Stashed Paper", status="active", stash_metadata={})
        db.add_all([document, stash])
        db.commit()

        assert sync_doi_stash_library_matches(db, [stash]) is True
        db.commit()
        rendered = doi_stash_out(stash)

        assert stash.status == "imported"
        assert stash.imported_document_id == document.id
        assert stash.imported_at is not None
        assert stash.stash_metadata["matched_import"]["source"] == "library_doi_match"
        assert stash.stash_metadata["matched_import"]["match_reasons"] == ["doi"]
        assert rendered.library_match_basis == "doi"
        assert rendered.imported_document_title == "Imported Elsewhere"


def test_doi_stash_library_match_by_title_marks_imported_for_removal(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import doi_stash_out, sync_doi_stash_library_matches
    from app.models import Document, DoiStash

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Situated Knowledges",
            doi=None,
            original_filename="situated.pdf",
            checksum_sha256="t" * 64,
            processing_status="ready",
        )
        stash = DoiStash(doi="10.1000/not-the-library-doi", title="situated   knowledges", status="active", stash_metadata={})
        db.add_all([document, stash])
        db.commit()

        assert sync_doi_stash_library_matches(db, [stash]) is True
        db.commit()
        rendered = doi_stash_out(stash)

        assert stash.status == "imported"
        assert stash.imported_document_id == document.id
        assert stash.stash_metadata["matched_import"]["source"] == "library_title_match"
        assert stash.stash_metadata["matched_import"]["match_reasons"] == ["title"]
        assert rendered.library_match_basis == "title"
        assert rendered.imported_document_title == "Situated Knowledges"


def test_doi_stash_library_match_records_doi_and_title_basis(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import doi_stash_out, sync_doi_stash_library_matches
    from app.models import Document, DoiStash

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Both Ways Paper",
            doi="10.1000/both-ways",
            original_filename="both.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        stash = DoiStash(doi="https://doi.org/10.1000/both-ways", title="Both Ways Paper", status="active", stash_metadata={})
        db.add_all([document, stash])
        db.commit()

        assert sync_doi_stash_library_matches(db, [stash]) is True
        db.commit()
        rendered = doi_stash_out(stash)

        assert stash.status == "imported"
        assert stash.imported_document_id == document.id
        assert stash.stash_metadata["matched_import"]["source"] == "library_doi_title_match"
        assert stash.stash_metadata["matched_import"]["match_reasons"] == ["doi", "title"]
        assert rendered.library_match_basis == "doi_title"
        assert rendered.imported_document_title == "Both Ways Paper"


def test_create_doi_stash_snapshots_recommendation_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import create_doi_stash
    from app.models import Document, DocumentRecommendation
    from app.schemas import DoiStashCreate

    Session = make_session()
    with Session() as db:
        source = Document(
            title="Seed Paper",
            doi="10.1000/seed",
            original_filename="seed.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
        )
        db.add(source)
        db.flush()
        recommendation = DocumentRecommendation(
            source_document_id=source.id,
            match_key="doi:10.1000/recommended",
            title="Recommended Paper",
            doi="10.1000/recommended",
            authors=[{"given": "Ada", "family": "Lovelace", "affiliation": None}],
            publication_year=1843,
            journal="Notes Journal",
            description="A public recommendation abstract.",
            source_provider="openalex",
            source_url="https://example.test/recommended",
            raw_metadata={},
        )
        db.add(recommendation)
        db.commit()

        rendered = create_doi_stash(
            DoiStashCreate(doi="10.1000/recommended", recommendation_id=recommendation.id),
            object(),
            db,
        )

        assert rendered.title == "Recommended Paper"
        assert rendered.authors == [{"given": "Ada", "family": "Lovelace", "affiliation": None, "email": None}]
        assert rendered.publication_year == 1843
        assert rendered.journal == "Notes Journal"
        assert rendered.description == "A public recommendation abstract."
        assert rendered.metadata_source == "openalex"


def test_create_manual_doi_stash_enriches_public_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.schemas import DoiStashCreate

    class FakeCandidate:
        title = "Resolved Manual Paper"
        authors = [{"given": "Grace", "family": "Hopper", "affiliation": None}]
        publication_year = 1952
        journal = "Compiler Studies"
        description = "Metadata found from a public DOI database."
        source_url = "https://publisher.test/manual"
        pdf_url = None
        provider = "crossref"
        relation = "doi_lookup"

    monkeypatch.setattr(main, "resolve_doi_metadata_candidate", lambda *_args, **_kwargs: FakeCandidate())

    Session = make_session()
    with Session() as db:
        rendered = main.create_doi_stash(DoiStashCreate(doi="10.1000/manual"), object(), db)

        assert rendered.title == "Resolved Manual Paper"
        assert rendered.authors == [{"given": "Grace", "family": "Hopper", "affiliation": None, "email": None}]
        assert rendered.publication_year == 1952
        assert rendered.journal == "Compiler Studies"
        assert rendered.description == "Metadata found from a public DOI database."
        assert rendered.metadata_source == "crossref"
        assert rendered.stash_metadata["bibliographic_lookup"]["status"] == "complete"


def test_queue_doi_stash_open_pdf_import_queues_normal_import(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.models import DoiStash, ImportJob
    from app.services import recommendations as service
    from app.services.recommendations import RecommendationCandidate, queue_doi_stash_open_pdf_import

    get_settings.cache_clear()

    class FakeStorage:
        def put_bytes(self, key, data, content_type):
            class Stored:
                uri = str(tmp_path / key)
                backend = "local"

            assert key.endswith("10.1000-stashed.pdf")
            assert data.startswith(b"%PDF")
            assert content_type == "application/pdf"
            return Stored()

    Session = make_session()
    with Session() as db:
        stash = DoiStash(doi="10.1000/stashed", title="Stashed Paper", status="active", stash_metadata={})
        db.add(stash)
        db.commit()

        candidate = RecommendationCandidate(
            title="Resolved Stashed Paper",
            doi="10.1000/stashed",
            provider="unpaywall",
            relation="open_access",
            source_url="https://publisher.test/stashed",
            pdf_url="https://publisher.test/stashed.pdf",
        )
        monkeypatch.setattr(service, "resolve_open_pdf_candidate_for_doi", lambda *_args, **_kwargs: candidate)
        monkeypatch.setattr(service, "_download_pdf", lambda _url: (b"%PDF-1.4 stashed", "application/pdf"))
        monkeypatch.setattr(service, "get_storage_service", lambda: FakeStorage())

        result = queue_doi_stash_open_pdf_import(db, stash)
        db.commit()

        job = db.query(ImportJob).one()
        db.refresh(stash)

        assert result["queued_count"] == 1
        assert job.status == "queued"
        assert job.document.doi == "10.1000/stashed"
        assert job.document.title == "Resolved Stashed Paper"
        assert job.document.metadata_evidence["doi_stash_import"]["resolver_provider"] == "unpaywall"
        assert stash.status == "import_queued"
        assert stash.import_job_id == job.id
        assert stash.stash_metadata["last_doi_import"]["status"] == "queued"


def test_queue_doi_stash_open_pdf_import_records_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.models import DoiStash, ImportJob, ProcessingEvent
    from app.services import recommendations as service
    from app.services.recommendations import queue_doi_stash_open_pdf_import

    get_settings.cache_clear()

    Session = make_session()
    with Session() as db:
        stash = DoiStash(doi="10.1000/missing", title="Missing Open PDF", status="active", stash_metadata={})
        db.add(stash)
        db.commit()

        monkeypatch.setattr(service, "resolve_open_pdf_candidate_for_doi", lambda *_args, **_kwargs: None)

        result = queue_doi_stash_open_pdf_import(db, stash)
        db.commit()

        job = db.query(ImportJob).one()
        event = db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "download_unavailable").one()
        db.refresh(stash)

        assert result["unavailable_count"] == 1
        assert result["queued_count"] == 0
        assert job.status == "complete"
        assert job.current_step == "download_unavailable"
        assert event.payload["doi_stash_id"] == stash.id
        assert stash.status == "active"
        assert stash.stash_metadata["last_doi_import"]["status"] == "unavailable"


def test_doi_stash_upload_duplicate_marks_imported(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import upload_doi_stash_pdf
    from app.models import Document, DoiStash, ImportJob

    class FakeUpload:
        filename = "duplicate.pdf"
        content_type = "application/pdf"

        async def read(self):
            return b"%PDF-1.4 duplicate"

    checksum = hashlib.sha256(b"%PDF-1.4 duplicate").hexdigest()
    Session = make_session()
    with Session() as db:
        existing = Document(
            title="Existing PDF",
            doi="10.1000/existing",
            original_filename="existing.pdf",
            checksum_sha256=checksum,
            processing_status="ready",
        )
        stash = DoiStash(doi="10.1000/stashed", title="Stashed Paper", status="active", stash_metadata={})
        db.add_all([existing, stash])
        db.commit()

        result = asyncio.run(upload_doi_stash_pdf(stash.id, FakeUpload(), object(), db))
        job = db.query(ImportJob).one()

        assert result.status == "imported"
        assert result.imported_document_id == existing.id
        assert result.uploaded_filename == "duplicate.pdf"
        assert job.status == "complete"
        assert job.current_step == "duplicate_skipped"
