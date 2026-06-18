from __future__ import annotations

import signal
import time

from sqlalchemy import asc

from app.config import get_settings
from app.database import init_db, session_scope
from app.models import ConcordanceJob, ImportJob
from app.security import ensure_admin_user
from app.services.concordance import ConcordanceProcessor
from app.services.processing import DocumentProcessor


running = True


def stop(_: int, __: object) -> None:
    global running
    running = False


def claim_next_import_job():
    with session_scope() as db:
        job = (
            db.query(ImportJob)
            .filter(ImportJob.status == "queued")
            .order_by(asc(ImportJob.created_at))
            .first()
        )
        if job:
            job.status = "running"
            db.flush()
            return job.id
    return None


def claim_next_concordance_job():
    with session_scope() as db:
        job = (
            db.query(ConcordanceJob)
            .filter(ConcordanceJob.status == "queued")
            .order_by(asc(ConcordanceJob.created_at))
            .first()
        )
        if job:
            job.status = "running"
            db.flush()
            return job.id
    return None


def process_once(import_processor: DocumentProcessor, concordance_processor: ConcordanceProcessor) -> bool:
    job_id = claim_next_import_job()
    if not job_id:
        concordance_job_id = claim_next_concordance_job()
        if not concordance_job_id:
            return False
        with session_scope() as db:
            job = db.get(ConcordanceJob, concordance_job_id)
            if job:
                concordance_processor.process_job(db, job)
        return True
    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        if job:
            import_processor.process_job(db, job)
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    init_db()
    with session_scope() as db:
        ensure_admin_user(db)
    import_processor = DocumentProcessor()
    concordance_processor = ConcordanceProcessor()
    settings = get_settings()
    while running:
        worked = process_once(import_processor, concordance_processor)
        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
