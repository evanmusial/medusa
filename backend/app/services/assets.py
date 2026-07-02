from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AssetDeletionQueue, Document, DocumentPage, Figure, utc_now
from app.services.google_credentials import load_service_account_credentials
from app.services.preferences import get_active_google_project_id, get_active_storage_settings
from app.services.storage import get_storage_service, split_gs_uri


logger = logging.getLogger(__name__)
ASSET_DELETION_PENDING_STATUSES = {"queued", "delete_failed", "invalidate_failed"}


def _active_gcs_bucket() -> str | None:
    bucket = get_active_storage_settings().get("gcs_bucket")
    return str(bucket).strip() if bucket else None


def _cdn_base_url() -> str | None:
    value = get_settings().asset_cdn_base_url
    if not value:
        return None
    value = value.strip().rstrip("/")
    if not value.startswith(("https://", "http://")):
        return None
    return value


def _object_path(object_name: str) -> str:
    return "/" + "/".join(quote(part, safe="") for part in object_name.split("/"))


def asset_cdn_path_for_storage_uri(storage_uri: str | None) -> str | None:
    if not storage_uri or not storage_uri.startswith("gs://"):
        return None
    try:
        bucket_name, object_name = split_gs_uri(storage_uri)
    except ValueError:
        return None
    active_bucket = _active_gcs_bucket()
    if active_bucket and bucket_name != active_bucket:
        return None
    return _object_path(object_name)


def asset_cdn_invalidation_path_for_storage_uri(storage_uri: str | None) -> str | None:
    path = asset_cdn_path_for_storage_uri(storage_uri)
    if not path:
        return None
    parts = [part for part in path.split("/") if part]
    for marker in ("figures", "documents"):
        if marker in parts:
            index = parts.index(marker)
            if len(parts) >= index + 3:
                return "/" + "/".join(parts[: index + 3]) + "/*"
    return path


def _decode_signed_url_key(value: str | None) -> bytes | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        decoded = stripped.encode("utf-8")
    return decoded or None


def sign_cdn_url(url: str, *, expires_at: int | None = None) -> str | None:
    settings = get_settings()
    key_name = (settings.asset_cdn_signed_url_key_name or "").strip()
    key = _decode_signed_url_key(settings.asset_cdn_signed_url_key)
    if not key_name or not key:
        return url
    expiry = expires_at or int(time.time()) + max(1, settings.asset_cdn_signed_url_ttl_seconds)
    separator = "&" if "?" in url else "?"
    unsigned = f"{url}{separator}Expires={expiry}&KeyName={quote(key_name, safe='')}"
    signature = base64.urlsafe_b64encode(hmac.new(key, unsigned.encode("utf-8"), hashlib.sha1).digest()).decode("ascii")
    return f"{unsigned}&Signature={signature}"


def asset_cdn_url_for_storage_uri(
    storage_uri: str | None,
    *,
    query: dict[str, str] | None = None,
    expires_at: int | None = None,
) -> str | None:
    base_url = _cdn_base_url()
    path = asset_cdn_path_for_storage_uri(storage_uri)
    if not base_url or not path:
        return None
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return sign_cdn_url(url, expires_at=expires_at)


