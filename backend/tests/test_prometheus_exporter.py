from datetime import datetime, timezone
import json
import time

import pytest


class DummyRequest:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


def test_metric_writer_escapes_labels_and_help(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.tools.prometheus_exporter import MetricWriter

    writer = MetricWriter()
    writer.add(
        "sample_total",
        3,
        {"label": 'quoted "value"\nwith \\ slash', "enabled": True},
        help_text="sample help\nwith newline",
        metric_type="counter",
    )
    writer.add("skipped", None, help_text="not emitted")

    rendered = writer.render()

    assert "# HELP medusa_sample_total sample help\\nwith newline" in rendered
    assert "# TYPE medusa_sample_total counter" in rendered
    assert 'enabled="true"' in rendered
    assert 'label="quoted \\"value\\"\\nwith \\\\ slash"' in rendered
    assert "medusa_sample_total" in rendered
    assert "medusa_skipped" not in rendered


def test_metrics_bearer_token_reads_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    token_file = tmp_path / "token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    monkeypatch.delenv("MEDUSA_METRICS_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("MEDUSA_METRICS_BEARER_TOKEN_FILE", str(token_file))

    from app.config import get_settings
    from app.tools.prometheus_exporter import metrics_bearer_token

    get_settings.cache_clear()

    assert metrics_bearer_token() == "secret-token"


def test_backend_snapshot_collector_reports_down_without_internal_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_METRICS_INTERNAL_TOKEN", "")

    from app.config import get_settings
    from app.tools.prometheus_exporter import MetricWriter, collect_backend_snapshot_metrics

    get_settings.cache_clear()
    writer = MetricWriter()

    collect_backend_snapshot_metrics(writer)

    assert 'medusa_backend_snapshot_up{reason="token_not_configured"} 0' in writer.render()


def test_backend_snapshot_metrics_are_promtool_friendly(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_METRICS_INTERNAL_TOKEN", "secret")

    from app.config import get_settings
    from app.tools import prometheus_exporter

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "checked_at": "2026-06-28T18:00:00+00:00",
                "container": {"cpu_usage_seconds": 9},
                "cache": {
                    "request_metrics": [
                        {"route": "/api/health", "count": 2, "average_ms": 120, "p95_ms": 250, "slow_count": 0, "last_status": 200}
                    ]
                },
            }

    get_settings.cache_clear()
    monkeypatch.setattr(prometheus_exporter.httpx, "get", lambda *args, **kwargs: FakeResponse())
    writer = prometheus_exporter.MetricWriter()

    prometheus_exporter.collect_backend_snapshot_metrics(writer)
    rendered = writer.render()

    assert "medusa_backend_cpu_usage_seconds_total 9" in rendered
    assert 'medusa_backend_route_average_duration_seconds{route="/api/health"} 0.12' in rendered
    assert 'medusa_backend_route_p95_duration_seconds{route="/api/health"} 0.25' in rendered
    assert "quantile=" not in rendered


def test_database_collector_handles_empty_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from sqlalchemy import create_engine

    from app import models  # noqa: F401
    from app.config import get_settings
    from app.database import Base
    from app.tools import prometheus_exporter

    get_settings.cache_clear()
    test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(prometheus_exporter, "engine", test_engine)

    writer = prometheus_exporter.MetricWriter()
    prometheus_exporter.collect_database_metrics(writer)

    rendered = writer.render()
    assert "medusa_database_table_rows" in rendered
    assert "medusa_library_documents 0" in rendered


def test_collector_partial_failure_still_renders(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.tools import prometheus_exporter

    get_settings.cache_clear()

    def broken_collector(_writer):
        raise RuntimeError("boom")

    monkeypatch.setattr(prometheus_exporter, "_live_collectors", lambda: [("database", broken_collector), ("storage", lambda writer: writer.add("storage_fake_count", 1, help_text="Fake count."))])
    monkeypatch.setattr(prometheus_exporter, "_heavy_collectors", lambda: [])
    monkeypatch.setattr(prometheus_exporter, "_load_heavy_snapshot", lambda: (None, "missing"))

    rendered = prometheus_exporter.collect_metrics()

    assert 'medusa_exporter_collector_up{collector="database"} 0' in rendered
    assert "medusa_storage_fake_records 1" in rendered


def test_collect_metrics_uses_heavy_snapshot_without_running_heavy_collectors(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.tools import prometheus_exporter

    get_settings.cache_clear()
    prometheus_exporter._LAST_COLLECTOR_SUCCESS.clear()

    def should_not_run(_writer):
        raise AssertionError("heavy collector should not run during collect_metrics")

    snapshot = {
        "generated_at": time.time(),
        "duration_seconds": 0.25,
        "sample_count": 1,
        "rendered": "# HELP medusa_library_documents Current library documents.\n# TYPE medusa_library_documents gauge\nmedusa_library_documents 7\n",
        "collectors": [{"collector": "database", "up": 1, "duration_seconds": 0.25, "last_success_timestamp_seconds": 123.0}],
    }
    monkeypatch.setattr(prometheus_exporter, "_live_collectors", lambda: [])
    monkeypatch.setattr(prometheus_exporter, "_heavy_collectors", lambda: [("database", should_not_run)])
    monkeypatch.setattr(prometheus_exporter, "_load_heavy_snapshot", lambda: (snapshot, "valkey"))

    rendered = prometheus_exporter.collect_metrics()

    assert "medusa_library_documents 7" in rendered
    assert 'medusa_exporter_heavy_snapshot_up{source="valkey"} 1' in rendered
    assert 'medusa_exporter_collector_cached{collector="database"} 1' in rendered


def test_refresh_heavy_metrics_snapshot_stores_rendered_text_in_valkey(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.tools import prometheus_exporter

    get_settings.cache_clear()
    stored: dict[str, str] = {}

    class FakeValkey:
        def set(self, key, value, ex=None):
            stored[key] = value
            stored[f"{key}:ex"] = str(ex)

        def get(self, key):
            return stored.get(key)

    monkeypatch.setattr(prometheus_exporter, "_metrics_valkey_client", lambda: FakeValkey())
    monkeypatch.setattr(prometheus_exporter, "_heavy_collectors", lambda: [("storage", lambda writer: writer.add("storage_fake_count", 4, help_text="Fake count."))])

    payload = prometheus_exporter.refresh_heavy_metrics_snapshot()
    loaded, source = prometheus_exporter._load_heavy_snapshot()

    assert payload["storage"] == "valkey"
    assert source == "valkey"
    assert loaded is not None
    assert "medusa_storage_fake_records 4" in loaded["rendered"]
    assert json.loads(stored[prometheus_exporter._HEAVY_SNAPSHOT_KEY])["sample_count"] == 1


def test_metrics_snapshot_access_disabled_missing_wrong_and_valid(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app import main

    monkeypatch.setattr(main.settings, "metrics_internal_token", "")
    with pytest.raises(HTTPException) as disabled:
        main._require_metrics_snapshot_access(DummyRequest())
    assert disabled.value.status_code == 404

    monkeypatch.setattr(main.settings, "metrics_internal_token", "secret")
    with pytest.raises(HTTPException) as missing:
        main._require_metrics_snapshot_access(DummyRequest())
    assert missing.value.status_code == 403
    with pytest.raises(HTTPException) as wrong:
        main._require_metrics_snapshot_access(DummyRequest({"authorization": "Bearer wrong"}))
    assert wrong.value.status_code == 403

    main._require_metrics_snapshot_access(DummyRequest({"authorization": "Bearer secret"}))

    monkeypatch.setattr(main, "utc_now", lambda: datetime(2026, 6, 28, tzinfo=timezone.utc))
    monkeypatch.setattr(main, "cache_status_payload", lambda db, request_metrics=None: {"request_metrics": request_metrics or []})
    monkeypatch.setattr(main, "route_performance_summary", lambda limit=24: [{"route": "/api/health", "count": 1}])
    monkeypatch.setattr(main, "container_footprint_status", lambda: {"process_uptime_seconds": 12})
    monkeypatch.setattr(main, "database_maintenance_status_out", lambda db: {"active_operation": None})
    monkeypatch.setattr(main, "release_status", lambda db=None: {"phase": "idle", "update_available": False})

    payload = main.internal_metrics_snapshot(DummyRequest({"authorization": "Bearer secret"}), db=object())

    assert payload["cache"]["request_metrics"][0]["route"] == "/api/health"
    assert payload["container"]["process_uptime_seconds"] == 12
