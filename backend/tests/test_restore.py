from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_restore_export_round_trips_core_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import (
        Annotation,
        AppPreference,
        AttributeDefinition,
        CitationCandidate,
        Document,
        DocumentAttributeValue,
        DocumentPage,
        Domain,
        Figure,
        ImportBatch,
        ImportJob,
        Note,
        ProcessingEvent,
        Project,
        ProjectBibliography,
        ProjectItem,
        Tag,
        TagAlias,
        TextChunk,
        User,
    )
    from app.services.exports import build_metadata_export
    from app.services.restore import restore_metadata_export

    SourceSession = make_session()
    with SourceSession() as source:
        user = User(email="admin@medusa.local", display_name="Admin", password_hash="not-in-export")
        tag = Tag(name="systems", kind="tag")
        parent = Domain(name="Philosophy")
        child = Domain(name="Cybernetics", parent=parent, tags=[tag])
        attribute = AttributeDefinition(name="Aspect summary", value_type="markdown")
        source.add_all([user, parent, child, tag, attribute])
        source.flush()
        source.add(TagAlias(alias_name="system theory", target_tag_id=tag.id, source="merge", alias_metadata={"source_tag_name": "system theory"}))

        document = Document(
            title="Restorable Paper",
            authors=[{"given": "Ada", "family": "Lovelace"}],
            publication_year=1843,
            original_filename="restorable.pdf",
            checksum_sha256="a" * 64,
            gcs_uri="gs://musial-medusa-assets/medusa/documents/aa/restorable.pdf",
            storage_status="gcs",
            search_text="Restorable Paper systems",
            domains=[child],
            tags=[tag],
        )
        source.add(document)
        source.flush()
        source.add(DocumentPage(document_id=document.id, page_number=1, text="Extracted page text.", normalized_text="Readable page text."))
        source.add(TextChunk(document_id=document.id, page_start=1, page_end=1, text="Extracted page text.", token_count=3))
        source.add(
            Figure(
                document_id=document.id,
                page_number=1,
                figure_label="Figure p1-001",
                asset_uri="gs://bucket/figure.png",
                geometry={"source": "vector_graphic", "bbox": [20, 30, 200, 180]},
            )
        )
        source.add(Annotation(document_id=document.id, page_number=1, body="Important margin note.", color="#60a5fa"))
        source.add(DocumentAttributeValue(document_id=document.id, attribute_definition_id=attribute.id, value={"value": "Machines"}))
        source.add(Note(document_id=document.id, title="Use this", body="Relevant to the introduction."))
        source.add(CitationCandidate(document_id=document.id, source="crossref", citation_text="Lovelace, A. (1843).", status="needs_review"))

        project = Project(name="Paper draft", description="Run sheet")
        source.add(project)
        source.flush()
        source.add(ProjectItem(project_id=project.id, document_id=document.id, status="selected", priority="high", used_in_output=True))
        source.add(ProjectBibliography(project_id=project.id, style="apa7", body="Lovelace, A. (1843)."))

        batch = ImportBatch(label="Backup batch", status="running", total_files=1)
        source.add(batch)
        source.flush()
        job = ImportJob(batch_id=batch.id, document_id=document.id, status="queued", current_step="extracting")
        source.add(job)
        source.flush()
        source.add(ProcessingEvent(import_job_id=job.id, document_id=document.id, event_type="queued", message="Queued."))
        source.add(AppPreference(key="import_worker_concurrency", value={"value": 3}))
        source.commit()

        exported = build_metadata_export(source)

    DestinationSession = make_session()
    with DestinationSession() as destination:
        dry_run = restore_metadata_export(destination, exported, dry_run=True)
        assert dry_run["applied"] is False
        assert dry_run["counts"]["documents"] == 1
        assert destination.query(Document).count() == 0

        result = restore_metadata_export(destination, exported, dry_run=False)
        destination.commit()

        restored = destination.query(Document).one()
        restored_job = destination.query(ImportJob).one()
        restored_project = destination.query(Project).one()
        restored_preference = destination.query(AppPreference).one()
        restored_alias = destination.query(TagAlias).one()

        assert result["applied"] is True
        assert result["restored_counts"]["tag_aliases"] == 1
        assert destination.query(User).count() == 0
        assert restored.title == "Restorable Paper"
        assert restored.domains[0].name == "Cybernetics"
        assert restored.domains[0].parent.name == "Philosophy"
        assert restored.domains[0].tags[0].name == "systems"
        assert restored.tags[0].name == "systems"
        assert restored_alias.alias_name == "system theory"
        assert restored_alias.target_tag_id == restored.tags[0].id
        assert restored.pages[0].text == "Extracted page text."
        assert restored.pages[0].normalized_text == "Readable page text."
        assert restored.figures[0].asset_uri == "gs://bucket/figure.png"
        assert restored.figures[0].geometry["source"] == "vector_graphic"
        assert restored.annotations[0].body == "Important margin note."
        assert restored.attributes[0].value == {"value": "Machines"}
        assert restored_project.items[0].document_id == restored.id
        assert restored_preference.key == "import_worker_concurrency"
        assert restored_preference.value == {"value": 3}
        assert restored_job.status == "restored_paused"
        assert "parked" in restored_job.last_error


def test_restore_validation_rejects_secret_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services.exports import EXPORT_SCHEMA_VERSION
    from app.services.restore import RestoreValidationError, restore_metadata_export, validate_metadata_export

    payload = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "safety": {"secrets_included": False},
        "data": {
            "documents": [{"id": "doc", "title": "Bad", "password_hash": "nope"}],
            "domains": [],
            "tags": [],
        },
    }

    validation = validate_metadata_export(payload)

    assert validation["valid"] is False
    assert "password_hash" in validation["errors"][0]

    Session = make_session()
    with Session() as db:
        try:
            restore_metadata_export(db, payload, dry_run=False)
        except RestoreValidationError as exc:
            assert "password_hash" in str(exc)
        else:
            raise AssertionError("Restore should reject exports containing secret-bearing keys.")
