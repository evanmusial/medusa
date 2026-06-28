from __future__ import annotations

import json
import logging
import os
import re
import secrets
import signal
import socket
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import engine
from app.services.backups import backup_run_is_verified
from app.services.cache import storage_footprints
from app.services.document_cache import current_document_cache_usage
from app.services.haproxy_stats import haproxy_stats_status


logger = logging.getLogger("medusa.metrics")

METRIC_PREFIX = "medusa_"
LIBRARY_VISIBLE_STATUSES = ("ready", "complete", "completed", "restored")
ACTIVE_JOB_STATUSES = ("queued", "running")
CORE_TABLES = (
    "documents",
    "document_pages",
    "text_chunks",
    "figures",
    "annotations",
    "notes",
    "domains",
    "tags",
    "tag_aliases",
    "tag_relationships",
    "document_tag_assessments",
    "projects",
    "project_items",
    "project_bibliographies",
    "portfolio_items",
    "portfolio_versions",
    "portfolio_materials",
    "portfolio_suggestions",
    "portfolio_assessment_runs",
    "portfolio_assessment_findings",
    "document_recommendations",
    "doi_stashes",
    "import_batches",
    "import_jobs",
    "concordance_runs",
    "concordance_jobs",
    "document_capabilities",
    "document_accessory_summaries",
    "slipstream_clients",
    "slipstream_leases",
    "processing_events",
    "openai_usage_records",
    "document_composition_records",
    "model_pricing_records",
    "backup_runs",
)

_LAST_COLLECTOR_SUCCESS: dict[str, float] = {}
_HEAVY_SNAPSHOT_KEY = "medusa:metrics:heavy_snapshot:v1"
_HEAVY_SNAPSHOT_CACHE: dict[str, Any] | None = None
_HEAVY_SNAPSHOT_LOCK = threading.Lock()
_HEAVY_SNAPSHOT_REFRESH_STOP = threading.Event()
_HEAVY_SNAPSHOT_REFRESH_THREAD: threading.Thread | None = None
_SHUTDOWN = False

