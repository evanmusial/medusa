from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine, is_postgres, run_migrations, session_scope
from app.models import BackupRun, utc_now
from app.services.google_credentials import load_service_account_credentials
from app.services.preferences import get_gcs_bucket, get_google_project_id, get_google_service_account_path


ACTIVE_BACKUP_STATUSES = {"queued", "running"}
BACKUP_FOLDER = "backups"
BACKUP_SCHEMA_VERSION = 1
RESTORE_STATE_FILE = "latest-restore-state.json"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
BACKUP_RUN_SNAPSHOT_FIELDS = (
    "id",
    "kind",
    "reason",
    "status",
    "phase",
    "progress",
    "status_detail",
    "hostname",
    "filename",
    "object_key",
    "gcs_uri",
    "size_bytes",
    "sha256",
    "source_kind",
    "source_filename",
    "source_uri",
    "source_local_path",
    "source_sha256",
    "safety_backup_id",
    "backup_metadata",
    "last_error",
    "started_at",
    "completed_at",
    "created_at",
)


def short_hostname(value: str | None = None) -> str:
    raw = (value or socket.gethostname() or "local").split(".", 1)[0].strip().lower()
    sanitized = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    return (sanitized or "local")[:32]


def backup_timestamp(value: datetime | None = None) -> str:
    now = value or datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S")


def backup_basename(value: datetime | None = None, hostname: str | None = None) -> str:
    return f"medusa-postgres-{backup_timestamp(value)}-{short_hostname(hostname)}"


def backup_object_prefix(gcs_prefix: str | None = None) -> str:
    prefix = (gcs_prefix if gcs_prefix is not None else get_settings().gcs_prefix).strip("/")
    return "/".join(part for part in (prefix, BACKUP_FOLDER) if part)


def backup_storage_uri(bucket_name: str, object_key: str) -> str:
    return f"gs://{bucket_name}/{object_key}"


def ensure_backup_tools_available() -> None:
    missing = [tool for tool in ("pg_dump", "pg_restore", "zstd") if not shutil.which(tool)]
    if missing:
        raise RuntimeError(f"Missing required backup tools: {', '.join(missing)}.")


def create_database_backup_run(
    db: Session,
    *,
    reason: str = "manual",
    label: str | None = None,
    allow_active: bool = False,
) -> BackupRun:
    if not is_postgres():
        raise ValueError("Full database backups require PostgreSQL.")
    if not allow_active:
        _ensure_no_active_backup_or_restore(db)
    name = backup_basename()
    run = BackupRun(
        kind="backup",
        reason=reason,
        status="queued",
        phase="initializing",
        progress=0,
        status_detail=label or "Preparing database backup.",
        hostname=short_hostname(),
        filename=f"{name}.dump.zst",
        backup_metadata={},
    )
    db.add(run)
    db.flush()
    return run


def create_restore_run(
    db: Session,
    *,
    source_kind: str,
    source_filename: str | None = None,
    source_uri: str | None = None,
    source_local_path: str | None = None,
    source_sha256: str | None = None,
) -> BackupRun:
    if not is_postgres():
        raise ValueError("Database restore requires PostgreSQL.")
    _ensure_no_active_backup_or_restore(db)
    run = BackupRun(
        kind="restore",
        reason="manual",
        status="queued",
        phase="initializing",
        progress=0,
        status_detail="Preparing restore request.",
        hostname=short_hostname(),
        source_kind=source_kind,
        source_filename=source_filename,
        source_uri=source_uri,
        source_local_path=source_local_path,
        source_sha256=source_sha256,
        backup_metadata={},
    )
    db.add(run)
    db.flush()
    return run


def launch_database_backup(run_id: str) -> None:
    thread = threading.Thread(target=_execute_backup_run, args=(run_id,), daemon=True)
    thread.start()


def launch_database_restore(run_id: str) -> None:
    thread = threading.Thread(target=_execute_restore_run, args=(run_id,), daemon=True)
    thread.start()


