import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, event
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
            processing_status="ready",
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
            processing_status="ready",
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


def test_patch_document_marks_no_doi_without_placeholder(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import patch_document
    from app.models import Document, DocumentVersion
    from app.schemas import DocumentPatch

    Session = make_session()
    with Session() as db:
        document = Document(
            title="No DOI Paper",
            authors=[{"given": "Ada", "family": "Lovelace"}],
            publication_year=1843,
            doi="10.1000/example",
            original_filename="no-doi.pdf",
            checksum_sha256="n" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.commit()

        updated = patch_document(document.id, DocumentPatch(no_doi=True), object(), db)

        assert updated.doi is None
        assert updated.no_doi is True
        assert updated.metadata_evidence["no_doi"]["status"] == "confirmed"
        assert updated.metadata_evidence["no_doi"]["source"] == "manual"

        first_version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()
        assert "doi" in first_version.metadata_snapshot["changed_fields"]
        assert "metadata_evidence" in first_version.metadata_snapshot["changed_fields"]
        assert first_version.metadata_snapshot["after"]["doi"] is None

        updated = patch_document(document.id, DocumentPatch(doi="10.1000/real"), object(), db)

        assert updated.doi == "10.1000/real"
        assert updated.no_doi is False
        assert "no_doi" not in updated.metadata_evidence


def test_document_lock_blocks_document_mutations(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import (
        bulk_update_documents,
        create_annotation,
        download_recommendations,
        patch_document,
        patch_document_page,
        patch_figure,
        refresh_document_bibliography,
        refresh_document_citation,
        refresh_document_summary,
        scrub_document_text,
        set_document_lock,
        trash_documents,
        validate_document_summary,
        verify_document_bibliography,
        verify_document_field,
    )
    from app.models import Document, DocumentPage, Figure
    from app.schemas import (
        AnnotationCreate,
        DocumentLockPatch,
        DocumentPagePatch,
        DocumentPatch,
        DocumentRecommendationDownloadCreate,
        DocumentTextScrub,
        DocumentTrashRequest,
        FigurePatch,
    )

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Lock Target",
            publication_year=2025,
            original_filename="lock-target.pdf",
            checksum_sha256="l" * 64,
            processing_status="ready",
            doi="10.1000/lock",
            apa_citation="Smith, A. (2025). Lock target.",
            apa_in_text_citation="(Smith, 2025)",
            bibliography="Smith, A. (2025). Lock target.",
            rich_summary="Validated lock summary.",
            search_text="Lock Target OCR text.",
        )
        db.add(document)
        db.flush()
        page = DocumentPage(document_id=document.id, page_number=1, text="Lock Target OCR text.", text_source="pdf")
        figure = Figure(document_id=document.id, page_number=1, figure_label="Figure 1", caption="Original caption.")
        db.add_all([page, figure])
        db.commit()
        db.refresh(page)
        db.refresh(figure)

        locked = set_document_lock(document.id, DocumentLockPatch(is_locked=True), object(), db)
        db.refresh(document)

        assert locked.is_locked is True
        assert document.locked_at is not None

        locked_patch_payloads = [
            DocumentPatch(title="Changed"),
            DocumentPatch(publication_year=2026),
            DocumentPatch(doi="10.1000/changed"),
            DocumentPatch(no_doi=True),
            DocumentPatch(apa_citation="Changed APA reference."),
            DocumentPatch(apa_in_text_citation="(Changed, 2026)"),
            DocumentPatch(bibliography="Changed bibliography."),
            DocumentPatch(rich_summary="Changed summary."),
        ]
        for payload in locked_patch_payloads:
            with pytest.raises(HTTPException) as patch_exc:
                patch_document(document.id, payload, object(), db)
            assert patch_exc.value.status_code == 423

        with pytest.raises(HTTPException) as bulk_exc:
            bulk_update_documents({"document_ids": [document.id], "updates": {"priority": "high"}}, object(), db)
        assert bulk_exc.value.status_code == 423

        with pytest.raises(HTTPException) as trash_exc:
            trash_documents(DocumentTrashRequest(document_ids=[document.id]), object(), db)
        assert trash_exc.value.status_code == 423

        locked_actions = [
            lambda: patch_document_page(document.id, page.id, DocumentPagePatch(normalized_text="Changed OCR text."), object(), db),
            lambda: scrub_document_text(document.id, DocumentTextScrub(text="OCR"), object(), db),
            lambda: verify_document_field(document.id, "doi", object(), db),
            lambda: verify_document_bibliography(document.id, object(), db),
            lambda: validate_document_summary(document.id, object(), db),
            lambda: refresh_document_citation(document.id, object(), db),
            lambda: refresh_document_bibliography(document.id, object(), db),
            lambda: refresh_document_summary(document.id, object(), db),
            lambda: create_annotation(document.id, AnnotationCreate(body="Changed note"), object(), db),
            lambda: patch_figure(figure.id, FigurePatch(figure_label="Changed figure"), object(), db),
            lambda: download_recommendations(document.id, DocumentRecommendationDownloadCreate(mode="new"), object(), db),
        ]
        for action in locked_actions:
            with pytest.raises(HTTPException) as locked_exc:
                action()
            assert locked_exc.value.status_code == 423

        unlocked = set_document_lock(document.id, DocumentLockPatch(is_locked=False), object(), db)
        updated = patch_document(document.id, DocumentPatch(title="Unlocked Change"), object(), db)

        assert unlocked.is_locked is False
        assert updated.title == "Unlocked Change"


def test_document_field_verification_requires_confirmed_doi_and_citation_edits(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import patch_document, verify_document_field
    from app.models import Document
    from app.schemas import DocumentPatch

    Session = make_session()
    user = SimpleNamespace(id="user-1", email="editor@example.com")
    with Session() as db:
        document = Document(
            title="Verified Citation Paper",
            authors=[{"given": "Ada", "family": "Lovelace"}],
            publication_year=1843,
            doi="10.1000/example",
            original_filename="verified-citation.pdf",
            checksum_sha256="f" * 64,
            apa_citation="Lovelace, A. (1843). Source.",
            apa_in_text_citation="(Lovelace, 1843)",
            processing_status="ready",
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        verified_doi = verify_document_field(document.id, "doi", user, db)
        verified_reference = verify_document_field(document.id, "apa_citation", user, db)

        assert verified_doi.doi_verified_by == "editor@example.com"
        assert verified_reference.apa_citation_verified_at is not None

        with pytest.raises(HTTPException) as exc_info:
            patch_document(document.id, DocumentPatch(doi="10.1000/other"), user, db)
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            patch_document(document.id, DocumentPatch(apa_citation="Edited reference."), user, db)
        assert exc_info.value.status_code == 409

        updated = patch_document(
            document.id,
            DocumentPatch(
                doi="10.1000/other",
                apa_citation="Edited reference.",
                confirm_verified_doi_edit=True,
                confirm_verified_apa_citation_edit=True,
            ),
            user,
            db,
        )

        assert updated.doi == "10.1000/other"
        assert updated.apa_citation == "Edited reference."
        assert updated.doi_verified_at is None
        assert updated.apa_citation_verified_at is None
        assert updated.metadata_evidence.get("doi_verification") is None
        assert updated.metadata_evidence.get("apa_citation_verification") is None


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
            processing_status="ready",
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
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, processing_status="ready")
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, processing_status="ready")
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
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, processing_status="ready", tags=[tag])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, processing_status="ready", tags=[tag])
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
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, processing_status="ready", tags=[collapse])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, processing_status="ready", tags=[keep, collapse])
        third = Document(title="Third", original_filename="third.pdf", checksum_sha256="3" * 64, processing_status="ready", tags=[keep])
        fourth = Document(title="Fourth", original_filename="fourth.pdf", checksum_sha256="4" * 64, processing_status="ready", tags=[untouched])
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
        document = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, processing_status="ready", tags=[alpha])
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
        document = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, processing_status="ready", tags=[first_source])
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
        def generate_tag_optimization_suggestions(self, tags, *, model, primary_limit, singleton_limit, usage_context):
            seen_inventory.extend(tags)
            assert model == "gpt-5.4-mini"
            assert primary_limit >= 60
            assert singleton_limit >= 120
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
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="1" * 64, processing_status="ready", tags=[base])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, processing_status="ready", tags=[detection])
        third = Document(title="Third", original_filename="third.pdf", checksum_sha256="3" * 64, processing_status="ready", tags=[plural])
        fourth = Document(title="Fourth", original_filename="fourth.pdf", checksum_sha256="4" * 64, processing_status="ready", tags=[unrelated])
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
        assert suggestion.source_tag_ids == [base.id, detection.id, plural.id]
        assert [tag.name for tag in suggestion.source_tags] == ["insider threat", "insider threat detection", "insider threats"]
        assert suggestion.affected_documents == 3
        assert suggestion.confidence == 0.84
        singleton_groups = {frozenset(suggestion.source_tag_ids): suggestion for suggestion in result.singleton_suggestions}
        plural_cleanup = singleton_groups[frozenset({base.id, plural.id})]
        prefix_cleanup = singleton_groups[frozenset({base.id, detection.id})]
        assert plural_cleanup.target_name == "insider threat"
        assert plural_cleanup.confidence == 0.78
        assert prefix_cleanup.target_name == "insider threat"
        assert prefix_cleanup.confidence == 0.7


