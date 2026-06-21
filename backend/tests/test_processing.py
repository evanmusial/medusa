import asyncio
import hashlib
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_refresh_import_batch_progress_flushes_pending_job_status(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import ImportBatch, ImportJob
    from app.services.processing import refresh_import_batch_progress

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[ImportBatch.__table__, ImportJob.__table__])
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, status="queued", current_step="stored")
        db.add_all([batch, job])
        db.commit()

        job.status = "complete"
        job.current_step = "complete"

        refresh_import_batch_progress(db, batch)

        assert batch.completed_files == 1
        assert batch.failed_files == 0
        assert batch.status == "complete"


def test_refresh_import_batch_progress_treats_cleared_jobs_as_terminal(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import ImportBatch, ImportJob
    from app.services.processing import refresh_import_batch_progress

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[ImportBatch.__table__, ImportJob.__table__])
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, status="cleared", current_step="cleared")
        db.add_all([batch, job])
        db.commit()

        refresh_import_batch_progress(db, batch)

        assert batch.completed_files == 0
        assert batch.failed_files == 0
        assert batch.status == "cleared"


def test_clear_import_queue_parks_non_running_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.database import Base
    from app.models import Document, ImportBatch, ImportJob, ProcessingEvent, utc_now

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        batch = ImportBatch(total_files=4, shared_defaults={})
        queued_document = Document(title="Queued", original_filename="queued.pdf", checksum_sha256="a" * 64, processing_status="queued")
        failed_document = Document(title="Failed", original_filename="failed.pdf", checksum_sha256="b" * 64, processing_status="failed")
        running_document = Document(title="Running", original_filename="running.pdf", checksum_sha256="c" * 64, processing_status="running")
        restored_document = Document(
            title="Restored",
            original_filename="restored.pdf",
            checksum_sha256="d" * 64,
            processing_status="restored_paused",
        )
        queued_job = ImportJob(batch=batch, document=queued_document, status="queued", current_step="stored")
        failed_job = ImportJob(batch=batch, document=failed_document, status="failed", current_step="enriching", last_error="boom")
        running_job = ImportJob(batch=batch, document=running_document, status="running", current_step="extracting", locked_at=utc_now())
        restored_job = ImportJob(batch=batch, document=restored_document, status="restored_paused", current_step="stored")
        db.add_all([batch, queued_job, failed_job, running_job, restored_job])
        db.commit()

        result = main.clear_import_queue(object(), db)

        assert result.matched_count == 4
        assert result.updated_count == 3
        assert result.skipped_running_count == 1
        assert queued_job.status == "cleared"
        assert failed_job.status == "cleared"
        assert restored_job.status == "cleared"
        assert running_job.status == "running"
        assert queued_document.processing_status == "cleared"
        assert failed_document.processing_status == "cleared"
        assert restored_document.processing_status == "cleared"
        assert running_document.processing_status == "running"
        assert batch.status == "running"
        assert db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "manual_import_clear").count() == 3