_COUNT_SUFFIX_RENAMES = {
    "accessory_summary_count": "accessory_summary_records",
    "annotation_count": "annotations",
    "attribute_definition_count": "attribute_definitions",
    "backend_process_count": "backend_processes",
    "backend_route_sample_count": "backend_route_samples",
    "backend_route_slow_count": "backend_route_slow_requests",
    "backend_thread_count": "backend_threads",
    "backup_run_count": "backup_runs",
    "concordance_job_count": "concordance_jobs",
    "concordance_run_count": "concordance_runs",
    "concordance_run_job_count": "concordance_run_jobs",
    "database_maintenance_document_hash_missing_count": "database_maintenance_document_hash_missing_records",
    "database_maintenance_hidden_project_item_count": "database_maintenance_hidden_project_items",
    "database_maintenance_import_cache_count": "database_maintenance_import_cache_records",
    "database_maintenance_orphan_import_job_count": "database_maintenance_orphan_import_jobs",
    "database_maintenance_terminal_import_job_count": "database_maintenance_terminal_import_jobs",
    "document_attribute_value_count": "document_attribute_values",
    "document_capability_count": "document_capability_records",
    "document_domain_link_count": "document_domain_links",
    "document_page_record_count": "document_page_records",
    "document_soft_deleted_count": "document_soft_deleted_records",
    "document_tag_link_count": "document_tag_links",
    "doi_stash_count": "doi_stashes",
    "domain_count": "domains",
    "exporter_metric_sample_count": "exporter_metric_samples",
    "exporter_heavy_snapshot_sample_count": "exporter_heavy_snapshot_samples",
    "figure_count": "figures",
    "import_batch_count": "import_batches",
    "import_batch_file_count": "import_batch_files",
    "import_job_count": "import_jobs",
    "import_job_stale_running_count": "import_job_stale_running_records",
    "library_document_count": "library_documents",
    "library_duplicate_flagged_count": "library_duplicate_flagged_records",
    "library_duplicate_reference_count": "library_duplicate_references",
    "library_missing_bibliography_count": "library_missing_bibliography_records",
    "library_missing_search_text_count": "library_missing_search_text_records",
    "library_missing_summary_count": "library_missing_summary_records",
    "library_needs_review_citation_count": "library_needs_review_citations",
    "library_page_count": "library_pages",
    "library_verified_citation_count": "library_verified_citations",
    "model_pricing_current_record_count": "model_pricing_current_records",
    "note_count": "notes",
    "note_reminder_due_count": "note_reminders_due",
    "portfolio_assessment_finding_count": "portfolio_assessment_findings",
    "portfolio_assessment_run_count": "portfolio_assessment_runs",
    "portfolio_item_count": "portfolio_items",
    "portfolio_material_count": "portfolio_materials",
    "portfolio_suggestion_count": "portfolio_suggestions",
    "portfolio_version_count": "portfolio_versions",
    "project_bibliography_count": "project_bibliographies",
    "project_count": "projects",
    "project_item_count": "project_items",
    "recommendation_count": "recommendations",
    "saved_search_count": "saved_searches",
    "slipstream_client_count": "slipstream_clients",
    "slipstream_lease_count": "slipstream_leases",
    "storage_footprint_file_count": "storage_footprint_files",
    "tag_alias_count": "tag_aliases",
    "tag_assessment_count": "tag_assessments",
    "tag_count": "tags",
    "tag_relationship_count": "tag_relationships",
    "text_chunk_count": "text_chunks",
    "valkey_key_count": "valkey_keys",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return None


def _age_seconds(value: Any) -> float | None:
    timestamp = _timestamp(value)
    if timestamp is None:
        return None
    return max(0.0, time.time() - timestamp)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_number(value: Any) -> float:
    return 1.0 if bool(value) else 0.0


def _label_value(value: Any) -> str:
    if value is None or value == "":
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    text_value = str(value).strip()
    return text_value if text_value else "unknown"


def _storage_area(label: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(label or "unknown").strip().lower()).strip("_")
    return normalized or "unknown"


def _path_footprint(path: Path) -> tuple[bool, int, int]:
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


def _sql_in(values: Iterable[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _metric_name(name: str) -> str:
    renamed = _COUNT_SUFFIX_RENAMES.get(name)
    if renamed:
        return renamed
    if name.endswith("_count"):
        return f"{name[:-len('_count')]}_records"
    return name


class MetricWriter:
    def __init__(self) -> None:
        self._metadata: dict[str, tuple[str, str]] = {}
        self._samples: list[tuple[str, dict[str, str], float]] = []

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def add(
        self,
        name: str,
        value: Any,
        labels: dict[str, Any] | None = None,
        *,
        help_text: str,
        metric_type: str = "gauge",
    ) -> None:
        metric_value = _number(value)
        if metric_value is None:
            return
        name = _metric_name(name)
        metric_name = name if name.startswith(METRIC_PREFIX) else f"{METRIC_PREFIX}{name}"
        self._metadata.setdefault(metric_name, (help_text, metric_type))
        normalized_labels = {key: _label_value(label_value) for key, label_value in (labels or {}).items()}
        self._samples.append((metric_name, normalized_labels, metric_value))

    def add_info(self, name: str, labels: dict[str, Any], *, help_text: str) -> None:
        self.add(f"{name}_info", 1, labels, help_text=help_text, metric_type="gauge")

    def extend(self, other: "MetricWriter") -> None:
        for metric_name, metadata in other._metadata.items():
            self._metadata.setdefault(metric_name, metadata)
        self._samples.extend(other._samples)

    @staticmethod
    def _escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

    @staticmethod
    def _escape_help(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n")

    def render(self) -> str:
        lines: list[str] = []
        for metric_name, (help_text, metric_type) in sorted(self._metadata.items()):
            lines.append(f"# HELP {metric_name} {self._escape_help(help_text)}")
            lines.append(f"# TYPE {metric_name} {metric_type}")
            for sample_name, labels, value in self._samples:
                if sample_name != metric_name:
                    continue
                label_text = ""
                if labels:
                    pairs = ",".join(f'{key}="{self._escape_label(str(label_value))}"' for key, label_value in sorted(labels.items()))
                    label_text = f"{{{pairs}}}"
                lines.append(f"{sample_name}{label_text} {value:.12g}")
        return "\n".join(lines) + "\n"


def _rows(conn: Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql)).mappings().all()]


def _scalar(conn: Connection, sql: str) -> Any:
    return conn.execute(text(sql)).scalar()


def _attempt_bucket(value: Any) -> str:
    try:
        attempts = int(value or 0)
    except (TypeError, ValueError):
        attempts = 0
    if attempts <= 0:
        return "0"
    if attempts == 1:
        return "1"
    if attempts == 2:
        return "2"
    if attempts <= 5:
        return "3_5"
    return "6_plus"


def _word_count_sql(column: str) -> str:
    value = f"trim(coalesce({column}, ''))"
    return f"CASE WHEN {value} = '' THEN 0 ELSE length({value}) - length(replace({value}, ' ', '')) + 1 END"


def _emit_oldest_age(
    writer: MetricWriter,
    conn: Connection,
    *,
    table: str,
    status_column: str = "status",
    statuses: Iterable[str],
    labels: dict[str, Any],
    help_text: str,
) -> None:
    oldest = _scalar(
        conn,
        f"""
        SELECT min(created_at)
        FROM {table}
        WHERE {status_column} IN ({_sql_in(statuses)})
        """,
    )
    writer.add("queue_oldest_age_seconds", _age_seconds(oldest), labels, help_text=help_text)


def _emit_attempt_bucket_counts(
    writer: MetricWriter,
    metric_name: str,
    rows: Iterable[dict[str, Any]],
    *,
    label_keys: Iterable[str],
    help_text: str,
) -> None:
    buckets: dict[tuple[tuple[str, str], ...], float] = {}
    for row in rows:
        labels = {key: row[key] for key in label_keys}
        labels["attempt_bucket"] = _attempt_bucket(row.get("attempts"))
        label_tuple = tuple(sorted((key, _label_value(value)) for key, value in labels.items()))
        buckets[label_tuple] = buckets.get(label_tuple, 0.0) + float(row.get("count") or 0)
    for label_tuple, count in buckets.items():
        writer.add(metric_name, count, dict(label_tuple), help_text=help_text)


def collect_database_metrics(writer: MetricWriter) -> None:
    dialect = engine.dialect.name
    visible_statuses = _sql_in(LIBRARY_VISIBLE_STATUSES)
    with engine.connect() as conn:
        writer.add_info("database", {"dialect": dialect}, help_text="Database identity for the Medusa metrics exporter.")

        for table_name in CORE_TABLES:
            try:
                count = _scalar(conn, f"SELECT count(*) FROM {table_name}")
            except SQLAlchemyError:
                continue
            writer.add("database_table_rows", count, {"table": table_name}, help_text="Current row count for core Medusa tables.")

        if dialect == "postgresql":
            writer.add("database_size_bytes", _scalar(conn, "SELECT pg_database_size(current_database())"), help_text="Current PostgreSQL database size in bytes.")
            for row in _rows(
                conn,
                """
                SELECT
                  c.relname AS relation_name,
                  CASE WHEN c.relkind = 'i' THEN 'index' ELSE 'table' END AS relation_kind,
                  pg_total_relation_size(c.oid) AS total_bytes,
                  pg_relation_size(c.oid) AS relation_bytes,
                  coalesce(s.n_live_tup, 0) AS live_tuples,
                  coalesce(s.n_dead_tup, 0) AS dead_tuples,
                  s.last_vacuum,
                  s.last_autovacuum,
                  s.last_analyze,
                  s.last_autoanalyze
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'i', 'm')
                ORDER BY pg_total_relation_size(c.oid) DESC
                LIMIT 40
                """,
            ):
                labels = {"relation": row["relation_name"], "kind": row["relation_kind"]}
                writer.add("database_relation_size_bytes", row["total_bytes"], labels, help_text="PostgreSQL public relation total size in bytes.")
                writer.add("database_relation_heap_bytes", row["relation_bytes"], labels, help_text="PostgreSQL public relation heap or index bytes.")
                writer.add("database_relation_live_tuples", row["live_tuples"], labels, help_text="PostgreSQL estimated live tuples for public tables.")
                writer.add("database_relation_dead_tuples", row["dead_tuples"], labels, help_text="PostgreSQL estimated dead tuples for public tables.")
                latest_vacuum = row.get("last_vacuum") or row.get("last_autovacuum")
                latest_analyze = row.get("last_analyze") or row.get("last_autoanalyze")
                writer.add("database_relation_last_vacuum_timestamp_seconds", _timestamp(latest_vacuum), labels, help_text="Unix timestamp for latest vacuum by public table.")
                writer.add("database_relation_last_analyze_timestamp_seconds", _timestamp(latest_analyze), labels, help_text="Unix timestamp for latest analyze by public table.")

        for row in _rows(
            conn,
            """
            SELECT
              coalesce(document_kind, 'unknown') AS document_kind,
              coalesce(processing_status, 'unknown') AS processing_status,
              coalesce(citation_status, 'unknown') AS citation_status,
              coalesce(read_status, 'unknown') AS read_status,
              coalesce(priority, 'unknown') AS priority,
              count(*) AS count
            FROM documents
            WHERE deleted_at IS NULL
            GROUP BY document_kind, processing_status, citation_status, read_status, priority
            """,
        ):
            writer.add(
                "document_count",
                row["count"],
                {
                    "document_kind": row["document_kind"],
                    "processing_status": row["processing_status"],
                    "citation_status": row["citation_status"],
                    "read_status": row["read_status"],
                    "priority": row["priority"],
                },
                help_text="Current non-deleted document count grouped by bounded document states.",
            )
        writer.add("document_soft_deleted_count", _scalar(conn, "SELECT count(*) FROM documents WHERE deleted_at IS NOT NULL"), help_text="Current soft-deleted document count.")

        library = dict(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*) AS document_count,
                      coalesce(sum(page_count), 0) AS page_count,
                      coalesce(sum(CASE WHEN nullif(trim(coalesce(doi, '')), '') IS NOT NULL THEN 1 ELSE 0 END), 0) AS doi_count,
                      coalesce(sum(CASE WHEN citation_status = 'verified' THEN 1 ELSE 0 END), 0) AS verified_citation_count,
                      coalesce(sum(CASE WHEN citation_status = 'needs_review' THEN 1 ELSE 0 END), 0) AS needs_review_citation_count,
                      coalesce(sum(CASE WHEN rich_summary IS NULL OR trim(rich_summary) = '' THEN 1 ELSE 0 END), 0) AS missing_summary_count,
                      coalesce(sum(CASE WHEN bibliography IS NULL OR trim(bibliography) = '' THEN 1 ELSE 0 END), 0) AS missing_bibliography_count,
                      coalesce(sum(CASE WHEN search_text IS NULL OR trim(search_text) = '' THEN 1 ELSE 0 END), 0) AS missing_search_text_count,
                      coalesce(sum(CASE WHEN duplicate_count > 0 THEN 1 ELSE 0 END), 0) AS duplicate_flagged_count,
                      coalesce(sum(duplicate_count), 0) AS duplicate_reference_count,
                      coalesce(sum(length(coalesce(search_text, ''))), 0) AS indexed_character_count,
                      coalesce(sum({_word_count_sql('search_text')}), 0) AS indexed_word_count
                    FROM documents
                    WHERE deleted_at IS NULL
                      AND document_kind = 'library'
                      AND processing_status IN ({visible_statuses})
                    """
                )
            )
            .mappings()
            .one()
        )
        for key, value in library.items():
            writer.add(f"library_{key}", value, help_text="Current aggregate for library-visible documents.")

        page_text = dict(
            conn.execute(
                text(
                    f"""
                    SELECT
                      coalesce(sum(length(coalesce(p.normalized_text, p.text, ''))), 0) AS parsed_character_count,
                      coalesce(sum({_word_count_sql('coalesce(p.normalized_text, p.text)')}), 0) AS parsed_word_count
                    FROM document_pages p
                    JOIN documents d ON d.id = p.document_id
                    WHERE d.deleted_at IS NULL
                      AND d.document_kind = 'library'
                      AND d.processing_status IN ({visible_statuses})
                    """
                )
            )
            .mappings()
            .one()
        )
        for key, value in page_text.items():
            writer.add(f"library_{key}", value, help_text="Current parsed page text aggregate for library-visible documents.")

        for row in _rows(
            conn,
            f"""
            SELECT coalesce(p.text_source, 'unknown') AS text_source, p.low_text AS low_text, count(*) AS count
            FROM document_pages p
            JOIN documents d ON d.id = p.document_id
            WHERE d.deleted_at IS NULL
              AND d.document_kind = 'library'
              AND d.processing_status IN ({visible_statuses})
            GROUP BY p.text_source, p.low_text
            """,
        ):
            writer.add(
                "document_page_record_count",
                row["count"],
                {"text_source": row["text_source"], "low_text": row["low_text"]},
                help_text="Current page record count for library-visible documents.",
            )

        chunks = dict(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*) AS chunk_count,
                      coalesce(sum(token_count), 0) AS token_count,
                      coalesce(sum(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END), 0) AS embedded_chunk_count
                    FROM text_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.deleted_at IS NULL
                      AND d.document_kind = 'library'
                      AND d.processing_status IN ({visible_statuses})
                    """
                )
            )
            .mappings()
            .one()
        )
        for key, value in chunks.items():
            writer.add(f"text_{key}", value, help_text="Current text chunk aggregate for library-visible documents.")

        writer.add(
            "figure_count",
            _scalar(
                conn,
                f"""
                SELECT count(*)
                FROM figures f
                JOIN documents d ON d.id = f.document_id
                WHERE d.deleted_at IS NULL
                  AND d.document_kind = 'library'
                  AND d.processing_status IN ({visible_statuses})
                """,
            ),
            help_text="Current figure count for library-visible documents.",
        )
        for row in _rows(
            conn,
            f"""
            SELECT coalesce(a.kind, 'unknown') AS kind, count(*) AS count
            FROM annotations a
            JOIN documents d ON d.id = a.document_id
            WHERE a.deleted_at IS NULL
              AND d.deleted_at IS NULL
              AND d.document_kind = 'library'
              AND d.processing_status IN ({visible_statuses})
            GROUP BY a.kind
            """,
        ):
            writer.add("annotation_count", row["count"], {"kind": row["kind"]}, help_text="Current active annotation count for library-visible documents.")

        for row in _rows(
            conn,
            """
            SELECT
              coalesce(kind, 'unknown') AS kind,
              CASE
                WHEN document_id IS NOT NULL THEN 'document'
                WHEN domain_id IS NOT NULL THEN 'domain'
                WHEN project_id IS NOT NULL THEN 'project'
                ELSE 'library'
              END AS target,
              count(*) AS count
            FROM notes
            WHERE deleted_at IS NULL
            GROUP BY kind, target
            """,
        ):
            writer.add("note_count", row["count"], {"kind": row["kind"], "target": row["target"]}, help_text="Current active note count grouped by kind and attachment target.")
        writer.add("note_reminder_due_count", _scalar(conn, "SELECT count(*) FROM notes WHERE deleted_at IS NULL AND reminder_at IS NOT NULL AND reminder_at <= CURRENT_TIMESTAMP"), help_text="Current active notes with due reminders.")

        for row in _rows(conn, "SELECT CASE WHEN parent_id IS NULL THEN 'root' ELSE 'child' END AS scope, count(*) AS count FROM domains WHERE deleted_at IS NULL GROUP BY scope"):
            writer.add("domain_count", row["count"], {"scope": row["scope"]}, help_text="Current active domain count.")
        for row in _rows(conn, "SELECT coalesce(kind, 'unknown') AS kind, coalesce(status, 'unknown') AS status, count(*) AS count FROM tags GROUP BY kind, status"):
            writer.add("tag_count", row["count"], {"kind": row["kind"], "status": row["status"]}, help_text="Current tag count.")
        writer.add("tag_alias_count", _scalar(conn, "SELECT count(*) FROM tag_aliases"), help_text="Current tag alias count.")
        for row in _rows(conn, "SELECT coalesce(relationship_type, 'unknown') AS relationship_type, coalesce(status, 'unknown') AS status, count(*) AS count FROM tag_relationships GROUP BY relationship_type, status"):
            writer.add("tag_relationship_count", row["count"], {"relationship_type": row["relationship_type"], "status": row["status"]}, help_text="Current tag relationship count.")
        for row in _rows(conn, "SELECT coalesce(source, 'unknown') AS source, coalesce(decision, 'unknown') AS decision, coalesce(status, 'unknown') AS status, count(*) AS count FROM document_tag_assessments GROUP BY source, decision, status"):
            writer.add("tag_assessment_count", row["count"], {"source": row["source"], "decision": row["decision"], "status": row["status"]}, help_text="Current document tag assessment count.")
        writer.add("document_tag_link_count", _scalar(conn, "SELECT count(*) FROM document_tags"), help_text="Current document-tag link count.")
        writer.add("document_domain_link_count", _scalar(conn, "SELECT count(*) FROM document_domains"), help_text="Current document-domain link count.")
        writer.add("saved_search_count", _scalar(conn, "SELECT count(*) FROM saved_searches WHERE deleted_at IS NULL"), help_text="Current active saved search count.")
        for row in _rows(conn, "SELECT coalesce(value_type, 'unknown') AS value_type, count(*) AS count FROM attribute_definitions WHERE deleted_at IS NULL GROUP BY value_type"):
            writer.add("attribute_definition_count", row["count"], {"value_type": row["value_type"]}, help_text="Current active attribute definition count.")
        writer.add("document_attribute_value_count", _scalar(conn, "SELECT count(*) FROM document_attribute_values"), help_text="Current document attribute value count.")

        for row in _rows(conn, "SELECT coalesce(status, 'unknown') AS status, count(*) AS count FROM projects WHERE deleted_at IS NULL GROUP BY status"):
            writer.add("project_count", row["count"], {"status": row["status"]}, help_text="Current active project count.")
        for row in _rows(conn, "SELECT coalesce(status, 'unknown') AS status, coalesce(priority, 'unknown') AS priority, used_in_output AS used_in_output, count(*) AS count FROM project_items GROUP BY status, priority, used_in_output"):
            writer.add("project_item_count", row["count"], {"status": row["status"], "priority": row["priority"], "used_in_output": row["used_in_output"]}, help_text="Current project resource count.")
        writer.add("project_bibliography_count", _scalar(conn, "SELECT count(*) FROM project_bibliographies"), help_text="Current generated project bibliography count.")

        portfolio_queries = (
            ("portfolio_item_count", "SELECT coalesce(status, 'unknown') AS status, count(*) AS count FROM portfolio_items WHERE deleted_at IS NULL GROUP BY status"),
            ("portfolio_version_count", "SELECT coalesce(processing_status, 'unknown') AS processing_status, count(*) AS count FROM portfolio_versions GROUP BY processing_status"),
            ("portfolio_material_count", "SELECT coalesce(role, 'unknown') AS role, required_for_assessment AS required_for_assessment, count(*) AS count FROM portfolio_materials WHERE deleted_at IS NULL GROUP BY role, required_for_assessment"),
            ("portfolio_suggestion_count", "SELECT coalesce(status, 'unknown') AS status, coalesce(relation_family, 'unknown') AS relation_family, count(*) AS count FROM portfolio_suggestions GROUP BY status, relation_family"),
            ("portfolio_assessment_run_count", "SELECT coalesce(status, 'unknown') AS status, coalesce(mode, 'unknown') AS mode, count(*) AS count FROM portfolio_assessment_runs GROUP BY status, mode"),
            ("portfolio_assessment_finding_count", "SELECT coalesce(status, 'unknown') AS status, coalesce(severity, 'unknown') AS severity, count(*) AS count FROM portfolio_assessment_findings GROUP BY status, severity"),
        )
        for metric_name, sql in portfolio_queries:
            for row in _rows(conn, sql):
                labels = {key: value for key, value in row.items() if key != "count"}
                writer.add(metric_name, row["count"], labels, help_text="Current Portfolio workspace aggregate count.")

        recommendation_family_sql = "coalesce(raw_metadata #>> '{recommendations_v2,relation_family}', 'unknown')"
        recommendation_known_sql = "coalesce(raw_metadata #>> '{recommendations_v2,known_status}', 'unknown')"
        if dialect == "sqlite":
            recommendation_family_sql = "coalesce(json_extract(raw_metadata, '$.recommendations_v2.relation_family'), 'unknown')"
            recommendation_known_sql = "coalesce(json_extract(raw_metadata, '$.recommendations_v2.known_status'), 'unknown')"
        try:
            recommendation_rows = _rows(
                conn,
                f"""
                SELECT
                  coalesce(source_provider, 'unknown') AS provider,
                  coalesce(status, 'unknown') AS status,
                  {recommendation_family_sql} AS relation_family,
                  {recommendation_known_sql} AS known_status,
                  CASE WHEN pdf_url IS NULL OR trim(pdf_url) = '' THEN 'false' ELSE 'true' END AS open_pdf_available,
                  count(*) AS count
                FROM document_recommendations
                GROUP BY source_provider, status, relation_family, known_status, open_pdf_available
                """,
            )
        except SQLAlchemyError:
            recommendation_rows = _rows(
                conn,
                """
                SELECT
                  coalesce(source_provider, 'unknown') AS provider,
                  coalesce(status, 'unknown') AS status,
                  CASE WHEN pdf_url IS NULL OR trim(pdf_url) = '' THEN 'false' ELSE 'true' END AS open_pdf_available,
                  count(*) AS count
                FROM document_recommendations
                GROUP BY source_provider, status, open_pdf_available
                """,
            )
        for row in recommendation_rows:
            writer.add(
                "recommendation_count",
                row["count"],
                {
                    "provider": row["provider"],
                    "status": row["status"],
                    "relation_family": row.get("relation_family", "unknown"),
                    "known_status": row.get("known_status", "unknown"),
                    "open_pdf_available": row["open_pdf_available"],
                },
                help_text="Current related-paper recommendation count.",
            )

        for row in _rows(
            conn,
            """
            SELECT
              coalesce(source_provider, 'unknown') AS provider,
              coalesce(status, 'unknown') AS status,
              CASE
                WHEN imported_document_id IS NOT NULL THEN 'imported'
                WHEN import_job_id IS NOT NULL THEN 'queued'
                ELSE 'none'
              END AS import_state,
              count(*) AS count
            FROM doi_stashes
            WHERE deleted_at IS NULL
            GROUP BY source_provider, status, import_state
            """,
        ):
            writer.add("doi_stash_count", row["count"], {"provider": row["provider"], "status": row["status"], "import_state": row["import_state"]}, help_text="Current DOI stash count.")

        _emit_attempt_bucket_counts(
            writer,
            "import_job_count",
            _rows(conn, "SELECT coalesce(status, 'unknown') AS status, coalesce(current_step, 'unknown') AS current_step, attempts, count(*) AS count FROM import_jobs GROUP BY status, current_step, attempts"),
            label_keys=("status", "current_step"),
            help_text="Current import job count.",
        )
        _emit_oldest_age(writer, conn, table="import_jobs", statuses=ACTIVE_JOB_STATUSES, labels={"queue": "import"}, help_text="Oldest active queue item age in seconds.")
        stale_cutoff = time.time() - max(1, get_settings().worker_stale_job_seconds)
        stale_running = 0
        for row in _rows(conn, "SELECT locked_at FROM import_jobs WHERE status = 'running' AND locked_at IS NOT NULL"):
            locked_at = _timestamp(row.get("locked_at"))
            if locked_at is not None and locked_at < stale_cutoff:
                stale_running += 1
        writer.add("import_job_stale_running_count", stale_running, help_text="Current running import jobs with a lock older than the configured stale-job threshold.")
        for row in _rows(conn, "SELECT coalesce(status, 'unknown') AS status, count(*) AS count, coalesce(sum(total_files), 0) AS total_files, coalesce(sum(completed_files), 0) AS completed_files, coalesce(sum(failed_files), 0) AS failed_files FROM import_batches GROUP BY status"):
            labels = {"status": row["status"]}
            writer.add("import_batch_count", row["count"], labels, help_text="Current import batch count.")
            for field in ("total_files", "completed_files", "failed_files"):
                writer.add("import_batch_file_count", row[field], {**labels, "state": field.removesuffix("_files")}, help_text="Current import batch file progress count.")

        for row in _rows(conn, "SELECT coalesce(status, 'unknown') AS status, coalesce(scope_type, 'unknown') AS scope_type, count(*) AS count, coalesce(sum(total_jobs), 0) AS total_jobs, coalesce(sum(completed_jobs), 0) AS completed_jobs, coalesce(sum(failed_jobs), 0) AS failed_jobs FROM concordance_runs GROUP BY status, scope_type"):
            labels = {"status": row["status"], "scope_type": row["scope_type"]}
            writer.add("concordance_run_count", row["count"], labels, help_text="Current Concordance run count.")
            for field in ("total_jobs", "completed_jobs", "failed_jobs"):
                writer.add("concordance_run_job_count", row[field], {**labels, "state": field.removesuffix("_jobs")}, help_text="Current Concordance run job progress count.")
        _emit_attempt_bucket_counts(
            writer,
            "concordance_job_count",
            _rows(conn, "SELECT coalesce(capability_key, 'unknown') AS capability_key, coalesce(status, 'unknown') AS status, target_version, attempts, count(*) AS count FROM concordance_jobs GROUP BY capability_key, status, target_version, attempts"),
            label_keys=("capability_key", "status", "target_version"),
            help_text="Current Concordance job count.",
        )
        _emit_oldest_age(writer, conn, table="concordance_jobs", statuses=ACTIVE_JOB_STATUSES, labels={"queue": "concordance"}, help_text="Oldest active queue item age in seconds.")
        for row in _rows(conn, "SELECT coalesce(capability_key, 'unknown') AS capability_key, coalesce(status, 'unknown') AS status, version, count(*) AS count FROM document_capabilities GROUP BY capability_key, status, version"):
            writer.add("document_capability_count", row["count"], {"capability_key": row["capability_key"], "status": row["status"], "version": str(row["version"])}, help_text="Current document capability completion count.")
        _emit_attempt_bucket_counts(
            writer,
            "accessory_summary_count",
            _rows(conn, "SELECT coalesce(status, 'unknown') AS status, coalesce(model, 'unknown') AS model, attempts, count(*) AS count FROM document_accessory_summaries GROUP BY status, model, attempts"),
            label_keys=("status", "model"),
            help_text="Current document Inquest/accessory summary count.",
        )

        for row in _rows(conn, "SELECT coalesce(status, 'unknown') AS status, count(*) AS count, coalesce(sum(capacity), 0) AS capacity FROM slipstream_clients GROUP BY status"):
            writer.add("slipstream_client_count", row["count"], {"status": row["status"]}, help_text="Current Slipstream client count.")
            writer.add("slipstream_client_capacity", row["capacity"], {"status": row["status"]}, help_text="Current Slipstream client declared capacity.")
        for row in _rows(conn, "SELECT coalesce(job_type, 'unknown') AS job_type, coalesce(worker_kind, 'unknown') AS worker_kind, coalesce(status, 'unknown') AS status, count(*) AS count FROM slipstream_leases GROUP BY job_type, worker_kind, status"):
            writer.add("slipstream_lease_count", row["count"], {"job_type": row["job_type"], "worker_kind": row["worker_kind"], "status": row["status"]}, help_text="Current Slipstream lease count.")

        for row in _rows(conn, "SELECT coalesce(level, 'unknown') AS level, coalesce(event_type, 'unknown') AS event_type, count(*) AS count FROM processing_events GROUP BY level, event_type"):
            writer.add("processing_event_count", row["count"], {"level": row["level"], "event_type": row["event_type"]}, help_text="Current processing event count by bounded event type.")

        for row in _rows(conn, "SELECT coalesce(kind, 'unknown') AS kind, coalesce(status, 'unknown') AS status, coalesce(phase, 'unknown') AS phase, count(*) AS count FROM backup_runs GROUP BY kind, status, phase"):
            writer.add("backup_run_count", row["count"], {"kind": row["kind"], "status": row["status"], "phase": row["phase"]}, help_text="Current backup/restore run count.")
        latest_backup = conn.execute(
            text(
                """
                SELECT status, phase, size_bytes, completed_at, backup_metadata, gcs_uri, sha256
                FROM backup_runs
                WHERE kind = 'backup'
                ORDER BY completed_at DESC, created_at DESC
                LIMIT 1
                """
            )
        ).mappings().first()
        if latest_backup:
            labels = {"status": latest_backup["status"], "phase": latest_backup["phase"]}
            writer.add("backup_latest_size_bytes", latest_backup["size_bytes"], labels, help_text="Latest database backup size in bytes.")
            writer.add("backup_latest_age_seconds", _age_seconds(latest_backup["completed_at"]), labels, help_text="Age of the latest completed database backup in seconds.")

            class _BackupLike:
                status = latest_backup["status"]
                gcs_uri = latest_backup["gcs_uri"]
                sha256 = latest_backup["sha256"]
                size_bytes = latest_backup["size_bytes"]
                backup_metadata = latest_backup["backup_metadata"] or {}

            writer.add("backup_latest_verified", _bool_number(backup_run_is_verified(_BackupLike())), labels, help_text="Whether the latest database backup carries verification evidence.")

        for row in _rows(conn, "SELECT coalesce(provider, 'unknown') AS provider, coalesce(model, 'unknown') AS model, coalesce(task_key, 'unknown') AS task_key, coalesce(status, 'unknown') AS status, coalesce(source, 'unknown') AS source, count(*) AS request_count, coalesce(sum(input_tokens), 0) AS input_tokens, coalesce(sum(cached_input_tokens), 0) AS cached_input_tokens, coalesce(sum(output_tokens), 0) AS output_tokens, coalesce(sum(reasoning_output_tokens), 0) AS reasoning_output_tokens, coalesce(sum(total_tokens), 0) AS total_tokens, coalesce(sum(input_file_bytes), 0) AS input_file_bytes, coalesce(sum(input_text_characters), 0) AS input_text_characters, coalesce(sum(output_text_characters), 0) AS output_text_characters FROM openai_usage_records GROUP BY provider, model, task_key, status, source"):
            labels = {"provider": row["provider"], "model": row["model"], "task_key": row["task_key"], "status": row["status"], "source": row["source"]}
            writer.add("ai_usage_request_count", row["request_count"], labels, help_text="Current AI usage ledger request count.")
            for token_type in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"):
                writer.add("ai_usage_tokens", row[token_type], {**labels, "token_type": token_type.removesuffix("_tokens")}, help_text="Current AI usage ledger token totals.")
            writer.add("ai_usage_input_file_bytes", row["input_file_bytes"], labels, help_text="Current AI usage input file-context bytes.")
            writer.add("ai_usage_text_characters", row["input_text_characters"], {**labels, "direction": "input"}, help_text="Current AI usage text character totals.")
            writer.add("ai_usage_text_characters", row["output_text_characters"], {**labels, "direction": "output"}, help_text="Current AI usage text character totals.")
        writer.add("ai_usage_last_failure_timestamp_seconds", _timestamp(_scalar(conn, "SELECT max(created_at) FROM openai_usage_records WHERE status = 'failed'")), help_text="Unix timestamp for the latest failed AI usage ledger call.")

        for row in _rows(conn, "SELECT coalesce(record_kind, 'unknown') AS record_kind, coalesce(stage_key, 'unknown') AS stage_key, coalesce(provider, 'unknown') AS provider, coalesce(model, 'unknown') AS model, coalesce(status, 'unknown') AS status, count(*) AS count, coalesce(sum(amount_usd), 0) AS amount_usd, coalesce(sum(duration_ms), 0) AS duration_ms, coalesce(sum(input_tokens), 0) AS input_tokens, coalesce(sum(output_tokens), 0) AS output_tokens, coalesce(sum(total_tokens), 0) AS total_tokens FROM document_composition_records GROUP BY record_kind, stage_key, provider, model, status"):
            labels = {"record_kind": row["record_kind"], "stage_key": row["stage_key"], "provider": row["provider"], "model": row["model"], "status": row["status"]}
            writer.add("composition_record_count", row["count"], labels, help_text="Current document composition ledger row count.")
            writer.add("composition_amount_usd", row["amount_usd"], labels, help_text="Current document composition ledger dollar amount.")
            writer.add("composition_duration_seconds", float(row["duration_ms"] or 0) / 1000.0, labels, help_text="Current document composition ledger duration seconds.")
            for token_type in ("input_tokens", "output_tokens", "total_tokens"):
                writer.add("composition_tokens", row[token_type], {**labels, "token_type": token_type.removesuffix("_tokens")}, help_text="Current document composition ledger token totals.")

        for row in _rows(conn, "SELECT coalesce(provider, 'unknown') AS provider, coalesce(price_basis, 'unknown') AS price_basis, count(*) AS count, max(last_checked_at) AS last_checked_at FROM model_pricing_records WHERE superseded_at IS NULL GROUP BY provider, price_basis"):
            labels = {"provider": row["provider"], "price_basis": row["price_basis"]}
            writer.add("model_pricing_current_record_count", row["count"], labels, help_text="Current active model pricing record count.")
            writer.add("model_pricing_last_checked_timestamp_seconds", _timestamp(row["last_checked_at"]), labels, help_text="Unix timestamp for latest model pricing check.")


