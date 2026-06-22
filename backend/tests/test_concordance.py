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


def test_concordance_estimate_marks_same_model_summary_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.concordance import create_concordance_run, estimate_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Summarized",
            original_filename="already-summarized.pdf",
            checksum_sha256="m" * 64,
            processing_status="ready",
            rich_summary="This paper already has a summary.",
            page_count=12,
        )
        db.add(document)
        db.flush()
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="import",
                capability_key="summary_topics",
                task_key=MODEL_SUMMARY,
                operation="medusa_document_summary",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
            )
        )
        db.commit()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )
        run = create_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )

        assert estimate["planned_jobs"] == 0
        assert estimate["model_no_op_jobs"] == 1
        assert estimate["estimated_cost_usd"] == 0
        assert estimate["items"][0]["status"] == "model_no_op"
        assert run.total_jobs == 0
        assert run.status == "complete"


def test_forced_tag_refresh_queues_even_when_same_model_current(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_KEYWORDS_TOPICS
    from app.services.concordance import CAPABILITY_BY_KEY, create_concordance_run, estimate_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Tagged",
            original_filename="already-tagged.pdf",
            checksum_sha256="t" * 64,
            processing_status="ready",
            page_count=6,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="tag_refresh",
                version=CAPABILITY_BY_KEY["tag_refresh"].version,
                status="complete",
            )
        )
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="concordance",
                capability_key="tag_refresh",
                task_key=MODEL_KEYWORDS_TOPICS,
                operation="medusa_keywords_topics",
                endpoint="responses",
                model="gpt-5.4-mini",
                status="success",
            )
        )
        db.commit()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["tag_refresh"],
            force=True,
        )
        run = create_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["tag_refresh"],
            force=True,
        )

        assert estimate["planned_jobs"] == 1
        assert estimate["items"][0]["status"] == "planned"
        assert run.total_jobs == 1
        assert run.scope_data["_force"] is True


def test_concordance_estimate_queues_current_capability_when_model_changed(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.concordance import CAPABILITY_BY_KEY, create_concordance_run, estimate_concordance_run
    from app.services.preferences import update_app_preferences

    Session = make_session()
    with Session() as db:
        update_app_preferences(db, analysis_models={MODEL_SUMMARY: "gpt-5.5"})
        document = Document(
            title="Model Changed",
            original_filename="model-changed.pdf",
            checksum_sha256="n" * 64,
            processing_status="ready",
            rich_summary="This summary used the old model.",
            page_count=10,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="summary_refresh",
                version=CAPABILITY_BY_KEY["summary_refresh"].version,
                status="complete",
            )
        )
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="concordance",
                capability_key="summary_refresh",
                task_key=MODEL_SUMMARY,
                operation="medusa_document_summary",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
            )
        )
        db.commit()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )
        run = create_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )

        assert estimate["planned_jobs"] == 1
        assert estimate["items"][0]["status"] == "planned"
        assert estimate["items"][0]["estimated_cost_usd"] > 0
        assert run.total_jobs == 1


def test_concordance_worker_completes_same_model_noop_without_model_call(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCompositionRecord, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.concordance import ConcordanceProcessor

    class ExplodingAiService:
        def generate_document_summary(self, *_args, **_kwargs):
            raise AssertionError("same-model summary should not be regenerated")

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: ExplodingAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Worker No-op",
            original_filename="worker-noop.pdf",
            checksum_sha256="o" * 64,
            processing_status="ready",
            rich_summary="This summary is already current.",
            page_count=8,
        )
        db.add(document)
        run = ConcordanceRun(scope_type="documents", scope_data={"document_ids": []}, capability_keys=["summary_refresh"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_refresh",
            target_version=1,
        )
        db.add(job)
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="import",
                capability_key="summary_topics",
                task_key=MODEL_SUMMARY,
                operation="medusa_document_summary",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
            )
        )
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        record = (
            db.query(DocumentCompositionRecord)
            .filter(
                DocumentCompositionRecord.document_id == document.id,
                DocumentCompositionRecord.record_kind == "concordance",
            )
            .one()
        )
        assert job.status == "complete"
        assert run.status == "complete"
        assert record.stage_key == "summary_refresh"
        assert record.status == "model_no_op"


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
        def extract_document_identity(self, filename, text, *, pdf_bytes=None, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "task": "metadata",
                    "filename": filename,
                    "text": text,
                    "model": model,
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
                "confidence": 0.88,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

        def generate_document_summary(self, filename, text, *, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "task": "summary",
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "rich_summary": "Fresh summary.",
                "confidence": 0.9,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

        def extract_keywords_topics(self, filename, text, *, model=None, existing_tags=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "task": "tags",
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "existing_tags": existing_tags,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "topics": ["shared concept"],
                "keywords": ["new concept"],
                "confidence": 0.88,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
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
        assert document.rich_summary == "Fresh summary."
        assert sorted(tag.name for tag in document.tags) == ["manual keep", "shared concept"]
        assert document.metadata_evidence["concordance_tag_governance"]["new_candidate_count"] == 0
        assert document.metadata_evidence["concordance_tag_governance"]["decisions"][1]["candidate_name"] == "new concept"
        assert document.metadata_evidence["concordance_tag_governance"]["decisions"][1]["status"] == "not_attached"
        assert calls == [
            {
                "task": "metadata",
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "model": "gpt-5.5",
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}:metadata",
            },
            {
                "task": "summary",
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "model": "gpt-5.4",
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}:summary",
            },
            {
                "task": "tags",
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "model": "gpt-5.4-mini",
                "existing_tags": ["manual keep", "shared concept"],
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}:tags",
            },
        ]


