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


def add_chunk(db, document, text, page=1):
    from app.models import TextChunk

    chunk = TextChunk(document_id=document.id, page_start=page, page_end=page, text=text, token_count=max(1, len(text) // 4))
    db.add(chunk)
    return chunk


def test_recon_library_scope_excludes_hidden_portfolio_documents(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document
    from app.services.recon import retrieve_recon_evidence

    with Session() as db:
        library = Document(
            title="Behavioral Inference In Classrooms",
            original_filename="library.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
            search_text="behavioral inference classroom evidence",
        )
        portfolio = Document(
            title="Hidden Portfolio Draft",
            document_kind="portfolio_version",
            original_filename="draft.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
            search_text="behavioral inference classroom evidence",
        )
        db.add_all([library, portfolio])
        db.flush()
        add_chunk(db, library, "This paper offers behavioral inference evidence for classroom practice.")
        add_chunk(db, portfolio, "This hidden draft also mentions behavioral inference evidence.")
        db.commit()

        candidates, documents = retrieve_recon_evidence(
            db,
            question="show me papers about behavioral inference",
            scope_type="library",
            scope={},
            mode="source_finder",
        )

    assert [document.id for document in documents] == [library.id]
    assert candidates
    assert {candidate.document.id for candidate in candidates} == {library.id}


def test_recon_run_persists_source_finder_evidence(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document
    from app.services.recon import create_recon_inquiry, run_recon_inquiry

    with Session() as db:
        document = Document(
            title="Authoritative Source On Behavioral Inference",
            original_filename="source.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
            apa_citation="Author, A. (2025). Authoritative source.",
        )
        db.add(document)
        db.flush()
        add_chunk(db, document, "Behavioral inference is discussed with direct evidence and methodological limits.", page=3)
        db.commit()

        inquiry = create_recon_inquiry(
            db,
            title=None,
            question="I need an authoritative source about behavioral inference",
            default_mode="source_finder",
        )
        run = run_recon_inquiry(db, inquiry, mode="source_finder")

    assert run.status == "complete"
    assert run.evidence_count == 1
    assert run.evidence[0].document_id == document.id
    assert run.evidence[0].page_start == 3
    assert "Authoritative Source" in run.answers[0].answer
    assert run.answers[0].limitations


def test_recon_domain_scope_requires_domain_id(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document
    from app.services.recon import retrieve_recon_evidence

    with Session() as db:
        document = Document(
            title="Domain Candidate",
            original_filename="domain.pdf",
            checksum_sha256="f" * 64,
            processing_status="ready",
            search_text="behavioral inference",
        )
        db.add(document)
        db.flush()
        add_chunk(db, document, "Behavioral inference evidence.", page=1)
        db.commit()

        candidates, documents = retrieve_recon_evidence(
            db,
            question="behavioral inference",
            scope_type="domain",
            scope={"domain_ids": []},
            mode="source_finder",
        )

    assert candidates == []
    assert documents == []


def test_recon_quick_answer_without_evidence_does_not_call_model(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.services import recon as recon_service
    from app.services.recon import create_recon_inquiry, run_recon_inquiry

    class ExplodingAiService:
        def generate_recon_answer(self, *args, **kwargs):
            raise AssertionError("model should not be called without stored evidence")

    monkeypatch.setattr(recon_service, "get_ai_service", lambda: ExplodingAiService())

    with Session() as db:
        inquiry = create_recon_inquiry(
            db,
            title="No evidence",
            question="What supports behavioral inference?",
            default_mode="quick_answer",
        )
        run = run_recon_inquiry(db, inquiry, mode="quick_answer")

    assert run.status == "complete"
    assert run.evidence_count == 0
    assert run.answers[0].answer_metadata["method"] == "local_no_evidence"
    assert "No Library evidence matched" in run.answers[0].answer


def test_recon_quick_answer_uses_model_over_stored_evidence(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document
    from app.services import recon as recon_service
    from app.services.recon import create_recon_inquiry, run_recon_inquiry

    class FakeAiService:
        def generate_recon_answer(self, question, evidence_items, **kwargs):
            assert question.startswith("How does behavioral inference")
            assert evidence_items[0]["label"] == "R1"
            assert evidence_items[0]["document_id"]
            return {
                "answer": "Behavioral inference is supported by [R1].",
                "confidence": 0.81,
                "limitations": ["Only retrieved evidence was searched."],
                "_openai": {"model": kwargs.get("model"), "configured": True},
            }

    monkeypatch.setattr(recon_service, "get_ai_service", lambda: FakeAiService())

    with Session() as db:
        document = Document(
            title="Behavioral Inference Methods",
            original_filename="methods.pdf",
            checksum_sha256="d" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        add_chunk(db, document, "Behavioral inference methods connect observation, evidence, and interpretation.", page=5)
        db.commit()

        inquiry = create_recon_inquiry(
            db,
            title="Behavioral inference synthesis",
            question="How does behavioral inference support interpretation?",
            default_mode="quick_answer",
            model="fake-model",
        )
        run = run_recon_inquiry(db, inquiry, mode="quick_answer", model="fake-model")

    assert run.status == "complete"
    assert run.evidence_count == 1
    assert run.answers[0].answer == "Behavioral inference is supported by [R1]."
    assert float(run.answers[0].confidence) == 0.81
    assert run.answers[0].answer_metadata["method"] == "ai_synthesis"


def test_search_index_concordance_encodes_missing_chunks(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import ConcordanceJob, ConcordanceRun, Document
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    class FakeAiService:
        client = object()

        def embed(self, text, *, model=None, usage_context=None):
            assert usage_context.capability_key == "text_chunk_encoding"
            return [0.125] * 1536

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    with Session() as db:
        document = Document(
            title="Semantic Index Refresh",
            original_filename="semantic.pdf",
            checksum_sha256="e" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        chunk = add_chunk(db, document, "Older import chunk missing an embedding.", page=2)
        run = ConcordanceRun(scope_type="documents", scope_data={"document_ids": [document.id]}, capability_keys=["search_index"])
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="search_index",
            target_version=CAPABILITY_BY_KEY["search_index"].version,
        )
        db.add(job)
        db.flush()

        evidence = ConcordanceProcessor()._refresh_search_index(db, document, job)

    assert chunk.embedding == [0.125] * 1536
    assert evidence["text_chunk_encoding"]["chunk_count"] == 1
    assert evidence["text_chunk_encoding"]["encoded_chunks"] == 1
    assert evidence["text_chunk_encoding"]["status"] == "complete"
