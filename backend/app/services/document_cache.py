from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, ImportJob, utc_now
from app.services.preferences import get_document_cache_size_mb
from app.services.storage import get_storage_service


def document_cache_root() -> Path:
    root = get_settings().data_dir / "processing-cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def document_cache_path(document_id: str) -> Path:
    return document_cache_root() / f"{document_id}.pdf"


def is_managed_cache_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
        root = document_cache_root().resolve()
    except FileNotFoundError:
        resolved = path.absolute()
        root = document_cache_root().resolve()
    return resolved == root or root in resolved.parents


def write_document_cache(document_id: str, data: bytes) -> Path:
    path = document_cache_path(document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def current_document_cache_usage() -> dict[str, int]:
    root = document_cache_root()
    total_bytes = 0
    file_count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            total_bytes += path.stat().st_size
        except FileNotFoundError:
            continue
        file_count += 1
    mb = 1024 * 1024
    return {
        "current_size_bytes": total_bytes,
        "current_size_mb": (total_bytes + (mb // 2)) // mb,
        "file_count": file_count,
    }


def metadata_cache_path(document: Document, *, require_managed: bool = False) -> Path | None:
    evidence = document.metadata_evidence or {}
    for key in ("local_cache_path", "document_cache_path"):
        raw_path = evidence.get(key)
        if isinstance(raw_path, str) and raw_path:
            path = Path(raw_path).expanduser()
            if path.exists() and path.is_file() and (not require_managed or is_managed_cache_path(path)):
                return path
    return None


def register_document_cache(document: Document, path: Path, *, source: str = "upload", processing_path: bool = True) -> None:
    evidence = dict(document.metadata_evidence or {})
    size = path.stat().st_size if path.exists() else evidence.get("file_size_bytes")
    evidence["document_cache_path"] = str(path)
    if processing_path:
        evidence["local_cache_path"] = str(path)
    evidence["document_cache"] = {
        "status": "cached",
        "source": source,
        "size_bytes": size,
        "cached_at": utc_now().isoformat(),
    }
    document.metadata_evidence = evidence


def ensure_document_cache_file(
    db: Session,
    document: Document,
    *,
    source: str = "storage",
    processing_path: bool = True,
) -> Path | None:
    cached = metadata_cache_path(document)
    if cached:
        return cached
    if not document.gcs_uri:
        return None
    data = get_storage_service().get_bytes(document.gcs_uri)
    path = write_document_cache(document.id, data)
    register_document_cache(document, path, source=source, processing_path=processing_path)
    db.flush()
    return path


def ensure_document_pdf_bytes(db: Session, document: Document, *, source: str = "storage") -> bytes | None:
    path = ensure_document_cache_file(db, document, source=source, processing_path=False)
    if path and path.exists():
        return path.read_bytes()
    if not document.gcs_uri:
        return None
    return get_storage_service().get_bytes(document.gcs_uri)


def mark_processing_cache_retained(document: Document, path: Path) -> None:
    evidence = dict(document.metadata_evidence or {})
    evidence.pop("local_cache_path", None)
    evidence["document_cache_path"] = str(path)
    evidence["processing_cache"] = {"status": "retained_after_success"}
    existing = dict(evidence.get("document_cache") or {})
    evidence["document_cache"] = {
        **existing,
        "status": "cached",
        "size_bytes": path.stat().st_size if path.exists() else existing.get("size_bytes"),
        "cached_at": existing.get("cached_at") or utc_now().isoformat(),
    }
    document.metadata_evidence = evidence


def _cache_entries(db: Session) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    protected_document_ids = {
        row[0]
        for row in db.query(ImportJob.document_id)
        .filter(ImportJob.document_id.isnot(None), ImportJob.status.in_(["queued", "running", "paused", "failed", "restored_paused"]))
        .all()
    }
    for document in db.query(Document).all():
        evidence = document.metadata_evidence or {}
        raw_path = evidence.get("document_cache_path") or evidence.get("local_cache_path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.exists() or not path.is_file() or not is_managed_cache_path(path):
            continue
        stat = path.stat()
        entries.append(
            {
                "document": document,
                "path": path,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "protected": document.id in protected_document_ids,
            }
        )
    return entries


def enforce_document_cache_budget(db: Session, *, keep_document_id: str | None = None) -> dict[str, Any]:
    budget_mb = get_document_cache_size_mb(db)
    budget_bytes = budget_mb * 1024 * 1024
    entries = _cache_entries(db)
    total_bytes = sum(entry["size"] for entry in entries)
    deleted_files = 0
    deleted_bytes = 0

    if total_bytes > budget_bytes:
        for entry in sorted(entries, key=lambda item: item["mtime"]):
            document = entry["document"]
            if entry["protected"] or (keep_document_id and document.id == keep_document_id and budget_bytes > 0):
                continue
            if total_bytes <= budget_bytes:
                break
            path = entry["path"]
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            evidence = dict(document.metadata_evidence or {})
            if evidence.get("document_cache_path") == str(path):
                evidence.pop("document_cache_path", None)
            if evidence.get("local_cache_path") == str(path):
                evidence.pop("local_cache_path", None)
            evidence["document_cache"] = {
                "status": "pruned",
                "pruned_at": utc_now().isoformat(),
                "budget_mb": budget_mb,
            }
            document.metadata_evidence = evidence
            total_bytes -= entry["size"]
            deleted_bytes += entry["size"]
            deleted_files += 1

    db.flush()
    return {
        "budget_mb": budget_mb,
        "budget_bytes": budget_bytes,
        "after_bytes": total_bytes,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
    }
