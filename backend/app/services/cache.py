from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, inspect, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import event
from sqlalchemy.orm import Session as SQLAlchemySession

from app.config import get_settings
from app.models import CacheRevision, ConcordanceJob, DocumentAccessorySummary, ImportJob, SlipstreamClient, SlipstreamLease, utc_now
from app.services.slipstream import client_is_online


logger = logging.getLogger(__name__)

CACHE_KEY_SCHEMA_VERSION = "v1"
CACHE_REVISION_FAMILIES = (
    "library",
    "document_detail",
    "dashboard",
    "status",
    "organization",
    "jobs",
    "preferences",
    "publications",
    "finance",
    "recon",
    "portfolio",
    "backups",
)
CACHE_GLOBAL_FAMILY = "global"
CACHE_ALL_REVISION_FAMILIES = (CACHE_GLOBAL_FAMILY, *CACHE_REVISION_FAMILIES)
LAST_REFRESH_KEY = "medusa:cache:last_refresh_at"
LAST_HYDRATION_KEY = "medusa:cache:last_hydration_at"

MODEL_CACHE_FAMILIES: dict[str, set[str]] = {
    "Annotation": {"library", "document_detail", "status"},
    "AppPreference": {"preferences", "status", "library", "document_detail"},
    "BackupRun": {"backups", "dashboard", "jobs", "status"},
    "CitationCandidate": {"dashboard", "document_detail"},
    "ConcordanceJob": {"dashboard", "jobs", "status", "document_detail"},
    "ConcordanceRun": {"dashboard", "jobs", "status"},
    "Document": {"library", "document_detail", "dashboard", "status"},
    "DocumentAccessorySummary": {"library", "document_detail", "dashboard", "jobs", "status"},
    "DocumentAttributeValue": {"library", "document_detail"},
    "DocumentCapability": {"document_detail", "status"},
    "DocumentCompositionRecord": {"document_detail"},
    "DocumentPage": {"library", "document_detail", "status"},
    "DocumentRecommendation": {"document_detail"},
    "DocumentTagAssessment": {"document_detail", "organization"},
    "DocumentVersion": {"document_detail"},
    "DoiStash": {"dashboard"},
    "Domain": {"organization", "library", "document_detail", "dashboard", "status"},
    "Figure": {"library", "document_detail", "status"},
    "ImportBatch": {"dashboard", "jobs", "status"},
    "ImportJob": {"dashboard", "jobs", "status", "library", "document_detail"},
    "ModelPricingRecord": {"finance", "dashboard", "jobs", "status"},
    "Note": {"library", "document_detail", "dashboard", "status"},
    "OpenAIUsageRecord": {"finance", "dashboard", "jobs"},
    "ProcessingEvent": {"dashboard", "jobs", "document_detail"},
    "Publication": {"publications", "library", "document_detail", "organization", "status"},
    "PublicationAlias": {"publications", "library", "document_detail", "organization"},
    "Project": {"organization", "library", "document_detail", "dashboard", "status"},
    "ProjectBibliography": {"organization", "document_detail"},
    "ProjectItem": {"organization", "library", "document_detail", "dashboard", "status"},
    "ReconAnswerVersion": {"recon", "dashboard", "jobs", "status"},
    "ReconEvidence": {"recon", "dashboard", "jobs", "status"},
    "ReconInquiry": {"recon", "dashboard", "jobs", "status"},
    "ReconRun": {"recon", "dashboard", "jobs", "status"},
    "SavedSearch": {"organization"},
    "SlipstreamClient": {"dashboard", "jobs", "status"},
    "SlipstreamEnrollment": {"status"},
    "SlipstreamLease": {"dashboard", "jobs", "status", "document_detail"},
    "Tag": {"organization", "library", "document_detail", "dashboard", "status"},
    "TagAlias": {"organization"},
    "TagRelationship": {"organization"},
    "TextChunk": {"status"},
    "AttributeDefinition": {"organization", "library", "document_detail"},
    "DocumentPublication": {"publications", "library", "document_detail", "organization", "status"},
    "PortfolioAssessmentFinding": {"portfolio", "dashboard", "jobs", "status"},
    "PortfolioAssessmentRun": {"portfolio", "dashboard", "jobs", "status"},
    "PortfolioAuditAnchor": {"portfolio", "status"},
    "PortfolioAuditEvent": {"portfolio", "status"},
    "PortfolioItem": {"portfolio", "dashboard", "jobs", "status"},
    "PortfolioMaterial": {"portfolio", "dashboard", "jobs", "status"},
    "PortfolioSuggestion": {"portfolio", "dashboard", "jobs", "status"},
    "PortfolioVersion": {"portfolio", "dashboard", "jobs", "status"},
    "PortfolioVersionEdge": {"portfolio", "dashboard", "jobs", "status"},
}

