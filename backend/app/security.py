from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SessionToken, User, utc_now


def _hash_secret(secret: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 240_000)
    return base64.b64encode(salt).decode("ascii") + "$" + base64.b64encode(digest).decode("ascii")


def hash_password(password: str) -> str:
    return _hash_secret(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        encoded_salt, encoded_digest = password_hash.split("$", 1)
        salt = base64.b64decode(encoded_salt)
        expected = base64.b64decode(encoded_digest)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, user_agent: str | None = None) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    session = SessionToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utc_now() + timedelta(hours=settings.session_ttl_hours),
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
    db.commit()
    db.refresh(user)
    return user
