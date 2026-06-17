from __future__ import annotations

import signal
import time

from sqlalchemy import asc

from app.config import get_settings
from app.database import init_db, session_scope
from app.models import ImportJob
from app.security import ensure_admin_user
from app.services.processing import DocumentProcessor


running = True


def stop(_: int, __: object) -> None:
    global running
    running = False


def claim_next_job():
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


def process_once(processor: DocumentProcessor) -> bool:
    job_id = claim_next_job()
    if not job_id:
        return False
    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        if job:
            processor.process_job(db, job)
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    init_db()
    with session_scope() as db:
        ensure_admin_user(db)
    processor = DocumentProcessor()
    settings = get_settings()
    while running:
        worked = process_once(processor)
        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