_cache_backend: CacheBackend | None = None
_cache_lock = threading.Lock()
_family_stats_lock = threading.Lock()
_family_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0, "bypass": 0, "error": 0, "write": 0})
_revision_hooks_installed = False


def _utc_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _normalize_cache_url(url: str) -> str:
    return f"redis://{url[len('valkey://'):]}" if url.startswith("valkey://") else url


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_loads(raw: bytes | str) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def record_cache_event(family: str, event_name: str) -> None:
    if event_name not in {"hit", "miss", "bypass", "error", "write"}:
        return
    with _family_stats_lock:
        _family_stats[family][event_name] += 1


def cache_family_stats() -> list[dict[str, Any]]:
    with _family_stats_lock:
        rows = []
        for family, stats in sorted(_family_stats.items()):
            hits = stats.get("hit", 0)
            misses = stats.get("miss", 0)
            total = hits + misses
            rows.append(
                {
                    "family": family,
                    "hits": hits,
                    "misses": misses,
                    "bypasses": stats.get("bypass", 0),
                    "errors": stats.get("error", 0),
                    "writes": stats.get("write", 0),
                    "hit_rate": (hits / total) if total else 0.0,
                }
            )
        return rows


class CacheBackend:
    name = "none"
    enabled = False

    def get_json(self, key: str, family: str) -> tuple[str, Any | None]:
        record_cache_event(family, "bypass")
        return "bypass", None

    def set_json(self, key: str, family: str, payload: Any, ttl_seconds: int, max_payload_bytes: int) -> str:
        record_cache_event(family, "bypass")
        return "bypass"

    def remember_refresh(self, refreshed_at: datetime | None = None) -> None:
        return None

    def last_refresh_at(self) -> datetime | None:
        return None

    def remember_hydration(self, hydrated_at: datetime | None = None) -> None:
        return None

    def last_hydration_at(self) -> datetime | None:
        return None

    def configure_maxmemory(self, value: str) -> bool:
        return False

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "enabled": False,
            "reachable": False,
            "mode": "disabled",
            "message": "Server-side response caching is disabled.",
        }


class NullCache(CacheBackend):
    name = "none"