def collect_storage_metrics(writer: MetricWriter) -> None:
    settings = get_settings()
    try:
        cache = current_document_cache_usage()
    except OSError:
        _, size_bytes, file_count = _path_footprint(settings.data_dir / "processing-cache")
        cache = {"current_size_bytes": size_bytes, "file_count": file_count}
    writer.add("document_cache_size_bytes", cache.get("current_size_bytes"), help_text="Current managed document cache size in bytes.")
    writer.add("document_cache_file_count", cache.get("file_count"), help_text="Current managed document cache file count.")
    writer.add("document_cache_limit_bytes", max(0, settings.document_cache_size_mb) * 1024 * 1024, help_text="Configured managed document cache size limit in bytes.")
    for row in storage_footprints():
        labels = {"storage_area": _storage_area(row.get("label"))}
        writer.add("storage_footprint_bytes", row.get("size_bytes"), labels, help_text="Current local Medusa storage footprint by bounded area.")
        writer.add("storage_footprint_files", row.get("file_count"), labels, help_text="Current local Medusa storage file count by bounded area.")
        writer.add("storage_footprint_exists", _bool_number(row.get("exists")), labels, help_text="Whether a local Medusa storage area exists.")


def collect_valkey_metrics(writer: MetricWriter) -> None:
    settings = get_settings()
    if (settings.cache_backend or "").strip().lower() != "valkey":
        writer.add("valkey_up", 0, {"backend": settings.cache_backend or "none"}, help_text="Whether Valkey is configured and reachable.")
        return
    try:
        from redis import Redis

        url = settings.cache_url
        if url.startswith("valkey://"):
            url = f"redis://{url[len('valkey://'):]}"
        client = Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=1.5, retry_on_timeout=False)
        info = client.info()
        key_count = int(client.dbsize() or 0)
    except Exception as exc:
        writer.add("valkey_up", 0, {"backend": "valkey"}, help_text="Whether Valkey is configured and reachable.")
        writer.add_info("valkey_error", {"error_class": exc.__class__.__name__}, help_text="Class of the latest Valkey exporter error.")
        return
    writer.add("valkey_up", 1, {"backend": "valkey"}, help_text="Whether Valkey is configured and reachable.")
    writer.add_info("valkey", {"version": info.get("valkey_version") or info.get("redis_version") or "unknown", "policy": info.get("maxmemory_policy") or "unknown"}, help_text="Valkey version and memory policy.")
    writer.add("valkey_uptime_seconds", info.get("uptime_in_seconds"), help_text="Valkey uptime in seconds.")
    writer.add("valkey_memory_bytes", info.get("used_memory"), {"kind": "used"}, help_text="Valkey memory by kind in bytes.")
    writer.add("valkey_memory_bytes", info.get("used_memory_peak"), {"kind": "peak"}, help_text="Valkey memory by kind in bytes.")
    writer.add("valkey_memory_bytes", info.get("used_memory_rss"), {"kind": "rss"}, help_text="Valkey memory by kind in bytes.")
    writer.add("valkey_memory_bytes", info.get("maxmemory"), {"kind": "max"}, help_text="Valkey memory by kind in bytes.")
    writer.add("valkey_key_count", key_count, help_text="Current Valkey key count.")
    writer.add("valkey_connected_clients", info.get("connected_clients"), help_text="Current Valkey connected clients.")
    writer.add("valkey_ops_per_second", info.get("instantaneous_ops_per_sec"), help_text="Current Valkey instantaneous operations per second.")
    for key in ("keyspace_hits", "keyspace_misses", "evicted_keys", "expired_keys"):
        writer.add(f"valkey_{key}_total", info.get(key), help_text=f"Valkey {key.replace('_', ' ')} total.", metric_type="counter")