def save_restore_upload(content: bytes, filename: str | None) -> dict[str, Any]:
    if not content:
        raise ValueError("Upload a PostgreSQL dump file.")
    settings = get_settings()
    upload_dir = settings.data_dir / BACKUP_FOLDER / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename or "uploaded-dump").strip("-") or "uploaded-dump"
    stored_name = f"{backup_timestamp()}-{short_hostname()}-{safe_name}"
    path = upload_dir / stored_name
    path.write_bytes(content)
    return {
        "filename": filename or safe_name,
        "local_path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def list_backup_runs(db: Session, limit: int = 50) -> list[BackupRun]:
    return db.query(BackupRun).order_by(BackupRun.created_at.desc()).limit(limit).all()


def estimate_backup_size(db: Session) -> dict[str, Any]:
    database_size_bytes = current_database_size_bytes(db)
    latest_backup = (
        db.query(BackupRun)
        .filter(BackupRun.kind == "backup", BackupRun.status == "complete", BackupRun.size_bytes.is_not(None))
        .order_by(BackupRun.completed_at.desc(), BackupRun.created_at.desc())
        .first()
    )
    latest_backup_size = latest_backup.size_bytes if latest_backup else None
    latest_backup_database_size = None
    if latest_backup and isinstance(latest_backup.backup_metadata, dict):
        metadata_database_size = latest_backup.backup_metadata.get("database_size_bytes")
        latest_backup_database_size = metadata_database_size if isinstance(metadata_database_size, int) else None

    basis = "unavailable"
    estimated_size_bytes = None
    if database_size_bytes and latest_backup_size and latest_backup_database_size:
        ratio = latest_backup_size / max(1, latest_backup_database_size)
        estimated_size_bytes = max(1, round(database_size_bytes * ratio))
        basis = "latest_backup_ratio"
    elif latest_backup_size:
        estimated_size_bytes = latest_backup_size
        basis = "latest_backup"
    elif database_size_bytes:
        estimated_size_bytes = database_size_bytes
        basis = "database_size_upper_bound"

    return {
        "database_size_bytes": database_size_bytes,
        "estimated_size_bytes": estimated_size_bytes,
        "latest_backup_size_bytes": latest_backup_size,
        "latest_backup_completed_at": latest_backup.completed_at.isoformat() if latest_backup and latest_backup.completed_at else None,
        "basis": basis,
    }


def current_database_size_bytes(db: Session) -> int | None:
    if not is_postgres():
        return None
    try:
        value = db.execute(text("SELECT pg_database_size(current_database())")).scalar_one_or_none()
    except Exception:
        return None
    return int(value) if isinstance(value, int) and value > 0 else None


def list_gcs_backup_artifacts(db: Session, limit: int | None = None) -> list[dict[str, Any]]:
    bucket, bucket_name, prefix = _gcs_bucket_from_db(db)
    artifacts: list[dict[str, Any]] = []
    manifest_by_dump_key: dict[str, dict[str, Any]] = {}
    for blob in bucket.list_blobs(prefix=f"{prefix}/"):
        if blob.name.endswith(".manifest.json"):
            try:
                manifest = json.loads(blob.download_as_bytes().decode("utf-8"))
            except Exception:
                continue
            dump_key = manifest.get("object_key")
            if isinstance(dump_key, str):
                manifest_by_dump_key[dump_key] = manifest

    for blob in bucket.list_blobs(prefix=f"{prefix}/"):
        if not blob.name.endswith(".dump.zst"):
            continue
        metadata = blob.metadata or {}
        manifest = manifest_by_dump_key.get(blob.name, {})
        created_at = manifest.get("completed_at") or manifest.get("created_at") or (blob.updated.isoformat() if blob.updated else None)
        artifacts.append(
            {
                "id": manifest.get("backup_id") or metadata.get("backup_id") or blob.name,
                "filename": blob.name.rsplit("/", 1)[-1],
                "object_key": blob.name,
                "gcs_uri": backup_storage_uri(bucket_name, blob.name),
                "size_bytes": int(blob.size or manifest.get("size_bytes") or 0),
                "sha256": manifest.get("sha256") or metadata.get("sha256"),
                "created_at": created_at,
                "completed_at": manifest.get("completed_at"),
                "hostname": manifest.get("hostname") or metadata.get("hostname"),
                "verified": bool(manifest.get("verified_at") or metadata.get("verified_at")),
                "manifest": manifest,
            }
        )
    sorted_artifacts = sorted(artifacts, key=lambda item: item.get("created_at") or "", reverse=True)
    return sorted_artifacts if limit is None else sorted_artifacts[:limit]


def _execute_backup_run(run_id: str) -> None:
    work_dir = get_settings().data_dir / BACKUP_FOLDER / "work" / run_id
    raw_path: Path | None = None
    compressed_path: Path | None = None
    try:
        ensure_backup_tools_available()
        with session_scope() as db:
            run = db.get(BackupRun, run_id)
            if not run:
                return
            bucket, bucket_name, prefix = _gcs_bucket_from_db(db)
            basename = Path(run.filename or f"{backup_basename()}.dump.zst").name.removesuffix(".dump.zst")
            object_key = f"{prefix}/{basename}.dump.zst"
            manifest_key = f"{prefix}/{basename}.manifest.json"
            run.status = "running"
            run.phase = "initializing"
            run.progress = 4
            run.started_at = utc_now()
            run.status_detail = "Initializing database backup."
            run.object_key = object_key
            run.gcs_uri = backup_storage_uri(bucket_name, object_key)
            run.backup_metadata = {
                "manifest_key": manifest_key,
                "bucket": bucket_name,
                "database_size_bytes": current_database_size_bytes(db),
            }

        work_dir.mkdir(parents=True, exist_ok=True)
        raw_path = work_dir / f"{basename}.dump"
        compressed_path = work_dir / f"{basename}.dump.zst"

        _update_run(run_id, phase="dumping", progress=18, status_detail="Dumping PostgreSQL with pg_dump.")
        _run_pg_dump(raw_path)

        _update_run(run_id, phase="compressing", progress=48, status_detail="Compressing dump with zstd.")
        _run_command(["zstd", "-T0", "-19", "-f", str(raw_path), "-o", str(compressed_path)])
        size_bytes = compressed_path.stat().st_size
        sha256 = sha256_file(compressed_path)

        with session_scope() as db:
            run = db.get(BackupRun, run_id)
            if not run:
                return
            bucket, bucket_name, prefix = _gcs_bucket_from_db(db)
            object_key = run.object_key or f"{prefix}/{compressed_path.name}"
            manifest_key = (run.backup_metadata or {}).get("manifest_key") or object_key.removesuffix(".dump.zst") + ".manifest.json"
            run.size_bytes = size_bytes
            run.sha256 = sha256
            run.status_detail = "Uploading compressed dump to GCS."

        _update_run(run_id, phase="uploading", progress=72, status_detail="Uploading compressed dump to GCS.")
        blob = bucket.blob(object_key)
        blob.metadata = {
            "backup_id": run_id,
            "hostname": short_hostname(),
            "sha256": sha256,
            "compression": "zstd",
            "dump_format": "pg_dump_custom",
        }
        blob.upload_from_filename(str(compressed_path), content_type="application/zstd")

        _update_run(run_id, phase="verifying", progress=88, status_detail="Verifying uploaded checksum.")
        verified_sha256 = _sha256_gcs_blob(blob)
        if verified_sha256 != sha256:
            raise RuntimeError("Uploaded GCS object checksum did not match the local backup checksum.")

        database_size_bytes = None
        with session_scope() as db:
            database_size_bytes = current_database_size_bytes(db)
        manifest = _backup_manifest(
            run_id,
            object_key,
            backup_storage_uri(bucket_name, object_key),
            size_bytes,
            sha256,
            database_size_bytes=database_size_bytes,
        )
        manifest["verified_at"] = datetime.now(timezone.utc).isoformat()
        manifest["verification_sha256"] = verified_sha256
        manifest_blob = bucket.blob(manifest_key)
        manifest_blob.upload_from_string(
            json.dumps(manifest, indent=2, sort_keys=True),
            content_type="application/json",
        )

        _update_run(
            run_id,
            status="complete",
            phase="complete",
            progress=100,
            status_detail="Backup uploaded and verified.",
            completed_at=utc_now(),
            backup_metadata=manifest,
        )
    except Exception as exc:
        _update_run(
            run_id,
            status="failed",
            phase="failed",
            progress=100,
            status_detail="Backup failed.",
            last_error=str(exc),
            completed_at=utc_now(),
        )
    finally:
        if raw_path and raw_path.exists():
            raw_path.unlink(missing_ok=True)
        if compressed_path and compressed_path.exists():
            compressed_path.unlink(missing_ok=True)


def _execute_restore_run(run_id: str) -> None:
    work_dir = get_settings().data_dir / BACKUP_FOLDER / "restore" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_path: Path | None = None
    downloaded_path: Path | None = None
    restore_started_at: datetime | None = None
    safety_snapshot: dict[str, Any] | None = None
    safety_id: str | None = None
    source_kind: str | None = None
    source_filename: str | None = None
    source_uri: str | None = None
    source_local_path: str | None = None
    source_sha256: str | None = None
    source_size_bytes: int | None = None
    try:
        ensure_backup_tools_available()
        restore_started_at = utc_now()
        _write_restore_state(run_id, "running", "safety_backup", "Creating pre-restore safety backup.")
        _update_run(
            run_id,
            status="running",
            phase="safety_backup",
            progress=6,
            started_at=restore_started_at,
            status_detail="Creating and verifying a pre-restore safety backup.",
        )
        with session_scope() as db:
            safety = create_database_backup_run(
                db,
                reason="pre_restore",
                label="Pre-restore safety backup.",
                allow_active=True,
            )
            restore_run = db.get(BackupRun, run_id)
            if restore_run:
                restore_run.safety_backup_id = safety.id
            safety_id = safety.id

        _execute_backup_run(safety_id)
        with session_scope() as db:
            safety = db.get(BackupRun, safety_id)
            if not safety or safety.status != "complete" or not safety.sha256 or not safety.gcs_uri:
                raise RuntimeError("Pre-restore safety backup did not complete and verify.")
            safety_snapshot = _backup_run_snapshot(safety)
            restore_run = db.get(BackupRun, run_id)
            source_kind = restore_run.source_kind if restore_run else None
            source_filename = restore_run.source_filename if restore_run else None
            source_uri = restore_run.source_uri if restore_run else None
            source_local_path = restore_run.source_local_path if restore_run else None
            source_sha256 = restore_run.source_sha256 if restore_run else None

        _update_run(run_id, phase="fetching", progress=34, status_detail="Fetching restore source.")
        _write_restore_state(run_id, "running", "fetching", "Fetching restore source.")
        if source_kind == "gcs":
            if not source_uri:
                raise RuntimeError("Restore source is missing a GCS URI.")
            downloaded_path = work_dir / Path(urlparse(source_uri).path).name
            expected_sha256 = _download_gcs_backup(source_uri, downloaded_path)
            actual_sha256 = sha256_file(downloaded_path)
            if expected_sha256 and expected_sha256 != actual_sha256:
                raise RuntimeError("Downloaded GCS backup checksum did not match its manifest.")
            source_sha256 = actual_sha256
            source_size_bytes = downloaded_path.stat().st_size
            source_path = downloaded_path
        else:
            if not source_local_path:
                raise RuntimeError("Restore source is missing an uploaded dump file.")
            source_path = Path(source_local_path)
            if not source_path.exists():
                raise RuntimeError("Uploaded restore file is no longer available.")
            actual_sha256 = sha256_file(source_path)
            if source_sha256 and actual_sha256 != source_sha256:
                raise RuntimeError("Uploaded restore file changed before restore could start.")
            source_sha256 = actual_sha256
            source_size_bytes = source_path.stat().st_size

        _update_run(run_id, phase="checking", progress=48, status_detail="Checking and decompressing restore dump.")
        _write_restore_state(run_id, "running", "checking", "Checking and decompressing restore dump.")
        raw_path = _prepare_restore_dump(source_path, work_dir)
        _run_command(["pg_restore", "--list", str(raw_path)])

        _update_run(run_id, phase="restoring", progress=68, status_detail="Applying PostgreSQL restore.")
        _write_restore_state(run_id, "running", "restoring", "Applying PostgreSQL restore.")
        engine.dispose()
        _run_pg_restore(raw_path)

        _update_run(run_id, phase="migrating", progress=92, status_detail="Running migrations after restore.")
        _write_restore_state(run_id, "running", "migrating", "Running migrations after restore.")
        engine.dispose()
        run_migrations()
        engine.dispose()

        completed_at = utc_now()
        _finalize_restored_database_state(
            run_id,
            source_kind=source_kind,
            source_filename=source_filename,
            source_uri=source_uri,
            source_sha256=source_sha256,
            source_size_bytes=source_size_bytes,
            safety_backup_id=safety_id,
            safety_snapshot=safety_snapshot,
            started_at=restore_started_at,
            completed_at=completed_at,
        )
        _write_restore_state(run_id, "complete", "complete", "Restore applied.")
    except Exception as exc:
        _update_run(
            run_id,
            status="failed",
            phase="failed",
            progress=100,
            status_detail="Restore failed.",
            last_error=str(exc),
            completed_at=utc_now(),
        )
        _write_restore_state(run_id, "failed", "failed", str(exc))
    finally:
        if downloaded_path and downloaded_path.exists():
            downloaded_path.unlink(missing_ok=True)
        if raw_path and raw_path.exists() and downloaded_path and raw_path != downloaded_path:
            raw_path.unlink(missing_ok=True)


def _backup_run_snapshot(run: BackupRun) -> dict[str, Any]:
    snapshot = {field: getattr(run, field) for field in BACKUP_RUN_SNAPSHOT_FIELDS}
    snapshot["backup_metadata"] = dict(run.backup_metadata or {})
    return snapshot


def _upsert_backup_run_snapshot(db: Session, snapshot: dict[str, Any]) -> BackupRun:
    run_id = snapshot.get("id")
    run = db.get(BackupRun, run_id) if run_id else None
    if not run:
        run = BackupRun(id=run_id, backup_metadata={})
        db.add(run)
    for field in BACKUP_RUN_SNAPSHOT_FIELDS:
        if field in snapshot:
            setattr(run, field, snapshot[field])
    return run


def _finalize_restored_database_state(
    run_id: str,
    *,
    source_kind: str | None,
    source_filename: str | None,
    source_uri: str | None,
    source_sha256: str | None,
    source_size_bytes: int | None,
    safety_backup_id: str | None,
    safety_snapshot: dict[str, Any] | None,
    started_at: datetime | None,
    completed_at: datetime,
) -> None:
    with session_scope() as db:
        if safety_snapshot:
            _upsert_backup_run_snapshot(db, safety_snapshot)

        completed_source_ids: set[str] = set()
        if source_uri:
            restored_source_runs = (
                db.query(BackupRun)
                .filter(
                    BackupRun.kind == "backup",
                    BackupRun.status.in_(ACTIVE_BACKUP_STATUSES),
                    BackupRun.gcs_uri == source_uri,
                )
                .all()
            )
            for run in restored_source_runs:
                run.status = "complete"
                run.phase = "complete"
                run.progress = 100
                run.status_detail = "Backup uploaded and verified before restore."
                run.completed_at = run.completed_at or completed_at
                if source_sha256 and not run.sha256:
                    run.sha256 = source_sha256
                if source_size_bytes and not run.size_bytes:
                    run.size_bytes = source_size_bytes
                completed_source_ids.add(run.id)

        stale_runs = (
            db.query(BackupRun)
            .filter(BackupRun.status.in_(ACTIVE_BACKUP_STATUSES), BackupRun.id != run_id)
            .all()
        )
        for run in stale_runs:
            if run.id in completed_source_ids:
                continue
            run.status = "failed"
            run.phase = "restored_snapshot"
            run.progress = 100
            run.status_detail = "Run was active in the restored snapshot and is not running on this host."
            run.last_error = run.last_error or "Marked inactive after database restore."
            run.completed_at = run.completed_at or completed_at

        restore_run = db.get(BackupRun, run_id)
        if not restore_run:
            restore_run = BackupRun(id=run_id, kind="restore", reason="manual", backup_metadata={})
            db.add(restore_run)
        restore_run.kind = "restore"
        restore_run.reason = "manual"
        restore_run.status = "complete"
        restore_run.phase = "complete"
        restore_run.progress = 100
        restore_run.status_detail = "Restore applied. Sign in again if your session changed."
        restore_run.hostname = short_hostname()
        restore_run.source_kind = source_kind
        restore_run.source_filename = source_filename
        restore_run.source_uri = source_uri
        restore_run.source_sha256 = source_sha256
        restore_run.safety_backup_id = safety_backup_id
        restore_run.size_bytes = source_size_bytes
        restore_run.started_at = started_at or completed_at
        restore_run.completed_at = completed_at
        restore_run.created_at = started_at or completed_at
        restore_run.backup_metadata = {
            "post_restore_reconstructed": True,
            "source_size_bytes": source_size_bytes,
        }


def _ensure_no_active_backup_or_restore(db: Session) -> None:
    active = db.query(BackupRun).filter(BackupRun.status.in_(ACTIVE_BACKUP_STATUSES)).first()
    if active:
        raise ValueError("A backup or restore is already running.")


def _backup_manifest(
    run_id: str,
    object_key: str,
    gcs_uri: str,
    size_bytes: int,
    sha256: str,
    *,
    database_size_bytes: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    database = _database_identity()
    return {
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "backup_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "hostname": short_hostname(),
        "filename": Path(object_key).name,
        "object_key": object_key,
        "gcs_uri": gcs_uri,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "database_size_bytes": database_size_bytes,
        "compression": "zstd",
        "dump_format": "pg_dump_custom",
        "database": database,
        "non_secret_runtime_settings": {
            "app_name": settings.app_name,
            "environment": settings.environment,
            "public_port": settings.public_port,
            "gcs_prefix": settings.gcs_prefix,
            "google_cloud_project": settings.google_cloud_project,
            "google_cloud_location": settings.google_cloud_location,
            "openai_send_pdf_file": settings.openai_send_pdf_file,
            "openai_pdf_file_max_mb": settings.openai_pdf_file_max_mb,
            "openai_normalize_page_text": settings.openai_normalize_page_text,
            "openai_page_normalization_mode": settings.openai_page_normalization_mode,
            "openai_page_normalization_auto_max_pages": settings.openai_page_normalization_auto_max_pages,
            "openai_text_normalization_page_max_chars": settings.openai_text_normalization_page_max_chars,
            "openai_request_timeout_seconds": settings.openai_request_timeout_seconds,
            "openai_combine_document_intelligence": settings.openai_combine_document_intelligence,
            "openai_prompt_cache_retention": settings.openai_prompt_cache_retention,
            "openai_page_normalization_timeout_seconds": settings.openai_page_normalization_timeout_seconds,
            "openai_embedding_timeout_seconds": settings.openai_embedding_timeout_seconds,
            "raw_text_extraction_timeout_seconds": settings.raw_text_extraction_timeout_seconds,
            "recommendations_enable_openalex": settings.recommendations_enable_openalex,
            "recommendations_enable_semantic_scholar": settings.recommendations_enable_semantic_scholar,
            "recommendations_enable_crossref": settings.recommendations_enable_crossref,
            "recommendations_max_results_per_source": settings.recommendations_max_results_per_source,
            "recommendations_request_timeout_seconds": settings.recommendations_request_timeout_seconds,
            "recommendation_download_timeout_seconds": settings.recommendation_download_timeout_seconds,
            "recommendation_download_max_mb": settings.recommendation_download_max_mb,
            "enable_google_vision": settings.enable_google_vision,
            "worker_stale_job_seconds": settings.worker_stale_job_seconds,
        },
        "safety": {
            "api_keys_included": False,
            "service_account_credentials_included": False,
            "plaintext_passwords_included": False,
            "password_hashes_included": True,
            "session_tokens_included": True,
            "two_factor_secrets_included": True,
            "database_dump_includes_auth_tables": True,
        },
    }


def _database_identity() -> dict[str, Any]:
    url = make_url(get_settings().database_url)
    return {
        "driver": url.drivername,
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "username": url.username,
    }


def _gcs_bucket_from_db(db: Session):
    bucket_name = get_gcs_bucket(db)
    if not bucket_name:
        raise ValueError("Save a GCS bucket in Settings before running database backups.")
    credentials, project = _gcs_credentials_from_db(db)
    from google.cloud import storage

    client = storage.Client(project=project, credentials=credentials)
    bucket = client.bucket(bucket_name)
    return bucket, bucket_name, backup_object_prefix(get_settings().gcs_prefix)


def _gcs_credentials_from_db(db: Session):
    credentials_path = get_google_service_account_path(db)
    if not credentials_path:
        raise ValueError("Configure a Google service account JSON before using GCS backups.")
    credentials = load_service_account_credentials(credentials_path)
    project = getattr(credentials, "project_id", None) or get_google_project_id(db)
    return credentials, project


def _download_gcs_backup(gcs_uri: str, destination: Path) -> str | None:
    parsed = urlparse(gcs_uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path:
        raise RuntimeError("Restore source must be a gs:// URI.")
    from google.cloud import storage

    with session_scope() as db:
        credentials, project = _gcs_credentials_from_db(db)
    client = storage.Client(project=project, credentials=credentials)
    bucket = client.bucket(parsed.netloc)
    object_key = parsed.path.lstrip("/")
    blob = bucket.blob(object_key)
    manifest_blob = bucket.blob(object_key.removesuffix(".dump.zst") + ".manifest.json")
    expected_sha256 = None
    if manifest_blob.exists():
        try:
            manifest = json.loads(manifest_blob.download_as_bytes().decode("utf-8"))
            expected_sha256 = manifest.get("sha256")
        except Exception:
            expected_sha256 = None
    if not expected_sha256:
        blob.reload()
        expected_sha256 = (blob.metadata or {}).get("sha256")
    if not expected_sha256:
        raise RuntimeError("Selected GCS backup is missing checksum metadata.")
    blob.download_to_filename(str(destination))
    return expected_sha256


def _prepare_restore_dump(source_path: Path, work_dir: Path) -> Path:
    with source_path.open("rb") as handle:
        magic = handle.read(4)
    if magic == ZSTD_MAGIC or source_path.name.endswith(".zst"):
        _run_command(["zstd", "-t", str(source_path)])
        raw_path = work_dir / source_path.name.removesuffix(".zst")
        _run_command(["zstd", "-d", "-f", str(source_path), "-o", str(raw_path)])
        return raw_path
    return source_path


def _run_pg_dump(raw_path: Path) -> None:
    env, database = _postgres_env()
    _run_command(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(raw_path), database], env=env)


def _run_pg_restore(raw_path: Path) -> None:
    env, database = _postgres_env()
    _run_command(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            database,
            str(raw_path),
        ],
        env=env,
    )


def _postgres_env() -> tuple[dict[str, str], str]:
    url = make_url(get_settings().database_url)
    env: dict[str, str] = {}
    if url.host:
        env["PGHOST"] = url.host
    if url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    database = url.database or "medusa"
    return env, database


def _run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(command, capture_output=True, env=merged_env, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"Command failed: {command[0]}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_gcs_blob(blob: Any) -> str:
    digest = hashlib.sha256()
    with blob.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_run(run_id: str, **fields: Any) -> None:
    try:
        with session_scope() as db:
            run = db.get(BackupRun, run_id)
            if not run:
                return
            for key, value in fields.items():
                setattr(run, key, value)
            run.updated_at = utc_now()
    except SQLAlchemyError:
        return


def _write_restore_state(run_id: str, status: str, phase: str, detail: str) -> None:
    path = get_settings().data_dir / BACKUP_FOLDER / RESTORE_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "status": status,
        "phase": phase,
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