class ValkeyCache(CacheBackend):
    name = "valkey"
    enabled = True

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: Any | None = None
        self._client_lock = threading.Lock()

    def _redis(self) -> Any:
        with self._client_lock:
            if self._client is None:
                from redis import Redis

                self._client = Redis.from_url(
                    _normalize_cache_url(self.url),
                    socket_connect_timeout=0.25,
                    socket_timeout=0.75,
                    retry_on_timeout=False,
                )
            return self._client

    def get_json(self, key: str, family: str) -> tuple[str, Any | None]:
        try:
            raw = self._redis().get(key)
        except Exception:
            logger.debug("Valkey cache get failed for %s", key, exc_info=True)
            record_cache_event(family, "error")
            return "error", None
        if raw is None:
            record_cache_event(family, "miss")
            return "miss", None
        try:
            payload = _json_loads(raw)
        except (TypeError, ValueError):
            record_cache_event(family, "error")
            return "error", None
        record_cache_event(family, "hit")
        return "hit", payload

    def set_json(self, key: str, family: str, payload: Any, ttl_seconds: int, max_payload_bytes: int) -> str:
        try:
            raw = _json_bytes(payload)
        except (TypeError, ValueError, RecursionError):
            record_cache_event(family, "bypass")
            return "bypass"
        if len(raw) > max_payload_bytes:
            record_cache_event(family, "bypass")
            return "bypass"
        try:
            self._redis().setex(key, max(1, ttl_seconds), raw)
        except Exception:
            logger.debug("Valkey cache set failed for %s", key, exc_info=True)
            record_cache_event(family, "error")
            return "error"
        record_cache_event(family, "write")
        return "write"

    def remember_refresh(self, refreshed_at: datetime | None = None) -> None:
        try:
            self._redis().set(LAST_REFRESH_KEY, _utc_iso(refreshed_at))
        except Exception:
            logger.debug("Valkey cache refresh timestamp write failed", exc_info=True)

    def last_refresh_at(self) -> datetime | None:
        try:
            raw = self._redis().get(LAST_REFRESH_KEY)
        except Exception:
            return None
        if not raw:
            return None
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def remember_hydration(self, hydrated_at: datetime | None = None) -> None:
        try:
            self._redis().set(LAST_HYDRATION_KEY, _utc_iso(hydrated_at))
        except Exception:
            logger.debug("Valkey cache hydration timestamp write failed", exc_info=True)

    def last_hydration_at(self) -> datetime | None:
        try:
            raw = self._redis().get(LAST_HYDRATION_KEY)
        except Exception:
            return None
        if not raw:
            return None
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def configure_maxmemory(self, value: str) -> bool:
        try:
            self._redis().config_set("maxmemory", value)
        except Exception:
            logger.debug("Valkey cache maxmemory update failed for %s", value, exc_info=True)
            return False
        return True

    def status(self) -> dict[str, Any]:
        started = perf_counter()
        try:
            client = self._redis()
            info = client.info()
            key_count = int(client.dbsize() or 0)
        except Exception as exc:
            return {
                "backend": self.name,
                "enabled": True,
                "reachable": False,
                "mode": "degraded",
                "message": f"Valkey is configured but unreachable: {exc}",
            }
        hits = int(info.get("keyspace_hits") or 0)
        misses = int(info.get("keyspace_misses") or 0)
        total = hits + misses
        return {
            "backend": self.name,
            "enabled": True,
            "reachable": True,
            "mode": "online",
            "message": "Valkey cache is online.",
            "version": info.get("valkey_version") or info.get("redis_version"),
            "uptime_seconds": int(info.get("uptime_in_seconds") or 0),
            "used_memory_bytes": int(info.get("used_memory") or 0),
            "peak_memory_bytes": int(info.get("used_memory_peak") or 0),
            "rss_memory_bytes": int(info.get("used_memory_rss") or 0),
            "maxmemory_bytes": int(info.get("maxmemory") or 0),
            "maxmemory_policy": info.get("maxmemory_policy") or "",
            "key_count": key_count,
            "hit_count": hits,
            "miss_count": misses,
            "hit_rate": (hits / total) if total else 0.0,
            "evicted_keys": int(info.get("evicted_keys") or 0),
            "expired_keys": int(info.get("expired_keys") or 0),
            "connected_clients": int(info.get("connected_clients") or 0),
            "ops_per_second": float(info.get("instantaneous_ops_per_sec") or 0),
            "latency_ms": (perf_counter() - started) * 1000,
        }


def get_cache_backend() -> CacheBackend:
    global _cache_backend
    if _cache_backend is not None:
        return _cache_backend
    with _cache_lock:
        if _cache_backend is not None:
            return _cache_backend
        settings = get_settings()
        backend = (settings.cache_backend or "none").strip().lower()
        if backend in {"", "none", "disabled", "off", "false"}:
            _cache_backend = NullCache()
        elif backend == "valkey":
            _cache_backend = ValkeyCache(settings.cache_url)
        else:
            logger.warning("Unknown MEDUSA_CACHE_BACKEND=%s; disabling response cache.", settings.cache_backend)
            _cache_backend = NullCache()
        return _cache_backend