def enqueue_asset_deletion(
    db: Session,
    storage_uri: str | None,
    *,
    source_kind: str,
    source_id: str | None = None,
    document_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AssetDeletionQueue | None:
    if not storage_uri:
        return None
    row = AssetDeletionQueue(
        storage_uri=storage_uri,
        cdn_url_path=asset_cdn_path_for_storage_uri(storage_uri),
        cdn_invalidation_path=asset_cdn_invalidation_path_for_storage_uri(storage_uri),
        source_kind=source_kind,
        source_id=source_id,
        document_id=document_id,
        status="queued",
        attempts=0,
        deletion_metadata=metadata or {},
    )
    db.add(row)
    return row


def _storage_uri_still_referenced(db: Session, storage_uri: str) -> bool:
    return any(
        (
            db.query(Figure.id).filter(Figure.asset_uri == storage_uri).first(),
            db.query(Document.id)
            .filter(Document.gcs_uri == storage_uri, Document.deleted_at.is_(None))
            .first(),
            db.query(DocumentPage.id).filter(DocumentPage.image_uri == storage_uri).first(),
        )
    )


def _auth_token_for_compute_api() -> str | None:
    credentials_path = get_active_storage_settings().get("google_credentials_path")
    if not credentials_path:
        return None
    try:
        from google.auth.transport.requests import Request

        credentials = load_service_account_credentials(str(credentials_path))
        if hasattr(credentials, "with_scopes"):
            credentials = credentials.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        return str(credentials.token) if credentials.token else None
    except Exception:
        logger.exception("Could not mint Google access token for CDN invalidation.")
        return None


def invalidate_cdn_path(path: str) -> bool:
    settings = get_settings()
    url_map = (settings.asset_cdn_url_map or "").strip()
    project = (settings.asset_cdn_project or get_active_google_project_id() or "").strip()
    if not url_map or not project:
        return False
    token = _auth_token_for_compute_api()
    if not token:
        return False
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/global/urlMaps/{url_map}/invalidateCache"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"path": path},
        timeout=30,
    )
    response.raise_for_status()
    return True


def _finish_asset_deletion(row: AssetDeletionQueue, *, status: str, now: datetime, error: str | None = None) -> None:
    row.status = status
    row.last_error = error
    if status in {"deleted", "skipped_referenced"}:
        row.completed_at = now


def process_asset_deletion_queue(db: Session, *, limit: int | None = None) -> dict[str, int]:
    settings = get_settings()
    limit = max(1, limit or settings.asset_cleanup_batch_size)
    now = utc_now()
    stats = {
        "checked": 0,
        "deleted": 0,
        "skipped_referenced": 0,
        "delete_failed": 0,
        "invalidated": 0,
        "invalidate_failed": 0,
    }
    rows = (
        db.query(AssetDeletionQueue)
        .filter(
            AssetDeletionQueue.status.in_(ASSET_DELETION_PENDING_STATUSES),
            or_(AssetDeletionQueue.completed_at.is_(None), AssetDeletionQueue.status == "invalidate_failed"),
        )
        .order_by(AssetDeletionQueue.created_at)
        .limit(limit)
        .all()
    )
    pending_invalidation: dict[str, list[AssetDeletionQueue]] = {}
    storage = get_storage_service()
    for row in rows:
        stats["checked"] += 1
        if row.storage_deleted_at is None:
            if _storage_uri_still_referenced(db, row.storage_uri):
                _finish_asset_deletion(row, status="skipped_referenced", now=now)
                stats["skipped_referenced"] += 1
                continue
            row.attempts += 1
            try:
                storage.delete_uri(row.storage_uri)
                row.storage_deleted_at = now
                row.status = "invalidate_pending" if row.cdn_invalidation_path else "deleted"
                row.last_error = None
                stats["deleted"] += 1
            except Exception as exc:
                _finish_asset_deletion(row, status="delete_failed", now=now, error=str(exc))
                stats["delete_failed"] += 1
                continue
        if row.cdn_invalidation_path:
            pending_invalidation.setdefault(row.cdn_invalidation_path, []).append(row)
        elif row.storage_deleted_at is not None:
            _finish_asset_deletion(row, status="deleted", now=now)

    if pending_invalidation and (settings.asset_cdn_url_map or "").strip():
        for path, path_rows in pending_invalidation.items():
            try:
                invalidated = invalidate_cdn_path(path)
            except Exception as exc:
                invalidated = False
                error = str(exc)
            else:
                error = None
            for row in path_rows:
                if invalidated:
                    row.invalidated_at = now
                    row.status = "deleted"
                    row.completed_at = now
                    row.last_error = None
                    stats["invalidated"] += 1
                else:
                    row.status = "invalidate_failed"
                    row.last_error = error or "CDN invalidation is not configured."
                    stats["invalidate_failed"] += 1
    else:
        for path_rows in pending_invalidation.values():
            for row in path_rows:
                row.status = "deleted"
                row.completed_at = now
                row.last_error = None
                row.deletion_metadata = {
                    **(row.deletion_metadata or {}),
                    "cdn_invalidation": "skipped_unconfigured",
                }

    db.flush()
    return stats