def test_list_documents_marks_and_filters_checksum_duplicates(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_documents, scan_document_duplicates
    from app.models import Document

    Session = make_session()
    with Session() as db:
        first = Document(title="First duplicate", original_filename="first.pdf", checksum_sha256="d" * 64, processing_status="ready")
        second = Document(title="Second duplicate", original_filename="second.pdf", checksum_sha256="d" * 64, processing_status="ready")
        unique = Document(title="Unique", original_filename="unique.pdf", checksum_sha256="u" * 64, processing_status="ready")
        db.add_all([first, second, unique])
        db.commit()

        scan_document_duplicates(object(), db)
        all_documents = list_documents(object(), db)
        duplicate_documents = list_documents(object(), db, duplicate_status="duplicates")
        unique_documents = list_documents(object(), db, duplicate_status="unique")

        counts = {document.title: document.duplicate_count for document in all_documents}
        assert counts["First duplicate"] == 1
        assert counts["Second duplicate"] == 1
        assert counts["Unique"] == 0
        assert {document.title for document in duplicate_documents} == {"First duplicate", "Second duplicate"}
        assert [document.title for document in unique_documents] == ["Unique"]


def test_list_documents_filters_health_status_scopes(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_list_rows_out, list_documents
    from app.models import Document, Domain, Figure, Project, ProjectItem, Tag

    Session = make_session()

    def make_document(index: int, title: str, **overrides):
        values = {
            "title": title,
            "authors": [{"given": "Ada", "family": "Lovelace"}],
            "publication_year": 1843,
            "doi": f"10.1000/{index}",
            "rich_summary": "Summary present.",
            "citation_status": "verified",
            "original_filename": f"health-{index}.pdf",
            "checksum_sha256": f"{index:064x}",
            "processing_status": "ready",
        }
        values.update(overrides)
        return Document(**values)

    with Session() as db:
        domain = Domain(name="Research")
        tag = Tag(name="evidence")
        project = Project(name="Run sheet")
        documents = [
            make_document(1, "Complete"),
            make_document(2, "DOI gap", doi=None),
            make_document(3, "Confirmed no DOI", doi=None, metadata_evidence={"no_doi": {"status": "confirmed"}}),
            make_document(4, "Citation review", citation_status="rejected"),
            make_document(5, "Missing summary", rich_summary=" "),
            make_document(6, "Identity gap", authors=[], publication_year=None),
            make_document(7, "Unfiled domains"),
            make_document(8, "Untagged"),
            make_document(9, "No project use"),
        ]
        for document in documents:
            if document.title != "Unfiled domains":
                document.domains.append(domain)
            if document.title != "Untagged":
                document.tags.append(tag)
        db.add_all([domain, tag, project, *documents])
        db.flush()
        db.add_all(
            [
                Figure(document_id=documents[-1].id, page_number=1, figure_label="Figure 1"),
                Figure(document_id=documents[-1].id, page_number=2, figure_label="Figure 2"),
            ]
        )
        for document in documents:
            if document.title != "No project use":
                db.add(ProjectItem(project_id=project.id, document_id=document.id))
        db.commit()

        assert [document.title for document in list_documents(object(), db, health_status="doi_gap")] == ["DOI gap"]
        assert [document.title for document in list_documents(object(), db, health_status="citation_review")] == ["Citation review"]
        assert [document.title for document in list_documents(object(), db, health_status="missing_summary")] == ["Missing summary"]
        assert [document.title for document in list_documents(object(), db, health_status="identity_gap")] == ["Identity gap"]
        assert [document.title for document in list_documents(object(), db, health_status="unfiled_domains")] == ["Unfiled domains"]
        assert [document.title for document in list_documents(object(), db, health_status="untagged")] == ["Untagged"]

        no_project_rows = document_list_rows_out(db, health_status="no_project_use")
        assert no_project_rows.total_count == 1
        assert [document.title for document in no_project_rows.items] == ["No project use"]
        assert [document.figure_count for document in no_project_rows.items] == [2]


def test_get_document_uses_persisted_duplicate_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import get_document, scan_document_duplicates
    from app.models import Document

    Session = make_session()
    with Session() as db:
        first = Document(title="First duplicate", original_filename="first.pdf", checksum_sha256="d" * 64, processing_status="ready")
        second = Document(title="Second duplicate", original_filename="second.pdf", checksum_sha256="d" * 64, processing_status="ready")
        db.add_all([first, second])
        db.commit()

        scan_document_duplicates(object(), db)

        def fail_full_duplicate_summary(*args, **kwargs):
            raise AssertionError("Document detail should not scan the full duplicate graph")

        monkeypatch.setattr("app.main.duplicate_summary_by_document", fail_full_duplicate_summary)

        detail = get_document(first.id, object(), db)

        assert detail.duplicate_count == 1
        assert detail.duplicate_reasons == ["sha256"]
        assert detail.duplicate_document_ids == []


def test_list_documents_can_skip_library_only_enrichments(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_documents, scan_document_duplicates
    from app.models import Document, Project, ProjectItem

    Session = make_session()
    with Session() as db:
        first = Document(title="First duplicate", original_filename="first.pdf", checksum_sha256="d" * 64, processing_status="ready")
        second = Document(title="Second duplicate", original_filename="second.pdf", checksum_sha256="d" * 64, processing_status="ready")
        project = Project(name="Performance pass")
        db.add_all([first, second, project])
        db.flush()
        db.add(ProjectItem(project_id=project.id, document_id=first.id))
        db.commit()

        scan_document_duplicates(object(), db)
        enriched_documents = list_documents(object(), db)
        reference_documents = list_documents(object(), db, include_duplicate_summary=False, include_projects=False)

    enriched_first = next(document for document in enriched_documents if document.id == first.id)
    reference_first = next(document for document in reference_documents if document.id == first.id)
    assert enriched_first.duplicate_count == 1
    assert [project.name for project in enriched_first.projects] == ["Performance pass"]
    assert reference_first.duplicate_count == 0
    assert reference_first.projects == []


def test_list_documents_sorts_by_title(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_documents
    from app.models import Document

    Session = make_session()
    with Session() as db:
        db.add_all(
            [
                Document(title="Zeta", original_filename="zeta.pdf", checksum_sha256="z" * 64, processing_status="ready"),
                Document(title="alpha", original_filename="alpha.pdf", checksum_sha256="a" * 64, processing_status="ready"),
                Document(title="Beta", original_filename="beta.pdf", checksum_sha256="b" * 64, processing_status="ready"),
                Document(title="Advanced methods", original_filename="advanced.pdf", checksum_sha256="c" * 64, processing_status="ready"),
                Document(title="A framework", original_filename="framework.pdf", checksum_sha256="f" * 64, processing_status="ready"),
            ]
        )
        db.commit()

        documents = list_documents(object(), db)

    assert [document.title for document in documents] == ["A framework", "Advanced methods", "alpha", "Beta", "Zeta"]


def test_list_document_rows_supports_date_and_page_count_sort(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_document_rows
    from app.models import Document

    Session = make_session()
    with Session() as db:
        db.add_all(
            [
                Document(
                    title="Short old",
                    publication_year=1999,
                    page_count=12,
                    original_filename="short-old.pdf",
                    checksum_sha256="1" * 64,
                    processing_status="ready",
                ),
                Document(
                    title="Long new",
                    publication_year=2024,
                    page_count=220,
                    original_filename="long-new.pdf",
                    checksum_sha256="2" * 64,
                    processing_status="ready",
                ),
                Document(
                    title="Middle study",
                    publication_year=2010,
                    page_count=48,
                    original_filename="middle-study.pdf",
                    checksum_sha256="3" * 64,
                    processing_status="ready",
                ),
                Document(
                    title="Undated appendix",
                    publication_year=None,
                    page_count=90,
                    original_filename="undated-appendix.pdf",
                    checksum_sha256="4" * 64,
                    processing_status="ready",
                ),
            ]
        )
        db.commit()

        by_date = list_document_rows(object(), db, sort="date", limit=10)
        by_page_count = list_document_rows(object(), db, sort="page_count", limit=10)

    assert [document.title for document in by_date.items] == ["Long new", "Middle study", "Short old", "Undated appendix"]
    assert [document.title for document in by_page_count.items] == ["Long new", "Undated appendix", "Middle study", "Short old"]


def test_list_documents_default_uses_50_row_window(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_document_rows, list_documents
    from app.models import Document

    Session = make_session()
    with Session() as db:
        db.add_all(
            [
                Document(
                    title=f"Document {index:03d}",
                    original_filename=f"document-{index:03d}.pdf",
                    checksum_sha256=f"{index:064x}"[-64:],
                    processing_status="ready",
                )
                for index in range(125)
            ]
        )
        db.commit()

        documents = list_documents(object(), db)
        default_page = list_document_rows(object(), db)
        limited_documents = list_documents(object(), db, limit=80)
        first_page = list_document_rows(object(), db, limit=40)
        second_page = list_document_rows(object(), db, offset=40, limit=40)
        last_page = list_document_rows(object(), db, offset=120, limit=40)
        all_page = list_document_rows(object(), db, offset=40, limit=40, all_results=True)
        focused_document_id = db.query(Document.id).filter(Document.title == "Document 087").scalar()
        focused_page = list_document_rows(object(), db, limit=40, focus_document_id=focused_document_id)
        missing_focus_page = list_document_rows(object(), db, limit=40, focus_document_id="missing-document")

    assert len(documents) == 125
    assert len(default_page.items) == 50
    assert default_page.total_count == 125
    assert default_page.offset == 0
    assert default_page.limit == 50
    assert default_page.has_more is True
    assert len(limited_documents) == 80
    assert len(first_page.items) == 40
    assert first_page.total_count == 125
    assert first_page.offset == 0
    assert first_page.limit == 40
    assert first_page.has_more is True
    assert len(second_page.items) == 40
    assert second_page.offset == 40
    assert second_page.has_more is True
    assert len(last_page.items) == 5
    assert last_page.offset == 120
    assert last_page.has_more is False
    assert len(all_page.items) == 125
    assert all_page.offset == 0
    assert all_page.limit == 125
    assert all_page.has_more is False
    assert focused_page.focus_document_id == focused_document_id
    assert focused_page.focus_index == 87
    assert focused_page.offset == 80
    assert [document.title for document in focused_page.items][:2] == ["Document 080", "Document 081"]
    assert any(document.id == focused_document_id for document in focused_page.items)
    assert missing_focus_page.focus_index is None
    assert missing_focus_page.offset == 0


def test_document_list_rows_omits_heavy_text_columns(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_document_rows
    from app.models import Document

    Session = make_session()
    with Session() as db:
        db.add_all(
            [
                Document(
                    title="Compact row",
                    original_filename="compact-row.pdf",
                    checksum_sha256="a" * 64,
                    processing_status="ready",
                    search_text="heavy search text " * 1000,
                    bibliography="heavy bibliography " * 1000,
                    apa_citation="heavy citation " * 1000,
                    apa_in_text_citation="heavy in-text citation " * 1000,
                ),
                Document(
                    title="Second row",
                    original_filename="second-row.pdf",
                    checksum_sha256="b" * 64,
                    processing_status="ready",
                    search_text="more heavy search text " * 1000,
                ),
            ]
        )
        db.commit()

        statements: list[str] = []

        def record_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(str(statement).lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", record_select)
        try:
            page = list_document_rows(object(), db, limit=1)
        finally:
            event.remove(bind, "before_cursor_execute", record_select)

    assert len(page.items) == 1
    row_selects = [statement for statement in statements if " from documents " in statement and " limit " in statement]
    assert row_selects
    row_select = row_selects[-1]
    assert "documents.search_text" not in row_select
    assert "documents.bibliography" not in row_select
    assert "documents.apa_citation" not in row_select
    assert "documents.apa_in_text_citation" not in row_select


def test_document_list_rows_marks_documents_with_verified_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_document_rows
    from app.models import Document, utc_now

    Session = make_session()
    with Session() as db:
        verified = Document(
            title="Verified DOI",
            original_filename="verified-doi.pdf",
            checksum_sha256="v" * 64,
            doi="10.1000/verified",
            processing_status="ready",
            metadata_evidence={
                "doi_verification": {
                    "status": "verified",
                    "verified_at": utc_now().isoformat(),
                    "verified_by": "editor@example.com",
                }
            },
        )
        broad_status_only = Document(
            title="Broad Citation Status",
            original_filename="broad-status.pdf",
            checksum_sha256="s" * 64,
            citation_status="verified",
            processing_status="ready",
        )
        db.add_all([verified, broad_status_only])
        db.commit()

        rows = list_document_rows(object(), db).items

    row_by_title = {row.title: row for row in rows}
    assert row_by_title["Verified DOI"].has_verified_fields is True
    assert row_by_title["Broad Citation Status"].has_verified_fields is False


def test_cleanup_document_titles_normalizes_spacing_and_records_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import cleanup_document_titles
    from app.models import Document, DocumentVersion

    Session = make_session()
    with Session() as db:
        messy = Document(title="  A   messy\n title\t ", original_filename="messy.pdf", checksum_sha256="m" * 64, processing_status="ready")
        clean = Document(title="Clean Title", original_filename="clean.pdf", checksum_sha256="c" * 64, processing_status="ready")
        db.add_all([messy, clean])
        db.commit()

        result = cleanup_document_titles(object(), db)

        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == messy.id).all()
        clean_versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == clean.id).all()

    assert result == {"updated": 1}
    assert messy.title == "A messy title"
    assert messy.search_text == "A messy title"
    assert clean.title == "Clean Title"
    assert len(versions) == 1
    assert versions[0].change_note == "Title cleanup"
    assert versions[0].metadata_snapshot["changed_fields"] == ["search_text", "title"]
    assert versions[0].metadata_snapshot["before"]["title"] == "  A   messy\n title\t "
    assert versions[0].metadata_snapshot["after"]["title"] == "A messy title"
    assert clean_versions == []


def test_trash_documents_soft_deletes_visible_documents_with_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_documents, trash_documents
    from app.models import Document, DocumentCompositionRecord, DocumentVersion
    from app.schemas import DocumentTrashRequest

    Session = make_session()
    with Session() as db:
        first = Document(
            title="First",
            original_filename="first.pdf",
            checksum_sha256="1" * 64,
            processing_status="ready",
            metadata_evidence=["legacy malformed evidence"],
        )
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="2" * 64, processing_status="ready")
        queued = Document(title="Queued", original_filename="queued.pdf", checksum_sha256="3" * 64, processing_status="queued")
        db.add_all([first, second, queued])
        db.commit()

        result = trash_documents(
            DocumentTrashRequest(document_ids=[first.id, queued.id, second.id, first.id]),
            object(),
            db,
        )
        visible = list_documents(object(), db)
        first_versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == first.id).all()
        second_versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == second.id).all()
        queued_versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == queued.id).all()
        first_composition = db.query(DocumentCompositionRecord).filter(DocumentCompositionRecord.document_id == first.id).all()

    assert result.trashed == 2
    assert result.document_ids == [first.id, second.id]
    assert first.deleted_at is not None
    assert second.deleted_at is not None
    assert queued.deleted_at is None
    assert {document.title for document in visible} == set()
    assert isinstance(first.metadata_evidence, dict)
    assert first.metadata_evidence["trash_events"][0]["source"] == "library_selection"
    assert first_versions[0].change_note == "Moved to Trash"
    assert first_versions[0].metadata_snapshot["changed_fields"] == ["deleted_at", "metadata_evidence"]
    assert second_versions[0].change_note == "Moved to Trash"
    assert queued_versions == []
    assert first_composition[0].message == "Moved to Trash"


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
            processing_status="ready",
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


def test_figure_asset_uses_fast_storage_read(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import figure_asset
    from app.models import Document, Figure

    calls = []

    class FakeStorage:
        def get_bytes(self, uri, **kwargs):
            calls.append((uri, kwargs))
            return b"fake-png"

    monkeypatch.setattr("app.main.get_storage_service", lambda: FakeStorage())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Paper with figures",
            original_filename="paper.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        figure = Figure(
            document_id=document.id,
            page_number=1,
            figure_label="Figure 1",
            asset_uri="gs://bucket/figures/figure-1.png",
        )
        db.add(figure)
        db.commit()

        response = figure_asset(figure.id, object(), db)

    assert response.body == b"fake-png"
    assert response.media_type == "image/png"
    assert calls == [("gs://bucket/figures/figure-1.png", {"timeout": 5, "retry": None})]


def test_patch_figure_updates_search_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import patch_figure
    from app.models import Document, DocumentVersion, Figure
    from app.schemas import FigurePatch

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Paper with figure corrections",
            original_filename="paper.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        figure = Figure(
            document_id=document.id,
            page_number=2,
            figure_label="Figure 9",
            caption="Wrong caption.",
            gist="Wrong description.",
            asset_uri="gs://bucket/figures/figure-9.png",
        )
        db.add(figure)
        db.commit()

        updated = patch_figure(
            figure.id,
            FigurePatch(figure_label="Figure 2", caption="Corrected caption.", gist="Corrected chart description."),
            object(),
            db,
        )
        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).all()

        assert updated.figures[0].figure_label == "Figure 2"
        assert updated.figures[0].caption == "Corrected caption."
        assert updated.figures[0].gist == "Corrected chart description."
        assert "Corrected chart description" in (document.search_text or "")
        assert len(versions) == 1
        assert versions[0].change_note == "Updated extracted figure Figure 2"
        assert "figures" in versions[0].metadata_snapshot["changed_fields"]
        assert versions[0].metadata_snapshot["before"]["figures"][0]["figure_label"] == "Figure 9"
        assert versions[0].metadata_snapshot["after"]["figures"][0]["figure_label"] == "Figure 2"