def collect_haproxy_metrics(writer: MetricWriter) -> None:
    status = haproxy_stats_status()
    writer.add("haproxy_up", _bool_number(status.available), help_text="Whether HAProxy stats are reachable.")
    writer.add("haproxy_current_sessions", status.total_current_sessions, help_text="Current HAProxy frontend sessions.")
    writer.add("haproxy_sessions_total", status.total_sessions, help_text="Total HAProxy frontend sessions.", metric_type="counter")
    writer.add("haproxy_bytes_total", status.total_bytes_in, {"direction": "in"}, help_text="Total HAProxy frontend bytes.", metric_type="counter")
    writer.add("haproxy_bytes_total", status.total_bytes_out, {"direction": "out"}, help_text="Total HAProxy frontend bytes.", metric_type="counter")
    writer.add("haproxy_errors_total", status.total_errors, help_text="Total HAProxy errors/retries/denials.", metric_type="counter")
    for service in status.services:
        labels = {"proxy": service.proxy_name, "service": service.service_name, "kind": service.kind, "status": service.status or "unknown"}
        writer.add("haproxy_service_current_sessions", service.current_sessions, labels, help_text="Current HAProxy service sessions.")
        writer.add("haproxy_service_session_rate", service.session_rate, labels, help_text="Current HAProxy service session rate.")
        writer.add("haproxy_service_sessions_total", service.total_sessions, labels, help_text="Total HAProxy service sessions.", metric_type="counter")
        writer.add("haproxy_service_bytes_total", service.bytes_in, {**labels, "direction": "in"}, help_text="Total HAProxy service bytes.", metric_type="counter")
        writer.add("haproxy_service_bytes_total", service.bytes_out, {**labels, "direction": "out"}, help_text="Total HAProxy service bytes.", metric_type="counter")
        writer.add("haproxy_service_errors_total", service.error_requests + service.error_connections + service.error_responses, labels, help_text="Total HAProxy service errors.", metric_type="counter")
        writer.add("haproxy_service_denied_total", service.denied_requests + service.denied_responses, labels, help_text="Total HAProxy service denied requests/responses.", metric_type="counter")
        writer.add("haproxy_service_retries_total", service.retries, labels, help_text="Total HAProxy service retries.", metric_type="counter")
        writer.add("haproxy_service_redispatches_total", service.redispatches, labels, help_text="Total HAProxy service redispatches.", metric_type="counter")
        writer.add("haproxy_service_check_duration_seconds", None if service.check_duration_ms is None else service.check_duration_ms / 1000.0, labels, help_text="Latest HAProxy service health-check duration.")
        writer.add("haproxy_service_downtime_seconds", service.downtime_seconds, labels, help_text="HAProxy service downtime in seconds.")
        writer.add("haproxy_service_last_change_seconds", service.last_change_seconds, labels, help_text="Seconds since HAProxy service status last changed.")


