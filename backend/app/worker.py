from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import timedelta

from sqlalchemy import and_, asc, or_, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine, init_db, is_postgres, session_scope
from app.models import ConcordanceJob, DocumentAccessorySummary, ImportJob, ProcessingEvent, utc_now
from app.security import ensure_admin_user
from app.services.cache import install_cache_revision_hooks
from app.services.accessory_summaries import AccessorySummaryProcessor
from app.services.concordance import ConcordanceProcessor, refresh_concordance_run_progress
from app.services.processing import DocumentProcessor, refresh_import_batch_progress
from app.services.preferences import get_import_worker_concurrency


running = True
logger = logging.getLogger(__name__)
install_cache_revision_hooks()


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


def claim_import_job(db: Session, stale_after_seconds: int, exclude_ids: set[str] | None = None) -> str | None:
    cutoff = stale_cutoff(stale_after_seconds)
    now = utc_now()
    query = (
        db.query(ImportJob)
        .filter(or_(ImportJob.status == "queued", stale_running_filter(ImportJob, cutoff)))
        .order_by(asc(ImportJob.created_at))
    )
    if exclude_ids:
        query = query.filter(ImportJob.id.notin_(exclude_ids))
    job = query.first()
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


def import_pipeline_active(db: Session) -> bool:
    return db.query(ImportJob.id).filter(ImportJob.status.in_(["queued", "running"])).first() is not None


def vacuum_database_after_import_queue() -> None:
    if not is_postgres():
        return
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("VACUUM (ANALYZE)"))
        logger.info("PostgreSQL VACUUM (ANALYZE) completed after import queue drain.")
    except Exception:
        logger.exception("PostgreSQL VACUUM (ANALYZE) failed after import queue drain.")


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


def claim_accessory_summary(db: Session, stale_after_seconds: int) -> str | None:
    cutoff = stale_cutoff(stale_after_seconds)
    summary = (
        db.query(DocumentAccessorySummary)
        .filter(or_(DocumentAccessorySummary.status == "queued", stale_running_filter(DocumentAccessorySummary, cutoff)))
        .order_by(asc(DocumentAccessorySummary.created_at))
        .first()
    )
    if not summary:
        return None

    summary.status = "running"
    summary.locked_at = utc_now()
    summary.last_error = None
    db.flush()
    return summary.id


def recover_interrupted_jobs_on_start(db: Session) -> tuple[int, int, int]:
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

    accessory_summaries = db.query(DocumentAccessorySummary).filter(DocumentAccessorySummary.status == "running").all()
    for summary in accessory_summaries:
        summary.status = "queued"
        summary.locked_at = None

    db.flush()
    return len(import_jobs), len(concordance_jobs), len(accessory_summaries)


def claim_next_import_job(exclude_ids: set[str] | None = None):
    settings = get_settings()
    with session_scope() as db:
        return claim_import_job(db, settings.worker_stale_job_seconds, exclude_ids)


def claim_next_concordance_job():
    settings = get_settings()
    with session_scope() as db:
        return claim_concordance_job(db, settings.worker_stale_job_seconds)


def claim_next_accessory_summary():
    settings = get_settings()
    with session_scope() as db:
        return claim_accessory_summary(db, settings.worker_stale_job_seconds)


def process_once(
    import_processor: DocumentProcessor,
    concordance_processor: ConcordanceProcessor,
    accessory_processor: AccessorySummaryProcessor | None = None,
) -> bool:
    accessory_processor = accessory_processor or AccessorySummaryProcessor()
    job_id = claim_next_import_job()
    if not job_id:
        concordance_job_id = claim_next_concordance_job()
        if concordance_job_id:
            with session_scope() as db:
                job = db.get(ConcordanceJob, concordance_job_id)
                if job:
                    concordance_processor.process_job(db, job)
            return True
        accessory_summary_id = claim_next_accessory_summary()
        if not accessory_summary_id:
            return False
        process_accessory_summary(accessory_summary_id, accessory_processor)
        return True
    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        if job:
            import_processor.process_job(db, job)
    return True


def process_import_job(job_id: str) -> None:
    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        if job:
            DocumentProcessor().process_job(db, job)


def process_concordance_job(job_id: str) -> None:
    with session_scope() as db:
        job = db.get(ConcordanceJob, job_id)
        if job:
            ConcordanceProcessor().process_job(db, job)


def process_accessory_summary(summary_id: str, processor: AccessorySummaryProcessor | None = None) -> None:
    with session_scope() as db:
        summary = db.get(DocumentAccessorySummary, summary_id)
        if summary:
            (processor or AccessorySummaryProcessor()).process_summary(db, summary)


def configured_import_concurrency() -> int:
    with session_scope() as db:
        return get_import_worker_concurrency(db)


def run_import_thread(job_id: str) -> None:
    try:
        process_import_job(job_id)
    except Exception:
        logger.exception("Import worker thread crashed while processing job %s", job_id)


def collect_finished_imports(inflight_imports: dict[threading.Thread, str]) -> bool:
    finished = [thread for thread in inflight_imports if not thread.is_alive()]
    for thread in finished:
        inflight_imports.pop(thread)
    return bool(finished)


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    init_db()
    with session_scope() as db:
        ensure_admin_user(db)
        recover_interrupted_jobs_on_start(db)
    settings = get_settings()
    inflight_imports: dict[threading.Thread, str] = {}
    processed_import_queue_since_vacuum = False
    while running:
        finished_imports = collect_finished_imports(inflight_imports)
        worked = finished_imports
        if finished_imports:
            processed_import_queue_since_vacuum = True
        import_concurrency = configured_import_concurrency()
        active_import_ids = set(inflight_imports.values())

        while running and len(inflight_imports) < import_concurrency:
            job_id = claim_next_import_job(active_import_ids)
            if not job_id:
                break
            thread = threading.Thread(
                target=run_import_thread,
                args=(job_id,),
                name=f"medusa-import-{job_id[:8]}",
                daemon=True,
            )
            thread.start()
            inflight_imports[thread] = job_id
            active_import_ids.add(job_id)
            processed_import_queue_since_vacuum = True
            worked = True

        if processed_import_queue_since_vacuum and not inflight_imports:
            with session_scope() as db:
                should_vacuum = not import_pipeline_active(db)
            if should_vacuum:
                vacuum_database_after_import_queue()
                processed_import_queue_since_vacuum = False
                worked = True

        if not inflight_imports:
            concordance_job_id = claim_next_concordance_job()
            if concordance_job_id:
                process_concordance_job(concordance_job_id)
                worked = True
            else:
                accessory_summary_id = claim_next_accessory_summary()
                if accessory_summary_id:
                    process_accessory_summary(accessory_summary_id)
                    worked = True

        if not worked:
            time.sleep(settings.worker_poll_seconds)

    if inflight_imports:
        logger.info(
            "Worker shutdown requested with %s import job(s) in flight. They will be recovered on next startup if interrupted.",
            len(inflight_imports),
        )


if __name__ == "__main__":
    main()