def test_delete_figure_removes_row_and_records_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import delete_figure
    from app.models import Document, DocumentPage, DocumentVersion, Figure

    deleted_assets = []

    class FakeStorage:
        def delete_uri(self, uri):
            deleted_assets.append(uri)
            return True

    monkeypatch.setattr("app.main.get_storage_service", lambda: FakeStorage())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Paper with disposable figures",
            original_filename="paper.pdf",
            checksum_sha256="b" * 64,
            search_text="Paper with disposable figures Figure 4 Extra extraction.",
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        figure = Figure(
            document_id=document.id,
            page_number=4,
            figure_label="Figure 4",
            caption="Extra extraction.",
            asset_uri="gs://bucket/figures/figure-4.png",
        )
        db.add(figure)
        db.flush()
        document.pages.append(
            DocumentPage(
                page_number=4,
                text=f"Before marker.\n\n![Figure 4](medusa-figure:{figure.id})\n\nAfter marker.",
                low_text=False,
                text_source="pymupdf",
            )
        )
        db.commit()

        updated = delete_figure(figure.id, object(), db)
        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).all()
        page = db.query(DocumentPage).filter(DocumentPage.document_id == document.id).one()

        assert updated.figures == []
        assert db.query(Figure).count() == 0
        assert "medusa-figure:" not in (page.text or "")
        assert deleted_assets == ["gs://bucket/figures/figure-4.png"]
        assert "Extra extraction" not in (document.search_text or "")
        assert len(versions) == 1
        assert versions[0].change_note == "Deleted extracted figure Figure 4"
        assert "pages" in versions[0].metadata_snapshot["changed_fields"]
        assert versions[0].metadata_snapshot["figure_delete"]["figure"]["figure_label"] == "Figure 4"


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
        assert detail.pages[0].reader_text is None


