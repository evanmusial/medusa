from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_maintenance_readiness_reports_sessions_and_active_work(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))

    from app.config import get_settings
    from app.models import BackupRun, Document, DocumentAccessorySummary, ImportBatch, ImportJob, SessionToken, User, utc_now
    from app.security import hash_password, hash_token
    from app.services.maintenance import maintenance_readiness, override_active_sessions

    get_settings.cache_clear()
    Session = make_session()
    now = utc_now()

    with Session() as db:
        user = User(email="admin@medusa.local", display_name="Admin", password_hash=hash_password("password"))
        db.add(user)
        db.flush()
        document = Document(
            title="Maintenance Gates",
            original_filename="maintenance.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        batch = ImportBatch(label="active batch", status="running", total_files=1)
        db.add_all([document, batch])
        db.flush()
        db.add_all(
            [
                SessionToken(
                    user_id=user.id,
                    token_hash=hash_token("fresh"),
                    expires_at=now + timedelta(hours=1),
                    last_seen_at=now,
                ),
                SessionToken(
                    user_id=user.id,
                    token_hash=hash_token("expired"),
                    expires_at=now - timedelta(minutes=1),
                    last_seen_at=now,
                ),
                ImportJob(batch_id=batch.id, document_id=document.id, status="running"),
                DocumentAccessorySummary(
                    document_id=document.id,
                    prompt="Summarize",
                    model="gpt-test",
                    status="queued",
                ),
                BackupRun(kind="backup", reason="manual", status="running", phase="dumping", progress=20),
            ]
        )
        db.commit()

        readiness = maintenance_readiness(db, idle_grace_seconds=300)
        assert readiness["idle"] is False
        assert readiness["active_session_count"] == 1
        assert readiness["active_import_jobs"] == 1
        assert readiness["active_accessory_summary_jobs"] == 1
        assert readiness["active_backup_runs"] == 1
        assert any("active user session" in blocker for blocker in readiness["blockers"])
        assert any("active import job" in blocker for blocker in readiness["blockers"])
        assert any("active backup/restore run" in blocker for blocker in readiness["blockers"])

        overridden = override_active_sessions(readiness)
        assert overridden["idle"] is False
        assert overridden["active_sessions_overridden"] is True
        assert not any("active user session" in blocker for blocker in overridden["blockers"])
        assert any("active import job" in blocker for blocker in overridden["blockers"])
