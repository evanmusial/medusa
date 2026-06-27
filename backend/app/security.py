from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SessionToken, User, utc_now


def _hash_secret(secret: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 240_000)
    return base64.b64encode(salt).decode("ascii") + "$" + base64.b64encode(digest).decode("ascii")


def hash_password(password: str) -> str:
    return _hash_secret(password)


def verify_secret(secret: str, secret_hash: str) -> bool:
    try:
        encoded_salt, encoded_digest = secret_hash.split("$", 1)
        salt = base64.b64decode(encoded_salt)
        expected = base64.b64decode(encoded_digest)
    except (ValueError, binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 240_000)
    return hmac.compare_digest(actual, expected)


def verify_password(password: str, password_hash: str) -> bool:
    return verify_secret(password, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_setup_uri(secret: str, email: str) -> str:
    issuer = get_settings().app_name or "Medusa"
    label = f"{issuer}:{email}"
    return (
        f"otpauth://totp/{quote(label)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


def _decode_totp_secret(secret: str) -> bytes:
    normalized = "".join(secret.upper().split())
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def _totp_code_for_step(secret: str, step: int) -> str:
    key = _decode_totp_secret(secret)
    counter = step.to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{code_int % 1_000_000:06d}"


def current_totp_code(secret: str, at_time: float | None = None) -> str:
    timestamp = time.time() if at_time is None else at_time
    return _totp_code_for_step(secret, int(timestamp // 30))


def normalize_totp_code(code: str | None) -> str:
    return "".join(char for char in (code or "") if char.isdigit())


def verify_totp_code(
    secret: str | None,
    code: str | None,
    *,
    at_time: float | None = None,
    window: int = 1,
    last_used_step: int | None = None,
) -> int | None:
    normalized = normalize_totp_code(code)
    if not secret or len(normalized) != 6:
        return None
    timestamp = time.time() if at_time is None else at_time
    current_step = int(timestamp // 30)
    try:
        for step in range(current_step - window, current_step + window + 1):
            if last_used_step is not None and step <= last_used_step:
                continue
            if hmac.compare_digest(_totp_code_for_step(secret, step), normalized):
                return step
    except (ValueError, binascii.Error):
        return None
    return None


def generate_recovery_codes(count: int = 10) -> list[str]:
    codes: list[str] = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(5)).decode("ascii").rstrip("=")
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def normalize_recovery_code(code: str | None) -> str:
    return "".join(char for char in (code or "").upper() if char.isalnum())


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [_hash_secret(normalize_recovery_code(code)) for code in codes]


def verify_two_factor_code(user: User, code: str | None) -> bool:
    if not user.two_factor_enabled:
        return True
    matched_step = verify_totp_code(
        user.two_factor_secret,
        code,
        last_used_step=user.two_factor_last_used_step,
    )
    if matched_step is not None:
        user.two_factor_last_used_step = matched_step
        return True

    normalized_recovery = normalize_recovery_code(code)
    if not normalized_recovery:
        return False
    recovery_hashes = list(user.two_factor_recovery_hashes or [])
    for index, recovery_hash in enumerate(recovery_hashes):
        if verify_secret(normalized_recovery, recovery_hash):
            user.two_factor_recovery_hashes = recovery_hashes[:index] + recovery_hashes[index + 1 :]
            return True
    return False


def create_session(db: Session, user: User, user_agent: str | None = None) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    now = utc_now()
    session = SessionToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        last_seen_at=now,
        user_agent=user_agent,
    )
    db.add(session)
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    session = db.query(SessionToken).filter(SessionToken.token_hash == hash_token(token)).one_or_none()
    if session:
        session.revoked_at = utc_now()
        db.commit()


def revoke_other_sessions(db: Session, user: User, token: str | None) -> None:
    query = (
        db.query(SessionToken)
        .filter(SessionToken.user_id == user.id)
        .filter(SessionToken.revoked_at.is_(None))
    )
    if token:
        query = query.filter(SessionToken.token_hash != hash_token(token))
    query.update({"revoked_at": utc_now()}, synchronize_session=False)


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    session = (
        db.query(SessionToken)
        .filter(SessionToken.token_hash == hash_token(token))
        .filter(SessionToken.revoked_at.is_(None))
        .filter(SessionToken.expires_at > now)
        .one_or_none()
    )
    if not session or not session.user.is_active:
        return None
    return session.user


def touch_session(db: Session, token: str | None) -> SessionToken | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    session = (
        db.query(SessionToken)
        .filter(SessionToken.token_hash == hash_token(token))
        .filter(SessionToken.revoked_at.is_(None))
        .filter(SessionToken.expires_at > now)
        .one_or_none()
    )
    if not session or not session.user.is_active:
        return None
    session.last_seen_at = now
    return session


def ensure_admin_user(db: Session) -> User:
    settings = get_settings()
    user = db.query(User).filter(User.email == settings.admin_email).one_or_none()
    if user:
        return user
    if settings.admin_password == "medusa" and not settings.allow_default_password:
        raise RuntimeError("Set MEDUSA_PASSWORD before starting Medusa.")
    user = User(
        email=settings.admin_email,
        display_name="Medusa Admin",
        password_hash=hash_password(settings.admin_password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(User).filter(User.email == settings.admin_email).one_or_none()
        if existing:
            return existing
        raise
    db.refresh(user)
    return user