def test_document_detail_out_derives_inline_figure_reader_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_detail_out
    from app.models import Document, DocumentPage, Figure

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Figure Reader Paper",
            original_filename="figure-reader.pdf",
            checksum_sha256="f" * 64,
            processing_status="ready",
            page_count=1,
        )
        document.pages.append(
            DocumentPage(
                page_number=1,
                text="Opening paragraph.\n\nFigure 1. Diagram caption.\n\nClosing paragraph.",
                low_text=False,
                text_source="pymupdf",
            )
        )
        figure = Figure(
            page_number=1,
            figure_label="Figure 1",
            caption="Figure 1. Diagram caption.",
            asset_uri="gs://bucket/figures/figure-1.png",
            geometry={"bbox": [40, 80, 240, 220], "page_height": 400},
        )
        document.figures.append(figure)
        db.add(document)
        db.commit()
        db.refresh(document)

        detail = document_detail_out(document, db)
        marker = f"![Figure 1](medusa-figure:{figure.id})"

        assert "medusa-figure:" not in (document.pages[0].text or "")
        assert marker in (detail.pages[0].reader_text or "")
        assert "Figure 1. Diagram caption." in (detail.pages[0].reader_text or "")
        assert "medusa-figure:" not in (detail.pages[0].text or "")

        document.figures.remove(figure)
        db.delete(figure)
        db.flush()
        detail = document_detail_out(document, db)

        assert "medusa-figure:" not in (detail.pages[0].reader_text or "")


