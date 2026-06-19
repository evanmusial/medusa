from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_patch_document_records_manual_correction(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import patch_document
    from app.models import AttributeDefinition, Document, DocumentAttributeValue, DocumentVersion
    from app.schemas import DocumentPatch

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Wrong Title",
            authors=[{"given": "Ada", "family": "Wrong"}],
            publication_year=2020,
            original_filename="paper.pdf",
            checksum_sha256="c" * 64,
        )
        db.add(document)
        db.flush()
        definition = AttributeDefinition(name="Old attribute", value_type="markdown")
        db.add(definition)
        db.flush()
        db.add(
            DocumentAttributeValue(
                document_id=document.id,
                attribute_definition_id=definition.id,
                value={"value": "remove me"},
            )
        )
        db.commit()

        updated = patch_document(
            document.id,
            DocumentPatch(
                title="Correct Title",
                authors=[{"given": "Ada", "family": "Lovelace"}],
                tag_names=["Computation", "history of science"],
                attribute_values={"Old attribute": "", "Aspect summary": "Analytical engine context."},
            ),
            object(),
            db,
        )

        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).all()

        assert updated.title == "Correct Title"
        assert "Lovelace" in (updated.apa_citation or "")
        assert sorted(tag.name for tag in updated.tags) == ["computation", "history of science"]
        assert {value.definition.name: value.value for value in updated.attributes} == {
            "Aspect summary": {"value": "Analytical engine context."}
        }
        assert len(versions) == 1
        assert versions[0].change_note == "Manual correction"
        assert "title" in versions[0].metadata_snapshot["changed_fields"]


def test_patch_document_marks_inline_citation_edits_user_provided(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import patch_document
    from app.models import Document, DocumentVersion
    from app.schemas import DocumentPatch

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Citation Paper",
            authors=[{"given": "Ada", "family": "Lovelace"}],
            publication_year=1843,
            original_filename="citation.pdf",
            checksum_sha256="d" * 64,
            apa_citation="Lovelace, A. (1843). Old.",
            apa_citation_model="gpt-5.5",
            apa_citation_source="model",
            apa_in_text_citation="(Lovelace, 1843)",
            apa_in_text_citation_model="gpt-5.5",
            apa_in_text_citation_source="model",
        )
        db.add(document)
        db.commit()

        updated = patch_document(
            document.id,
            DocumentPatch(apa_in_text_citation="(A. Lovelace, 1843)"),
            object(),
            db,
        )
        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()

        assert updated.apa_in_text_citation == "(A. Lovelace, 1843)"
        assert updated.apa_in_text_citation_source == "user"
        assert updated.apa_in_text_citation_model is None
        assert updated.apa_citation_model == "gpt-5.5"
        assert version.metadata_snapshot["changed_fields"] == [
            "apa_in_text_citation",
            "apa_in_text_citation_model",
            "apa_in_text_citation_source",
        ]


def test_create_document_note_updates_search_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import create_note
    from app.models import Document
    from app.schemas import NoteCreate

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Methods Paper",
            original_filename="methods.pdf",
            checksum_sha256="f" * 64,
            search_text="Methods Paper",
        )
        db.add(document)
        db.commit()

        create_note(
            NoteCreate(title="Use later", body="This anchors the methods section.", document_id=document.id),
            object(),
            db,
        )
        db.refresh(document)

        assert "anchors the methods section" in (document.search_text or "")


def test_bulk_update_documents_can_create_custom_tag(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import bulk_update_documents
    from app.models import Document, Tag

    Session = make_session()
    with Session() as db:
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64)
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64)
        db.add_all([first, second])
        db.commit()

        result = bulk_update_documents(
            {"document_ids": [first.id, second.id], "updates": {"tag_names": ["New Research Thread"]}},
            object(),
            db,
        )
        db.refresh(first)
        db.refresh(second)

        assert result == {"updated": 2}
        assert db.query(Tag).filter(Tag.name == "new research thread").count() == 1
        assert [tag.name for tag in first.tags] == ["new research thread"]
        assert [tag.name for tag in second.tags] == ["new research thread"]