def test_retry_failed_import_jobs_requeues_document_jobs_only(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.database import Base
    from app.models import Document, ImportBatch, ImportJob, ProcessingEvent

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        batch = ImportBatch(total_files=2, shared_defaults={})
        document = Document(title="Failed", original_filename="failed.pdf", checksum_sha256="e" * 64, processing_status="failed")
        retryable = ImportJob(batch=batch, document=document, status="failed", current_step="enriching", last_error="boom")
        unretryable = ImportJob(batch=batch, document_id=None, status="failed", current_step="download_failed", last_error="no pdf")
        db.add_all([batch, retryable, unretryable])
        db.commit()

        result = main.retry_failed_import_jobs(object(), db)

        assert result.matched_count == 2
        assert result.updated_count == 1
        assert result.skipped_unretryable_count == 1
        assert retryable.status == "queued"
        assert retryable.last_error is None
        assert document.processing_status == "queued"
        assert unretryable.status == "failed"
        event = db.query(ProcessingEvent).filter(ProcessingEvent.import_job_id == retryable.id).one()
        assert event.event_type == "manual_import_retry_failed"


def test_claim_import_job_recovers_stale_running_job(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import (
        ConcordanceJob,
        ConcordanceRun,
        Document,
        ImportBatch,
        ImportJob,
        ProcessingEvent,
        utc_now,
    )
    from app.worker import claim_import_job

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            ImportBatch.__table__,
            ImportJob.__table__,
            ProcessingEvent.__table__,
            ConcordanceRun.__table__,
            ConcordanceJob.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        document = Document(
            title="Stuck import",
            original_filename="stuck-import.pdf",
            checksum_sha256="a" * 64,
            metadata_evidence={},
        )
        batch = ImportBatch(total_files=1, shared_defaults={})
        stale_locked_at = utc_now() - timedelta(minutes=30)
        job = ImportJob(
            batch=batch,
            document=document,
            status="running",
            current_step="stored",
            locked_at=stale_locked_at,
            last_error="previous interruption",
        )
        db.add_all([document, batch, job])
        db.commit()

        claimed_id = claim_import_job(db, stale_after_seconds=60)

        assert claimed_id == job.id
        assert job.status == "running"
        assert job.locked_at is not None
        assert job.locked_at > stale_locked_at
        assert job.last_error is None

        event = db.query(ProcessingEvent).one()
        assert event.import_job_id == job.id
        assert event.document_id == document.id
        assert event.event_type == "stale_import_recovered"
        assert event.payload["previous_step"] == "stored"


def test_claim_import_job_leaves_fresh_running_job_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import (
        ConcordanceJob,
        ConcordanceRun,
        Document,
        ImportBatch,
        ImportJob,
        ProcessingEvent,
        utc_now,
    )
    from app.worker import claim_import_job

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            ImportBatch.__table__,
            ImportJob.__table__,
            ProcessingEvent.__table__,
            ConcordanceRun.__table__,
            ConcordanceJob.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        document = Document(
            title="Fresh import",
            original_filename="fresh-import.pdf",
            checksum_sha256="b" * 64,
            metadata_evidence={},
        )
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(
            batch=batch,
            document=document,
            status="running",
            current_step="stored",
            locked_at=utc_now(),
        )
        db.add_all([document, batch, job])
        db.commit()

        claimed_id = claim_import_job(db, stale_after_seconds=60)

        assert claimed_id is None
        assert db.query(ProcessingEvent).count() == 0


def test_claim_import_job_skips_excluded_inflight_job(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import (
        ConcordanceJob,
        ConcordanceRun,
        Document,
        ImportBatch,
        ImportJob,
        ProcessingEvent,
        utc_now,
    )
    from app.worker import claim_import_job

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            ImportBatch.__table__,
            ImportJob.__table__,
            ProcessingEvent.__table__,
            ConcordanceRun.__table__,
            ConcordanceJob.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        running_document = Document(
            title="Long import",
            original_filename="long-import.pdf",
            checksum_sha256="1" * 64,
            metadata_evidence={},
        )
        queued_document = Document(
            title="Next import",
            original_filename="next-import.pdf",
            checksum_sha256="2" * 64,
            metadata_evidence={},
        )
        batch = ImportBatch(total_files=2, shared_defaults={})
        stale_running_job = ImportJob(
            batch=batch,
            document=running_document,
            status="running",
            current_step="normalizing_pages",
            locked_at=utc_now() - timedelta(minutes=30),
        )
        queued_job = ImportJob(batch=batch, document=queued_document, status="queued", current_step="stored")
        db.add_all([running_document, queued_document, batch, stale_running_job, queued_job])
        db.commit()

        claimed_id = claim_import_job(db, stale_after_seconds=60, exclude_ids={stale_running_job.id})

        assert claimed_id == queued_job.id
        assert stale_running_job.status == "running"
        assert queued_job.status == "running"
        assert db.query(ProcessingEvent).count() == 0


def test_worker_start_requeues_interrupted_running_import(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import (
        ConcordanceJob,
        ConcordanceRun,
        Document,
        DocumentAccessorySummary,
        ImportBatch,
        ImportJob,
        ProcessingEvent,
        utc_now,
    )
    from app.worker import recover_interrupted_jobs_on_start

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            ImportBatch.__table__,
            ImportJob.__table__,
            ProcessingEvent.__table__,
            ConcordanceRun.__table__,
            ConcordanceJob.__table__,
            DocumentAccessorySummary.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        document = Document(
            title="Interrupted import",
            original_filename="interrupted-import.pdf",
            checksum_sha256="c" * 64,
            metadata_evidence={},
            processing_status="running",
        )
        batch = ImportBatch(total_files=1, shared_defaults={}, status="running")
        job = ImportJob(
            batch=batch,
            document=document,
            status="running",
            current_step="normalizing_pages",
            locked_at=utc_now(),
        )
        db.add_all([document, batch, job])
        db.commit()

        import_count, concordance_count, accessory_summary_count = recover_interrupted_jobs_on_start(db)

        assert import_count == 1
        assert concordance_count == 0
        assert accessory_summary_count == 0
        assert job.status == "queued"
        assert job.current_step == "normalizing_pages"
        assert job.locked_at is None
        assert document.processing_status == "queued"

        event = db.query(ProcessingEvent).one()
        assert event.event_type == "interrupted_import_requeued"
        assert event.payload["previous_step"] == "normalizing_pages"


def test_rescue_import_job_requeues_stale_running_import(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.database import Base
    from app.models import Document, ImportBatch, ImportJob, ProcessingEvent, utc_now

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        document = Document(
            title="Stale import",
            original_filename="stale-import.pdf",
            checksum_sha256="3" * 64,
            metadata_evidence={},
            processing_status="running",
        )
        batch = ImportBatch(total_files=1, shared_defaults={}, status="running")
        job = ImportJob(
            batch=batch,
            document=document,
            status="running",
            current_step="normalizing_page_7",
            locked_at=utc_now() - timedelta(minutes=30),
            last_error="hung request",
        )
        db.add_all([document, batch, job])
        db.commit()

        rescued = main.rescue_import_job(job.id, object(), db)

        assert rescued["status"] == "queued"
        assert job.status == "queued"
        assert job.locked_at is None
        assert job.last_error is None
        assert document.processing_status == "queued"
        assert db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "manual_import_rescue").count() == 1


def test_extract_replaces_existing_pages_on_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCompositionRecord, DocumentPage, ImportBatch, ImportJob, OpenAIUsageRecord, ProcessingEvent, TextChunk
    from app.services import processing
    from app.services.processing import DocumentProcessor

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            DocumentPage.__table__,
            TextChunk.__table__,
            ImportBatch.__table__,
            ImportJob.__table__,
            ProcessingEvent.__table__,
            ConcordanceRun.__table__,
            ConcordanceJob.__table__,
            OpenAIUsageRecord.__table__,
            DocumentCompositionRecord.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    cache_path = tmp_path / "retry.pdf"
    cache_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        processing,
        "extract_pdf_text",
        lambda _, extractor=None: SimpleNamespace(
            page_count=1,
            pages=[SimpleNamespace(page_number=1, text="\x00\x02Replacement text\x7f", low_text=False, source="test")],
            source="test",
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(
        processing,
        "normalize_document_pages",
        lambda document, ai=None, db=None, job=None, resume_existing=False, model=None, pdf_bytes=None, usage_context=None, **_: {
            "pages": 1,
            "sources": {"test": 1},
        },
    )
    monkeypatch.setattr(processing, "get_ai_service", lambda: object())

    with Session() as db:
        document = Document(
            title="Retry import",
            original_filename="retry-import.pdf",
            checksum_sha256="d" * 64,
            metadata_evidence={"local_cache_path": str(cache_path)},
        )
        document.pages.append(DocumentPage(page_number=1, text="Old text", low_text=False))
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="extracting")
        db.add_all([document, batch, job])
        db.commit()

        DocumentProcessor()._extract(db, job, document)

        pages = db.query(DocumentPage).filter(DocumentPage.document_id == document.id).all()
        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert pages[0].text == "Replacement text"
        assert "\x00" not in document.search_text
        assert job.current_step == "extracted"
        composition_rows = db.query(DocumentCompositionRecord).filter(DocumentCompositionRecord.document_id == document.id).all()
        raw_composition = next(row for row in composition_rows if row.stage_key == "raw_text_extraction")
        assert raw_composition.method == "test"
        assert {row.stage_key for row in composition_rows} >= {"document_structure_cleanup", "bibliography_extraction", "raw_text_extraction"}


def test_extract_resumes_page_normalization_from_persisted_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE", "always")

    from app.database import Base
    from app.config import get_settings
    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCompositionRecord, DocumentPage, ImportBatch, ImportJob, OpenAIUsageRecord, ProcessingEvent, TextChunk
    from app.services.processing import DocumentProcessor
    from app.services import processing

    get_settings.cache_clear()

    class FakeAi:
        def __init__(self):
            self.pages: list[int] = []
            self.text_inputs: list[str] = []

        def normalize_page_text(self, filename, page_number, text, **_):
            self.pages.append(page_number)
            self.text_inputs.append(text)
            return {"normalized_text": f"\x00normalized {page_number}\x7f", "source": "test", "notes": []}

    fake_ai = FakeAi()
    monkeypatch.setattr(processing, "get_ai_service", lambda: fake_ai)

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            DocumentPage.__table__,
            TextChunk.__table__,
            ImportBatch.__table__,
            ImportJob.__table__,
            ProcessingEvent.__table__,
            ConcordanceRun.__table__,
            ConcordanceJob.__table__,
            OpenAIUsageRecord.__table__,
            DocumentCompositionRecord.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        document = Document(
            title="Resume import",
            original_filename="resume-import.pdf",
            checksum_sha256="4" * 64,
            metadata_evidence={},
            page_count=2,
        )
        document.pages.append(DocumentPage(page_number=1, text="Page one", normalized_text="already done", low_text=False))
        document.pages.append(DocumentPage(page_number=2, text="\x00Page two\x7f", low_text=False))
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="normalizing_page_2")
        db.add_all([document, batch, job])
        db.commit()

        DocumentProcessor()._extract(db, job, document)

        assert fake_ai.pages == [2]
        assert fake_ai.text_inputs == ["Page two"]
        assert document.pages[0].normalized_text == "already done"
        assert document.pages[1].normalized_text == "normalized 2"
        assert "\x00" not in document.search_text
        assert job.current_step == "extracted"
        assert document.metadata_evidence["page_text_normalization"]["sources"] == {"existing": 1, "test": 1}


def test_auto_page_normalization_uses_local_for_clean_marker_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE", "auto")

    from app.config import get_settings
    from app.models import Document, DocumentPage
    from app.services.processing import normalize_document_pages

    get_settings.cache_clear()

    class FailIfCalled:
        def normalize_page_text(self, *_, **__):
            raise AssertionError("clean Marker page should not call OpenAI normalization")

    document = Document(title="Marker", original_filename="marker.pdf", checksum_sha256="5" * 64)
    document.pages.append(
        DocumentPage(page_number=1, text="A clean paragraph from Marker.\n\nA second clean paragraph.", low_text=False, text_source="marker")
    )

    summary = normalize_document_pages(document, ai=FailIfCalled(), pdf_bytes=b"%PDF")

    assert document.pages[0].normalized_text == "A clean paragraph from Marker.\n\nA second clean paragraph."
    assert summary["sources"] == {"local_auto": 1}
    assert summary["auto_cloud_pages"] == 0


def test_auto_page_normalization_escalates_artifact_pages_without_pdf_context(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE", "auto")

    from app.config import get_settings
    from app.models import Document, DocumentPage
    from app.services.processing import normalize_document_pages

    get_settings.cache_clear()

    class FakeAi:
        def __init__(self):
            self.pdf_bytes = "not called"

        def normalize_page_text(self, filename, page_number, text, **kwargs):
            del filename, page_number, text
            self.pdf_bytes = kwargs.get("pdf_bytes")
            return {"normalized_text": "Cloud cleaned text", "source": "openai", "notes": [], "_openai": {"model": "test"}}

    fake_ai = FakeAi()
    document = Document(title="Artifact", original_filename="artifact.pdf", checksum_sha256="6" * 64)
    document.pages.append(
        DocumentPage(
            page_number=1,
            text="The article de-\nscribes one issue.\n\nThe method com-\npares another issue.",
            low_text=False,
            text_source="pymupdf",
        )
    )

    summary = normalize_document_pages(document, ai=fake_ai, pdf_bytes=b"%PDF")

    assert document.pages[0].normalized_text == "Cloud cleaned text"
    assert fake_ai.pdf_bytes is None
    assert summary["sources"] == {"openai": 1}
    assert summary["auto_cloud_pages"] == 1
    assert summary["auto_reasons"] == {"hyphenated_wraps": 1}


def test_duplicate_preflight_and_skip_strategy(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app import main
    from app.models import Document, DocumentCompositionRecord, ImportJob

    class FakeStorage:
        def put_bytes(self, key, data, content_type):
            return SimpleNamespace(uri=f"memory://{key}", backend="fake")

    monkeypatch.setattr(main, "get_storage_service", lambda: FakeStorage())
    main.settings.data_dir = tmp_path / "data"

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    data = b"%PDF-1.4 duplicate"
    checksum = hashlib.sha256(data).hexdigest()

    with Session() as db:
        existing = Document(title="Existing", original_filename="existing.pdf", checksum_sha256=checksum)
        db.add(existing)
        db.commit()

        check = asyncio.run(
            main.check_import_duplicates(
                object(),
                db,
                [UploadFile(filename="existing.pdf", file=BytesIO(data))],
            )
        )
        assert check.duplicate_file_count == 1
        assert check.files[0].existing_documents[0].id == existing.id

        batch = asyncio.run(
            main.create_import_batch(
                object(),
                db,
                files=[UploadFile(filename="existing.pdf", file=BytesIO(data))],
                duplicate_strategy="skip",
            )
        )

        assert db.query(Document).count() == 1
        job = db.query(ImportJob).filter(ImportJob.batch_id == batch.id).one()
        assert job.status == "complete"
        assert job.current_step == "duplicate_skipped"


def test_duplicate_preflight_ignores_cleared_queue_documents(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    from app.database import Base
    from app import main
    from app.models import Document, ImportJob

    class FakeStorage:
        def put_bytes(self, key, data, content_type):
            return SimpleNamespace(uri=f"memory://{key}", backend="fake")

    monkeypatch.setattr(main, "get_storage_service", lambda: FakeStorage())
    main.settings.data_dir = tmp_path / "data"

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    data = b"%PDF-1.4 cleared duplicate source"
    checksum = hashlib.sha256(data).hexdigest()

    with Session() as db:
        stale = Document(
            title="Chapter stale",
            original_filename="Chapter stale.pdf",
            checksum_sha256=checksum,
            processing_status="cleared",
        )
        db.add(stale)
        db.commit()

        check = asyncio.run(
            main.check_import_duplicates(
                object(),
                db,
                [UploadFile(filename="Chapter fresh.pdf", file=BytesIO(data))],
            )
        )
        assert check.duplicate_file_count == 0
        assert check.files[0].existing_documents == []

        batch = asyncio.run(
            main.create_import_batch(
                object(),
                db,
                files=[UploadFile(filename="Chapter fresh.pdf", file=BytesIO(data))],
                duplicate_strategy="skip",
            )
        )

        jobs = db.query(ImportJob).filter(ImportJob.batch_id == batch.id).all()
        assert len(jobs) == 1
        assert jobs[0].status == "staged"
        assert jobs[0].current_step == "staged"
        assert db.query(Document).count() == 2


def test_import_anyway_allows_same_checksum_document(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app import main
    from app.models import Document, DocumentCompositionRecord, ImportJob

    class FakeStorage:
        def put_bytes(self, key, data, content_type):
            return SimpleNamespace(uri=f"memory://{key}", backend="fake")

    monkeypatch.setattr(main, "get_storage_service", lambda: FakeStorage())
    main.settings.data_dir = tmp_path / "data"

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    data = b"%PDF-1.4 duplicate"
    checksum = hashlib.sha256(data).hexdigest()

    with Session() as db:
        db.add(Document(title="Existing", original_filename="existing.pdf", checksum_sha256=checksum))
        db.commit()

        batch = asyncio.run(
            main.create_import_batch(
                object(),
                db,
                files=[UploadFile(filename="copy.pdf", file=BytesIO(data))],
                duplicate_strategy="import_anyway",
            )
        )

        documents = db.query(Document).filter(Document.checksum_sha256 == checksum).all()
        assert len(documents) == 2
        job = db.query(ImportJob).filter(ImportJob.batch_id == batch.id).one()
        assert job.status == "staged"
        assert job.current_step == "staged"
        estimate_record = (
            db.query(DocumentCompositionRecord)
            .filter(
                DocumentCompositionRecord.import_job_id == job.id,
                DocumentCompositionRecord.record_kind == "estimate",
                DocumentCompositionRecord.stage_key == "import_cost_estimate",
            )
            .one()
        )
        assert float(estimate_record.amount_usd) > 0
        assert estimate_record.record_metadata["estimate_basis"] == "preset_steps"
        assert any(
            step["task_key"] == "page_text_normalization"
            for step in estimate_record.record_metadata.get("step_estimates", [])
        )


def test_html_import_converts_to_pdf_mezzanine_and_uses_source_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.config import get_settings
    from app.database import Base
    from app.models import Document, ImportJob
    from app.services.processing import DocumentProcessor

    class FakeStorage:
        def __init__(self):
            self.objects = []

        def put_bytes(self, key, data, content_type):
            self.objects.append({"key": key, "data": data, "content_type": content_type})
            return SimpleNamespace(uri=f"memory://{key}", backend="fake")

    fake_storage = FakeStorage()
    monkeypatch.setattr(main, "get_storage_service", lambda: fake_storage)
    settings = get_settings()
    monkeypatch.setattr(main.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "openai_normalize_page_text", False)

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    html = b"""
    <html>
      <head><title>Browser Wrapper</title></head>
      <body>
        <h1>Actual Research Title</h1>
        <h2>Methods</h2>
        <p>Signal-bearing HTML body text should become searchable reader text.</p>
      </body>
    </html>
    """
    checksum = hashlib.sha256(html).hexdigest()

    with Session() as db:
        check = asyncio.run(
            main.check_import_duplicates(
                object(),
                db,
                [UploadFile(filename="article.html", file=BytesIO(html))],
            )
        )
        assert check.files[0].source_kind == "html"
        assert check.files[0].stored_filename == "article.pdf"

        batch = asyncio.run(
            main.create_import_batch(
                object(),
                db,
                files=[UploadFile(filename="article.html", file=BytesIO(html))],
                duplicate_strategy="skip",
            )
        )

        document = db.query(Document).one()
        assert document.title == "Actual Research Title"
        assert document.original_filename == "article.pdf"
        assert document.content_type == "application/pdf"
        assert document.checksum_sha256 == checksum
        assert fake_storage.objects[0]["content_type"] == "application/pdf"
        assert fake_storage.objects[0]["data"].startswith(b"%PDF")
        assert fake_storage.objects[0]["key"].endswith("/article.pdf")
        assert document.metadata_evidence["source_import"]["kind"] == "html"
        assert document.metadata_evidence["source_import"]["mezzanine"]["checksum_sha256"]

        job = db.query(ImportJob).filter(ImportJob.batch_id == batch.id).one()
        DocumentProcessor()._extract(db, job, document)
        db.refresh(document)

        reading_text = "\n".join(page.text for page in document.pages)
        assert "Actual Research Title" in reading_text
        assert "Methods" in reading_text
        assert "Signal-bearing HTML body text" in reading_text
        source_evidence = document.metadata_evidence["source_import"]
        assert "extracted_pages" not in source_evidence
        assert source_evidence["extracted_page_count"] == document.page_count