def test_concordance_tag_refresh_replaces_document_tags_with_governed_suggestions(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentVersion, Tag
    from app.services.concordance import ConcordanceProcessor

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def extract_keywords_topics(self, filename, text, *, model=None, existing_tags=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "existing_tags": existing_tags,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "topics": ["shared concept"],
                "keywords": ["zero trust mesh"],
                "confidence": 0.91,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        stale_tag = Tag(name="stale manual tag", kind="tag", status="canonical")
        shared_tag = Tag(name="shared concept", kind="tag", status="canonical")
        document = Document(
            title="Tagged Target",
            original_filename="tagged-target.pdf",
            checksum_sha256="7" * 64,
            search_text="This document is about a shared concept and a zero trust mesh.",
            processing_status="ready",
            tags=[stale_tag],
        )
        db.add_all([stale_tag, shared_tag, document])
        db.flush()
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"document_ids": [document.id], "_force": True},
            capability_keys=["tag_refresh"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="tag_refresh",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()

        assert job.status == "complete"
        assert sorted(tag.name for tag in document.tags) == ["shared concept", "zero trust mesh"]
        assert "stale manual tag" not in (document.search_text or "")
        assert "shared concept" in (document.search_text or "")
        assert "zero trust mesh" in (document.search_text or "")
        assert document.metadata_evidence["tag_refresh_tag_governance"]["replace_existing"] is True
        assert document.metadata_evidence["tag_refresh_tag_governance"]["replaced_tags"] == ["stale manual tag"]
        assert version.change_note == "Concordance tag refresh"
        assert "tags" in version.metadata_snapshot["changed_fields"]
        assert calls == [
            {
                "filename": "tagged-target.pdf",
                "text": "This document is about a shared concept and a zero trust mesh.",
                "model": "gpt-5.4-mini",
                "existing_tags": ["shared concept", "stale manual tag"],
                "capability_key": "tag_refresh",
                "prompt_cache_key": f"medusa-doc:{'7' * 64}:tag-refresh",
            }
        ]


def test_concordance_summary_topics_skips_same_model_subtasks(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_KEYWORDS_TOPICS, MODEL_METADATA, MODEL_SUMMARY
    from app.services.concordance import ConcordanceProcessor, estimate_concordance_run

    calls: list[str] = []

    class FakeAiService:
        def extract_document_identity(self, *_args, **_kwargs):
            raise AssertionError("metadata should be same-model no-op")

        def generate_document_summary(self, *_args, **_kwargs):
            raise AssertionError("summary should be same-model no-op")

        def extract_keywords_topics(self, *_args, **_kwargs):
            calls.append("tags")
            return {
                "topics": [],
                "keywords": [],
                "confidence": 0.8,
                "needs_review_reasons": [],
                "_openai": {"model": "gpt-5.4-mini", "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Partial No-op",
            original_filename="partial-noop.pdf",
            checksum_sha256="7" * 64,
            processing_status="ready",
            authors=[{"family": "Researcher"}],
            publication_year=2025,
            rich_summary="Already current summary.",
            search_text="Document text.",
            page_count=4,
        )
        db.add(document)
        db.flush()
        for task_key, model in [(MODEL_METADATA, "gpt-5.5"), (MODEL_SUMMARY, "gpt-5.4")]:
            db.add(
                OpenAIUsageRecord(
                    document_id=document.id,
                    source="import",
                    capability_key="summary_topics",
                    task_key=task_key,
                    operation=f"medusa_{task_key}",
                    endpoint="responses",
                    model=model,
                    status="success",
                )
            )
        db.commit()
        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_topics"],
        )
        run = ConcordanceRun(scope_type="documents", scope_data={"document_ids": [document.id]}, capability_keys=["summary_topics"], total_jobs=1)
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

        planned = estimate["items"][0]
        assert estimate["planned_jobs"] == 1
        assert [step["task_key"] for step in planned["cost_steps"]] == [MODEL_KEYWORDS_TOPICS]
        assert calls == ["tags"]
        assert document.metadata_evidence["concordance_ai"]["skipped_fields"] == ["metadata", "rich_summary"]
