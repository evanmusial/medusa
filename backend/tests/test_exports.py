from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_metadata_export_includes_manifest_without_auth_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, Figure, SessionToken, TextChunk, User
    from app.services.exports import build_metadata_export

    Session = make_session()
    with Session() as db:
        user = User(email="admin@medusa.local", display_name="Admin", password_hash="never-export-this")
        db.add(user)
        db.flush()
        db.add(
            SessionToken(
                user_id=user.id,
                token_hash="session-token-hash",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        document = Document(
            title="Exported Paper",
            original_filename="paper.pdf",
            checksum_sha256="a" * 64,
            gcs_uri="gs://musial-medusa-assets/medusa/documents/aa/aaa/paper.pdf",
            storage_status="gcs",
            search_text="searchable text",
        )
        db.add(document)
        db.flush()
        db.add(TextChunk(document_id=document.id, page_start=1, page_end=1, text="chunk text", token_count=2))
        db.add(
            Figure(
                document_id=document.id,
                page_number=2,
                figure_label="Figure p2-001",
                gist="Embedded image extracted from page 2.",
                asset_uri="gs://musial-medusa-assets/medusa/figures/aa/aaa/page-0002-figure-001.png",
            )
        )
        db.commit()

        exported = build_metadata_export(db)

        assert exported["safety"]["password_hashes_included"] is False
        assert exported["safety"]["session_tokens_included"] is False
        assert "sessions" not in exported["data"]
        assert exported["data"]["users"][0] == {
            "id": user.id,
            "email": "admin@medusa.local",
            "display_name": "Admin",
            "is_active": True,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }
        assert "password_hash" not in exported["data"]["users"][0]
        assert exported["data"]["documents"][0]["text_chunks"][0]["text"] == "chunk text"
        assert exported["storage_manifest"]["counts"] == {"figure": 1, "original": 1}


def test_storage_manifest_maps_gcs_and_local_uris(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentPage
    from app.services.exports import build_storage_manifest

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Manifest Paper",
            original_filename="paper.pdf",
            checksum_sha256="b" * 64,
            gcs_uri=str(tmp_path / "data" / "originals" / "paper.pdf"),
            storage_status="local",
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, image_uri="gs://bucket/pages/p1.png"))
        db.commit()

        manifest = build_storage_manifest(db)

        assert manifest["object_count"] == 2
        assert manifest["objects"][0]["backend"] == "local"
        assert manifest["objects"][0]["path"].endswith("paper.pdf")
        assert manifest["objects"][1]["backend"] == "gcs"
        assert manifest["objects"][1]["bucket"] == "bucket"
        assert manifest["objects"][1]["object"] == "pages/p1.png"
