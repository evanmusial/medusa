from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PortfolioAuditAnchor, PortfolioAuditEvent, new_id, utc_now


AUDIT_SCHEMA_VERSION = "medusa.portfolio.audit.v1"


class PortfolioAuditError(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _key_path() -> Path:
    settings = get_settings()
    return settings.portfolio_audit_key_path or (settings.data_dir / "audit" / "portfolio-ed25519.key")


def _load_or_create_signing_key() -> Ed25519PrivateKey:
    path = _key_path()
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(private_bytes)
    os.chmod(path, 0o600)
    return key


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _public_key_id(public_key_bytes: bytes) -> str:
    return sha256_hex(public_key_bytes)


def configured_timestamp_urls() -> list[str]:
    raw = (get_settings().audit_timestamp_urls or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [url for url in re.split(r"[\s,]+", raw) if url]


def append_portfolio_audit_event(
    db: Session,
    *,
    portfolio_item_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    version_id: str | None = None,
    material_id: str | None = None,
    assessment_run_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> PortfolioAuditEvent:
    private_key = _load_or_create_signing_key()
    public_bytes = _public_key_bytes(private_key)
    public_key_b64 = base64.b64encode(public_bytes).decode("ascii")
    public_key_id = _public_key_id(public_bytes)

    latest = db.execute(
        select(PortfolioAuditEvent)
        .where(PortfolioAuditEvent.portfolio_item_id == portfolio_item_id)
        .order_by(PortfolioAuditEvent.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()
    sequence = (latest.sequence if latest else 0) + 1
    previous_hash = latest.event_hash if latest else None
    occurred_at = utc_now()
    event_id = new_id()
    canonical_payload = {
        "schema": AUDIT_SCHEMA_VERSION,
        "event": {
            "id": event_id,
            "portfolio_item_id": portfolio_item_id,
            "version_id": version_id,
            "material_id": material_id,
            "assessment_run_id": assessment_run_id,
            "event_type": event_type,
            "sequence": sequence,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "occurred_at": _json_default(occurred_at),
        },
        "payload": payload or {},
        "signature": {
            "algorithm": "ed25519",
            "public_key_id": public_key_id,
            "public_key_base64": public_key_b64,
        },
    }
    payload_sha256 = sha256_hex(canonical_json_bytes(canonical_payload))
    event_hash_payload = {
        "schema": AUDIT_SCHEMA_VERSION,
        "sequence": sequence,
        "previous_event_hash": previous_hash,
        "payload_sha256": payload_sha256,
    }
    event_hash = sha256_hex(canonical_json_bytes(event_hash_payload))
    signature = base64.b64encode(private_key.sign(bytes.fromhex(event_hash))).decode("ascii")
    event = PortfolioAuditEvent(
        id=event_id,
        portfolio_item_id=portfolio_item_id,
        version_id=version_id,
        material_id=material_id,
        assessment_run_id=assessment_run_id,
        event_type=event_type,
        sequence=sequence,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_type=actor_type,
        actor_id=actor_id,
        occurred_at=occurred_at,
        canonical_payload=canonical_payload,
        payload_sha256=payload_sha256,
        previous_event_hash=previous_hash,
        event_hash=event_hash,
        signature_public_key_id=public_key_id,
        signature_algorithm="ed25519",
        signature=signature,
    )
    db.add(event)
    db.flush()
    return event


def verify_portfolio_audit_chain(db: Session, portfolio_item_id: str, *, verify_signatures: bool = True) -> dict[str, Any]:
    events = list(
        db.execute(
            select(PortfolioAuditEvent)
            .where(PortfolioAuditEvent.portfolio_item_id == portfolio_item_id)
            .order_by(PortfolioAuditEvent.sequence)
        ).scalars()
    )
    previous_hash: str | None = None
    errors: list[dict[str, Any]] = []
    for expected_sequence, event in enumerate(events, start=1):
        recalculated_payload_sha = sha256_hex(canonical_json_bytes(event.canonical_payload))
        recalculated_hash = sha256_hex(
            canonical_json_bytes(
                {
                    "schema": AUDIT_SCHEMA_VERSION,
                    "sequence": event.sequence,
                    "previous_event_hash": event.previous_event_hash,
                    "payload_sha256": recalculated_payload_sha,
                }
            )
        )
        if event.sequence != expected_sequence:
            errors.append({"sequence": event.sequence, "error": "sequence_gap", "expected_sequence": expected_sequence})
        if event.previous_event_hash != previous_hash:
            errors.append({"sequence": event.sequence, "error": "previous_hash_mismatch"})
        if event.payload_sha256 != recalculated_payload_sha:
            errors.append({"sequence": event.sequence, "error": "payload_sha256_mismatch"})
        if event.event_hash != recalculated_hash:
            errors.append({"sequence": event.sequence, "error": "event_hash_mismatch"})
        if verify_signatures:
            public_key_b64 = (
                ((event.canonical_payload or {}).get("signature") or {}).get("public_key_base64")
                if isinstance(event.canonical_payload, dict)
                else None
            )
            try:
                if not public_key_b64:
                    raise PortfolioAuditError("missing_public_key")
                public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
                public_key.verify(base64.b64decode(event.signature), bytes.fromhex(event.event_hash))
            except (InvalidSignature, ValueError, PortfolioAuditError) as exc:
                errors.append({"sequence": event.sequence, "error": "signature_verification_failed", "detail": str(exc)})
        previous_hash = event.event_hash

    return {
        "ok": not errors,
        "event_count": len(events),
        "latest_sequence": events[-1].sequence if events else None,
        "latest_event_hash": events[-1].event_hash if events else None,
        "errors": errors,
    }


def portfolio_audit_status(db: Session, portfolio_item_id: str) -> dict[str, Any]:
    chain = verify_portfolio_audit_chain(db, portfolio_item_id, verify_signatures=True)
    latest_event = db.execute(
        select(PortfolioAuditEvent)
        .where(PortfolioAuditEvent.portfolio_item_id == portfolio_item_id)
        .order_by(PortfolioAuditEvent.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_anchor = db.execute(
        select(PortfolioAuditAnchor)
        .where(PortfolioAuditAnchor.portfolio_item_id == portfolio_item_id)
        .order_by(PortfolioAuditAnchor.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    anchor_count = db.execute(
        select(func.count(PortfolioAuditAnchor.id)).where(PortfolioAuditAnchor.portfolio_item_id == portfolio_item_id)
    ).scalar_one()
    status = "empty"
    if latest_event:
        status = "verified" if chain["ok"] else "chain_failed"
        if chain["ok"] and (not latest_anchor or (latest_anchor.end_sequence or 0) < latest_event.sequence):
            status = "anchor_pending"
        elif chain["ok"] and latest_anchor and latest_anchor.verification_status != "verified":
            status = latest_anchor.verification_status
    return {
        "verification_status": status,
        "event_count": chain["event_count"],
        "latest_sequence": chain["latest_sequence"],
        "latest_event_hash": chain["latest_event_hash"],
        "latest_anchor_id": latest_anchor.id if latest_anchor else None,
        "latest_anchor_status": latest_anchor.verification_status if latest_anchor else None,
        "latest_anchor_time": latest_anchor.tsa_time if latest_anchor else None,
        "latest_anchor_root_hash": latest_anchor.root_hash if latest_anchor else None,
        "anchor_count": int(anchor_count or 0),
        "errors": chain["errors"],
    }


def _build_timestamp_request_der(root_hash: str, nonce: int) -> bytes:
    from asn1crypto import algos, core, tsp

    return tsp.TimeStampReq(
        {
            "version": "v1",
            "message_imprint": tsp.MessageImprint(
                {
                    "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
                    "hashed_message": bytes.fromhex(root_hash),
                }
            ),
            "nonce": core.Integer(nonce),
            "cert_req": True,
        }
    ).dump()


def _parse_timestamp_response_der(response_der: bytes, *, expected_root_hash: str, expected_nonce: int) -> dict[str, Any]:
    from asn1crypto import tsp

    response = tsp.TimeStampResp.load(response_der)
    status = response["status"]["status"].native
    if status not in {"granted", "granted_with_mods"}:
        return {"verification_status": "anchor_failed", "verification_error": f"TSA status {status}"}

    token = response["time_stamp_token"]
    signed_data = token["content"]
    content_info = signed_data["encap_content_info"]
    tst_info = content_info["content"].parsed
    hashed_message = tst_info["message_imprint"]["hashed_message"].native
    nonce = tst_info["nonce"].native if "nonce" in tst_info and tst_info["nonce"].native is not None else None
    if hashed_message != bytes.fromhex(expected_root_hash):
        return {"verification_status": "anchor_failed", "verification_error": "TSA imprint did not match root hash"}
    if nonce != expected_nonce:
        return {"verification_status": "anchor_failed", "verification_error": "TSA nonce did not match request"}
    return {
        "verification_status": "verified",
        "tsa_policy_oid": tst_info["policy"].native,
        "tsa_serial_number": str(tst_info["serial_number"].native),
        "tsa_time": tst_info["gen_time"].native,
        "anchor_metadata": {
            "rfc3161_status": status,
            "hash_algorithm": tst_info["message_imprint"]["hash_algorithm"]["algorithm"].native,
            "nonce": nonce,
        },
    }


def create_timestamp_anchor(db: Session, portfolio_item_id: str, *, tsa_url: str | None = None) -> PortfolioAuditAnchor | None:
    latest_event = db.execute(
        select(PortfolioAuditEvent)
        .where(PortfolioAuditEvent.portfolio_item_id == portfolio_item_id)
        .order_by(PortfolioAuditEvent.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_event is None:
        return None

    root_hash = latest_event.event_hash
    anchor = PortfolioAuditAnchor(
        portfolio_item_id=portfolio_item_id,
        root_event_id=latest_event.id,
        start_sequence=1,
        end_sequence=latest_event.sequence,
        root_hash=root_hash,
        tsa_url=tsa_url,
        verification_status="anchor_pending",
        anchor_metadata={"schema": "medusa.portfolio.audit.anchor.v1", "protocol": "RFC3161"},
    )
    db.add(anchor)
    db.flush()
    if not tsa_url:
        return anchor

    nonce = int.from_bytes(secrets.token_bytes(16), "big")
    try:
        request_der = _build_timestamp_request_der(root_hash, nonce)
        anchor.request_sha256 = sha256_hex(request_der)
        timeout = get_settings().audit_timestamp_timeout_seconds
        response = httpx.post(
            tsa_url,
            content=request_der,
            headers={"Content-Type": "application/timestamp-query", "Accept": "application/timestamp-reply"},
            timeout=timeout,
        )
        response.raise_for_status()
        response_der = response.content
        anchor.response_der_base64 = base64.b64encode(response_der).decode("ascii")
        parsed = _parse_timestamp_response_der(response_der, expected_root_hash=root_hash, expected_nonce=nonce)
        anchor.verification_status = parsed.get("verification_status", "anchor_failed")
        anchor.verification_error = parsed.get("verification_error")
        anchor.tsa_policy_oid = parsed.get("tsa_policy_oid")
        anchor.tsa_serial_number = parsed.get("tsa_serial_number")
        anchor.tsa_time = parsed.get("tsa_time")
        anchor.anchor_metadata = {**(anchor.anchor_metadata or {}), **(parsed.get("anchor_metadata") or {})}
    except Exception as exc:  # noqa: BLE001 - anchor failures should not block local audit writes.
        anchor.verification_status = "anchor_failed"
        anchor.verification_error = str(exc)
    anchor.last_verified_at = utc_now()
    db.flush()
    return anchor


def maybe_anchor_portfolio_audit(db: Session, portfolio_item_id: str) -> PortfolioAuditAnchor | None:
    settings = get_settings()
    if not settings.audit_timestamp_enabled:
        return None
    latest_event = db.execute(
        select(PortfolioAuditEvent)
        .where(PortfolioAuditEvent.portfolio_item_id == portfolio_item_id)
        .order_by(PortfolioAuditEvent.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_event is None:
        return None
    covering_anchor = db.execute(
        select(PortfolioAuditAnchor)
        .where(
            PortfolioAuditAnchor.portfolio_item_id == portfolio_item_id,
            PortfolioAuditAnchor.end_sequence >= latest_event.sequence,
        )
        .order_by(PortfolioAuditAnchor.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if covering_anchor is not None:
        return covering_anchor
    urls = configured_timestamp_urls()
    return create_timestamp_anchor(db, portfolio_item_id, tsa_url=urls[0] if urls else None)
