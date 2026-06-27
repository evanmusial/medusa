from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import and_, asc, exists, inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import is_postgres
from app.models import (
    ConcordanceJob,
    ConcordanceRun,
    Document,
    DocumentCapability,
    DocumentCompositionRecord,
    DocumentPage,
    ImportBatch,
    ImportJob,
    ProcessingEvent,
    SlipstreamClient,
    SlipstreamEnrollment,
    SlipstreamLease,
    utc_now,
)
from app.services.concordance import CURRENT_CAPABILITIES, refresh_concordance_run_progress
from app.services.document_cache import ensure_document_pdf_bytes
from app.services.extraction import sanitize_extracted_text
from app.services.preferences import get_analysis_models
from app.services.processing import import_processing_preset_for_job, refresh_import_batch_progress


SLIPSTREAM_JOB_IMPORT = "import"
SLIPSTREAM_JOB_CONCORDANCE = "concordance"
ACTIVE_LEASE_STATUS = "active"
TERMINAL_LEASE_STATUSES = {"complete", "failed", "expired", "canceled"}


class SlipstreamError(ValueError):
    pass


class SlipstreamAuthError(SlipstreamError):
    pass


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def canonical_signature_message(method: str, path: str, timestamp: str, nonce: str, body_hash: str) -> bytes:
    return "\n".join([method.upper(), path, timestamp, nonce, body_hash]).encode("utf-8")


def _decode_base64(value: str) -> bytes:
    cleaned = value.strip()
    if cleaned.startswith("ed25519:"):
        cleaned = cleaned.split(":", 1)[1]
    padding = "=" * (-len(cleaned) % 4)
    try:
        return base64.urlsafe_b64decode(cleaned + padding)
    except Exception:
        return base64.b64decode(cleaned + padding)


