import base64
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    monkeypatch.setenv("MEDUSA_SLIPSTREAM_ENABLED", "true")
    monkeypatch.setenv("MEDUSA_SLIPSTREAM_LEASE_TTL_SECONDS", "180")
    monkeypatch.setenv("MEDUSA_SLIPSTREAM_SIGNATURE_WINDOW_SECONDS", "60")

    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401

    get_settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def keypair():
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.urlsafe_b64encode(public_bytes).decode("ascii").rstrip("=")
    return private_key, public_key


def sign(private_key, *, method="POST", path="/api/slipstream/check-in", timestamp="1000", nonce="nonce", body=b"{}"):
    from app.services.slipstream import body_sha256, canonical_signature_message

    body_hash = body_sha256(body)
    message = canonical_signature_message(method, path, timestamp, nonce, body_hash)
    signature = base64.urlsafe_b64encode(private_key.sign(message)).decode("ascii").rstrip("=")
    return body_hash, signature


def registered_client(db, *, name="remote-1"):
    from app.services.slipstream import create_enrollment, register_client

    private_key, public_key = keypair()
    enrollment, token = create_enrollment(db, label=name)
    client = register_client(
        db,
        enrollment_token=token,
        name=name,
        public_key=public_key,
        version="pytest",
        capabilities=["import", "concordance"],
        capacity=1,
    )
    return client, private_key, enrollment, token


def import_job(db, *, checksum="a" * 64):
    from app.models import Document, ImportBatch, ImportJob

    batch = ImportBatch(total_files=1, shared_defaults={})
    document = Document(
        title="Queued",
        original_filename="queued.pdf",
        checksum_sha256=checksum,
        processing_status="queued",
    )
    job = ImportJob(batch=batch, document=document, status="queued", current_step="stored")
    db.add_all([batch, document, job])
    db.flush()
    return batch, document, job


def concordance_job(db):
    from app.models import ConcordanceJob, ConcordanceRun, Document

    document = Document(
        title="Ready",
        original_filename="ready.pdf",
        checksum_sha256="c" * 64,
        processing_status="ready",
    )
    run = ConcordanceRun(
        label="Refresh",
        capability_keys=["search_index"],
        total_jobs=1,
        status="running",
    )
    job = ConcordanceJob(
        run=run,
        document=document,
        capability_key="search_index",
        target_version=3,
        status="queued",
    )
    db.add_all([document, run, job])
    db.flush()
    return run, document, job


