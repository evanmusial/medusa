import base64

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def clear_settings_cache():
    yield
    from app.config import get_settings

    get_settings.cache_clear()


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_asset_cdn_url_signs_gcs_object(monkeypatch):
    monkeypatch.setenv("MEDUSA_ASSET_CDN_BASE_URL", "https://assets.medusa.evan.engineer")
    monkeypatch.setenv("MEDUSA_ASSET_CDN_SIGNED_URL_KEY_NAME", "medusa-assets-test")
    monkeypatch.setenv(
        "MEDUSA_ASSET_CDN_SIGNED_URL_KEY",
        base64.urlsafe_b64encode(b"0123456789abcdef").decode("ascii"),
    )

    from app.config import get_settings
    from app.services import assets

    get_settings.cache_clear()
    monkeypatch.setattr(assets, "get_active_storage_settings", lambda: {"gcs_bucket": "musial-medusa-assets"})

    url = assets.asset_cdn_url_for_storage_uri(
        "gs://musial-medusa-assets/medusa/figures/ab/abcdef/Figure 1.png",
        expires_at=12345,
    )

    assert url is not None
    assert url.startswith("https://assets.medusa.evan.engineer/medusa/figures/ab/abcdef/Figure%201.png?")
    assert "Expires=12345" in url
    assert "KeyName=medusa-assets-test" in url
    assert "Signature=" in url


def test_asset_cleanup_deletes_unreferenced_uri_and_marks_invalidation_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_ASSET_CDN_BASE_URL", "https://assets.medusa.evan.engineer")

    from app.config import get_settings
    from app.models import AssetDeletionQueue
    from app.services import assets

    get_settings.cache_clear()
    monkeypatch.setattr(assets, "get_active_storage_settings", lambda: {"gcs_bucket": "musial-medusa-assets"})
    deleted_assets = []

    class FakeStorage:
        def delete_uri(self, uri):
            deleted_assets.append(uri)
            return True

    monkeypatch.setattr(assets, "get_storage_service", lambda: FakeStorage())

    Session = make_session()
    with Session() as db:
        assets.enqueue_asset_deletion(
            db,
            "gs://musial-medusa-assets/medusa/figures/ab/abcdef/figure.png",
            source_kind="figure",
            source_id="figure-1",
            document_id=None,
        )
        db.commit()

        stats = assets.process_asset_deletion_queue(db)
        row = db.query(AssetDeletionQueue).one()

        assert stats["deleted"] == 1
        assert deleted_assets == ["gs://musial-medusa-assets/medusa/figures/ab/abcdef/figure.png"]
        assert row.status == "deleted"
        assert row.storage_deleted_at is not None
        assert row.completed_at is not None
        assert row.deletion_metadata["cdn_invalidation"] == "skipped_unconfigured"


def test_asset_cleanup_skips_currently_referenced_uri(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.models import AssetDeletionQueue, Document, Figure
    from app.services import assets

    get_settings.cache_clear()
    deleted_assets = []

    class FakeStorage:
        def delete_uri(self, uri):
            deleted_assets.append(uri)
            return True

    monkeypatch.setattr(assets, "get_storage_service", lambda: FakeStorage())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Current Figure",
            original_filename="paper.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        db.add(
            Figure(
                document_id=document.id,
                figure_label="Figure 1",
                asset_uri="gs://musial-medusa-assets/medusa/figures/ab/abcdef/figure.png",
            )
        )
        assets.enqueue_asset_deletion(
            db,
            "gs://musial-medusa-assets/medusa/figures/ab/abcdef/figure.png",
            source_kind="figure",
            source_id="old-figure",
            document_id=document.id,
        )
        db.commit()

        stats = assets.process_asset_deletion_queue(db)
        row = db.query(AssetDeletionQueue).one()

        assert stats["skipped_referenced"] == 1
        assert deleted_assets == []
        assert row.status == "skipped_referenced"
        assert row.completed_at is not None
