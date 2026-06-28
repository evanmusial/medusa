from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_accessory_summary_uses_preference_model_and_updates_search(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentPage
    from app.services import accessory_summaries as service
    from app.services.analysis_models import MODEL_ACCESSORY_SUMMARIES
    from app.services.preferences import update_app_preferences

    class FakeAi:
        def generate_accessory_summary(self, filename, text, prompt, *, model=None, **kwargs):
            assert filename == "insider-risk.pdf"
            assert "training data" in text
            assert prompt == "How does this paper handle role-based baselines?"
            assert model == "gpt-5.4-mini"
            return {
                "title": "Role baselines",
                "summary": "The paper compares user behavior against role-based baselines.",
                "confidence": 0.84,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr(service, "get_ai_service", lambda: FakeAi())

    Session = make_session()
    with Session() as db:
        update_app_preferences(db, analysis_models={MODEL_ACCESSORY_SUMMARIES: "gpt-5.4-mini"})
        document = Document(
            title="Role-Based Insider Risk",
            original_filename="insider-risk.pdf",
            checksum_sha256="d" * 64,
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, normalized_text="The model uses training data and role baselines."))
        summary = service.create_accessory_summary(
            db,
            document,
            prompt="How does this paper handle role-based baselines?",
        )
        db.commit()

        assert summary.status == "queued"
        assert summary.model == "gpt-5.4-mini"

        service.AccessorySummaryProcessor().process_summary(db, summary)
        db.refresh(document)
        db.refresh(summary)

        assert summary.status == "complete"
        assert summary.title == "Role baselines"
        assert summary.summary == "The paper compares user behavior against role-based baselines."
        assert summary.evidence["model"] == "gpt-5.4-mini"
        assert "role-based baselines" in (document.search_text or "")
        assert "How does this paper handle" in (document.search_text or "")


def test_inquest_inline_route_completes_and_updates_search(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.models import Document, DocumentPage, User
    from app.schemas import AccessorySummaryCreate
    from app.services import accessory_summaries as service

    class FakeAi:
        def generate_accessory_summary(self, filename, text, prompt, *, model=None, timeout_seconds=None, **kwargs):
            assert filename == "reader-inquest.pdf"
            assert "participant interviews" in text
            assert prompt == "What methods does the paper use?"
            assert model == "gpt-5.4"
            assert timeout_seconds == main.settings.inquest_inline_timeout_seconds
            return {
                "title": "Methods",
                "summary": "The paper uses participant interviews and qualitative coding.",
                "confidence": 0.9,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr(service, "get_ai_service", lambda: FakeAi())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Reader Inquest",
            original_filename="reader-inquest.pdf",
            checksum_sha256="e" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, normalized_text="The paper reports participant interviews."))
        db.commit()

        summary = main.create_document_inquest(
            document.id,
            AccessorySummaryCreate(prompt="What methods does the paper use?", model="gpt-5.4"),
            User(email="tester@example.com", password_hash="hash"),
            db,
        )
        db.refresh(document)

        assert summary.status == "complete"
        assert summary.summary == "The paper uses participant interviews and qualitative coding."
        assert summary.title == "Methods"
        assert "What methods does the paper use?" in (document.search_text or "")
        assert "qualitative coding" in (document.search_text or "")


def test_inquest_inline_timeout_requeues_for_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentPage
    from app.services import accessory_summaries as service

    calls = {"count": 0}

    class FakeAi:
        def generate_accessory_summary(self, filename, text, prompt, *, model=None, timeout_seconds=None, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("inline Inquest timed out")
            return {
                "title": "Recovered answer",
                "summary": "The worker later answers the saved Inquest.",
                "confidence": 0.75,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr(service, "get_ai_service", lambda: FakeAi())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Timeout Inquest",
            original_filename="timeout.pdf",
            checksum_sha256="f" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, normalized_text="The text can answer later."))
        summary = service.create_accessory_summary(db, document, prompt="What is deferred?")
        db.commit()

        service.AccessorySummaryProcessor().process_summary(db, summary, timeout_seconds=0.01, defer_timeouts=True)
        db.refresh(summary)

        assert summary.status == "queued"
        assert summary.locked_at is None
        assert summary.last_error is None
        assert summary.evidence["inline_deferred"] is True

        service.AccessorySummaryProcessor().process_summary(db, summary)
        db.refresh(summary)

        assert summary.status == "complete"
        assert summary.summary == "The worker later answers the saved Inquest."
        assert summary.evidence["inline_deferred"] is True
        assert calls["count"] == 2


def test_source_finding_inquest_uses_related_recommendations_without_ai(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentRecommendation
    from app.services import accessory_summaries as service

    class FakeAi:
        def generate_accessory_summary(self, *args, **kwargs):
            raise AssertionError("source-finding Inquests should use recommendation rows, not generic AI answers")

    def fake_refresh(db, document, *, limit=None):
        assert document.title == "Classic Insider Threat Chapter"
        assert limit == 20
        return []

    monkeypatch.setattr(service, "get_ai_service", lambda: FakeAi())
    monkeypatch.setattr(service, "refresh_document_recommendations", fake_refresh)

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Classic Insider Threat Chapter",
            original_filename="insider-threat.pdf",
            checksum_sha256="1" * 64,
            processing_status="ready",
            publication_year=2005,
        )
        db.add(document)
        db.flush()
        db.add_all(
            [
                DocumentRecommendation(
                    source_document_id=document.id,
                    match_key="doi:10.1000/behavioral",
                    title="Behavioral Analysis of Insider Threat Actors",
                    doi="10.1000/behavioral",
                    authors=[{"given": "Frank", "family": "Greitzer"}],
                    publication_year=2019,
                    journal="Computers & Security",
                    description="A behavioral profile of psychosocial indicators for insider threat actors.",
                    source_provider="semantic_scholar",
                    source_relation="title_search",
                    source_url="https://example.test/behavioral",
                    pdf_url="https://example.test/behavioral.pdf",
                    score=0.72,
                ),
                DocumentRecommendation(
                    source_document_id=document.id,
                    match_key="doi:10.1000/technical",
                    title="Network Telemetry for Enterprise Security",
                    doi="10.1000/technical",
                    authors=[{"given": "Terry", "family": "Analyst"}],
                    publication_year=2007,
                    journal="Security Monitoring",
                    description="A technical monitoring paper with little behavioral profiling.",
                    source_provider="crossref",
                    source_relation="related",
                    source_url="https://example.test/technical",
                    score=0.4,
                ),
            ]
        )
        summary = service.create_accessory_summary(
            db,
            document,
            prompt=(
                "Find me more sources and papers like this one, especially more recent and/or "
                "that attempt a behavioral analysis or profile of insider threats and threat actors."
            ),
        )
        db.commit()

        service.AccessorySummaryProcessor().process_summary(db, summary)
        db.refresh(summary)

        assert summary.status == "complete"
        assert "Medusa's related-paper discovery" in summary.summary
        assert "Behavioral Analysis of Insider Threat Actors" in summary.summary
        assert "https://doi.org/10.1000/behavioral" in summary.summary
        assert "https://example.test/behavioral.pdf" in summary.summary
        assert summary.summary.index("Behavioral Analysis") < summary.summary.index("Network Telemetry")
        assert summary.evidence["source_finder"]["refreshed_recommendations"] is True
        assert len(summary.evidence["source_finder"]["recommendation_ids"]) == 2


def test_source_finding_inquest_defers_inline_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document
    from app.services import accessory_summaries as service

    def fake_refresh(*args, **kwargs):
        raise AssertionError("inline source-finding should defer before refreshing providers")

    monkeypatch.setattr(service, "refresh_document_recommendations", fake_refresh)

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Insider Threat Behavioral Indicators",
            original_filename="source-finder.pdf",
            checksum_sha256="2" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        summary = service.create_accessory_summary(db, document, prompt="Find more recent papers like this one.")
        db.commit()

        service.AccessorySummaryProcessor().process_summary(db, summary, timeout_seconds=0.01, defer_timeouts=True)
        db.refresh(summary)

        assert summary.status == "queued"
        assert summary.locked_at is None
        assert summary.last_error is None
        assert summary.evidence["inline_deferred"] is True
        assert "Source-finding Inquest deferred" in summary.evidence["inline_defer_reason"]


def test_legacy_accessory_summary_route_still_queues(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.models import Document, User
    from app.schemas import AccessorySummaryCreate

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Legacy",
            original_filename="legacy.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.commit()

        summary = main.queue_document_accessory_summary(
            document.id,
            AccessorySummaryCreate(prompt="Keep compatibility.", model="gpt-5.4-mini"),
            User(email="tester@example.com", password_hash="hash"),
            db,
        )

        assert summary.status == "queued"
        assert summary.model == "gpt-5.4-mini"


def test_inquest_route_rejects_hidden_document_and_empty_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    import pytest
    from fastapi import HTTPException

    from app import main
    from app.models import Document, User
    from app.schemas import AccessorySummaryCreate

    Session = make_session()
    with Session() as db:
        hidden = Document(
            title="Hidden",
            original_filename="hidden.pdf",
            checksum_sha256="b" * 64,
            processing_status="staged",
        )
        ready = Document(
            title="Ready",
            original_filename="ready.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
        )
        db.add_all([hidden, ready])
        db.commit()
        user = User(email="tester@example.com", password_hash="hash")

        with pytest.raises(HTTPException) as hidden_error:
            main.create_document_inquest(hidden.id, AccessorySummaryCreate(prompt="Question?"), user, db)
        assert hidden_error.value.status_code == 404

        with pytest.raises(HTTPException) as prompt_error:
            main.create_document_inquest(ready.id, AccessorySummaryCreate(prompt="   "), user, db)
        assert prompt_error.value.status_code == 400