def test_enrollment_token_is_single_use_and_expires(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import utc_now
    from app.services.slipstream import SlipstreamAuthError, create_enrollment, register_client

    with Session() as db:
        _, token = create_enrollment(db, label="one-shot")
        _, public_key = keypair()

        client = register_client(db, enrollment_token=token, name="Worker", public_key=public_key)
        assert client.status == "active"

        with pytest.raises(SlipstreamAuthError):
            register_client(db, enrollment_token=token, name="Worker again", public_key=public_key)

        expired, expired_token = create_enrollment(db, label="expired")
        expired.expires_at = utc_now() - timedelta(seconds=1)
        with pytest.raises(SlipstreamAuthError):
            register_client(db, enrollment_token=expired_token, name="Late", public_key=public_key)


def test_signature_verification_rejects_replay_skew_and_revoked_clients(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import utc_now
    from app.services.slipstream import SlipstreamAuthError, verify_signature

    with Session() as db:
        client, private_key, _, _ = registered_client(db)
        body = b'{"status":"ok"}'
        timestamp = str(utc_now().timestamp())
        body_hash, signature = sign(private_key, timestamp=timestamp, nonce="nonce-1", body=body)

        verify_signature(
            client,
            method="POST",
            path="/api/slipstream/check-in",
            timestamp=timestamp,
            nonce="nonce-1",
            request_body_hash=body_hash,
            signature=signature,
            body=body,
        )
        with pytest.raises(SlipstreamAuthError, match="already been used"):
            verify_signature(
                client,
                method="POST",
                path="/api/slipstream/check-in",
                timestamp=timestamp,
                nonce="nonce-1",
                request_body_hash=body_hash,
                signature=signature,
                body=body,
            )

        old_timestamp = str((utc_now() - timedelta(minutes=10)).timestamp())
        old_hash, old_signature = sign(private_key, timestamp=old_timestamp, nonce="nonce-2", body=body)
        with pytest.raises(SlipstreamAuthError, match="outside"):
            verify_signature(
                client,
                method="POST",
                path="/api/slipstream/check-in",
                timestamp=old_timestamp,
                nonce="nonce-2",
                request_body_hash=old_hash,
                signature=old_signature,
                body=body,
            )

        client.status = "revoked"
        client.revoked_at = utc_now()
        new_timestamp = str(utc_now().timestamp())
        revoked_hash, revoked_signature = sign(private_key, timestamp=new_timestamp, nonce="nonce-3", body=body)
        with pytest.raises(SlipstreamAuthError, match="not active"):
            verify_signature(
                client,
                method="POST",
                path="/api/slipstream/check-in",
                timestamp=new_timestamp,
                nonce="nonce-3",
                request_body_hash=revoked_hash,
                signature=revoked_signature,
                body=body,
            )


def test_claim_returns_one_active_lease_for_competing_clients(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import SlipstreamLease
    from app.services.slipstream import claim_next_job_lease

    with Session() as db:
        client_a, _, _, _ = registered_client(db, name="remote-a")
        client_b, _, _, _ = registered_client(db, name="remote-b")
        _, document, job = import_job(db)

        first = claim_next_job_lease(db, client=client_a, job_types=["import"])
        second = claim_next_job_lease(db, client=client_b, job_types=["import"])

        assert first is not None
        assert first["work"]["job_id"] == job.id
        assert second is None
        assert job.status == "running"
        assert document.processing_status == "running"
        assert db.query(SlipstreamLease).filter_by(job_id=job.id, status="active").count() == 1


def test_heartbeat_extends_lease_and_expiry_requeues_job(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import SlipstreamLease, utc_now
    from app.services.slipstream import claim_next_job_lease, expire_stale_leases, heartbeat_lease

    with Session() as db:
        client, _, _, _ = registered_client(db)
        _, document, job = import_job(db)
        claimed = claim_next_job_lease(db, client=client, job_types=["import"])
        lease = db.get(SlipstreamLease, claimed["lease"]["id"])

        lease.expires_at = utc_now() - timedelta(seconds=1)
        db.flush()
        heartbeat_lease(db, lease, detail="page 1")
        assert lease.expires_at > utc_now()
        assert lease.payload["last_detail"] == "page 1"

        lease.expires_at = utc_now() - timedelta(seconds=1)
        db.flush()
        expired_count = expire_stale_leases(db)

        assert expired_count == 1
        assert lease.status == "expired"
        assert job.status == "queued"
        assert document.processing_status == "queued"


def test_canceled_and_revoked_leases_stop_followup_work(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import utc_now
    from app.services.slipstream import (
        SlipstreamAuthError,
        SlipstreamError,
        cancel_lease,
        claim_next_job_lease,
        revoke_client,
        validate_lease_access,
        verify_signature,
    )

    with Session() as db:
        client, private_key, _, _ = registered_client(db)
        import_job(db)
        claimed = claim_next_job_lease(db, client=client, job_types=["import"])
        from app.models import SlipstreamLease

        lease = db.get(SlipstreamLease, claimed["lease"]["id"])
        cancel_lease(db, lease, reason="pytest cancel")

        with pytest.raises(SlipstreamError):
            validate_lease_access(db, lease_id=lease.id, client=client, lease_token=claimed["lease_token"])
        with pytest.raises(SlipstreamError):
            from app.services.slipstream import complete_lease_from_result

            complete_manifest = {"idempotency_key": claimed["work"]["idempotency_key"], "document": {"title": "Too late"}}
            complete_lease_from_result(db, lease, manifest=complete_manifest)

        revoke_client(db, client)
        timestamp = str(utc_now().timestamp())
        body_hash, signature = sign(private_key, timestamp=timestamp, nonce="after-revoke", body=b"{}")
        with pytest.raises(SlipstreamAuthError):
            verify_signature(
                client,
                method="POST",
                path="/api/slipstream/check-in",
                timestamp=timestamp,
                nonce="after-revoke",
                request_body_hash=body_hash,
                signature=signature,
                body=b"{}",
            )


def test_stale_result_after_release_is_rejected(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import SlipstreamLease, utc_now
    from app.services.slipstream import SlipstreamError, claim_next_job_lease, complete_lease_from_result, expire_stale_leases

    with Session() as db:
        client_a, _, _, _ = registered_client(db, name="remote-a")
        client_b, _, _, _ = registered_client(db, name="remote-b")
        import_job(db)

        first = claim_next_job_lease(db, client=client_a, job_types=["import"])
        old_lease = db.get(SlipstreamLease, first["lease"]["id"])
        old_lease.expires_at = utc_now() - timedelta(seconds=1)
        db.flush()
        expire_stale_leases(db)

        second = claim_next_job_lease(db, client=client_b, job_types=["import"])
        assert second is not None

        with pytest.raises(SlipstreamError, match="expired"):
            complete_lease_from_result(
                db,
                old_lease,
                manifest={"idempotency_key": first["work"]["idempotency_key"], "document": {"title": "Old result"}},
            )


def test_slipstream_import_result_is_idempotent_and_updates_processing_state(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import DocumentCompositionRecord, DocumentPage, ProcessingEvent, SlipstreamLease
    from app.services.slipstream import claim_next_job_lease, complete_lease_from_result

    with Session() as db:
        client, _, _, _ = registered_client(db)
        batch, document, job = import_job(db)
        claimed = claim_next_job_lease(db, client=client, job_types=["import"])
        lease = db.get(SlipstreamLease, claimed["lease"]["id"])
        manifest = {
            "idempotency_key": claimed["work"]["idempotency_key"],
            "current_step": "complete",
            "document": {"title": "Remote Title", "page_count": 1, "search_text": "alpha\x00 beta"},
            "pages": [{"page_number": 1, "text": "alpha\x00 beta", "text_source": "slipstream"}],
            "composition": [
                {
                    "record_kind": "local",
                    "stage_key": "slipstream_pdf_text",
                    "stage_label": "Slipstream PDF text",
                    "status": "complete",
                    "message": "Extracted remotely.",
                }
            ],
        }

        first = complete_lease_from_result(db, lease, manifest=manifest)
        second = complete_lease_from_result(db, lease, manifest=manifest)

        assert first["status"] == "complete"
        assert second["status"] == "complete"
        assert job.status == "complete"
        assert document.processing_status == "ready"
        assert document.title == "Remote Title"
        assert "\x00" not in document.search_text
        assert batch.completed_files == 1
        assert db.query(DocumentPage).filter_by(document_id=document.id, page_number=1).one().text == "alpha beta"
        assert db.query(DocumentCompositionRecord).filter_by(document_id=document.id).count() == 1
        assert db.query(ProcessingEvent).filter_by(import_job_id=job.id, event_type="slipstream_job_complete").count() == 1


def test_slipstream_concordance_result_refreshes_capability_progress(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import DocumentCapability, SlipstreamLease
    from app.services.slipstream import claim_next_job_lease, complete_lease_from_result

    with Session() as db:
        client, _, _, _ = registered_client(db)
        run, document, job = concordance_job(db)

        claimed = claim_next_job_lease(db, client=client, job_types=["concordance"])
        lease = db.get(SlipstreamLease, claimed["lease"]["id"])
        complete_lease_from_result(
            db,
            lease,
            manifest={
                "idempotency_key": claimed["work"]["idempotency_key"],
                "capabilities": [
                    {
                        "capability_key": "search_index",
                        "version": 3,
                        "status": "complete",
                        "evidence": {"source": "pytest"},
                    }
                ],
            },
        )

        capability = db.query(DocumentCapability).filter_by(document_id=document.id, capability_key="search_index").one()
        assert capability.version == 3
        assert capability.status == "complete"
        assert job.status == "complete"
        assert run.completed_jobs == 1
        assert run.status == "complete"
