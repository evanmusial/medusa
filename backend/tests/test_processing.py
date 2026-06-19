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


def test_claim_import_job_recovers_stale_running_job(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import ConcordanceJob, ConcordanceRun, Document, ImportBatch, ImportJob, ProcessingEvent, utc_now
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
    from app.models import ConcordanceJob, ConcordanceRun, Document, ImportBatch, ImportJob, ProcessingEvent, utc_now
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
    from app.models import ConcordanceJob, ConcordanceRun, Document, ImportBatch, ImportJob, ProcessingEvent, utc_now
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
    from app.models import ConcordanceJob, ConcordanceRun, Document, ImportBatch, ImportJob, ProcessingEvent, utc_now
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

        import_count, concordance_count = recover_interrupted_jobs_on_start(db)

        assert import_count == 1
        assert concordance_count == 0
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
    from app.models import Document, DocumentPage, ImportBatch, ImportJob, ProcessingEvent, TextChunk
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
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    cache_path = tmp_path / "retry.pdf"
    cache_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        processing,
        "extract_pdf_text",
        lambda _: SimpleNamespace(
            page_count=1,
            pages=[SimpleNamespace(page_number=1, text="Replacement text", low_text=False)],
        ),
    )
    monkeypatch.setattr(
        processing,
        "normalize_document_pages",
        lambda document, ai=None, db=None, job=None, resume_existing=False, model=None, pdf_bytes=None: {
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
        assert job.current_step == "extracted"


def test_extract_resumes_page_normalization_from_persisted_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import Document, DocumentPage, ImportBatch, ImportJob, ProcessingEvent, TextChunk
    from app.services.processing import DocumentProcessor
    from app.services import processing

    class FakeAi:
        def __init__(self):
            self.pages: list[int] = []

        def normalize_page_text(self, filename, page_number, text, **_):
            self.pages.append(page_number)
            return {"normalized_text": f"normalized {page_number}", "source": "test", "notes": []}

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
        document.pages.append(DocumentPage(page_number=2, text="Page two", low_text=False))
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="normalizing_page_2")
        db.add_all([document, batch, job])
        db.commit()

        DocumentProcessor()._extract(db, job, document)

        assert fake_ai.pages == [2]
        assert document.pages[0].normalized_text == "already done"
        assert document.pages[1].normalized_text == "normalized 2"
        assert job.current_step == "extracted"
        assert document.metadata_evidence["page_text_normalization"]["sources"] == {"existing": 1, "test": 1}


def test_duplicate_preflight_and_skip_strategy(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

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


def test_import_anyway_allows_same_checksum_document(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

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
        assert job.status == "queued"
