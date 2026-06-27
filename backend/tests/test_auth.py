from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_update_me_rotates_password_and_revokes_other_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import update_me
    from app.models import SessionToken, User
    from app.schemas import AccountUpdateRequest
    from app.security import hash_password, hash_token, verify_password

    Session = make_session()
    with Session() as db:
        user = User(
            email="admin@medusa.local",
            display_name="Admin",
            password_hash=hash_password("old-password"),
        )
        db.add(user)
        db.flush()
        current_session = SessionToken(
            user_id=user.id,
            token_hash=hash_token("current-token"),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        other_session = SessionToken(
            user_id=user.id,
            token_hash=hash_token("other-token"),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.add_all([current_session, other_session])
        db.commit()

        updated = update_me(
            AccountUpdateRequest(
                email="researcher@example.test",
                current_password="old-password",
                new_password="new-password",
                new_password_confirmation="new-password",
            ),
            user,
            db,
            token="current-token",
        )

        db.refresh(current_session)
        db.refresh(other_session)

        assert updated.email == "researcher@example.test"
        assert verify_password("new-password", updated.password_hash)
        assert current_session.revoked_at is None
        assert other_session.revoked_at is not None


def test_login_requires_two_factor_code_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import login
    from app.models import User
    from app.schemas import LoginRequest
    from app.security import current_totp_code, generate_totp_secret, hash_password

    secret = generate_totp_secret()
    Session = make_session()
    with Session() as db:
        user = User(
            email="admin@medusa.local",
            display_name="Admin",
            password_hash=hash_password("correct-password"),
            two_factor_enabled=True,
            two_factor_secret=secret,
            two_factor_recovery_hashes=[],
        )
        db.add(user)
        db.commit()

        request = SimpleNamespace(headers={"user-agent": "pytest"})
        with pytest.raises(HTTPException) as missing_code:
            login(LoginRequest(email="admin@medusa.local", password="correct-password"), request, Response(), db)
        assert missing_code.value.status_code == 401

        response = Response()
        logged_in = login(
            LoginRequest(
                email="admin@medusa.local",
                password="correct-password",
                otp_code=current_totp_code(secret),
            ),
            request,
            response,
            db,
        )
        assert logged_in.id == user.id
        assert "medusa_session=" in response.headers["set-cookie"]


def test_two_factor_setup_enable_and_recovery_code_login(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import enable_two_factor, login, setup_two_factor
    from app.models import User
    from app.schemas import LoginRequest, TwoFactorEnableRequest, TwoFactorSetupRequest
    from app.security import current_totp_code, hash_password

    Session = make_session()
    with Session() as db:
        user = User(
            email="admin@medusa.local",
            display_name="Admin",
            password_hash=hash_password("correct-password"),
        )
        db.add(user)
        db.commit()

        setup = setup_two_factor(TwoFactorSetupRequest(current_password="correct-password"), user)
        enabled = enable_two_factor(
            TwoFactorEnableRequest(
                current_password="correct-password",
                secret=setup.secret,
                otp_code=current_totp_code(setup.secret),
            ),
            user,
            db,
            token=None,
        )
        db.refresh(user)

        assert user.two_factor_enabled
        assert user.two_factor_secret == setup.secret
        assert len(enabled["recovery_codes"]) == 10
        assert user.two_factor_recovery_codes_remaining == 10

        recovery_code = enabled["recovery_codes"][0]
        logged_in = login(
            LoginRequest(
                email="admin@medusa.local",
                password="correct-password",
                otp_code=recovery_code,
            ),
            SimpleNamespace(headers={}),
            Response(),
            db,
        )
        db.refresh(user)
        assert logged_in.id == user.id
        assert user.two_factor_recovery_codes_remaining == 9


def test_activity_heartbeat_updates_last_seen_without_reviving_invalid_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import activity_heartbeat
    from app.models import SessionToken, User
    from app.security import hash_password, hash_token

    Session = make_session()
    now = datetime.now(timezone.utc)
    with Session() as db:
        user = User(
            email="admin@medusa.local",
            display_name="Admin",
            password_hash=hash_password("correct-password"),
        )
        db.add(user)
        db.flush()
        active_session = SessionToken(
            user_id=user.id,
            token_hash=hash_token("active-token"),
            expires_at=now + timedelta(days=1),
            last_seen_at=now - timedelta(minutes=20),
        )
        revoked_session = SessionToken(
            user_id=user.id,
            token_hash=hash_token("revoked-token"),
            expires_at=now + timedelta(days=1),
            last_seen_at=now - timedelta(minutes=20),
            revoked_at=now - timedelta(minutes=1),
        )
        expired_session = SessionToken(
            user_id=user.id,
            token_hash=hash_token("expired-token"),
            expires_at=now - timedelta(minutes=1),
            last_seen_at=now - timedelta(minutes=20),
        )
        db.add_all([active_session, revoked_session, expired_session])
        db.commit()

        result = activity_heartbeat(db, token="active-token")
        db.refresh(active_session)
        assert result["status"] == "ok"
        assert active_session.last_seen_at is not None
        assert active_session.last_seen_at > now - timedelta(minutes=1)

        with pytest.raises(HTTPException) as revoked:
            activity_heartbeat(db, token="revoked-token")
        with pytest.raises(HTTPException) as expired:
            activity_heartbeat(db, token="expired-token")

        db.refresh(revoked_session)
        db.refresh(expired_session)
        assert revoked.value.status_code == 401
        assert expired.value.status_code == 401
        assert revoked_session.last_seen_at == now - timedelta(minutes=20)
        assert expired_session.last_seen_at == now - timedelta(minutes=20)


def test_ensure_admin_user_handles_concurrent_insert(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))

    from app.config import get_settings

    get_settings.cache_clear()

    from app.models import User
    from app.security import ensure_admin_user

    existing = User(email="admin@medusa.local", display_name="Medusa Admin", password_hash="hash")

    class FakeQuery:
        def __init__(self, db):
            self.db = db

        def filter(self, *args):
            return self

        def one_or_none(self):
            self.db.query_count += 1
            return None if self.db.query_count == 1 else existing

    class FakeDb:
        def __init__(self):
            self.query_count = 0
            self.rollback_called = False

        def query(self, model):
            assert model is User
            return FakeQuery(self)

        def add(self, user):
            self.added_user = user

        def commit(self):
            raise IntegrityError("insert user", {}, Exception("duplicate"))

        def rollback(self):
            self.rollback_called = True

    db = FakeDb()

    user = ensure_admin_user(db)

    assert user is existing
    assert db.rollback_called