def _backend_snapshot_headers() -> dict[str, str]:
    token = (get_settings().metrics_internal_token or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def collect_backend_snapshot_metrics(writer: MetricWriter) -> None:
    settings = get_settings()
    token = (settings.metrics_internal_token or "").strip()
    if not token:
        writer.add("backend_snapshot_up", 0, {"reason": "token_not_configured"}, help_text="Whether the private backend metrics snapshot is reachable.")
        return
    try:
        response = httpx.get(settings.metrics_internal_snapshot_url, headers=_backend_snapshot_headers(), timeout=4.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        writer.add("backend_snapshot_up", 0, {"reason": exc.__class__.__name__}, help_text="Whether the private backend metrics snapshot is reachable.")
        return
    writer.add("backend_snapshot_up", 1, {"reason": "ok"}, help_text="Whether the private backend metrics snapshot is reachable.")
    writer.add("backend_snapshot_age_seconds", _age_seconds(payload.get("checked_at")), help_text="Age of the private backend metrics snapshot in seconds.")

    container = payload.get("container") if isinstance(payload.get("container"), dict) else {}
    writer.add("backend_process_uptime_seconds", container.get("process_uptime_seconds"), help_text="Backend process uptime in seconds.")
    writer.add("backend_memory_bytes", container.get("memory_current_bytes"), {"kind": "cgroup_current"}, help_text="Backend memory usage by kind in bytes.")
    writer.add("backend_memory_bytes", container.get("memory_limit_bytes"), {"kind": "cgroup_limit"}, help_text="Backend memory usage by kind in bytes.")
    writer.add("backend_memory_bytes", container.get("memory_peak_bytes"), {"kind": "cgroup_peak"}, help_text="Backend memory usage by kind in bytes.")
    writer.add("backend_memory_bytes", container.get("process_rss_bytes"), {"kind": "process_rss"}, help_text="Backend memory usage by kind in bytes.")
    writer.add("backend_cpu_usage_seconds_total", container.get("cpu_usage_seconds"), help_text="Backend cgroup CPU usage seconds.", metric_type="counter")
    writer.add("backend_cpu_limit_cores", container.get("cpu_limit_cores"), help_text="Backend cgroup CPU limit in cores.")
    writer.add("backend_process_count", container.get("process_count"), help_text="Backend container process count.")
    writer.add("backend_thread_count", container.get("thread_count"), help_text="Backend process thread count.")

    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    writer.add("cache_backend_up", _bool_number(cache.get("reachable")), {"backend": cache.get("backend", "unknown")}, help_text="Whether the configured Medusa response cache backend is reachable.")
    writer.add("cache_hit_rate", cache.get("hit_rate"), {"backend": cache.get("backend", "unknown")}, help_text="Current cache backend hit rate.")
    writer.add("cache_last_refresh_timestamp_seconds", _timestamp(cache.get("last_refresh_at")), help_text="Unix timestamp for latest manual cache refresh.")
    writer.add("cache_last_hydration_timestamp_seconds", _timestamp(cache.get("last_hydration_at")), help_text="Unix timestamp for latest cache hydration.")
    writer.add("cache_last_invalidation_timestamp_seconds", _timestamp(cache.get("last_invalidation_at")), help_text="Unix timestamp for latest cache invalidation.")
    for family in cache.get("families") or []:
        if not isinstance(family, dict):
            continue
        labels = {"family": family.get("family", "unknown")}
        for event_name, key in (("hit", "hits"), ("miss", "misses"), ("bypass", "bypasses"), ("error", "errors"), ("write", "writes")):
            writer.add("cache_family_events_total", family.get(key), {**labels, "event": event_name}, help_text="Backend process-local cache family event count.", metric_type="counter")
        writer.add("cache_family_hit_rate", family.get("hit_rate"), labels, help_text="Backend process-local cache family hit rate.")
    for route in cache.get("request_metrics") or []:
        if not isinstance(route, dict):
            continue
        labels = {"route": route.get("route", "unknown")}
        writer.add("backend_route_sample_count", route.get("count"), labels, help_text="Backend route timing sample count.")
        writer.add("backend_route_average_duration_seconds", (route.get("average_ms") or 0) / 1000.0, labels, help_text="Backend route average duration in seconds.")
        writer.add("backend_route_p95_duration_seconds", (route.get("p95_ms") or 0) / 1000.0, labels, help_text="Backend route p95 duration in seconds.")
        writer.add("backend_route_slow_count", route.get("slow_count"), labels, help_text="Backend route slow request count.")
        writer.add("backend_route_last_status", route.get("last_status"), labels, help_text="Backend route latest HTTP status code.")

    maintenance = payload.get("database_maintenance") if isinstance(payload.get("database_maintenance"), dict) else {}
    writer.add("database_maintenance_active", _bool_number(maintenance.get("active_operation")), {"operation": maintenance.get("active_operation") or "none"}, help_text="Whether database maintenance is active.")
    writer.add("database_maintenance_elapsed_seconds", maintenance.get("active_operation_elapsed_seconds"), {"operation": maintenance.get("active_operation") or "none"}, help_text="Active database maintenance elapsed seconds.")
    for key in ("import_cache_count", "document_hash_missing_count", "hidden_project_item_count", "terminal_import_job_count", "orphan_import_job_count"):
        writer.add(f"database_maintenance_{key}", maintenance.get(key), help_text="Database maintenance status count.")

    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    writer.add("release_update_available", _bool_number(release.get("update_available")), {"phase": release.get("phase") or "unknown"}, help_text="Whether a Medusa release update is available.")
    writer.add("release_apply_available", _bool_number(release.get("apply_available")), {"phase": release.get("phase") or "unknown"}, help_text="Whether a Medusa release apply is available.")
    writer.add("release_browser_reload_recommended", _bool_number(release.get("browser_reload_recommended")), {"phase": release.get("phase") or "unknown"}, help_text="Whether browser reload is recommended.")
    writer.add("release_dirty", _bool_number(release.get("dirty")), {"phase": release.get("phase") or "unknown"}, help_text="Whether the host release status reports a dirty checkout.")
    writer.add("maintenance_idle", _bool_number(release.get("maintenance_idle", True)), {"phase": release.get("maintenance_phase") or "unknown"}, help_text="Whether release maintenance reports an idle app.")
    writer.add("maintenance_active_session_count", release.get("maintenance_active_session_count"), {"phase": release.get("maintenance_phase") or "unknown"}, help_text="Active session count reported by maintenance readiness.")


def _docker_socket_path() -> Path | None:
    settings = get_settings()
    raw_path = settings.metrics_docker_socket_path or os.environ.get("DOCKER_HOST", "")
    if raw_path.startswith("unix://"):
        raw_path = raw_path[len("unix://") :]
    if not raw_path:
        return None
    return Path(raw_path)


def _docker_service_name(container: dict[str, Any]) -> str:
    labels = container.get("Labels") if isinstance(container.get("Labels"), dict) else {}
    return _label_value(labels.get("com.docker.compose.service") or labels.get("com.docker.swarm.service.name") or "unknown")


def _docker_block_io_bytes(stats: dict[str, Any], operation: str) -> int:
    blkio = stats.get("blkio_stats") if isinstance(stats.get("blkio_stats"), dict) else {}
    entries = blkio.get("io_service_bytes_recursive") if isinstance(blkio.get("io_service_bytes_recursive"), list) else []
    total = 0
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("op", "")).lower() == operation.lower():
            total += int(entry.get("value") or 0)
    return total


def collect_docker_metrics(writer: MetricWriter) -> None:
    socket_path = _docker_socket_path()
    if not socket_path or not socket_path.exists():
        writer.add("docker_up", 0, {"reason": "socket_not_configured"}, help_text="Whether Docker Engine metrics are reachable.")
        return
    transport = httpx.HTTPTransport(uds=str(socket_path))
    try:
        with httpx.Client(transport=transport, base_url="http://docker", timeout=3.0) as client:
            containers = client.get("/containers/json", params={"all": "1", "size": "1"}).json()
            writer.add("docker_up", 1, {"reason": "ok"}, help_text="Whether Docker Engine metrics are reachable.")
            service_states: dict[tuple[str, str], int] = {}
            image_layers: dict[str, int] = {}
            for container in containers if isinstance(containers, list) else []:
                service = _docker_service_name(container)
                state = _label_value(container.get("State"))
                service_states[(service, state)] = service_states.get((service, state), 0) + 1
                container_id = str(container.get("Id") or "")
                if not container_id:
                    continue
                labels = {"service": service}
                image_id = str(container.get("ImageID") or "")
                if image_id and image_id not in image_layers:
                    try:
                        image_detail = client.get(f"/images/{image_id}/json").json()
                        rootfs = image_detail.get("RootFS") if isinstance(image_detail.get("RootFS"), dict) else {}
                        image_layers[image_id] = len(rootfs.get("Layers") or [])
                    except Exception:
                        image_layers[image_id] = 0
                try:
                    detail = client.get(f"/containers/{container_id}/json").json()
                    stats = client.get(f"/containers/{container_id}/stats", params={"stream": "false"}).json()
                except Exception:
                    continue
                state_detail = detail.get("State") if isinstance(detail.get("State"), dict) else {}
                writer.add("docker_container_restart_count", detail.get("RestartCount"), labels, help_text="Docker container restart count.")
                writer.add("docker_container_started_timestamp_seconds", _timestamp(state_detail.get("StartedAt")), labels, help_text="Docker container started timestamp.")
                writer.add("docker_container_image_size_bytes", container.get("SizeRootFs"), labels, help_text="Docker container root filesystem image size in bytes.")
                writer.add("docker_container_writable_layer_bytes", container.get("SizeRw"), labels, help_text="Docker container writable layer size in bytes.")
                writer.add("docker_container_image_layer_count", image_layers.get(image_id), labels, help_text="Docker image layer count for the container image.")
                memory_stats = stats.get("memory_stats") if isinstance(stats.get("memory_stats"), dict) else {}
                cpu_stats = stats.get("cpu_stats") if isinstance(stats.get("cpu_stats"), dict) else {}
                cpu_usage = cpu_stats.get("cpu_usage") if isinstance(cpu_stats.get("cpu_usage"), dict) else {}
                writer.add("docker_container_memory_bytes", memory_stats.get("usage"), {**labels, "kind": "usage"}, help_text="Docker container memory by kind in bytes.")
                writer.add("docker_container_memory_bytes", memory_stats.get("limit"), {**labels, "kind": "limit"}, help_text="Docker container memory by kind in bytes.")
                writer.add("docker_container_cpu_seconds_total", (cpu_usage.get("total_usage") or 0) / 1_000_000_000, labels, help_text="Docker container CPU usage seconds.", metric_type="counter")
                writer.add("docker_container_block_io_bytes_total", _docker_block_io_bytes(stats, "read"), {**labels, "direction": "read"}, help_text="Docker container block I/O bytes.", metric_type="counter")
                writer.add("docker_container_block_io_bytes_total", _docker_block_io_bytes(stats, "write"), {**labels, "direction": "write"}, help_text="Docker container block I/O bytes.", metric_type="counter")
                networks = stats.get("networks") if isinstance(stats.get("networks"), dict) else {}
                for network_name, network in networks.items():
                    if not isinstance(network, dict):
                        continue
                    network_labels = {**labels, "network": network_name}
                    writer.add("docker_container_network_bytes_total", network.get("rx_bytes"), {**network_labels, "direction": "rx"}, help_text="Docker container network bytes.", metric_type="counter")
                    writer.add("docker_container_network_bytes_total", network.get("tx_bytes"), {**network_labels, "direction": "tx"}, help_text="Docker container network bytes.", metric_type="counter")
            for (service, state), count in service_states.items():
                writer.add("docker_container_state_count", count, {"service": service, "state": state}, help_text="Docker container count by Compose service and state.")
    except Exception as exc:
        writer.add("docker_up", 0, {"reason": exc.__class__.__name__}, help_text="Whether Docker Engine metrics are reachable.")


Collector = Callable[[MetricWriter], None]


def _metrics_valkey_client() -> Any | None:
    settings = get_settings()
    if (settings.cache_backend or "").strip().lower() != "valkey":
        return None
    try:
        from redis import Redis

        url = settings.cache_url
        if url.startswith("valkey://"):
            url = f"redis://{url[len('valkey://'):]}"
        return Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=2.0, retry_on_timeout=False)
    except Exception:
        return None


