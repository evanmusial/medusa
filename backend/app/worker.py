from __future__ import annotations

import signal
import time
from datetime import timedelta

from sqlalchemy import and_, asc, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import init_db, session_scope
from app.models import ConcordanceJob, ImportJob, ProcessingEvent, utc_now
from app.security import ensure_admin_user
from app.services.concordance import ConcordanceProcessor, refresh_concordance_run_progress
from app.services.processing import DocumentProcessor, refresh_import_batch_progress


running = True


def stop(_: int, __: object) -> None:
    global running
    running = False


def stale_cutoff(stale_after_seconds: int):
    return utc_now() - timedelta(seconds=max(1, stale_after_seconds))


def stale_running_filter(model, cutoff):
    return and_(
        model.status == "running",
        or_(
            and_(model.locked_at.isnot(None), model.locked_at < cutoff),
            and_(model.locked_at.is_(None), model.updated_at < cutoff),
        ),
    )


def claim_import_job(db: Session, stale_after_seconds: int) -> str | None:
    cutoff = stale_cutoff(stale_after_seconds)
    now = utc_now()
    job = (
        db.query(ImportJob)
        .filter(or_(ImportJob.status == "queued", stale_running_filter(ImportJob, cutoff)))
        .order_by(asc(ImportJob.created_at))
        .first()
    )
    if not job:
        return None

    was_stale = job.status == "running"
    previous_locked_at = job.locked_at
    previous_step = job.current_step
    if was_stale:
        db.add(
            ProcessingEvent(
                import_job_id=job.id,
                document_id=job.document_id,
                level="warning",
                event_type="stale_import_recovered",
                message="Import job was recovered after a previous worker stopped before completion.",
                payload={
                    "previous_step": previous_step,
                    "previous_locked_at": previous_locked_at.isoformat() if previous_locked_at else None,
                },
            )
        )

    job.status = "running"
    job.locked_at = now
    job.last_error = None
    db.flush()
    return job.id


def claim_concordance_job(db: Session, stale_after_seconds: int) -> str | None:
    cutoff = stale_cutoff(stale_after_seconds)
    job = (
        db.query(ConcordanceJob)
        .filter(or_(ConcordanceJob.status == "queued", stale_running_filter(ConcordanceJob, cutoff)))
        .order_by(asc(ConcordanceJob.created_at))
        .first()
    )
    if not job:
        return None

    job.status = "running"
    job.locked_at = utc_now()
    job.last_error = None
    if job.run:
        refresh_concordance_run_progress(db, job.run)
    db.flush()
    return job.id


def recover_interrupted_jobs_on_start(db: Session) -> tuple[int, int]:
    import_jobs = db.query(ImportJob).filter(ImportJob.status == "running").all()
    for job in import_jobs:
        previous_locked_at = job.locked_at
        db.add(
            ProcessingEvent(
                import_job_id=job.id,
                document_id=job.document_id,
                level="warning",
                event_type="interrupted_import_requeued",
                message="Import job was requeued because the worker restarted before it completed.",
                payload={
                    "previous_step": job.current_step,
                    "previous_locked_at": previous_locked_at.isoformat() if previous_locked_at else None,
                },
            )
        )
        job.status = "queued"
        job.locked_at = None
        if job.document and job.document.processing_status == "running":
            job.document.processing_status = "queued"
        if job.batch:
            refresh_import_batch_progress(db, job.batch)

    concordance_jobs = db.query(ConcordanceJob).filter(ConcordanceJob.status == "running").all()
    touched_runs = {}
    for job in concordance_jobs:
        job.status = "queued"
        job.locked_at = None
        if job.run:
            touched_runs[job.run.id] = job.run
    for run in touched_runs.values():
        refresh_concordance_run_progress(db, run)

    db.flush()
    return len(import_jobs), len(concordance_jobs)


def claim_next_import_job():
    settings = get_settings()
    with session_scope() as db:
        return claim_import_job(db, settings.worker_stale_job_seconds)


def claim_next_concordance_job():
    settings = get_settings()
    with session_scope() as db:
        return claim_concordance_job(db, settings.worker_stale_job_seconds)


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
        recover_interrupted_jobs_on_start(db)
    import_processor = DocumentProcessor()
    concordance_processor = ConcordanceProcessor()
    settings = get_settings()
    while running:
        worked = process_once(import_processor, concordance_processor)
        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