def test_document_detail_includes_bibliography_generated_time(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_detail_out
    from app.models import Document, DocumentCapability, utc_now

    Session = make_session()
    with Session() as db:
        generated_at = utc_now()
        document = Document(
            title="References Paper",
            original_filename="references.pdf",
            checksum_sha256="g" * 64,
            bibliography="Smith, A. (2024). Source. Journal.",
            metadata_evidence={"bibliography_extraction": {"status": "extracted"}},
            page_count=1,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="bibliography_extraction",
                version=1,
                status="complete",
                completed_at=generated_at,
            )
        )
        db.commit()
        db.refresh(document)

        detail = document_detail_out(document, db)

        assert detail.bibliography_generated_at == generated_at


def test_document_detail_compacts_history_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_detail_out
    from app.models import Document, DocumentVersion

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Heavy History Paper",
            original_filename="heavy-history.pdf",
            checksum_sha256="i" * 64,
            processing_status="ready",
            page_count=1,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentVersion(
                document_id=document.id,
                version_number=1,
                change_note="Large correction",
                metadata_snapshot={
                    "changed_fields": ["title", "pages"],
                    "after": {
                        "title": "Restored Heavy History Paper",
                        "publication_year": 2026,
                        "tags": ["performance"],
                        "abstract": "x" * 100_000,
                    },
                    "page_after": {
                        "page_number": 1,
                        "normalized_text": "y" * 100_000,
                    },
                },
            )
        )
        db.commit()
        db.refresh(document)

        detail = document_detail_out(document, db)
        db_version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()

        snapshot = detail.versions[0].metadata_snapshot
        assert snapshot["changed_fields"] == ["title", "pages"]
        assert snapshot["restorable"] is True
        assert snapshot["preview_lines"] == ["Restored Heavy History Paper", "Year 2026", "1 tags", "Page 1"]
        assert "after" not in snapshot
        assert "page_after" not in snapshot
        assert db_version.metadata_snapshot["after"]["abstract"] == "x" * 100_000