def _heavy_snapshot_ttl_seconds() -> int:
    return max(15, int(get_settings().metrics_heavy_ttl_seconds or 900))


def _heavy_snapshot_expiry_seconds() -> int:
    ttl = _heavy_snapshot_ttl_seconds()
    return max(300, ttl * 4)


def _heavy_collectors() -> list[tuple[str, Collector]]:
    return [
        ("database", collect_database_metrics),
        ("storage", collect_storage_metrics),
        ("docker", collect_docker_metrics),
    ]


def _live_collectors() -> list[tuple[str, Collector]]:
    return [
        ("valkey", collect_valkey_metrics),
        ("haproxy", collect_haproxy_metrics),
        ("backend_snapshot", collect_backend_snapshot_metrics),
    ]


def _run_collector(writer: MetricWriter, collector_name: str, collector: Collector) -> dict[str, Any]:
    collector_started = time.monotonic()
    success = 0.0
    try:
        collector(writer)
        success = 1.0
        _LAST_COLLECTOR_SUCCESS[collector_name] = time.time()
    except Exception:
        logger.exception("Medusa metrics collector failed: %s", collector_name)
    return {
        "collector": collector_name,
        "up": success,
        "duration_seconds": time.monotonic() - collector_started,
        "last_success_timestamp_seconds": _LAST_COLLECTOR_SUCCESS.get(collector_name),
    }