def cache_settings() -> tuple[int, int]:
    settings = get_settings()
    return max(1, settings.cache_ttl_seconds), max(1024, settings.cache_max_payload_bytes)


def _cache_revision_table_available(session: Session) -> bool:
    try:
        return inspect(session.connection()).has_table(CacheRevision.__tablename__)
    except Exception:
        logger.debug("Could not inspect cache revision table availability.", exc_info=True)
        return False


def current_cache_revisions(db: Session, families: list[str] | tuple[str, ...] | set[str]) -> dict[str, int]:
    requested = [family for family in dict.fromkeys([CACHE_GLOBAL_FAMILY, *families]) if family]
    if not _cache_revision_table_available(db):
        return {family: 0 for family in requested}
    rows = db.query(CacheRevision).filter(CacheRevision.family.in_(requested)).all()
    versions = {row.family: int(row.version or 0) for row in rows}
    return {family: versions.get(family, 0) for family in requested}


def cache_key(family: str, key_parts: dict[str, Any], revisions: dict[str, int]) -> str:
    payload = {
        "schema": CACHE_KEY_SCHEMA_VERSION,
        "family": family,
        "key": key_parts,
        "revisions": revisions,
    }
    digest = hashlib.sha256(_json_bytes(payload)).hexdigest()
    return f"medusa:cache:{CACHE_KEY_SCHEMA_VERSION}:{family}:{digest}"


def get_cached_payload(
    db: Session,
    *,
    family: str,
    revision_families: list[str] | tuple[str, ...] | set[str],
    key_parts: dict[str, Any],
) -> tuple[str, Any | None, str, dict[str, int]]:
    revisions = current_cache_revisions(db, revision_families)
    key = cache_key(family, key_parts, revisions)
    status, payload = get_cache_backend().get_json(key, family)
    return status, payload, key, revisions


def set_cached_payload(key: str, family: str, payload: Any) -> str:
    ttl_seconds, max_payload_bytes = cache_settings()
    return get_cache_backend().set_json(key, family, payload, ttl_seconds, max_payload_bytes)


def _insert_statement(session: Session, family: str, reason: str | None):
    bind = session.get_bind()
    now = utc_now()
    values = {"family": family, "version": 1, "updated_at": now, "reason": reason}
    if bind.dialect.name == "postgresql":
        statement = pg_insert(CacheRevision).values(**values)
        return statement.on_conflict_do_update(
            index_elements=[CacheRevision.family],
            set_={
                "version": CacheRevision.version + 1,
                "updated_at": now,
                "reason": reason,
            },
        )
    if bind.dialect.name == "sqlite":
        statement = sqlite_insert(CacheRevision).values(**values)
        return statement.on_conflict_do_update(
            index_elements=[CacheRevision.family],
            set_={
                "version": CacheRevision.version + 1,
                "updated_at": now,
                "reason": reason,
            },
        )
    return None


def bump_cache_revisions(session: Session, families: list[str] | tuple[str, ...] | set[str], reason: str | None = None) -> None:
    requested_families = {family for family in families if family in CACHE_ALL_REVISION_FAMILIES}
    unique_families = [family for family in CACHE_ALL_REVISION_FAMILIES if family in requested_families]
    if not unique_families:
        return
    if not _cache_revision_table_available(session):
        return
    session.info["_medusa_cache_revision_upsert"] = True
    try:
        with session.no_autoflush:
            for family in unique_families:
                statement = _insert_statement(session, family, reason)
                if statement is not None:
                    session.execute(statement)
                else:
                    row = session.get(CacheRevision, family)
                    if row:
                        row.version = int(row.version or 0) + 1
                        row.updated_at = utc_now()
                        row.reason = reason
                    else:
                        session.add(CacheRevision(family=family, version=1, reason=reason))
    finally:
        session.info.pop("_medusa_cache_revision_upsert", None)


