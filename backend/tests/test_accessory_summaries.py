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