def _add_collector_result(writer: MetricWriter, result: dict[str, Any], *, cached: float) -> None:
    labels = {"collector": result.get("collector", "unknown")}
    writer.add("exporter_collector_up", result.get("up", 0), labels, help_text="Whether the exporter collector succeeded on its latest run.")
    writer.add("exporter_collector_cached", cached, labels, help_text="Whether the exporter collector came from the Valkey-backed heavy snapshot.")
    writer.add("exporter_collector_duration_seconds", result.get("duration_seconds"), labels, help_text="Exporter collector duration in seconds on its latest run.")
    writer.add("exporter_collector_last_success_timestamp_seconds", result.get("last_success_timestamp_seconds"), labels, help_text="Unix timestamp for the collector's last successful run.")


def _build_heavy_snapshot() -> dict[str, Any]:
    writer = MetricWriter()
    started = time.monotonic()
    results = [_run_collector(writer, collector_name, collector) for collector_name, collector in _heavy_collectors()]
    rendered = writer.render()
    return {
        "generated_at": time.time(),
        "duration_seconds": time.monotonic() - started,
        "sample_count": writer.sample_count,
        "rendered": rendered,
        "collectors": results,
    }


def _store_heavy_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    stored_payload = dict(payload)
    stored_payload["stored_at"] = time.time()
    stored_payload["storage"] = "memory"
    client = _metrics_valkey_client()
    if client is not None:
        try:
            valkey_payload = {**stored_payload, "storage": "valkey"}
            client.set(_HEAVY_SNAPSHOT_KEY, json.dumps(valkey_payload), ex=_heavy_snapshot_expiry_seconds())
            stored_payload = valkey_payload
        except Exception:
            logger.exception("Unable to store Medusa heavy metrics snapshot in Valkey")
    global _HEAVY_SNAPSHOT_CACHE
    with _HEAVY_SNAPSHOT_LOCK:
        _HEAVY_SNAPSHOT_CACHE = stored_payload
    return stored_payload