def mark_cache_families_dirty(session: Session, families: list[str] | tuple[str, ...] | set[str], reason: str = "mutation") -> None:
    if session.info.get("_medusa_cache_revision_upsert"):
        return
    dirty = set(session.info.get("medusa_cache_dirty_families", set()))
    dirty.update(family for family in families if family in CACHE_REVISION_FAMILIES)
    if dirty:
        session.info["medusa_cache_dirty_families"] = dirty
        session.info.setdefault("medusa_cache_dirty_reason", reason)


def _collect_families_from_session(session: Session) -> None:
    families: set[str] = set()
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        obj_families = MODEL_CACHE_FAMILIES.get(obj.__class__.__name__)
        if obj_families:
            families.update(obj_families)
    if families:
        mark_cache_families_dirty(session, families, reason="orm_mutation")


def install_cache_revision_hooks() -> None:
    global _revision_hooks_installed
    if _revision_hooks_installed:
        return
    _revision_hooks_installed = True

    @event.listens_for(SQLAlchemySession, "before_flush")
    def before_flush(session: Session, flush_context: Any, instances: Any) -> None:  # noqa: ARG001
        if session.info.get("_medusa_cache_revision_upsert"):
            return
        _collect_families_from_session(session)

    @event.listens_for(SQLAlchemySession, "do_orm_execute")
    def do_orm_execute(execute_state: Any) -> None:
        session = execute_state.session
        if session.info.get("_medusa_cache_revision_upsert"):
            return
        if execute_state.is_update or execute_state.is_delete or execute_state.is_insert:
            mark_cache_families_dirty(session, CACHE_REVISION_FAMILIES, reason="bulk_mutation")

    @event.listens_for(SQLAlchemySession, "before_commit")
    def before_commit(session: Session) -> None:
        if session.info.get("_medusa_cache_revision_upsert"):
            return
        _collect_families_from_session(session)
        dirty = set(session.info.pop("medusa_cache_dirty_families", set()))
        reason = session.info.pop("medusa_cache_dirty_reason", "mutation")
        if dirty:
            bump_cache_revisions(session, dirty, reason=reason)

    @event.listens_for(SQLAlchemySession, "after_rollback")
    def after_rollback(session: Session) -> None:
        session.info.pop("medusa_cache_dirty_families", None)
        session.info.pop("medusa_cache_dirty_reason", None)


def last_cache_invalidation_at(db: Session) -> datetime | None:
    if not _cache_revision_table_available(db):
        return None
    return db.query(func.max(CacheRevision.updated_at)).scalar()


def database_footprints(db: Session) -> list[dict[str, Any]]:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return []
    try:
        result = db.execute(
            text(
                """
                SELECT
                  c.relname AS name,
                  CASE WHEN c.relkind = 'i' THEN 'index' ELSE 'table' END AS kind,
                  pg_total_relation_size(c.oid) AS total_bytes,
                  pg_relation_size(c.oid) AS relation_bytes
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'i', 'm')
                ORDER BY pg_total_relation_size(c.oid) DESC
                LIMIT 10
                """
            )
        ).mappings()
        return [
            {
                "name": row["name"],
                "kind": row["kind"],
                "total_bytes": int(row["total_bytes"] or 0),
                "relation_bytes": int(row["relation_bytes"] or 0),
            }
            for row in result
        ]
    except SQLAlchemyError:
        logger.debug("Database footprint query failed.", exc_info=True)
        return []


def _path_size(path: Path) -> tuple[bool, int, int]:
    if not path.exists():
        return False, 0, 0
    if path.is_file():
        try:
            return True, path.stat().st_size, 1
        except OSError:
            return True, 0, 1
    total_size = 0
    file_count = 0
    for root, _, files in os.walk(path):
        for name in files:
            candidate = Path(root) / name
            try:
                total_size += candidate.stat().st_size
                file_count += 1
            except OSError:
                continue
    return True, total_size, file_count