def test_list_documents_marks_and_filters_checksum_duplicates(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_documents
    from app.models import Document

    Session = make_session()
    with Session() as db:
        first = Document(title="First duplicate", original_filename="first.pdf", checksum_sha256="d" * 64)
        second = Document(title="Second duplicate", original_filename="second.pdf", checksum_sha256="d" * 64)
        unique = Document(title="Unique", original_filename="unique.pdf", checksum_sha256="u" * 64)
        db.add_all([first, second, unique])
        db.commit()

        all_documents = list_documents(object(), db)
        duplicate_documents = list_documents(object(), db, duplicate_status="duplicates")
        unique_documents = list_documents(object(), db, duplicate_status="unique")

        counts = {document.title: document.duplicate_count for document in all_documents}
        assert counts["First duplicate"] == 1
        assert counts["Second duplicate"] == 1
        assert counts["Unique"] == 0
        assert {document.title for document in duplicate_documents} == {"First duplicate", "Second duplicate"}
        assert [document.title for document in unique_documents] == ["Unique"]


def test_document_original_serves_storage_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_original
    from app.models import Document

    class FakeStorage:
        def get_bytes(self, uri):
            assert uri == "gs://bucket/documents/paper.pdf"
            return b"%PDF-1.4 fake"

    monkeypatch.setattr("app.main.get_storage_service", lambda: FakeStorage())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Stored Paper",
            original_filename="paper.pdf",
            checksum_sha256="a" * 64,
            gcs_uri="gs://bucket/documents/paper.pdf",
            content_type="application/pdf",
        )
        db.add(document)
        db.commit()

        response = document_original(document.id, object(), db)

        assert response.body == b"%PDF-1.4 fake"
        assert response.media_type == "application/pdf"
        assert 'filename="paper.pdf"' in response.headers["content-disposition"]


def test_document_detail_schema_includes_parsed_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentPage
    from app.schemas import DocumentDetail

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Readable Paper",
            original_filename="readable.pdf",
            checksum_sha256="b" * 64,
            page_count=1,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentPage(
                document_id=document.id,
                page_number=1,
                text="Parsed page text.",
                normalized_text="Readable page text.",
                text_source="pdf",
            )
        )
        db.commit()
        db.refresh(document)

        detail = DocumentDetail.model_validate(document)

        assert detail.pages[0].page_number == 1
        assert detail.pages[0].text == "Parsed page text."
        assert detail.pages[0].normalized_text == "Readable page text."


def test_refresh_document_citation_queues_citation_concordance(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import refresh_document_citation
    from app.models import ConcordanceJob, Document

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Citation Paper",
            original_filename="citation.pdf",
            checksum_sha256="9" * 64,
            citation_status="needs_review",
        )
        db.add(document)
        db.commit()

        run = refresh_document_citation(document.id, object(), db)
        jobs = db.query(ConcordanceJob).filter(ConcordanceJob.run_id == run.id).all()

        assert run.capability_keys == ["citation_refresh"]
        assert run.scope_type == "documents"
        assert jobs
        assert jobs[0].document_id == document.id
        assert jobs[0].capability_key == "citation_refresh"


def test_document_annotations_update_search_text_and_soft_delete(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import create_annotation, delete_annotation
    from app.models import Annotation, Document
    from app.schemas import AnnotationCreate

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Annotated Paper",
            original_filename="annotated.pdf",
            checksum_sha256="b" * 64,
            search_text="Annotated Paper",
        )
        db.add(document)
        db.commit()

        annotation = create_annotation(
            document.id,
            AnnotationCreate(page_number=3, kind="highlight", body="This is the core argument.", color="#f6c343"),
            object(),
            db,
        )
        db.refresh(document)

        assert annotation.page_number == 3
        assert "core argument" in (document.search_text or "")

        delete_annotation(annotation.id, object(), db)
        db.refresh(document)
        stored = db.get(Annotation, annotation.id)

        assert stored and stored.deleted_at is not None
        assert "core argument" not in (document.search_text or "")