def refresh_heavy_metrics_snapshot() -> dict[str, Any]:
    return _store_heavy_snapshot(_build_heavy_snapshot())


def _load_heavy_snapshot() -> tuple[dict[str, Any] | None, str]:
    client = _metrics_valkey_client()
    if client is not None:
        try:
            raw_payload = client.get(_HEAVY_SNAPSHOT_KEY)
            if raw_payload:
                payload = json.loads(raw_payload)
                if isinstance(payload, dict):
                    return payload, "valkey"
        except Exception:
            logger.exception("Unable to read Medusa heavy metrics snapshot from Valkey")
    with _HEAVY_SNAPSHOT_LOCK:
        if _HEAVY_SNAPSHOT_CACHE is not None:
            return dict(_HEAVY_SNAPSHOT_CACHE), "memory"
    return None, "missing"


def _heavy_snapshot_refresh_loop() -> None:
    while not _HEAVY_SNAPSHOT_REFRESH_STOP.wait(_heavy_snapshot_ttl_seconds()):
        refresh_heavy_metrics_snapshot()


def start_heavy_snapshot_refresh_thread() -> None:
    global _HEAVY_SNAPSHOT_REFRESH_THREAD
    if _HEAVY_SNAPSHOT_REFRESH_THREAD is not None and _HEAVY_SNAPSHOT_REFRESH_THREAD.is_alive():
        return
    _HEAVY_SNAPSHOT_REFRESH_STOP.clear()
    _HEAVY_SNAPSHOT_REFRESH_THREAD = threading.Thread(target=_heavy_snapshot_refresh_loop, name="medusa-metrics-heavy-snapshot", daemon=True)
    _HEAVY_SNAPSHOT_REFRESH_THREAD.start()


def collect_metrics() -> str:
    writer = MetricWriter()
    started = time.monotonic()
    writer.add_info(
        "exporter_build",
        {
            "hostname": socket.gethostname(),
            "version": os.environ.get("MEDUSA_BUILD_VERSION") or "unknown",
            "git_sha": os.environ.get("MEDUSA_GIT_SHA") or "unknown",
        },
        help_text="Medusa metrics exporter build and host identity.",
    )
    for collector_name, collector in _live_collectors():
        _add_collector_result(writer, _run_collector(writer, collector_name, collector), cached=0.0)

    snapshot_payload, snapshot_source = _load_heavy_snapshot()
    snapshot_rendered = ""
    snapshot_sample_count = 0
    if snapshot_payload and isinstance(snapshot_payload.get("rendered"), str):
        snapshot_rendered = snapshot_payload["rendered"]
        snapshot_sample_count = int(snapshot_payload.get("sample_count") or 0)
        writer.add("exporter_heavy_snapshot_up", 1, {"source": snapshot_source}, help_text="Whether the Valkey-backed heavy metrics snapshot is available.")
        writer.add("exporter_heavy_snapshot_age_seconds", max(0.0, time.time() - float(snapshot_payload.get("generated_at") or 0)), help_text="Age of the Valkey-backed heavy metrics snapshot in seconds.")
        writer.add("exporter_heavy_snapshot_duration_seconds", snapshot_payload.get("duration_seconds"), help_text="Time spent generating the latest heavy metrics snapshot.")
        writer.add("exporter_heavy_snapshot_sample_count", snapshot_sample_count, help_text="Number of samples in the latest heavy metrics snapshot.")
        for result in snapshot_payload.get("collectors") or []:
            if isinstance(result, dict):
                _add_collector_result(writer, result, cached=1.0)
    else:
        writer.add("exporter_heavy_snapshot_up", 0, {"source": snapshot_source}, help_text="Whether the Valkey-backed heavy metrics snapshot is available.")
        for collector_name, _ in _heavy_collectors():
            _add_collector_result(writer, {"collector": collector_name, "up": 0}, cached=0.0)

    writer.add("exporter_scrape_duration_seconds", time.monotonic() - started, help_text="Total exporter scrape duration in seconds.")
    writer.add("exporter_scrape_timestamp_seconds", time.time(), help_text="Unix timestamp for this exporter scrape.")
    writer.add("exporter_metric_sample_count", writer.sample_count + snapshot_sample_count + 1, help_text="Number of Prometheus metric samples rendered by this scrape.")
    return writer.render() + snapshot_rendered


def _read_token_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def metrics_bearer_token() -> str | None:
    settings = get_settings()
    return (settings.metrics_bearer_token or "").strip() or _read_token_file(settings.metrics_bearer_token_file)


def _request_bearer_token(headers: Any) -> str:
    auth_header = (headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


class MetricsHandler(BaseHTTPRequestHandler):
    server_version = "MedusaMetrics/1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        logger.info("%s - %s", self.address_string(), format % args)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n", "application/json")

    def _metrics_authorized(self) -> tuple[bool, str]:
        settings = get_settings()
        expected = metrics_bearer_token()
        if not settings.metrics_require_auth:
            return True, "auth_disabled"
        if not expected:
            return False, "token_not_configured"
        provided = _request_bearer_token(self.headers)
        if not provided or not secrets.compare_digest(provided, expected):
            return False, "invalid_token"
        return True, "ok"

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            settings = get_settings()
            auth_configured = bool(metrics_bearer_token()) or not settings.metrics_require_auth
            status = HTTPStatus.OK if auth_configured else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(
                status,
                {
                    "status": "ok" if auth_configured else "missing_metrics_token",
                    "auth_required": settings.metrics_require_auth,
                    "auth_configured": auth_configured,
                    "time": _utc_now().isoformat(),
                },
            )
            return
        if path != "/metrics":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        authorized, reason = self._metrics_authorized()
        if not authorized:
            status = HTTPStatus.SERVICE_UNAVAILABLE if reason == "token_not_configured" else HTTPStatus.UNAUTHORIZED
            self._send_json(status, {"error": reason})
            return
        try:
            rendered = collect_metrics().encode("utf-8")
        except Exception as exc:
            logger.exception("Medusa metrics scrape failed")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": exc.__class__.__name__})
            return
        self._send(HTTPStatus.OK, rendered, "text/plain; version=0.0.4; charset=utf-8")


def _install_signal_handlers(server: ThreadingHTTPServer) -> None:
    def stop(_: int, __: Any) -> None:
        global _SHUTDOWN
        _SHUTDOWN = True
        _HEAVY_SNAPSHOT_REFRESH_STOP.set()
        server.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main() -> None:
    logging.basicConfig(level=os.environ.get("MEDUSA_METRICS_LOG_LEVEL", "INFO"))
    settings = get_settings()
    address = (settings.metrics_bind_host, int(settings.metrics_port))
    server = ThreadingHTTPServer(address, MetricsHandler)
    _install_signal_handlers(server)
    logger.info("Seeding Medusa heavy metrics snapshot")
    try:
        refresh_heavy_metrics_snapshot()
    except Exception:
        logger.exception("Initial Medusa heavy metrics snapshot failed")
    start_heavy_snapshot_refresh_thread()
    logger.info("Starting Medusa metrics exporter on %s:%s", address[0], address[1])
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
