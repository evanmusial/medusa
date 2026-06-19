from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_backup_names_use_timestamp_and_short_hostname(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GCS_PREFIX", "medusa")

    from app.config import get_settings
    from app.services.backups import backup_basename, backup_object_prefix, backup_storage_uri

    get_settings.cache_clear()
    when = datetime(2026, 6, 19, 14, 5, tzinfo=timezone.utc)

    assert backup_basename(when, "Research-Desk.local") == "medusa-postgres-20260619-1405-research-desk"
    assert backup_object_prefix() == "medusa/backups"
    assert backup_storage_uri("bucket", "medusa/backups/example.dump.zst") == "gs://bucket/medusa/backups/example.dump.zst"


def test_restore_upload_is_stored_and_hashed(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.services.backups import save_restore_upload, sha256_file

    get_settings.cache_clear()
    uploaded = save_restore_upload(b"pg-dump-bytes", "unsafe path?.dump.zst")

    assert uploaded["filename"] == "unsafe path?.dump.zst"
    assert uploaded["local_path"].endswith("unsafe-path-.dump.zst")
    assert uploaded["size_bytes"] == len(b"pg-dump-bytes")
    assert uploaded["sha256"] == sha256_file(tmp_path / "data" / "backups" / "uploads" / uploaded["local_path"].rsplit("/", 1)[-1])


def test_backup_manifest_records_non_secret_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://medusa:secret@db:5432/medusa")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-key")
    monkeypatch.setenv("GCS_PREFIX", "medusa")

    from app.config import get_settings
    from app.services.backups import _backup_manifest

    get_settings.cache_clear()
    manifest = _backup_manifest(
        "backup-id",
        "medusa/backups/medusa-postgres-20260619-1405-host.dump.zst",
        "gs://bucket/medusa/backups/medusa-postgres-20260619-1405-host.dump.zst",
        123,
        "a" * 64,
    )

    rendered = str(manifest)
    assert manifest["compression"] == "zstd"
    assert manifest["dump_format"] == "pg_dump_custom"
    assert manifest["database"]["username"] == "medusa"
    assert "secret-openai-key" not in rendered
    assert "secret@db" not in rendered
    assert manifest["safety"]["api_keys_included"] is False
    assert manifest["safety"]["service_account_credentials_included"] is False
    assert manifest["safety"]["plaintext_passwords_included"] is False
    assert manifest["safety"]["password_hashes_included"] is True
    assert manifest["safety"]["database_dump_includes_auth_tables"] is True


def test_backup_runs_block_overlapping_work(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services import backups
    from app.services.backups import create_database_backup_run, create_restore_run

    monkeypatch.setattr(backups, "is_postgres", lambda: True)
    Session = make_session()
    with Session() as db:
        run = create_database_backup_run(db)
        assert run.status == "queued"

        try:
            create_restore_run(db, source_kind="gcs", source_uri="gs://bucket/backup.dump.zst")
        except ValueError as exc:
            assert "already running" in str(exc)
        else:
            raise AssertionError("Expected active backup to block restore.")