def _load_public_key(value: str) -> Ed25519PublicKey:
    if "BEGIN PUBLIC KEY" in value:
        loaded = serialization.load_pem_public_key(value.encode("utf-8"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise SlipstreamAuthError("Slipstream public key must be Ed25519.")
        return loaded
    raw = _decode_base64(value)
    if len(raw) != 32:
        raise SlipstreamAuthError("Slipstream public key must be a 32-byte Ed25519 key.")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_signature(
    client: SlipstreamClient,
    *,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    request_body_hash: str,
    signature: str,
    body: bytes,
) -> None:
    settings = get_settings()
    if not client or client.status != "active" or client.revoked_at is not None:
        raise SlipstreamAuthError("Slipstream client is not active.")
    try:
        timestamp_value = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (TypeError, ValueError):
        raise SlipstreamAuthError("Slipstream timestamp is invalid.") from None
    skew = abs((utc_now() - timestamp_value).total_seconds())
    if skew > max(1, settings.slipstream_signature_window_seconds):
        raise SlipstreamAuthError("Slipstream timestamp is outside the allowed window.")
    actual_body_hash = body_sha256(body)
    if not hmac.compare_digest(actual_body_hash, request_body_hash):
        raise SlipstreamAuthError("Slipstream body hash does not match.")
    metadata = dict(client.client_metadata or {})
    recent_nonces = dict(metadata.get("recent_nonces") or {})
    cutoff = utc_now() - timedelta(seconds=max(1, settings.slipstream_signature_window_seconds))
    recent_nonces = {
        key: value
        for key, value in recent_nonces.items()
        if _parse_datetime(value) and _parse_datetime(value) >= cutoff
    }
    if nonce in recent_nonces:
        raise SlipstreamAuthError("Slipstream nonce has already been used.")
    public_key = _load_public_key(client.public_key)
    message = canonical_signature_message(client_method(method), path, timestamp, nonce, request_body_hash)
    try:
        public_key.verify(_decode_base64(signature), message)
    except InvalidSignature:
        raise SlipstreamAuthError("Slipstream signature is invalid.") from None
    recent_nonces[nonce] = utc_now().isoformat()
    metadata["recent_nonces"] = recent_nonces
    client.client_metadata = metadata
    client.last_nonce = nonce
    client.last_check_in_at = utc_now()


def client_method(method: str) -> str:
    return str(method or "").upper()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_enrollment(db: Session, *, label: str | None = None, ttl_minutes: int = 60) -> tuple[SlipstreamEnrollment, str]:
    token = secrets.token_urlsafe(32)
    enrollment = SlipstreamEnrollment(
        token_hash=token_hash(token),
        label=label,
        status="pending",
        expires_at=utc_now() + timedelta(minutes=max(1, ttl_minutes)),
    )
    db.add(enrollment)
    db.flush()
    return enrollment, token


def register_client(
    db: Session,
    *,
    enrollment_token: str,
    name: str,
    public_key: str,
    version: str | None = None,
    capabilities: list[str] | None = None,
    capacity: int = 1,
    metadata: dict[str, Any] | None = None,
) -> SlipstreamClient:
    enrollment = (
        db.query(SlipstreamEnrollment)
        .filter(SlipstreamEnrollment.token_hash == token_hash(enrollment_token))
        .one_or_none()
    )
    if not enrollment or enrollment.status != "pending":
        raise SlipstreamAuthError("Slipstream enrollment token is invalid or already used.")
    enrollment_expires_at = _aware_datetime(enrollment.expires_at)
    if enrollment_expires_at and enrollment_expires_at < utc_now():
        enrollment.status = "expired"
        raise SlipstreamAuthError("Slipstream enrollment token has expired.")
    _load_public_key(public_key)
    client = SlipstreamClient(
        name=name.strip() or "Slipstream client",
        public_key=public_key.strip(),
        version=version,
        capabilities=capabilities or [SLIPSTREAM_JOB_IMPORT, SLIPSTREAM_JOB_CONCORDANCE],
        capacity=max(1, int(capacity or 1)),
        status="active",
        last_check_in_at=utc_now(),
        client_metadata=metadata or {},
    )
    db.add(client)
    db.flush()
    enrollment.status = "used"
    enrollment.used_at = utc_now()
    enrollment.client_id = client.id
    db.flush()
    return client


def active_client_leases(db: Session, client_id: str) -> int:
    return (
        db.query(SlipstreamLease)
        .filter(SlipstreamLease.client_id == client_id, SlipstreamLease.status == ACTIVE_LEASE_STATUS)
        .count()
    )


def online_cutoff() -> datetime:
    return utc_now() - timedelta(seconds=max(30, get_settings().slipstream_heartbeat_seconds * 3))


def client_is_online(client: SlipstreamClient) -> bool:
    last_check_in_at = _aware_datetime(client.last_check_in_at)
    return bool(last_check_in_at and last_check_in_at >= online_cutoff())


def _job_has_active_lease(job_type: str, job_id: str):
    return exists().where(
        and_(
            SlipstreamLease.job_type == job_type,
            SlipstreamLease.job_id == job_id,
            SlipstreamLease.status == ACTIVE_LEASE_STATUS,
        )
    )


def slipstream_tables_available(db: Session) -> bool:
    try:
        return inspect(db.connection()).has_table(SlipstreamLease.__tablename__)
    except Exception:
        return False


def _stale_job_filter(model, stale_cutoff: datetime):
    return and_(
        model.status == "running",
        or_(
            and_(model.locked_at.isnot(None), model.locked_at < stale_cutoff),
            and_(model.locked_at.is_(None), model.updated_at < stale_cutoff),
        ),
    )


def _query_import_candidates(
    db: Session,
    *,
    exclude_ids: set[str] | None = None,
    use_lease_filter: bool = True,
    stale_after_seconds: int | None = None,
):
    settings = get_settings()
    stale_cutoff = utc_now() - timedelta(seconds=max(1, stale_after_seconds or settings.worker_stale_job_seconds))
    query = (
        db.query(ImportJob)
        .filter(or_(ImportJob.status == "queued", _stale_job_filter(ImportJob, stale_cutoff)))
        .order_by(asc(ImportJob.created_at), asc(ImportJob.id))
    )
    if use_lease_filter:
        query = query.filter(~_job_has_active_lease(SLIPSTREAM_JOB_IMPORT, ImportJob.id))
    if exclude_ids:
        query = query.filter(ImportJob.id.notin_(exclude_ids))
    if is_postgres():
        query = query.with_for_update(skip_locked=True)
    return query.limit(20).all()


def _query_concordance_candidates(
    db: Session,
    *,
    use_lease_filter: bool = True,
    stale_after_seconds: int | None = None,
):
    settings = get_settings()
    stale_cutoff = utc_now() - timedelta(seconds=max(1, stale_after_seconds or settings.worker_stale_job_seconds))
    query = (
        db.query(ConcordanceJob)
        .filter(or_(ConcordanceJob.status == "queued", _stale_job_filter(ConcordanceJob, stale_cutoff)))
        .order_by(asc(ConcordanceJob.created_at), asc(ConcordanceJob.id))
    )
    if use_lease_filter:
        query = query.filter(~_job_has_active_lease(SLIPSTREAM_JOB_CONCORDANCE, ConcordanceJob.id))
    if is_postgres():
        query = query.with_for_update(skip_locked=True)
    return query.limit(20).all()


def expire_stale_leases(db: Session) -> int:
    if not slipstream_tables_available(db):
        return 0
    settings = get_settings()
    now = utc_now()
    expired = 0
    leases = (
        db.query(SlipstreamLease)
        .filter(SlipstreamLease.status == ACTIVE_LEASE_STATUS, SlipstreamLease.expires_at < now)
        .order_by(asc(SlipstreamLease.expires_at))
        .limit(100)
        .all()
    )
    local_cutoff = now - timedelta(seconds=max(1, settings.worker_stale_job_seconds))
    for lease in leases:
        if lease.worker_kind == "local":
            job = _lease_job(db, lease)
            locked_at = _aware_datetime(getattr(job, "locked_at", None))
            if job is not None and getattr(job, "status", None) == "running" and locked_at and locked_at >= local_cutoff:
                lease.heartbeat_at = locked_at
                lease.expires_at = locked_at + timedelta(seconds=max(1, settings.worker_stale_job_seconds))
                continue
        _expire_lease(db, lease)
        expired += 1
    if expired:
        db.flush()
    return expired


def _expire_lease(db: Session, lease: SlipstreamLease) -> None:
    lease.status = "expired"
    lease.completed_at = utc_now()
    lease.last_error = "Lease expired without heartbeat."
    job = _lease_job(db, lease)
    if not job:
        return
    job.status = "queued"
    job.locked_at = None
    job.last_error = None
    if lease.job_type == SLIPSTREAM_JOB_IMPORT:
        if job.document and job.document.processing_status == "running":
            job.document.processing_status = "queued"
        if job.batch:
            refresh_import_batch_progress(db, job.batch)
        db.add(
            ProcessingEvent(
                import_job_id=job.id,
                document_id=job.document_id,
                level="warning",
                event_type="slipstream_lease_expired",
                message="Slipstream lease expired and the job was returned to the queue.",
                payload={"lease_id": lease.id, "client_id": lease.client_id, "worker_kind": lease.worker_kind},
            )
        )
    elif lease.job_type == SLIPSTREAM_JOB_CONCORDANCE and job.run:
        refresh_concordance_run_progress(db, job.run)


def _lease_job(db: Session, lease: SlipstreamLease) -> ImportJob | ConcordanceJob | None:
    if lease.job_type == SLIPSTREAM_JOB_IMPORT:
        return db.get(ImportJob, lease.job_id)
    if lease.job_type == SLIPSTREAM_JOB_CONCORDANCE:
        return db.get(ConcordanceJob, lease.job_id)
    return None


def _claim_candidate(
    db: Session,
    *,
    job_type: str,
    job: ImportJob | ConcordanceJob,
    client: SlipstreamClient | None,
    worker_kind: str,
    ttl_seconds: int,
) -> tuple[SlipstreamLease, str] | None:
    now = utc_now()
    lease_token = secrets.token_urlsafe(32)
    lease = SlipstreamLease(
        client_id=client.id if client else None,
        worker_kind=worker_kind,
        job_type=job_type,
        job_id=job.id,
        status=ACTIVE_LEASE_STATUS,
        lease_token_hash=token_hash(lease_token),
        claimed_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=max(1, ttl_seconds)),
        payload={"idempotency_key": f"{job_type}:{job.id}:{now.timestamp()}"},
    )
    try:
        with db.begin_nested():
            db.add(lease)
            db.flush()
    except IntegrityError:
        return None

    was_stale = job.status == "running"
    previous_locked_at = job.locked_at
    job.status = "running"
    job.locked_at = now
    job.last_error = None
    if job_type == SLIPSTREAM_JOB_IMPORT:
        if job.document:
            job.document.processing_status = "running"
        if was_stale:
            db.add(
                ProcessingEvent(
                    import_job_id=job.id,
                    document_id=job.document_id,
                    level="warning",
                    event_type="stale_import_recovered",
                    message="Import job was recovered while creating a Slipstream lease.",
                    payload={
                        "previous_step": job.current_step,
                        "previous_locked_at": previous_locked_at.isoformat() if previous_locked_at else None,
                    },
                )
            )
        if worker_kind == "slipstream":
            db.add(
                ProcessingEvent(
                    import_job_id=job.id,
                    document_id=job.document_id,
                    event_type="slipstream_lease_claimed",
                    message="Job was assigned to a Slipstream worker.",
                    payload={
                        "lease_id": lease.id,
                        "client_id": client.id if client else None,
                        "client_name": client.name if client else "Local worker",
                        "worker_kind": worker_kind,
                    },
                )
            )
        if job.batch:
            refresh_import_batch_progress(db, job.batch)
    elif job_type == SLIPSTREAM_JOB_CONCORDANCE and job.run:
        refresh_concordance_run_progress(db, job.run)
    db.flush()
    return lease, lease_token


def legacy_local_claim_response(
    db: Session,
    *,
    job_type: str,
    job: ImportJob | ConcordanceJob,
) -> dict[str, Any]:
    now = utc_now()
    was_stale = job.status == "running"
    previous_locked_at = job.locked_at
    previous_step = getattr(job, "current_step", None)
    job.status = "running"
    job.locked_at = now
    job.last_error = None
    if job_type == SLIPSTREAM_JOB_IMPORT and isinstance(job, ImportJob):
        if job.document:
            job.document.processing_status = "running"
        if was_stale:
            db.add(
                ProcessingEvent(
                    import_job_id=job.id,
                    document_id=job.document_id,
                    level="warning",
                    event_type="stale_import_recovered",
                    message="Import job was recovered from a stale worker lock.",
                    payload={
                        "previous_step": previous_step,
                        "previous_locked_at": previous_locked_at.isoformat() if previous_locked_at else None,
                    },
                )
            )
        if job.batch:
            refresh_import_batch_progress(db, job.batch)
    elif job_type == SLIPSTREAM_JOB_CONCORDANCE and isinstance(job, ConcordanceJob) and job.run:
        refresh_concordance_run_progress(db, job.run)
    db.flush()
    return {
        "lease": {
            "id": None,
            "client_id": None,
            "client_name": None,
            "worker_kind": "local",
            "job_type": job_type,
            "job_id": job.id,
            "status": ACTIVE_LEASE_STATUS,
        },
        "lease_token": None,
        "work": {"job_type": job_type, "job_id": job.id},
    }


def claim_next_job_lease(
    db: Session,
    *,
    client: SlipstreamClient | None = None,
    worker_kind: str = "slipstream",
    job_types: list[str] | None = None,
    exclude_import_ids: set[str] | None = None,
    local_stale_after_seconds: int | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    leases_available = slipstream_tables_available(db)
    if leases_available:
        expire_stale_leases(db)
    if worker_kind == "slipstream":
        if not settings.slipstream_enabled:
            raise SlipstreamError("Slipstream is disabled.")
        if not leases_available:
            raise SlipstreamError("Slipstream tables are unavailable.")
        if not client:
            raise SlipstreamAuthError("Slipstream client is required.")
        if active_client_leases(db, client.id) >= max(1, client.capacity):
            return None
        allowed_job_types = set(job_types or client.capabilities or [SLIPSTREAM_JOB_IMPORT, SLIPSTREAM_JOB_CONCORDANCE])
        ttl_seconds = settings.slipstream_lease_ttl_seconds
    else:
        allowed_job_types = set(job_types or [SLIPSTREAM_JOB_IMPORT, SLIPSTREAM_JOB_CONCORDANCE])
        ttl_seconds = settings.worker_stale_job_seconds

    if SLIPSTREAM_JOB_IMPORT in allowed_job_types:
        for job in _query_import_candidates(
            db,
            exclude_ids=exclude_import_ids,
            use_lease_filter=leases_available,
            stale_after_seconds=local_stale_after_seconds if worker_kind != "slipstream" else None,
        ):
            if not leases_available and worker_kind != "slipstream":
                return legacy_local_claim_response(db, job_type=SLIPSTREAM_JOB_IMPORT, job=job)
            claimed = _claim_candidate(
                db,
                job_type=SLIPSTREAM_JOB_IMPORT,
                job=job,
                client=client,
                worker_kind=worker_kind,
                ttl_seconds=ttl_seconds,
            )
            if claimed:
                lease, lease_token = claimed
                return lease_response(db, lease, lease_token=lease_token)

    if SLIPSTREAM_JOB_CONCORDANCE in allowed_job_types:
        for job in _query_concordance_candidates(
            db,
            use_lease_filter=leases_available,
            stale_after_seconds=local_stale_after_seconds if worker_kind != "slipstream" else None,
        ):
            if not leases_available and worker_kind != "slipstream":
                return legacy_local_claim_response(db, job_type=SLIPSTREAM_JOB_CONCORDANCE, job=job)
            claimed = _claim_candidate(
                db,
                job_type=SLIPSTREAM_JOB_CONCORDANCE,
                job=job,
                client=client,
                worker_kind=worker_kind,
                ttl_seconds=ttl_seconds,
            )
            if claimed:
                lease, lease_token = claimed
                return lease_response(db, lease, lease_token=lease_token)

    return None


def _capability_versions() -> dict[str, int]:
    return {capability.key: capability.version for capability in CURRENT_CAPABILITIES}


def lease_response(db: Session, lease: SlipstreamLease, *, lease_token: str | None = None) -> dict[str, Any]:
    return {
        "lease": lease_out(lease),
        "lease_token": lease_token,
        "work": work_bundle(db, lease),
    }


def lease_out(lease: SlipstreamLease) -> dict[str, Any]:
    client = lease.client
    return {
        "id": lease.id,
        "client_id": lease.client_id,
        "client_name": client.name if client else None,
        "worker_kind": lease.worker_kind,
        "job_type": lease.job_type,
        "job_id": lease.job_id,
        "status": lease.status,
        "claimed_at": lease.claimed_at,
        "heartbeat_at": lease.heartbeat_at,
        "expires_at": lease.expires_at,
        "completed_at": lease.completed_at,
        "canceled_at": lease.canceled_at,
        "last_error": lease.last_error,
    }


def client_out(client: SlipstreamClient) -> dict[str, Any]:
    return {
        "id": client.id,
        "name": client.name,
        "version": client.version,
        "capabilities": client.capabilities,
        "capacity": client.capacity,
        "status": client.status,
        "last_check_in_at": client.last_check_in_at,
        "online": client_is_online(client),
        "revoked_at": client.revoked_at,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
    }


def enrollment_out(enrollment: SlipstreamEnrollment, *, token: str | None = None) -> dict[str, Any]:
    return {
        "id": enrollment.id,
        "label": enrollment.label,
        "status": enrollment.status,
        "expires_at": enrollment.expires_at,
        "used_at": enrollment.used_at,
        "client_id": enrollment.client_id,
        "token": token,
        "created_at": enrollment.created_at,
    }


def slipstream_status(db: Session) -> dict[str, Any]:
    expire_stale_leases(db)
    clients = db.query(SlipstreamClient).order_by(SlipstreamClient.created_at.asc()).all()
    active_leases = (
        db.query(SlipstreamLease)
        .filter(SlipstreamLease.status == ACTIVE_LEASE_STATUS)
        .order_by(SlipstreamLease.claimed_at.asc())
        .all()
    )
    now = utc_now()
    oldest = min((_aware_datetime(lease.claimed_at) for lease in active_leases if _aware_datetime(lease.claimed_at)), default=None)
    failed_or_expired = (
        db.query(SlipstreamLease)
        .filter(SlipstreamLease.status.in_(["failed", "expired"]))
        .count()
    )
    return {
        "enabled": get_settings().slipstream_enabled,
        "public_base_url": get_settings().slipstream_public_base_url,
        "heartbeat_seconds": get_settings().slipstream_heartbeat_seconds,
        "lease_ttl_seconds": get_settings().slipstream_lease_ttl_seconds,
        "require_tls": get_settings().slipstream_require_tls,
        "clients": [client_out(client) for client in clients],
        "active_leases": [lease_out(lease) for lease in active_leases],
        "online_client_count": sum(1 for client in clients if client_is_online(client)),
        "active_lease_count": len(active_leases),
        "oldest_active_lease_age_seconds": int((now - oldest).total_seconds()) if oldest else None,
        "failed_or_expired_lease_count": failed_or_expired,
    }


def work_bundle(db: Session, lease: SlipstreamLease) -> dict[str, Any]:
    job = _lease_job(db, lease)
    if not job:
        raise SlipstreamError("Slipstream lease job is missing.")
    document = job.document
    model_preferences = get_analysis_models(db)
    checksum = document.checksum_sha256 if document else None
    base_url = (get_settings().slipstream_public_base_url or "").rstrip("/")
    artifact_path = f"/api/slipstream/leases/{lease.id}/artifact"
    artifact_url = f"{base_url}{artifact_path}" if base_url else artifact_path
    bundle: dict[str, Any] = {
        "job_type": lease.job_type,
        "job_id": job.id,
        "lease_id": lease.id,
        "document_id": getattr(job, "document_id", None),
        "document_title": document.title if document else None,
        "original_filename": document.original_filename if document else None,
        "checksum_sha256": checksum,
        "artifact_url": artifact_url,
        "idempotency_key": lease.payload.get("idempotency_key") or f"{lease.job_type}:{job.id}:{lease.id}",
        "model_preferences": model_preferences,
        "capability_versions": _capability_versions(),
    }
    if lease.job_type == SLIPSTREAM_JOB_IMPORT and isinstance(job, ImportJob):
        bundle.update(
            {
                "batch_id": job.batch_id,
                "current_step": job.current_step,
                "processing_preset": import_processing_preset_for_job(db, job, document) if document else {},
            }
        )
    if lease.job_type == SLIPSTREAM_JOB_CONCORDANCE and isinstance(job, ConcordanceJob):
        bundle.update(
            {
                "run_id": job.run_id,
                "capability_keys": [job.capability_key],
                "target_version": job.target_version,
            }
        )
    return bundle


def validate_lease_access(
    db: Session,
    *,
    lease_id: str,
    client: SlipstreamClient,
    lease_token: str | None,
    require_active: bool = True,
) -> SlipstreamLease:
    lease = db.get(SlipstreamLease, lease_id)
    if not lease:
        raise SlipstreamAuthError("Slipstream lease not found.")
    if lease.client_id != client.id:
        raise SlipstreamAuthError("Slipstream lease belongs to another client.")
    if not lease_token or not hmac.compare_digest(lease.lease_token_hash, token_hash(lease_token)):
        raise SlipstreamAuthError("Slipstream lease token is invalid.")
    if require_active and lease.status != ACTIVE_LEASE_STATUS:
        raise SlipstreamError(f"Slipstream lease is {lease.status}.")
    return lease


def heartbeat_lease(db: Session, lease: SlipstreamLease, *, detail: str | None = None) -> dict[str, Any]:
    now = utc_now()
    lease.heartbeat_at = now
    lease.expires_at = now + timedelta(seconds=max(1, get_settings().slipstream_lease_ttl_seconds))
    if detail:
        payload = dict(lease.payload or {})
        payload["last_detail"] = detail
        lease.payload = payload
    db.flush()
    return lease_out(lease)


def artifact_for_lease(db: Session, lease: SlipstreamLease) -> tuple[bytes, str]:
    job = _lease_job(db, lease)
    document = job.document if job else None
    if not document:
        raise SlipstreamError("Slipstream lease has no document artifact.")
    data = ensure_document_pdf_bytes(db, document, source="slipstream")
    if not data:
        raise SlipstreamError("Original document artifact is unavailable.")
    filename = document.original_filename or f"{document.id}.pdf"
    return data, filename


def record_client_event(db: Session, lease: SlipstreamLease, *, event_type: str, message: str, level: str = "info", payload: dict[str, Any] | None = None) -> None:
    job = _lease_job(db, lease)
    document_id = getattr(job, "document_id", None)
    import_job_id = job.id if lease.job_type == SLIPSTREAM_JOB_IMPORT and isinstance(job, ImportJob) else None
    db.add(
        ProcessingEvent(
            import_job_id=import_job_id,
            document_id=document_id,
            level=level,
            event_type=event_type or "slipstream_client_event",
            message=message or "Slipstream client event.",
            payload={"lease_id": lease.id, "client_id": lease.client_id, **(payload or {})},
        )
    )
    heartbeat_lease(db, lease)


def fail_lease(db: Session, lease: SlipstreamLease, *, error: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    lease.status = "failed"
    lease.completed_at = utc_now()
    lease.last_error = error
    job = _lease_job(db, lease)
    if not job:
        db.flush()
        return lease_out(lease)
    job.status = "failed"
    job.locked_at = None
    job.last_error = error
    if lease.job_type == SLIPSTREAM_JOB_IMPORT and isinstance(job, ImportJob):
        if job.document:
            job.document.processing_status = "failed"
        if job.batch:
            refresh_import_batch_progress(db, job.batch)
        db.add(
            ProcessingEvent(
                import_job_id=job.id,
                document_id=job.document_id,
                level="error",
                event_type="slipstream_job_failed",
                message="Slipstream client reported a job failure.",
                payload={"lease_id": lease.id, "client_id": lease.client_id, "error": error, **(payload or {})},
            )
        )
    elif lease.job_type == SLIPSTREAM_JOB_CONCORDANCE and isinstance(job, ConcordanceJob):
        job.completed_at = utc_now()
        if job.run:
            refresh_concordance_run_progress(db, job.run)
    db.flush()
    return lease_out(lease)


DOCUMENT_PATCH_FIELDS = {
    "title",
    "subtitle",
    "authors",
    "universities",
    "publication_year",
    "journal",
    "publisher",
    "doi",
    "abstract",
    "rich_summary",
    "apa_citation",
    "apa_in_text_citation",
    "citation_status",
    "bibliography",
    "page_count",
    "search_text",
}


def _apply_document_patch(document: Document, patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if key not in DOCUMENT_PATCH_FIELDS:
            continue
        if key == "search_text":
            value = sanitize_extracted_text(value)
        setattr(document, key, value)
    evidence = dict(document.metadata_evidence or {})
    evidence["slipstream_result"] = {
        **(evidence.get("slipstream_result") or {}),
        "applied_at": utc_now().isoformat(),
        "fields": sorted(key for key in patch if key in DOCUMENT_PATCH_FIELDS),
    }
    document.metadata_evidence = evidence


def _apply_pages(db: Session, document: Document, pages: list[dict[str, Any]]) -> None:
    for row in pages:
        page_number = int(row.get("page_number") or 0)
        if page_number <= 0:
            continue
        page = (
            db.query(DocumentPage)
            .filter(DocumentPage.document_id == document.id, DocumentPage.page_number == page_number)
            .one_or_none()
        )
        if not page:
            page = DocumentPage(document_id=document.id, page_number=page_number)
            db.add(page)
        if "text" in row:
            page.text = sanitize_extracted_text(row.get("text"))
        if "normalized_text" in row:
            page.normalized_text = sanitize_extracted_text(row.get("normalized_text"))
        if "text_source" in row:
            page.text_source = str(row.get("text_source") or "slipstream")
        else:
            page.text_source = page.text_source or "slipstream"
        if "low_text" in row:
            page.low_text = bool(row.get("low_text"))
        if "image_uri" in row:
            page.image_uri = row.get("image_uri")


def _apply_capabilities(db: Session, document: Document, capabilities: list[dict[str, Any]]) -> None:
    for row in capabilities:
        key = str(row.get("capability_key") or row.get("key") or "").strip()
        if not key:
            continue
        state = (
            db.query(DocumentCapability)
            .filter(DocumentCapability.document_id == document.id, DocumentCapability.capability_key == key)
            .one_or_none()
        )
        if not state:
            state = DocumentCapability(document_id=document.id, capability_key=key, version=int(row.get("version") or 1))
            db.add(state)
        state.version = int(row.get("version") or state.version or 1)
        state.status = str(row.get("status") or "complete")
        state.evidence = row.get("evidence") or {}
        state.completed_at = utc_now() if state.status == "complete" else state.completed_at


def _apply_composition(db: Session, document: Document, job: ImportJob | ConcordanceJob, entries: list[dict[str, Any]], *, lease: SlipstreamLease) -> None:
    sequence_base = (
        db.query(DocumentCompositionRecord)
        .filter(DocumentCompositionRecord.document_id == document.id)
        .count()
    )
    for index, row in enumerate(entries, start=1):
        db.add(
            DocumentCompositionRecord(
                document_id=document.id,
                import_job_id=job.id if isinstance(job, ImportJob) else None,
                sequence=sequence_base + index,
                record_kind=str(row.get("record_kind") or "remote_stage"),
                stage_key=str(row.get("stage_key") or "slipstream_remote"),
                stage_label=str(row.get("stage_label") or row.get("label") or "Slipstream remote work"),
                provider=row.get("provider") or "slipstream",
                method=row.get("method") or "remote_client",
                model=row.get("model"),
                status=str(row.get("status") or "complete"),
                amount_usd=row.get("amount_usd"),
                duration_ms=row.get("duration_ms"),
                input_tokens=int(row.get("input_tokens") or 0),
                output_tokens=int(row.get("output_tokens") or 0),
                total_tokens=int(row.get("total_tokens") or 0),
                started_at=_parse_datetime(row.get("started_at")),
                completed_at=_parse_datetime(row.get("completed_at")) or utc_now(),
                message=row.get("message"),
                record_metadata={"lease_id": lease.id, "client_id": lease.client_id, **(row.get("metadata") or {})},
            )
        )


def complete_lease_from_result(db: Session, lease: SlipstreamLease, *, manifest: dict[str, Any]) -> dict[str, Any]:
    idempotency_key = str(manifest.get("idempotency_key") or "")
    if lease.status == "complete":
        if idempotency_key and lease.result_idempotency_key == idempotency_key:
            return lease_out(lease)
        raise SlipstreamError("Slipstream lease has already completed.")
    if lease.status != ACTIVE_LEASE_STATUS:
        raise SlipstreamError(f"Slipstream lease is {lease.status}.")
    expected_key = str((lease.payload or {}).get("idempotency_key") or "")
    if expected_key and idempotency_key and idempotency_key != expected_key:
        raise SlipstreamError("Slipstream result idempotency key does not match the lease.")

    job = _lease_job(db, lease)
    document = job.document if job else None
    if not job or not document:
        raise SlipstreamError("Slipstream lease job or document is missing.")

    document_patch = manifest.get("document") if isinstance(manifest.get("document"), dict) else {}
    if document_patch:
        _apply_document_patch(document, document_patch)
    pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
    _apply_pages(db, document, pages)
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), list) else []
    _apply_capabilities(db, document, capabilities)
    composition_entries = manifest.get("composition") if isinstance(manifest.get("composition"), list) else []
    _apply_composition(db, document, job, composition_entries, lease=lease)

    lease.status = "complete"
    lease.completed_at = utc_now()
    lease.result_idempotency_key = idempotency_key or expected_key or f"{lease.job_type}:{lease.job_id}:{lease.id}"
    lease.last_error = None

    if lease.job_type == SLIPSTREAM_JOB_IMPORT and isinstance(job, ImportJob):
        job.current_step = str(manifest.get("current_step") or "complete")
        job.status = "complete"
        job.locked_at = None
        job.last_error = None
        document.processing_status = "ready"
        if job.batch:
            refresh_import_batch_progress(db, job.batch)
        db.add(
            ProcessingEvent(
                import_job_id=job.id,
                document_id=job.document_id,
                event_type="slipstream_job_complete",
                message="Slipstream client result was applied.",
                payload={"lease_id": lease.id, "client_id": lease.client_id, "idempotency_key": lease.result_idempotency_key},
            )
        )
    elif lease.job_type == SLIPSTREAM_JOB_CONCORDANCE and isinstance(job, ConcordanceJob):
        if not capabilities:
            _apply_capabilities(
                db,
                document,
                [
                    {
                        "capability_key": job.capability_key,
                        "version": job.target_version,
                        "status": "complete",
                        "evidence": {"slipstream_lease_id": lease.id},
                    }
                ],
            )
        job.status = "complete"
        job.locked_at = None
        job.last_error = None
        job.completed_at = utc_now()
        if job.run:
            refresh_concordance_run_progress(db, job.run)
    db.flush()
    return lease_out(lease)


def complete_local_lease_for_job(db: Session, *, job_type: str, job_id: str, failed_error: str | None = None) -> None:
    lease = (
        db.query(SlipstreamLease)
        .filter(
            SlipstreamLease.job_type == job_type,
            SlipstreamLease.job_id == job_id,
            SlipstreamLease.worker_kind == "local",
            SlipstreamLease.status == ACTIVE_LEASE_STATUS,
        )
        .order_by(SlipstreamLease.claimed_at.desc())
        .first()
    )
    if not lease:
        return
    job = _lease_job(db, lease)
    lease.status = "failed" if failed_error or getattr(job, "status", None) == "failed" else "complete"
    lease.completed_at = utc_now()
    lease.last_error = failed_error or getattr(job, "last_error", None)
    db.flush()


def cancel_lease(db: Session, lease: SlipstreamLease, *, reason: str = "Canceled by user.") -> dict[str, Any]:
    lease.status = "canceled"
    lease.canceled_at = utc_now()
    lease.completed_at = utc_now()
    lease.last_error = reason
    job = _lease_job(db, lease)
    if job and getattr(job, "status", None) == "running":
        job.status = "queued"
        job.locked_at = None
        if lease.job_type == SLIPSTREAM_JOB_IMPORT and isinstance(job, ImportJob):
            if job.document and job.document.processing_status == "running":
                job.document.processing_status = "queued"
            if job.batch:
                refresh_import_batch_progress(db, job.batch)
        elif lease.job_type == SLIPSTREAM_JOB_CONCORDANCE and isinstance(job, ConcordanceJob) and job.run:
            refresh_concordance_run_progress(db, job.run)
    db.flush()
    return lease_out(lease)


def revoke_client(db: Session, client: SlipstreamClient, *, disable_only: bool = False) -> SlipstreamClient:
    client.status = "disabled" if disable_only else "revoked"
    if not disable_only:
        client.revoked_at = utc_now()
    active_leases = (
        db.query(SlipstreamLease)
        .filter(SlipstreamLease.client_id == client.id, SlipstreamLease.status == ACTIVE_LEASE_STATUS)
        .all()
    )
    for lease in active_leases:
        cancel_lease(db, lease, reason="Client was disabled or revoked.")
    db.flush()
    return client
