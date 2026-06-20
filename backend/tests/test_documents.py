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


def test_rename_tag_updates_counts_search_and_document_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_tags, rename_tag
    from app.models import Document, DocumentVersion, Tag
    from app.schemas import TagRename

    Session = make_session()
    with Session() as db:
        tag = Tag(name="old topic", kind="tag")
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, tags=[tag])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, tags=[tag])
        db.add_all([first, second])
        db.commit()

        result = rename_tag(tag.id, TagRename(name="New Topic"), object(), db)
        db.refresh(first)
        db.refresh(second)

        versions = db.query(DocumentVersion).order_by(DocumentVersion.document_id, DocumentVersion.version_number).all()
        tags = list_tags(object(), db)

        assert result.tag.name == "new topic"
        assert result.tag.document_count == 2
        assert result.updated_documents == 2
        assert tags[0].document_count == 2
        assert [tag.name for tag in first.tags] == ["new topic"]
        assert "new topic" in (first.search_text or "")
        assert len(versions) == 2
        assert {version.change_note for version in versions} == {'Renamed tag "old topic" to "new topic"'}
        assert all(version.metadata_snapshot["operation"] == "tag_rename" for version in versions)


def test_merge_tags_collapses_links_records_history_and_remembers_aliases(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import get_or_create_tag_by_name, merge_tags
    from app.models import Document, DocumentVersion, Tag, TagAlias
    from app.schemas import TagMerge

    Session = make_session()
    with Session() as db:
        keep = Tag(name="keep me", kind="tag")
        collapse = Tag(name="collapse me", kind="tag")
        untouched = Tag(name="untouched", kind="tag")
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, tags=[collapse])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, tags=[keep, collapse])
        third = Document(title="Third", original_filename="third.pdf", checksum_sha256="3" * 64, tags=[keep])
        fourth = Document(title="Fourth", original_filename="fourth.pdf", checksum_sha256="4" * 64, tags=[untouched])
        db.add_all([first, second, third, fourth])
        db.commit()

        result = merge_tags(
            TagMerge(source_tag_ids=[keep.id, collapse.id], target_name="Merged Topic"),
            object(),
            db,
        )
        db.refresh(first)
        db.refresh(second)
        db.refresh(third)
        db.refresh(fourth)

        remaining_names = {tag.name for tag in db.query(Tag).all()}
        aliases = {alias.alias_name: alias.target_tag_id for alias in db.query(TagAlias).all()}
        versions = db.query(DocumentVersion).order_by(DocumentVersion.document_id, DocumentVersion.version_number).all()
        canonical = get_or_create_tag_by_name(db, "Collapse Me")

        assert result.tag.name == "merged topic"
        assert result.tag.document_count == 3
        assert result.updated_documents == 3
        assert set(result.removed_tag_ids) == {collapse.id}
        assert remaining_names == {"merged topic", "untouched"}
        assert aliases == {"collapse me": result.tag.id, "keep me": result.tag.id}
        assert canonical and canonical.id == result.tag.id
        assert db.query(Tag).filter(Tag.name == "collapse me").count() == 0
        assert [tag.name for tag in first.tags] == ["merged topic"]
        assert [tag.name for tag in second.tags] == ["merged topic"]
        assert [tag.name for tag in third.tags] == ["merged topic"]
        assert [tag.name for tag in fourth.tags] == ["untouched"]
        assert len(versions) == 3
        assert all(version.metadata_snapshot["operation"] == "tag_merge" for version in versions)


def test_merge_tags_carries_forward_existing_aliases(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import get_or_create_tag_by_name, merge_tags
    from app.models import Document, Tag, TagAlias
    from app.schemas import TagMerge

    Session = make_session()
    with Session() as db:
        alpha = Tag(name="alpha", kind="tag")
        beta = Tag(name="beta", kind="tag")
        gamma = Tag(name="gamma", kind="tag")
        document = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, tags=[alpha])
        db.add_all([alpha, beta, gamma, document])
        db.commit()

        first_merge = merge_tags(TagMerge(source_tag_ids=[alpha.id, beta.id], target_tag_id=beta.id), object(), db)
        second_merge = merge_tags(TagMerge(source_tag_ids=[first_merge.tag.id, gamma.id], target_tag_id=gamma.id), object(), db)
        db.refresh(document)

        aliases = {alias.alias_name: alias.target_tag_id for alias in db.query(TagAlias).all()}
        canonical = get_or_create_tag_by_name(db, "Alpha")

        assert second_merge.tag.name == "gamma"
        assert aliases == {"alpha": gamma.id, "beta": gamma.id}
        assert canonical and canonical.id == gamma.id
        assert [tag.name for tag in document.tags] == ["gamma"]