def test_document_detail_prefers_bibliography_generated_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_detail_out
    from app.models import Document

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Evidence References Paper",
            original_filename="evidence-references.pdf",
            checksum_sha256="h" * 64,
            bibliography="Jones, B. (2025). Evidence source. Journal.",
            metadata_evidence={"bibliography_extraction": {"status": "extracted", "generated_at": "2026-06-26T12:34:56+00:00"}},
            page_count=1,
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        detail = document_detail_out(document, db)

        assert detail.bibliography_generated_at is not None
        assert detail.bibliography_generated_at.isoformat() == "2026-06-26T12:34:56+00:00"


def test_document_detail_prefers_summary_generated_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import document_detail_out
    from app.models import Document, DocumentCapability, utc_now

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Evidence Summary Paper",
            original_filename="evidence-summary.pdf",
            checksum_sha256="s" * 64,
            rich_summary="Generated summary text.",
            metadata_evidence={"summary_refresh": {"status": "generated", "summary_generated_at": "2026-06-26T14:34:56+00:00"}},
            page_count=1,
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        detail = document_detail_out(document, db)

        assert detail.summary_generated_at is not None
        assert detail.summary_generated_at.isoformat() == "2026-06-26T14:34:56+00:00"

        skipped_document = Document(
            title="Skipped Summary Paper",
            original_filename="skipped-summary.pdf",
            checksum_sha256="t" * 64,
            rich_summary="Existing validated summary.",
            metadata_evidence={"summary_refresh": {"status": "skipped_validated_summary", "summary_generated_at": None}},
            page_count=1,
        )
        db.add(skipped_document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=skipped_document.id,
                capability_key="summary_refresh",
                version=1,
                status="complete",
                completed_at=utc_now(),
            )
        )
        db.commit()
        db.refresh(skipped_document)

        skipped_detail = document_detail_out(skipped_document, db)

        assert skipped_detail.summary_generated_at is None