def storage_footprints() -> list[dict[str, Any]]:
    settings = get_settings()
    data_dir = settings.data_dir
    paths = [
        ("Originals", settings.local_storage_dir),
        ("Processing cache", data_dir / "processing-cache"),
        ("Model cache", Path(os.environ.get("XDG_CACHE_HOME") or data_dir / "model-cache")),
        ("Backups", data_dir / "backups"),
    ]
    rows = []
    for label, path in paths:
        exists, size_bytes, file_count = _path_size(path)
        rows.append(
            {
                "label": label,
                "path": str(path),
                "exists": exists,
                "size_bytes": size_bytes,
                "file_count": file_count,
            }
        )
    return rows


def queue_stats(db: Session) -> list[dict[str, Any]]:
    now = utc_now()
    specs = [
        ("Imports", ImportJob, ("queued", "running")),
        ("Concordance", ConcordanceJob, ("queued", "running")),
        ("Accessory summaries", DocumentAccessorySummary, ("queued", "running")),
        ("Slipstream leases", SlipstreamLease, ("active",)),
    ]
    rows = []
    for label, model, statuses in specs:
        active = db.query(model).filter(model.status.in_(statuses))
        count = active.count()
        oldest = active.order_by(model.created_at.asc()).first()
        rows.append(
            {
                "queue": label,
                "active_count": int(count or 0),
                "oldest_age_seconds": int((now - oldest.created_at).total_seconds()) if oldest and oldest.created_at else None,
            }
        )
    online_clients = [client for client in db.query(SlipstreamClient).all() if client_is_online(client)]
    rows.append(
        {
            "queue": "Slipstream clients",
            "active_count": len(online_clients),
            "oldest_age_seconds": None,
        }
    )
    return rows


def cache_status_payload(db: Session, request_metrics: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    backend_status = get_cache_backend().status()
    last_refresh = get_cache_backend().last_refresh_at()
    last_hydration = get_cache_backend().last_hydration_at()
    last_invalidation = last_cache_invalidation_at(db)
    payload = {
        "checked_at": utc_now(),
        "backend": backend_status.get("backend", "none"),
        "enabled": bool(backend_status.get("enabled")),
        "reachable": bool(backend_status.get("reachable")),
        "mode": backend_status.get("mode", "disabled"),
        "message": backend_status.get("message", ""),
        "version": backend_status.get("version"),
        "uptime_seconds": backend_status.get("uptime_seconds"),
        "used_memory_bytes": backend_status.get("used_memory_bytes"),
        "peak_memory_bytes": backend_status.get("peak_memory_bytes"),
        "rss_memory_bytes": backend_status.get("rss_memory_bytes"),
        "maxmemory_bytes": backend_status.get("maxmemory_bytes"),
        "maxmemory_policy": backend_status.get("maxmemory_policy"),
        "key_count": backend_status.get("key_count", 0),
        "hit_count": backend_status.get("hit_count", 0),
        "miss_count": backend_status.get("miss_count", 0),
        "hit_rate": backend_status.get("hit_rate", 0.0),
        "evicted_keys": backend_status.get("evicted_keys", 0),
        "expired_keys": backend_status.get("expired_keys", 0),
        "connected_clients": backend_status.get("connected_clients", 0),
        "ops_per_second": backend_status.get("ops_per_second", 0.0),
        "latency_ms": backend_status.get("latency_ms"),
        "last_refresh_at": last_refresh,
        "last_hydration_at": last_hydration,
        "last_invalidation_at": last_invalidation,
        "families": cache_family_stats(),
        "request_metrics": request_metrics or [],
        "queue_stats": queue_stats(db),
        "database_footprints": database_footprints(db),
        "storage_footprints": storage_footprints(),
    }
    return payload