def test_merge_tags_target_name_uses_existing_alias_target(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import merge_tags
    from app.models import Document, Tag, TagAlias
    from app.schemas import TagMerge

    Session = make_session()
    with Session() as db:
        canonical = Tag(name="canonical", kind="tag")
        first_source = Tag(name="first source", kind="tag")
        second_source = Tag(name="second source", kind="tag")
        document = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, tags=[first_source])
        db.add_all([canonical, first_source, second_source, document])
        db.flush()
        db.add(TagAlias(alias_name="old canonical", target_tag_id=canonical.id, source="merge", alias_metadata={}))
        db.commit()

        result = merge_tags(
            TagMerge(source_tag_ids=[first_source.id, second_source.id], target_name="Old Canonical"),
            object(),
            db,
        )
        db.refresh(document)

        aliases = {alias.alias_name: alias.target_tag_id for alias in db.query(TagAlias).all()}
        remaining_names = {tag.name for tag in db.query(Tag).all()}

        assert result.tag.id == canonical.id
        assert result.tag.name == "canonical"
        assert remaining_names == {"canonical"}
        assert aliases == {
            "first source": canonical.id,
            "old canonical": canonical.id,
            "second source": canonical.id,
        }
        assert [tag.name for tag in document.tags] == ["canonical"]


def test_optimize_tags_returns_reviewable_suggestions_with_counts(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import optimize_tags
    from app.models import Document, Tag
    from app.schemas import TagOptimizationCreate

    seen_inventory = []

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, tags, *, model, usage_context):
            seen_inventory.extend(tags)
            assert model == "gpt-5.4-mini"
            assert usage_context.source == "tags"
            assert usage_context.capability_key == "tag_optimization"
            assert all(set(tag) == {"id", "name", "document_count"} for tag in tags)
            by_name = {tag["name"]: tag["id"] for tag in tags}
            return {
                "suggestions": [
                    {
                        "target_name": "Insider Threat",
                        "source_tag_ids": [by_name["insider threat detection"], by_name["insider threats"]],
                        "rationale": "These are close variants of the same primitive research tag.",
                        "confidence": 0.84,
                    }
                ]
            }

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        base = Tag(name="insider threat", kind="tag")
        detection = Tag(name="insider threat detection", kind="tag")
        plural = Tag(name="insider threats", kind="tag")
        unrelated = Tag(name="network defense", kind="tag")
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, tags=[base])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, tags=[detection])
        third = Document(title="Third", original_filename="third.pdf", checksum_sha256="3" * 64, tags=[plural])
        fourth = Document(title="Fourth", original_filename="fourth.pdf", checksum_sha256="4" * 64, tags=[unrelated])
        db.add_all([first, second, third, fourth])
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[base.id, detection.id, plural.id]), object(), db)

        suggestion = result.suggestions[0]
        inventory_counts = {tag["name"]: tag["document_count"] for tag in seen_inventory}

        assert result.model == "gpt-5.4-mini"
        assert result.considered_tags == 3
        assert inventory_counts == {"insider threat": 1, "insider threat detection": 1, "insider threats": 1}
        assert suggestion.target_name == "insider threat"
        assert suggestion.target_tag_id == base.id
        assert set(suggestion.source_tag_ids) == {base.id, detection.id, plural.id}
        assert sorted(tag.name for tag in suggestion.source_tags) == ["insider threat", "insider threat detection", "insider threats"]
        assert suggestion.affected_documents == 3
        assert suggestion.confidence == 0.84


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
            title='Stored/Paper: Study?',
            authors=[{"given": "Ada", "family": "Lovelace"}],
            publication_year=1843,
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

        download_response = document_original(document.id, object(), db, download=True)

        assert download_response.body == b"%PDF-1.4 fake"
        assert "attachment" in download_response.headers["content-disposition"]
        assert 'filename="Stored_Paper_ Study_ (1843).pdf"' in download_response.headers["content-disposition"]


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


def test_patch_document_page_records_history_and_updates_search_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import patch_document_page
    from app.models import Document, DocumentPage, DocumentVersion
    from app.schemas import DocumentPagePatch

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Editable Text Paper",
            original_filename="editable.pdf",
            checksum_sha256="e" * 64,
            search_text="Editable Text Paper old OCR",
        )
        db.add(document)
        db.flush()
        page = DocumentPage(
            document_id=document.id,
            page_number=2,
            text="Raw OCR text.",
            normalized_text="Old extracted text.",
            text_source="pdf",
        )
        db.add(page)
        db.commit()

        updated = patch_document_page(
            document.id,
            page.id,
            DocumentPagePatch(normalized_text="Corrected extracted text."),
            object(),
            db,
        )
        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()
        db.refresh(page)
        db.refresh(document)

        assert updated.pages[0].normalized_text == "Corrected extracted text."
        assert page.text_source == "manual"
        assert "Corrected extracted text" in (document.search_text or "")
        assert "Old extracted text" not in (document.search_text or "")
        assert version.change_note == "Edited extracted text page 2"
        assert version.metadata_snapshot["page_before"]["normalized_text"] == "Old extracted text."
        assert version.metadata_snapshot["page_after"]["normalized_text"] == "Corrected extracted text."
        assert "page_2_normalized_text" in version.metadata_snapshot["changed_fields"]