def test_document_bibliography_verification_requires_confirmed_edit(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import patch_document, verify_document_bibliography
    from app.models import Document
    from app.schemas import DocumentPatch

    Session = make_session()
    user = SimpleNamespace(id="user-1", email="editor@example.com")
    with Session() as db:
        document = Document(
            title="Verified References Paper",
            original_filename="verified-references.pdf",
            checksum_sha256="v" * 64,
            bibliography="Smith, A. (2024). Source. *Journal*.",
            processing_status="ready",
            page_count=1,
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        verified = verify_document_bibliography(document.id, user, db)

        assert verified.bibliography_verified_at is not None
        assert verified.bibliography_verified_by == "editor@example.com"

        with pytest.raises(HTTPException) as exc_info:
            patch_document(document.id, DocumentPatch(bibliography="Edited source."), user, db)
        assert exc_info.value.status_code == 409

        updated = patch_document(
            document.id,
            DocumentPatch(bibliography="Edited source.", confirm_verified_bibliography_edit=True),
            user,
            db,
        )

        assert updated.bibliography == "Edited source."
        assert updated.bibliography_verified_at is None
        assert updated.metadata_evidence.get("bibliography_verification") is None


def test_document_summary_validation_requires_confirmed_edit_and_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import patch_document, refresh_document_summary, validate_document_summary
    from app.models import ConcordanceJob, Document
    from app.schemas import DocumentPatch

    Session = make_session()
    user = SimpleNamespace(id="user-1", email="editor@example.com")
    with Session() as db:
        refresh_document = Document(
            title="Validated Summary Refresh Paper",
            original_filename="validated-summary-refresh.pdf",
            checksum_sha256="r" * 64,
            rich_summary="Validated summary for refresh.",
            processing_status="ready",
            page_count=1,
        )
        edit_document = Document(
            title="Validated Summary Edit Paper",
            original_filename="validated-summary-edit.pdf",
            checksum_sha256="q" * 64,
            rich_summary="Validated summary for edit.",
            processing_status="ready",
            page_count=1,
        )
        empty_document = Document(
            title="Empty Summary Paper",
            original_filename="empty-summary.pdf",
            checksum_sha256="p" * 64,
            rich_summary=" ",
            processing_status="ready",
            page_count=1,
        )
        db.add_all([refresh_document, edit_document, empty_document])
        db.commit()
        db.refresh(refresh_document)
        db.refresh(edit_document)
        db.refresh(empty_document)

        refresh_detail = validate_document_summary(refresh_document.id, user, db)
        db.refresh(refresh_document)

        assert refresh_detail.summary_validated_at is not None
        assert refresh_detail.summary_validated_by == "editor@example.com"
        validation = refresh_document.metadata_evidence["summary_validation"]
        assert validation["status"] == "validated"
        assert validation["exemplar"] is True
        assert validation["summary_sha256"]

        with pytest.raises(HTTPException) as exc_info:
            refresh_document_summary(refresh_document.id, user, db)
        assert exc_info.value.status_code == 409

        run = refresh_document_summary(refresh_document.id, user, db, confirm_validated=True)
        jobs = db.query(ConcordanceJob).filter(ConcordanceJob.run_id == run.id).all()
        db.refresh(refresh_document)

        assert jobs
        assert jobs[0].capability_key == "summary_refresh"
        assert refresh_document.metadata_evidence.get("summary_validation") is None

        validate_document_summary(edit_document.id, user, db)
        with pytest.raises(HTTPException) as exc_info:
            patch_document(edit_document.id, DocumentPatch(rich_summary="Edited summary."), user, db)
        assert exc_info.value.status_code == 409

        edited = patch_document(
            edit_document.id,
            DocumentPatch(rich_summary="Edited summary.", confirm_validated_summary_edit=True),
            user,
            db,
        )

        assert edited.rich_summary == "Edited summary."
        assert edited.summary_validated_at is None
        assert edited.metadata_evidence.get("summary_validation") is None

        with pytest.raises(HTTPException) as exc_info:
            validate_document_summary(empty_document.id, user, db)
        assert exc_info.value.status_code == 400


def test_document_bibliography_verification_can_confirm_empty_field(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import patch_document, refresh_document_bibliography, verify_document_bibliography, verify_document_field
    from app.models import Document
    from app.schemas import DocumentPatch

    Session = make_session()
    user = SimpleNamespace(id="user-1", email="editor@example.com")
    with Session() as db:
        document = Document(
            title="No References Paper",
            original_filename="no-references.pdf",
            checksum_sha256="e" * 64,
            bibliography=None,
            processing_status="ready",
            page_count=1,
        )
        doi_gap = Document(
            title="No DOI Paper",
            original_filename="no-doi.pdf",
            checksum_sha256="g" * 64,
            doi=None,
            processing_status="ready",
            page_count=1,
        )
        db.add_all([document, doi_gap])
        db.commit()
        db.refresh(document)
        db.refresh(doi_gap)

        verified = verify_document_bibliography(document.id, user, db)
        db.refresh(document)

        assert verified.bibliography is None
        assert verified.bibliography_verified_at is not None
        assert verified.bibliography_verified_by == "editor@example.com"
        verification = document.metadata_evidence["bibliography_verification"]
        assert verification["status"] == "verified"
        assert verification["value_state"] == "empty"
        assert verification["verified_empty"] is True

        with pytest.raises(HTTPException) as exc_info:
            verify_document_field(doi_gap.id, "doi", user, db)
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            patch_document(document.id, DocumentPatch(bibliography="Added source."), user, db)
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            refresh_document_bibliography(document.id, user, db)
        assert exc_info.value.status_code == 409

        updated = patch_document(
            document.id,
            DocumentPatch(bibliography="Added source.", confirm_verified_bibliography_edit=True),
            user,
            db,
        )

        assert updated.bibliography == "Added source."
        assert updated.bibliography_verified_at is None
        assert updated.metadata_evidence.get("bibliography_verification") is None


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
            processing_status="ready",
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
            processing_status="ready",
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
            processing_status="ready",
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
            processing_status="ready",
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


def test_refresh_document_citation_requires_confirmation_for_verified_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import refresh_document_citation
    from app.models import ConcordanceJob, Document

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Verified DOI Refresh Paper",
            original_filename="verified-doi-refresh.pdf",
            checksum_sha256="8" * 64,
            processing_status="ready",
            doi="10.1000/verified-refresh",
            apa_citation="Smith, A. (2024). Verified.",
            apa_in_text_citation="(Smith, 2024)",
            metadata_evidence={
                "doi_verification": {
                    "status": "verified",
                    "verified_at": "2026-06-27T12:00:00+00:00",
                    "verified_by": "editor@example.com",
                    "verified_by_user_id": "user-1",
                },
                "apa_citation_verification": {
                    "status": "verified",
                    "verified_at": "2026-06-27T12:05:00+00:00",
                    "verified_by": "editor@example.com",
                    "verified_by_user_id": "user-1",
                },
            },
        )
        db.add(document)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            refresh_document_citation(document.id, object(), db)
        assert exc_info.value.status_code == 409

        run = refresh_document_citation(document.id, object(), db, confirm_verified=True)
        jobs = db.query(ConcordanceJob).filter(ConcordanceJob.run_id == run.id).all()
        db.refresh(document)

        assert jobs
        assert jobs[0].capability_key == "citation_refresh"
        assert document.metadata_evidence.get("doi_verification") is None
        assert document.metadata_evidence.get("apa_citation_verification") is None


def test_refresh_document_bibliography_queues_forced_bibliography_concordance(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import refresh_document_bibliography
    from app.models import ConcordanceJob, Document, DocumentCapability
    from app.services.concordance import CAPABILITY_BY_KEY

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Bibliography Paper",
            original_filename="bibliography.pdf",
            checksum_sha256="8" * 64,
            processing_status="ready",
            bibliography="Old stored bibliography.",
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="bibliography_extraction",
                version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
                status="complete",
            )
        )
        db.commit()

        run = refresh_document_bibliography(document.id, object(), db)
        jobs = db.query(ConcordanceJob).filter(ConcordanceJob.run_id == run.id).all()

        assert run.capability_keys == ["bibliography_extraction"]
        assert run.scope_type == "documents"
        assert run.scope_data["_force"] is True
        assert jobs
        assert jobs[0].document_id == document.id
        assert jobs[0].capability_key == "bibliography_extraction"


def test_refresh_document_bibliography_requires_confirmation_for_verified_bibliography(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from fastapi import HTTPException

    from app.main import refresh_document_bibliography
    from app.models import ConcordanceJob, Document

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Verified Bibliography Paper",
            original_filename="verified-bibliography.pdf",
            checksum_sha256="9" * 64,
            processing_status="ready",
            bibliography="Verified source list.",
            metadata_evidence={
                "bibliography_verification": {
                    "status": "verified",
                    "verified_at": "2026-06-27T12:00:00+00:00",
                    "verified_by": "editor@example.com",
                    "verified_by_user_id": "user-1",
                }
            },
        )
        db.add(document)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            refresh_document_bibliography(document.id, object(), db)
        assert exc_info.value.status_code == 409

        run = refresh_document_bibliography(document.id, object(), db, confirm_verified=True)
        jobs = db.query(ConcordanceJob).filter(ConcordanceJob.run_id == run.id).all()
        db.refresh(document)

        assert jobs
        assert document.metadata_evidence.get("bibliography_verification") is None


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
            processing_status="ready",
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


def test_replace_document_in_place_queues_import_and_preserves_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    from app import main
    from app.config import get_settings
    from app.models import (
        Annotation,
        AttributeDefinition,
        Document,
        DocumentAttributeValue,
        DocumentCompositionRecord,
        DocumentVersion,
        ImportJob,
        ProcessingEvent,
        Tag,
    )

    get_settings.cache_clear()
    main.settings.data_dir = tmp_path / "data"

    class FakeStorage:
        def __init__(self):
            self.objects = []

        def put_bytes(self, key, data, content_type):
            self.objects.append({"key": key, "data": data, "content_type": content_type})
            return SimpleNamespace(uri=f"memory://{key}", backend="fake")

    fake_storage = FakeStorage()
    monkeypatch.setattr(main, "get_storage_service", lambda: fake_storage)

    Session = make_session()
    with Session() as db:
        tag = Tag(name="summary artifact")
        definition = AttributeDefinition(name="Old note", value_type="markdown")
        document = Document(
            title="Summary Only",
            original_filename="summary.pdf",
            checksum_sha256="a" * 64,
            checksum_md5="b" * 32,
            processing_status="ready",
            page_count=1,
            rich_summary="Only a summary was imported.",
            tags=[tag],
        )
        db.add_all([tag, definition, document])
        db.flush()
        db.add(
            DocumentAttributeValue(
                document_id=document.id,
                attribute_definition_id=definition.id,
                value={"value": "old attribute"},
            )
        )
        db.add(
            DocumentCompositionRecord(
                document_id=document.id,
                record_kind="llm",
                stage_key="summary_topics",
                stage_label="Summary",
                provider="openai",
                method="responses",
                model="gpt-test",
                status="complete",
                amount_usd=1.25,
                message="Prior import spend",
            )
        )
        db.add(Annotation(document_id=document.id, page_number=1, body="old source highlight"))
        db.commit()

        response = asyncio.run(
            main.replace_document_in_place(
                document.id,
                object(),
                db,
                UploadFile(filename="full-paper.md", file=BytesIO(b"Full Paper\n\nThis is the complete source.")),
            )
        )
        db.refresh(document)

        jobs = db.query(ImportJob).filter(ImportJob.document_id == document.id).all()
        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).all()
        replacement_events = db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "document_replacement_queued").all()
        composition_records = db.query(DocumentCompositionRecord).filter(DocumentCompositionRecord.document_id == document.id).all()

        assert response["document_id"] == document.id
        assert response["status"] == "queued"
        assert len(jobs) == 1
        assert document.processing_status == "queued"
        assert document.title.lower() == "full paper"
        assert document.original_filename == "full-paper.pdf"
        assert document.rich_summary is None
        assert document.tags == []
        assert document.attributes == []
        assert db.query(Annotation).filter(Annotation.document_id == document.id, Annotation.deleted_at.is_(None)).count() == 0
        assert document.metadata_evidence["document_replacement"]["previous_accession"]["title"] == "Summary Only"
        assert document.metadata_evidence["document_replacement"]["previous_accession"]["checksum_sha256"] == "a" * 64
        assert fake_storage.objects and fake_storage.objects[0]["content_type"] == "application/pdf"
        assert any(record.message == "Prior import spend" for record in composition_records)
        assert any((record.record_metadata or {}).get("operation") == "document_replacement" for record in composition_records)
        assert len(versions) == 1
        assert versions[0].change_note == "Document replacement queued"
        assert versions[0].metadata_snapshot["before"]["title"] == "Summary Only"
        assert versions[0].metadata_snapshot["previous_accession"]["title"] == "Summary Only"
        assert replacement_events and replacement_events[0].import_job_id == jobs[0].id


def test_replace_document_in_place_rejects_locked_document(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app import main
    from app.models import Document, ImportJob, utc_now

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Locked",
            original_filename="locked.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
            locked_at=utc_now(),
        )
        db.add(document)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                main.replace_document_in_place(
                    document.id,
                    object(),
                    db,
                    UploadFile(filename="replacement.md", file=BytesIO(b"Replacement\n\nBody.")),
                )
            )

        assert exc_info.value.status_code == 423
        assert db.query(ImportJob).count() == 0
