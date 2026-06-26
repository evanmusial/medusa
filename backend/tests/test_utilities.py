import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401

    get_settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_clear_import_cache_removes_only_hidden_terminal_import_rows(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import clear_hidden_import_cache, database_maintenance_status_out
    from app.models import Document, Domain, ImportBatch, ImportJob, ProcessingEvent, Project, ProjectItem
    from app.services.document_cache import document_cache_path, register_document_cache

    original_path = tmp_path / "staged-originals" / "cleared.pdf"
    original_path.parent.mkdir(parents=True)
    original_path.write_bytes(b"original")

    with Session() as db:
        project = Project(name="IT-CFS")
        domain = Domain(name="Cybersecurity")
        batch = ImportBatch(total_files=4, shared_defaults={})
        ready_document = Document(
            title="Ready",
            original_filename="ready.pdf",
            checksum_sha256="r" * 64,
            processing_status="ready",
        )
        cleared_document = Document(
            title="Cleared",
            original_filename="cleared.pdf",
            checksum_sha256="c" * 64,
            processing_status="cleared",
            gcs_uri=str(original_path),
        )
        active_document = Document(
            title="Queued",
            original_filename="queued.pdf",
            checksum_sha256="q" * 64,
            processing_status="queued",
        )
        cleared_document.domains.append(domain)
        db.add_all([project, domain, batch, ready_document, cleared_document, active_document])
        db.flush()
        db.add_all(
            [
                ProjectItem(project=project, document=ready_document),
                ProjectItem(project=project, document=cleared_document),
                ProjectItem(project=project, document=active_document),
            ]
        )
        db.add_all(
            [
                ImportJob(batch=batch, document=cleared_document, status="cleared", current_step="cleared"),
                ImportJob(batch=batch, document=cleared_document, status="complete", current_step="duplicate_skipped"),
                ImportJob(batch=batch, document=active_document, status="queued", current_step="stored"),
                ImportJob(batch=batch, status="cleared", current_step="cleared"),
            ]
        )
        cache_path = document_cache_path(cleared_document.id)
        cache_path.write_bytes(b"cache")
        register_document_cache(cleared_document, cache_path, source="upload")
        db.add(
            ProcessingEvent(
                document_id=cleared_document.id,
                event_type="manual_import_clear",
                message="Cleared.",
            )
        )
        db.commit()

        status = database_maintenance_status_out(db)
        assert status.import_cache_count == 1
        assert status.hidden_project_item_count == 1
        assert status.terminal_import_job_count == 2
        assert status.orphan_import_job_count == 1

        result = clear_hidden_import_cache(db)

        assert result.import_cache_count == 0
        assert result.removed_import_documents == 1
        assert result.removed_project_items == 1
        assert result.removed_import_jobs == 2
        assert result.removed_orphan_import_jobs == 1
        assert result.deleted_cache_files == 1
        assert result.deleted_original_objects == 1
        assert not cache_path.exists()
        assert not original_path.exists()
        assert db.get(Document, ready_document.id) is not None
        assert db.get(Document, active_document.id) is not None
        assert db.get(Document, cleared_document.id) is None
        assert db.get(Domain, domain.id) is not None
        assert db.query(ProjectItem).count() == 2
        assert db.query(ImportJob).count() == 1


def test_clear_import_cache_tolerates_original_delete_failure(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    import app.main as main
    from app.models import Document, DocumentCompositionRecord, ImportBatch, ImportJob
    from app.services.document_cache import document_cache_path, register_document_cache

    class FailingStorage:
        def delete_uri(self, uri):
            raise RuntimeError(f"cannot delete {uri}")

    monkeypatch.setattr(main, "get_storage_service", lambda: FailingStorage())

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(
            title="Cleared GCS",
            original_filename="cleared-gcs.pdf",
            checksum_sha256="g" * 64,
            processing_status="cleared",
            gcs_uri="gs://bucket/medusa/documents/cleared-gcs.pdf",
        )
        db.add_all([batch, document])
        db.flush()
        job = ImportJob(batch=batch, document=document, status="cleared", current_step="cleared")
        db.add(job)
        db.flush()
        db.add(
            DocumentCompositionRecord(
                document_id=document.id,
                import_job_id=job.id,
                record_kind="estimate",
                stage_key="import_cost_estimate",
                stage_label="Import cost estimate",
                status="estimated",
                amount_usd=0.01,
            )
        )
        cache_path = document_cache_path(document.id)
        cache_path.write_bytes(b"cache")
        register_document_cache(document, cache_path, source="upload")
        db.commit()

        result = main.clear_hidden_import_cache(db)

        assert result.status == "complete"
        assert result.removed_import_documents == 1
        assert result.removed_import_jobs == 1
        assert result.deleted_cache_files == 1
        assert result.deleted_original_objects == 0
        assert not cache_path.exists()
        assert db.get(Document, document.id) is None
        assert db.query(DocumentCompositionRecord).count() == 0


def test_database_sql_maintenance_starts_background_job(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    import app.main as main

    launched: list[str] = []

    class FakeThread:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def start(self):
            launched.append(self.kwargs["name"])

    def reset_maintenance_state():
        with main.DATABASE_MAINTENANCE_LOCK:
            main.DATABASE_MAINTENANCE_STATE.update(
                {
                    "active_operation": None,
                    "active_operation_started_at": None,
                    "active_operation_status_detail": None,
                    "last_operation": None,
                    "last_operation_status": None,
                    "last_operation_completed_at": None,
                    "last_operation_status_detail": None,
                    "last_operation_error": None,
                    "last_operation_database_size_before_bytes": None,
                    "last_operation_database_size_after_bytes": None,
                }
            )

    reset_maintenance_state()
    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main, "current_database_size_bytes", lambda db: 321)

    try:
        with Session() as db:
            result = main.run_database_sql_maintenance(
                db,
                operation="compact_database",
                postgres_sql="VACUUM (FULL, ANALYZE)",
                sqlite_sql="VACUUM",
            )

            assert result.status == "running"
            assert result.message == "Compact Database started."
            assert result.active_operation == "compact_database"
            assert result.active_operation_label == "Compact Database"
            assert result.database_size_before_bytes == 321
            assert launched == ["medusa-compact_database"]

            with pytest.raises(ValueError, match="Compact Database is already running"):
                main.run_database_sql_maintenance(
                    db,
                    operation="optimize_database",
                    postgres_sql="ANALYZE",
                    sqlite_sql="ANALYZE",
                )
    finally:
        reset_maintenance_state()


def test_container_footprint_status_reports_medusa_storage_paths(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    originals = data_dir / "originals"
    processing_cache = data_dir / "processing-cache"
    model_cache = data_dir / "model-cache"
    originals.mkdir(parents=True)
    processing_cache.mkdir(parents=True)
    model_cache.mkdir(parents=True)
    (originals / "paper.pdf").write_bytes(b"original")
    (processing_cache / "cached.pdf").write_bytes(b"cache")
    (model_cache / "weights.bin").write_bytes(b"model")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(originals))
    monkeypatch.setenv("XDG_CACHE_HOME", str(model_cache))
    monkeypatch.setenv("MEDUSA_DOCKER_SOCKET_PATH", str(tmp_path / "missing-docker.sock"))

    from app.config import get_settings
    from app.schemas import ContainerRuntimeVersionOut
    from app.services import container_footprint

    get_settings.cache_clear()
    monkeypatch.setattr(
        container_footprint,
        "runtime_versions",
        lambda: [
            ContainerRuntimeVersionOut(
                name="Python",
                version="3.12.test",
                source="unit test",
            )
        ],
    )
    status = container_footprint.container_footprint_status()
    footprints = {row.label: row for row in status.paths}

    assert status.data_dir == str(data_dir)
    assert status.data_dir_size_bytes >= len(b"originalcachemodel")
    assert footprints["Local originals"].size_bytes == len(b"original")
    assert footprints["Processing cache"].size_bytes == len(b"cache")
    assert footprints["Model cache"].size_bytes == len(b"model")
    assert footprints["Data volume"].file_count >= 3
    assert status.data_filesystem is not None
    assert status.runtime_versions[0].name == "Python"
    assert status.runtime_versions[0].version == "3.12.test"
    assert status.docker_image is None


def test_haproxy_stats_html_parses_runtime_version():
    from app.services.container_footprint import parse_haproxy_version_from_stats_html

    version, release_date = parse_haproxy_version_from_stats_html(
        '<h1><a href="http://www.haproxy.org/">HAProxy version 3.0.23-44b4517fc, released 2026/05/11</a></h1>'
    )

    assert version == "3.0.23-44b4517fc"
    assert release_date == "2026/05/11"


def test_docker_image_status_reports_image_when_socket_is_available(monkeypatch, tmp_path):
    from app.schemas import ContainerDockerImageOut
    from app.services import container_footprint

    socket_path = tmp_path / "docker.sock"
    docker_image = ContainerDockerImageOut(
        id="sha256:backend",
        repo_tags=["medusa-backend:latest"],
        size_bytes=100,
        unique_size_bytes=40,
        shared_size_bytes=60,
        layer_count=2,
    )
    monkeypatch.setattr(container_footprint, "_docker_socket_available", lambda path: path == socket_path)
    monkeypatch.setattr(container_footprint, "_docker_current_image", lambda path: docker_image)

    available, note, image = container_footprint.docker_image_status(socket_path)

    assert available is True
    assert "showing image and layer sizes" in note
    assert image == docker_image


def test_container_restart_is_disabled_outside_container(monkeypatch):
    from app.services import container_footprint

    monkeypatch.setattr(container_footprint, "_is_containerized", lambda: False)
    monkeypatch.setenv("MEDUSA_DOCKER_SOCKET_PATH", "/tmp/medusa-missing-docker.sock")

    status = container_footprint.container_footprint_status()
    assert status.restart_available is False
    assert status.restart_mode == "unavailable"

    try:
        container_footprint.request_container_restart()
    except RuntimeError as exc:
        assert "disabled outside Docker" in str(exc)
    else:
        raise AssertionError("expected restart outside Docker to be rejected")


def test_container_restart_schedules_process_exit_when_containerized(monkeypatch):
    from app.services import container_footprint

    scheduled: list[float] = []
    monkeypatch.setattr(container_footprint, "_is_containerized", lambda: True)
    monkeypatch.setattr(container_footprint, "_schedule_process_restart", scheduled.append)
    monkeypatch.setattr(container_footprint, "_RESTART_REQUESTED_AT", None)
    monkeypatch.setattr(container_footprint, "_RESTART_REQUESTED_MONOTONIC", None)

    result = container_footprint.request_container_restart(delay_seconds=0.25)

    assert result.status == "scheduled"
    assert result.restart_mode == "process_exit"
    assert scheduled == [0.25]


def test_haproxy_stats_csv_parses_core_proxy_rows():
    from app.services.haproxy_stats import parse_haproxy_stats_csv

    raw = "\n".join(
        [
            "# pxname,svname,qcur,qmax,scur,smax,slim,stot,bin,bout,dreq,dresp,ereq,econ,eresp,wretr,wredis,status,act,bck,chkfail,chkdown,lastchg,downtime,type,rate,check_status,check_code,check_duration",
            "medusa_https,FRONTEND,0,0,2,4,2048,12,345,678,0,0,0,0,0,0,0,OPEN,,,,,42,0,0,2,,,",
            "medusa_frontend,frontend,0,0,1,2,,11,300,600,0,0,0,1,0,0,0,UP,1,0,0,0,40,0,2,1,L7OK,200,3",
            "medusa_frontend,BACKEND,0,0,1,2,2048,11,300,600,0,0,0,0,0,0,0,UP,1,0,0,0,40,0,1,1,,,",
        ]
    )

    rows = parse_haproxy_stats_csv(raw)
    https = next(row for row in rows if row.proxy_name == "medusa_https")
    server = next(row for row in rows if row.proxy_name == "medusa_frontend" and row.service_name == "frontend")

    assert https.kind == "frontend"
    assert https.status == "OPEN"
    assert https.current_sessions == 2
    assert https.bytes_out == 678
    assert server.kind == "server"
    assert server.status == "UP"
    assert server.error_connections == 1
    assert server.check_status == "L7OK"
    assert server.check_code == 200
    assert server.check_duration_ms == 3
