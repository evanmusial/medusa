from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_create_concordance_run_skips_current_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability
    from app.services.concordance import CAPABILITY_BY_KEY, create_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Indexed",
            original_filename="already-indexed.pdf",
            checksum_sha256="a" * 64,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="search_index",
                version=CAPABILITY_BY_KEY["search_index"].version,
                status="complete",
            )
        )
        db.commit()

        run = create_concordance_run(db, capability_keys=["search_index"])

        assert run.total_jobs == 0
        assert run.status == "complete"


def test_concordance_search_index_job_marks_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import (
        AttributeDefinition,
        ConcordanceJob,
        ConcordanceRun,
        Document,
        DocumentAttributeValue,
        DocumentPage,
        Note,
    )
    from app.services.concordance import ConcordanceProcessor

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Tabled Reading",
            original_filename="tabled-reading.pdf",
            checksum_sha256="b" * 64,
            rich_summary="A paper about tabular evidence.",
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, text="Two-column text and a markdown table."))
        db.add(Note(document_id=document.id, title="Reminder", body="Use this in the methods section."))
        definition = AttributeDefinition(name="Aspect summary", value_type="markdown")
        db.add(definition)
        db.flush()
        db.add(
            DocumentAttributeValue(
                document_id=document.id,
                attribute_definition_id=definition.id,
                value={"value": "This aspect tracks experimental design."},
            )
        )
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["search_index"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="search_index",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert run.status == "complete"
        assert "methods section" in (document.search_text or "")
        assert "experimental design" in (document.search_text or "")
        assert document.capabilities[0].capability_key == "search_index"


def test_concordance_page_text_normalization_updates_pages_and_search(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services.concordance import ConcordanceProcessor

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Readable Flow",
            original_filename="readable-flow.pdf",
            checksum_sha256="c" * 64,
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, text="The article de-\nscribes normal flow ."))
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["page_text_normalization"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="page_text_normalization",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert document.pages[0].normalized_text == "The article describes normal flow."
        assert "normal flow." in (document.search_text or "")
        assert document.metadata_evidence["page_text_normalization"]["pages"] == 1


def test_create_concordance_run_from_saved_search(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, SavedSearch
    from app.services.concordance import create_concordance_run

    Session = make_session()
    with Session() as db:
        matching = Document(
            title="Cybernetics Reader",
            original_filename="cybernetics.pdf",
            checksum_sha256="d" * 64,
            read_status="unread",
            processing_status="ready",
        )
        other = Document(
            title="Garden Notes",
            original_filename="garden.pdf",
            checksum_sha256="e" * 64,
            read_status="read",
            processing_status="ready",
        )
        db.add_all([matching, other])
        db.flush()
        saved_search = SavedSearch(name="Unread cybernetics", query="cybernetics", filters={"read_status": "unread"})
        db.add(saved_search)
        db.commit()

        run = create_concordance_run(
            db,
            scope_type="saved_search",
            scope_data={"saved_search_id": saved_search.id},
            capability_keys=["search_index"],
        )

        assert run.total_jobs == 1
        assert run.jobs[0].document_id == matching.id


def test_concordance_citation_refresh_fills_missing_fields_from_stored_crossref(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("app.services.concordance.crossref_lookup", lambda *_args, **_kwargs: None)

    from app.models import CitationCandidate, ConcordanceJob, ConcordanceRun, Document
    from app.services.concordance import ConcordanceProcessor

    Session = make_session()
    with Session() as db:
        document = Document(
            title="A Bayesian Network Model for Predicting Insider Threats",
            original_filename="bayesian-network.pdf",
            checksum_sha256="f" * 64,
            apa_citation="(n.d.). A Bayesian Network Model for Predicting Insider Threats.",
            citation_status="needs_review",
            metadata_evidence={
                "crossref": {
                    "DOI": "10.1109/spw.2013.35",
                    "URL": "https://doi.org/10.1109/spw.2013.35",
                    "title": ["A Bayesian Network Model for Predicting Insider Threats"],
                    "author": [
                        {"given": "Elise T.", "family": "Axelrad"},
                        {"given": "Paul J.", "family": "Sticha"},
                        {"given": "Oliver", "family": "Brdiczka"},
                        {"family": "Jianqiang Shen"},
                    ],
                    "published": {"date-parts": [[2013, 5]]},
                    "container-title": ["2013 IEEE Security and Privacy Workshops"],
                    "publisher": "IEEE",
                }
            },
        )
        db.add(document)
        db.flush()
        stale_candidate = CitationCandidate(
            document_id=document.id,
            source="medusa-importer",
            citation_text="(n.d.). A Bayesian Network Model for Predicting Insider Threats.",
            status="needs_review",
        )
        db.add(stale_candidate)
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["citation_refresh"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="citation_refresh",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert document.publication_year == 2013
        assert document.doi == "10.1109/spw.2013.35"
        assert document.authors[0]["family"] == "Axelrad"
        assert document.citation_status == "verified"
        assert "Axelrad, E. T." in (document.apa_citation or "")
        assert "(2013)" in (document.apa_citation or "")
        assert "https://doi.org/10.1109/spw.2013.35" in (document.apa_citation or "")
        assert document.apa_in_text_citation == "(Axelrad et al., 2013)"
        assert document.apa_citation_model == "gpt-5.5"
        assert document.apa_in_text_citation_model == "gpt-5.5"
        db.refresh(stale_candidate)
        assert stale_candidate.status == "superseded"


def test_concordance_summary_refresh_uses_summary_only_model(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document
    from app.services.concordance import ConcordanceProcessor
    from app.services.preferences import update_app_preferences

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def generate_document_summary(self, filename, text, *, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "rich_summary": "**Fresh** summary\n\n- Method: close read",
                "confidence": 0.91,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        update_app_preferences(db, analysis_models={"summary": "gpt-5.4-mini"})
        document = Document(
            title="Summary Target",
            original_filename="summary-target.pdf",
            checksum_sha256="9" * 64,
            rich_summary="Old summary",
            search_text="Original searchable document text.",
        )
        db.add(document)
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["summary_refresh"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_refresh",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert run.status == "complete"
        assert document.rich_summary == "**Fresh** summary\n\n- Method: close read"
        assert "Fresh" in (document.search_text or "")
        assert "Method: close read" in (document.search_text or "")
        assert document.metadata_evidence["summary_refresh"]["model"] == "gpt-5.4-mini"
        assert document.capabilities[0].capability_key == "summary_refresh"
        assert calls == [
            {
                "filename": "summary-target.pdf",
                "text": "Original searchable document text.",
                "model": "gpt-5.4-mini",
                "capability_key": "summary_refresh",
                "prompt_cache_key": f"medusa-doc:{'9' * 64}:summary",
            }
        ]


def test_concordance_summary_topics_prefers_manifest_and_keeps_existing_document_tags(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, Tag
    from app.services.concordance import ConcordanceProcessor

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def extract_metadata(self, filename, text, *, pdf_bytes=None, models=None, existing_tags=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "filename": filename,
                    "text": text,
                    "existing_tags": existing_tags,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "title": "Tagged Target",
                "subtitle": None,
                "authors": [],
                "universities": [],
                "publication_year": None,
                "journal": None,
                "publisher": None,
                "doi": None,
                "abstract": None,
                "rich_summary": "Fresh summary.",
                "apa_citation": None,
                "topics": ["shared concept"],
                "keywords": ["new concept"],
                "confidence": 0.88,
                "needs_review_reasons": [],
                "citation_warnings": [],
                "_openai": {"model": "gpt-5.4-mini", "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        manual_tag = Tag(name="manual keep", kind="tag")
        shared_tag = Tag(name="shared concept", kind="tag")
        document = Document(
            title="Tagged Target",
            original_filename="tagged-target.pdf",
            checksum_sha256="8" * 64,
            search_text="Original searchable document text about a new concept.",
            tags=[manual_tag],
        )
        db.add_all([manual_tag, shared_tag, document])
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["summary_topics"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_topics",
            target_version=8,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert sorted(tag.name for tag in document.tags) == ["manual keep", "shared concept"]
        assert document.metadata_evidence["concordance_tag_governance"]["new_candidate_count"] == 0
        assert document.metadata_evidence["concordance_tag_governance"]["decisions"][1]["candidate_name"] == "new concept"
        assert document.metadata_evidence["concordance_tag_governance"]["decisions"][1]["status"] == "not_attached"
        assert calls == [
            {
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "existing_tags": ["manual keep", "shared concept"],
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}",
            }
        ]
