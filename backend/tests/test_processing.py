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