def test_scrub_document_text_removes_matches_across_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import scrub_document_text
    from app.models import Document, DocumentPage, DocumentVersion
    from app.schemas import DocumentTextScrub

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Scrub Paper",
            original_filename="scrub.pdf",
            checksum_sha256="s" * 64,
            search_text="Scrub Paper Copyright 2026",
        )
        db.add(document)
        db.flush()
        first = DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Raw page.",
            normalized_text="Copyright 2026\nBody text.\nCopyright 2026",
            text_source="pdf",
        )
        second = DocumentPage(
            document_id=document.id,
            page_number=2,
            text="Copyright 2026\nSecond page.",
            normalized_text=None,
            text_source="pdf",
        )
        db.add_all([first, second])
        db.commit()

        updated = scrub_document_text(document.id, DocumentTextScrub(text="Copyright 2026"), object(), db)
        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).all()
        db.refresh(first)
        db.refresh(second)
        db.refresh(document)

        assert "Copyright 2026" not in (first.normalized_text or "")
        assert "Copyright 2026" not in (second.normalized_text or "")
        assert second.text == "Copyright 2026\nSecond page."
        assert first.text_source == "manual"
        assert second.text_source == "manual"
        assert "Copyright 2026" not in (document.search_text or "")
        assert updated.pages[0].normalized_text == "\nBody text.\n"
        assert len(versions) == 1
        assert versions[0].metadata_snapshot["scrub_count"] == 3
        assert len(versions[0].metadata_snapshot["pages"]) == 2


def test_restore_document_version_creates_current_version(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import restore_document_version
    from app.models import AttributeDefinition, Document, DocumentAttributeValue, DocumentPage, DocumentVersion, Tag

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Current Title",
            authors=[{"given": "Current", "family": "Author"}],
            publication_year=2026,
            original_filename="restore.pdf",
            checksum_sha256="r" * 64,
            search_text="Current Title current page text",
        )
        db.add(document)
        db.flush()
        page = DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Raw page text.",
            normalized_text="Current page text.",
            text_source="manual",
        )
        tag = Tag(name="current tag")
        definition = AttributeDefinition(name="Current field", value_type="markdown")
        db.add_all([page, tag, definition])
        db.flush()
        document.tags = [tag]
        db.add(
            DocumentAttributeValue(
                document_id=document.id,
                attribute_definition_id=definition.id,
                value={"value": "current"},
            )
        )
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            change_note="Preferred cleanup",
            metadata_snapshot={
                "after": {
                    "title": "Restored Title",
                    "subtitle": None,
                    "authors": [{"given": "Ada", "family": "Lovelace"}],
                    "universities": [],
                    "publication_year": 1843,
                    "publisher": None,
                    "journal": "Scientific Memoirs",
                    "doi": "10.0000/restored",
                    "source_url": None,
                    "abstract": "Restored abstract.",
                    "rich_summary": "Restored summary.",
                    "apa_citation": "Lovelace, A. (1843). Restored.",
                    "apa_citation_model": None,
                    "apa_citation_source": "user",
                    "apa_in_text_citation": "(Lovelace, 1843)",
                    "apa_in_text_citation_model": None,
                    "apa_in_text_citation_source": "user",
                    "citation_status": "verified",
                    "read_status": "read",
                    "priority": "high",
                    "tags": ["restored tag"],
                    "domains": [],
                    "attributes": {"Restored field": {"value": "restored"}},
                },
                "page_after": {
                    "id": page.id,
                    "page_number": 1,
                    "text": "Raw page text.",
                    "normalized_text": "Restored page text.",
                    "text_source": "manual",
                    "low_text": False,
                    "image_uri": None,
                },
            },
        )
        db.add(version)
        db.commit()

        updated = restore_document_version(document.id, version.id, object(), db)
        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number).all()
        db.refresh(document)
        db.refresh(page)

        assert updated.title == "Restored Title"
        assert updated.authors == [{"given": "Ada", "family": "Lovelace"}]
        assert updated.priority == "high"
        assert [tag.name for tag in updated.tags] == ["restored tag"]
        assert {value.definition.name: value.value for value in updated.attributes} == {
            "Restored field": {"value": "restored"}
        }
        assert page.normalized_text == "Restored page text."
        assert "Restored Title" in (document.search_text or "")
        assert "Restored page text" in (document.search_text or "")
        assert len(versions) == 2
        assert versions[-1].change_note == "Restored v1 as current"
        assert versions[-1].metadata_snapshot["restored_version_number"] == 1
        assert versions[-1].metadata_snapshot["restored_pages"][0]["after"]["normalized_text"] == "Restored page text."


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
