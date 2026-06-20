from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    import app.models  # noqa: F401

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_import_jobs_list_keeps_active_jobs_visible_beyond_recent_limit(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_import_jobs
    from app.models import Document, ImportBatch, ImportJob, utc_now

    now = utc_now()
    with Session() as db:
        batch = ImportBatch(total_files=121, shared_defaults={})
        running_document = Document(
            title="Currently Running",
            original_filename="running.pdf",
            checksum_sha256="a" * 64,
            page_count=12,
        )
        running_job = ImportJob(
            batch=batch,
            document=running_document,
            status="running",
            current_step="normalizing_page_4",
            locked_at=now - timedelta(minutes=5),
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(minutes=5),
        )
        db.add_all([batch, running_document, running_job])
        for index in range(120):
            document = Document(
                title=f"Queued {index}",
                original_filename=f"queued-{index}.pdf",
                checksum_sha256=f"{index:064x}"[-64:],
            )
            db.add(
                ImportJob(
                    batch=batch,
                    document=document,
                    status="queued",
                    current_step="stored",
                    created_at=now + timedelta(seconds=index),
                    updated_at=now + timedelta(seconds=index),
                )
            )
        db.commit()

        rows = list_import_jobs(object(), db)

    assert rows[0]["id"] == running_job.id
    assert rows[0]["status"] == "running"
    assert rows[0]["current_step"] == "normalizing_page_4"
    assert len(rows) == 121


def test_cancel_import_job_clears_queued_row(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import cancel_import_job
    from app.models import Document, ImportBatch, ImportJob

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(title="Queued", original_filename="queued.pdf", checksum_sha256="b" * 64, processing_status="queued")
        job = ImportJob(batch=batch, document=document, status="queued", current_step="stored")
        db.add_all([batch, document, job])
        db.commit()

        row = cancel_import_job(job.id, object(), db)

        assert row["status"] == "cleared"
        assert row["current_step"] == "cleared"
        assert document.processing_status == "cleared"


def test_cancel_import_job_rejects_running_row(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import cancel_import_job
    from app.models import Document, ImportBatch, ImportJob, utc_now

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(title="Running", original_filename="running.pdf", checksum_sha256="c" * 64, processing_status="running")
        job = ImportJob(batch=batch, document=document, status="running", current_step="enriching", locked_at=utc_now())
        db.add_all([batch, document, job])
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            cancel_import_job(job.id, object(), db)

        assert exc_info.value.status_code == 409
        assert job.status == "running"
        assert document.processing_status == "running"
