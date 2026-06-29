from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_cache_key_changes_when_revision_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services.cache import bump_cache_revisions, cache_key, current_cache_revisions

    Session = make_session()
    with Session() as db:
        first_revisions = current_cache_revisions(db, {"library"})
        first_key = cache_key("documents:list", {"q": "volcano"}, first_revisions)

        bump_cache_revisions(db, {"library"}, reason="test")
        db.commit()

        second_revisions = current_cache_revisions(db, {"library"})
        second_key = cache_key("documents:list", {"q": "volcano"}, second_revisions)

    assert first_revisions["global"] == 0
    assert first_revisions["library"] == 0
    assert second_revisions["library"] == 1
    assert first_key != second_key


def test_cache_revision_hooks_bump_on_commit_not_rollback(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import CacheRevision, Document
    from app.services.cache import install_cache_revision_hooks

    install_cache_revision_hooks()
    Session = make_session()

    with Session() as db:
        db.add(
            Document(
                title="Rolled Back",
                original_filename="rollback.pdf",
                checksum_sha256="a" * 64,
                processing_status="ready",
            )
        )
        db.rollback()

    with Session() as db:
        assert db.query(CacheRevision).count() == 0

        db.add(
            Document(
                title="Committed",
                original_filename="committed.pdf",
                checksum_sha256="b" * 64,
                processing_status="ready",
            )
        )
        db.commit()

        revisions = {row.family: row.version for row in db.query(CacheRevision).all()}

    assert revisions["library"] == 1
    assert revisions["document_detail"] == 1
    assert revisions["dashboard"] == 1
    assert revisions["status"] == 1
    assert "global" not in revisions


def test_cache_revision_dirty_state_clears_on_rollback(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import AppPreference, CacheRevision, Document
    from app.services.cache import install_cache_revision_hooks

    install_cache_revision_hooks()
    Session = make_session()

    with Session() as db:
        db.add(
            Document(
                title="Flushed Then Rolled Back",
                original_filename="rollback.pdf",
                checksum_sha256="c" * 64,
                processing_status="ready",
            )
        )
        db.flush()
        db.rollback()

        db.add(AppPreference(key="unrelated", value={"ok": True}))
        db.commit()

        assert db.query(CacheRevision).count() == 0


def test_cache_revision_hooks_bump_dashboard_for_usage_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import CacheRevision, OpenAIUsageRecord
    from app.services.cache import install_cache_revision_hooks

    install_cache_revision_hooks()
    Session = make_session()

    with Session() as db:
        db.add(
            OpenAIUsageRecord(
                task_key="bibliography_cleanup",
                operation="cleanup_bibliography",
                endpoint="responses",
                model="gpt-5.4-nano",
                status="failed",
                source="concordance",
                error_message="timeout",
                usage_metadata={},
            )
        )
        db.commit()

        revisions = {row.family: row.version for row in db.query(CacheRevision).all()}

    assert revisions["dashboard"] == 1
    assert revisions["jobs"] == 1


def test_null_cache_is_a_bypass():
    from app.services.cache import NullCache

    cache = NullCache()

    status, payload = cache.get_json("key", "documents:list")
    write_status = cache.set_json("key", "documents:list", {"ok": True}, 60, 1024)

    assert status == "bypass"
    assert payload is None
    assert write_status == "bypass"
    assert cache.status()["mode"] == "disabled"


def test_valkey_cache_errors_are_misses():
    from app.services.cache import ValkeyCache

    cache = ValkeyCache("valkey://example.invalid:6379/0")

    def fail():
        raise RuntimeError("offline")

    cache._redis = fail

    status, payload = cache.get_json("key", "dashboard")
    write_status = cache.set_json("key", "dashboard", {"ok": True}, 60, 1024)
    backend_status = cache.status()

    assert status == "error"
    assert payload is None
    assert write_status == "error"
    assert backend_status["mode"] == "degraded"
    assert backend_status["reachable"] is False


def test_valkey_cache_bypasses_oversized_payloads():
    from app.services.cache import ValkeyCache

    class RecordingClient:
        def __init__(self):
            self.setex_calls = []

        def setex(self, *args):
            self.setex_calls.append(args)

    client = RecordingClient()
    cache = ValkeyCache("valkey://unused:6379/0")
    cache._client = client

    status = cache.set_json("key", "documents:detail", {"text": "x" * 200}, 60, 64)

    assert status == "bypass"
    assert client.setex_calls == []


def test_valkey_cache_configures_maxmemory():
    from app.services.cache import ValkeyCache

    class RecordingClient:
        def __init__(self):
            self.config_calls = []

        def config_set(self, key, value):
            self.config_calls.append((key, value))
            return True

    client = RecordingClient()
    cache = ValkeyCache("valkey://unused:6379/0")
    cache._client = client

    assert cache.configure_maxmemory("8gb") is True
    assert client.config_calls == [("maxmemory", "8gb")]


def test_hydrate_cache_warms_current_postgres_payloads(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, SavedSearch
    from app.services import cache as cache_service
    from app import main

    class RecordingCache:
        def __init__(self):
            self.data = {}
            self.hydrated_at = None

        def get_json(self, key, family):
            return ("hit", self.data[key]) if key in self.data else ("miss", None)

        def set_json(self, key, family, payload, ttl_seconds, max_payload_bytes):
            del family, ttl_seconds, max_payload_bytes
            self.data[key] = payload
            return "write"

        def remember_refresh(self, refreshed_at=None):
            return None

        def last_refresh_at(self):
            return None

        def remember_hydration(self, hydrated_at=None):
            self.hydrated_at = hydrated_at

        def last_hydration_at(self):
            return self.hydrated_at

        def status(self):
            return {
                "backend": "recording",
                "enabled": True,
                "reachable": True,
                "mode": "online",
                "message": "Recording cache online.",
                "key_count": len(self.data),
            }

    cache = RecordingCache()
    monkeypatch.setattr(cache_service, "_cache_backend", cache)

    Session = make_session()
    with Session() as db:
        db.add_all(
            [
                Document(
                    title="Alpha",
                    original_filename="alpha.pdf",
                    checksum_sha256="d" * 64,
                    processing_status="ready",
                    priority="high",
                    page_count=3,
                ),
                Document(
                    title="Beta",
                    original_filename="beta.pdf",
                    checksum_sha256="e" * 64,
                    processing_status="ready",
                    page_count=5,
                ),
                SavedSearch(name="High Priority", query=None, filters={"priority": "high"}),
            ]
        )
        db.commit()

        result = main.hydrate_cache(None, db, max_documents=10, page_size=25)

    assert result["status"] == "complete"
    assert result["document_count"] == 2
    assert result["base_keys"] == 2
    assert result["organization_keys"] == 3
    assert result["list_page_keys"] == 1
    assert result["saved_search_keys"] == 1
    assert result["document_detail_keys"] == 2
    assert result["hydrated_keys"] == 9
    assert result["after"]["last_hydration_at"] == result["hydrated_at"]
    assert cache.hydrated_at == result["hydrated_at"]


def test_hydrate_cache_default_document_limit_means_all(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document
    from app.services import cache as cache_service
    from app import main

    class RecordingCache:
        def __init__(self):
            self.data = {}
            self.hydrated_at = None

        def get_json(self, key, family):
            return ("hit", self.data[key]) if key in self.data else ("miss", None)

        def set_json(self, key, family, payload, ttl_seconds, max_payload_bytes):
            del family, ttl_seconds, max_payload_bytes
            self.data[key] = payload
            return "write"

        def remember_refresh(self, refreshed_at=None):
            return None

        def last_refresh_at(self):
            return None

        def remember_hydration(self, hydrated_at=None):
            self.hydrated_at = hydrated_at

        def last_hydration_at(self):
            return self.hydrated_at

        def status(self):
            return {
                "backend": "recording",
                "enabled": True,
                "reachable": True,
                "mode": "online",
                "message": "Recording cache online.",
                "key_count": len(self.data),
            }

    cache = RecordingCache()
    monkeypatch.setattr(cache_service, "_cache_backend", cache)
    monkeypatch.setattr(main.settings, "cache_hydrate_max_documents", 0)

    Session = make_session()
    with Session() as db:
        for index in range(3):
            db.add(
                Document(
                    title=f"Document {index}",
                    original_filename=f"document-{index}.pdf",
                    checksum_sha256=f"{index + 1}" * 64,
                    processing_status="ready",
                    page_count=index + 1,
                )
            )
        db.commit()

        result = main.hydrate_cache_payloads(db, include_saved_searches=False, page_size=25)

    assert result["status"] == "complete"
    assert result["document_count"] == 3
    assert result["document_detail_keys"] == 3
    assert result["hydrated_keys"] == 9


def test_startup_cache_hydration_schedules_shared_hydrator(monkeypatch):
    from app import main

    calls = []
    db_marker = object()

    @contextmanager
    def fake_session_scope():
        yield db_marker

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            self.target()

    def fake_hydrate(db):
        calls.append(db)
        return {
            "status": "complete",
            "hydrated_keys": 1,
            "document_count": 1,
            "skipped_payloads": 0,
            "errored_payloads": 0,
        }

    monkeypatch.setattr(main.settings, "cache_startup_hydrate", True)
    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "hydrate_cache_payloads", fake_hydrate)
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    main.schedule_startup_cache_hydration()

    assert calls == [db_marker]


def test_startup_cache_hydration_retries_until_cache_reachable(monkeypatch):
    from app import main

    db_marker = object()
    sleeps = []
    results = [
        {
            "status": "skipped",
            "message": "Valkey is configured but unreachable.",
            "before": {"enabled": True, "reachable": False},
        },
        {
            "status": "complete",
            "hydrated_keys": 2,
            "document_count": 1,
            "skipped_payloads": 0,
            "errored_payloads": 0,
            "before": {"enabled": True, "reachable": True},
        },
    ]

    @contextmanager
    def fake_session_scope():
        yield db_marker

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            self.target()

    def fake_hydrate(db):
        assert db is db_marker
        return results.pop(0)

    monkeypatch.setattr(main.settings, "cache_startup_hydrate", True)
    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "hydrate_cache_payloads", fake_hydrate)
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main, "sleep", lambda seconds: sleeps.append(seconds))

    main.schedule_startup_cache_hydration()

    assert results == []
    assert sleeps == [main.CACHE_STARTUP_HYDRATE_RETRY_SECONDS]
