from __future__ import annotations

import json
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    BackupRun,
    ConcordanceJob,
    DocumentAccessorySummary,
    ImportJob,
    SessionToken,
    utc_now,
)
from app.services.backups import ACTIVE_BACKUP_STATUSES


DEFAULT_IDLE_GRACE_SECONDS = 300
ACTIVE_WORK_STATUSES = {"queued", "running"}
DATABASE_MAINTENANCE_MARKER = "database-maintenance-status.json"


def _deploy_dir() -> Path:
    path = get_settings().data_dir / "deploy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_maintenance_marker_path() -> Path:
    return _deploy_dir() / DATABASE_MAINTENANCE_MARKER


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp_path.replace(path)


def write_database_maintenance_marker(payload: dict[str, Any]) -> None:
    _atomic_write_json(database_maintenance_marker_path(), payload)


def mark_database_maintenance_active(operation: str, detail: str | None = None) -> None:
    write_database_maintenance_marker(
        {
            "active": True,
            "operation": operation,
            "status": "running",
            "detail": detail or "Database maintenance is running.",
            "started_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
        }
    )


def mark_database_maintenance_finished(operation: str, *, status: str, detail: str, error: str | None = None) -> None:
    write_database_maintenance_marker(
        {
            "active": False,
            "operation": operation,
            "status": status,
            "detail": detail,
            "error": error,
            "completed_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
        }
    )


def read_database_maintenance_marker() -> dict[str, Any] | None:
    try:
        payload = json.loads(database_maintenance_marker_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _coalesce_session_seen_at():
    return func.coalesce(SessionToken.last_seen_at, SessionToken.updated_at, SessionToken.created_at)


def active_session_count(db: Session, *, idle_grace_seconds: int = DEFAULT_IDLE_GRACE_SECONDS) -> int:
    cutoff = utc_now() - timedelta(seconds=max(1, idle_grace_seconds))
    return (
        db.query(SessionToken)
        .filter(SessionToken.revoked_at.is_(None))
        .filter(SessionToken.expires_at > utc_now())
        .filter(_coalesce_session_seen_at() >= cutoff)
        .count()
    )


def count_active_import_jobs(db: Session) -> int:
    return db.query(ImportJob).filter(ImportJob.status.in_(ACTIVE_WORK_STATUSES)).count()


def count_active_concordance_jobs(db: Session) -> int:
    return db.query(ConcordanceJob).filter(ConcordanceJob.status.in_(ACTIVE_WORK_STATUSES)).count()


def count_active_accessory_summary_jobs(db: Session) -> int:
    return db.query(DocumentAccessorySummary).filter(DocumentAccessorySummary.status.in_(ACTIVE_WORK_STATUSES)).count()


def count_active_backup_runs(db: Session) -> int:
    return db.query(BackupRun).filter(BackupRun.status.in_(ACTIVE_BACKUP_STATUSES)).count()


def database_maintenance_is_active() -> bool:
    marker = read_database_maintenance_marker() or {}
    return bool(marker.get("active"))


def maintenance_readiness(db: Session, *, idle_grace_seconds: int = DEFAULT_IDLE_GRACE_SECONDS) -> dict[str, Any]:
    sessions = active_session_count(db, idle_grace_seconds=idle_grace_seconds)
    import_jobs = count_active_import_jobs(db)
    concordance_jobs = count_active_concordance_jobs(db)
    accessory_summary_jobs = count_active_accessory_summary_jobs(db)
    backup_runs = count_active_backup_runs(db)
    marker = read_database_maintenance_marker() or {}
    database_maintenance_active = bool(marker.get("active"))

    blockers: list[str] = []
    if sessions:
        blockers.append(f"{sessions} active user session{'s' if sessions != 1 else ''}")
    if import_jobs:
        blockers.append(f"{import_jobs} active import job{'s' if import_jobs != 1 else ''}")
    if concordance_jobs:
        blockers.append(f"{concordance_jobs} active Concordance job{'s' if concordance_jobs != 1 else ''}")
    if accessory_summary_jobs:
        blockers.append(f"{accessory_summary_jobs} active Accessory Summary job{'s' if accessory_summary_jobs != 1 else ''}")
    if backup_runs:
        blockers.append(f"{backup_runs} active backup/restore run{'s' if backup_runs != 1 else ''}")
    if database_maintenance_active:
        blockers.append(str(marker.get("detail") or marker.get("operation") or "database maintenance is active"))

    return {
        "checked_at": utc_now().isoformat(),
        "idle_grace_seconds": max(1, idle_grace_seconds),
        "idle": not blockers,
        "active_session_count": sessions,
        "active_import_jobs": import_jobs,
        "active_concordance_jobs": concordance_jobs,
        "active_accessory_summary_jobs": accessory_summary_jobs,
        "active_backup_runs": backup_runs,
        "database_maintenance_active": database_maintenance_active,
        "database_maintenance": marker,
        "blockers": blockers,
    }


def override_active_sessions(readiness: dict[str, Any]) -> dict[str, Any]:
    blockers = [
        blocker
        for blocker in readiness.get("blockers", [])
        if "active user session" not in str(blocker)
    ]
    next_readiness = dict(readiness)
    next_readiness["blockers"] = blockers
    next_readiness["idle"] = not blockers
    next_readiness["active_sessions_overridden"] = True
    return next_readiness
