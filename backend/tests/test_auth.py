from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
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
