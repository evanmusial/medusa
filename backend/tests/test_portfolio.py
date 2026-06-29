import json
import zipfile
from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401

    get_settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_portfolio_documents_stay_out_of_library_lists(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_documents
    from app.models import Document
    from app.services.document_visibility import document_is_library_visible

    with Session() as db:
        library = Document(
            title="Library Paper",
            original_filename="library.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
        )
        portfolio = Document(
            title="Portfolio Draft",
            document_kind="portfolio_version",
            original_filename="draft.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
        )
        material = Document(
            title="Portfolio Rubric",
            document_kind="portfolio_material",
            original_filename="rubric.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
        )
        db.add_all([library, portfolio, material])
        db.commit()

        rows = list_documents(object(), db)

    assert document_is_library_visible(library) is True
    assert document_is_library_visible(portfolio) is False
    assert document_is_library_visible(material) is False
    assert [row.id for row in rows] == [library.id]


def test_portfolio_version_lineage_and_material_scope(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, PortfolioItem, PortfolioMaterial, PortfolioVersion, PortfolioVersionEdge

    with Session() as db:
        item = PortfolioItem(title="Methods Portfolio")
        db.add(item)
        db.flush()
        draft_one = Document(
            title="Draft One",
            document_kind="portfolio_version",
            original_filename="draft-one.pdf",
            checksum_sha256="1" * 64,
            processing_status="ready",
        )
        draft_two = Document(
            title="Draft Two",
            document_kind="portfolio_version",
            original_filename="draft-two.pdf",
            checksum_sha256="2" * 64,
            processing_status="queued",
        )
        rubric_document = Document(
            title="Rubric",
            document_kind="portfolio_material",
            original_filename="rubric.pdf",
            checksum_sha256="3" * 64,
            processing_status="ready",
        )
        db.add_all([draft_one, draft_two, rubric_document])
        db.flush()
        version_one = PortfolioVersion(
            portfolio_item_id=item.id,
            document_id=draft_one.id,
            version_number=1,
            source_filename="draft-one.md",
            source_content_type="text/markdown",
            source_checksum_sha256="1" * 64,
            source_size_bytes=128,
            processing_status="ready",
        )
        version_two = PortfolioVersion(
            portfolio_item_id=item.id,
            document_id=draft_two.id,
            version_number=2,
            source_filename="draft-two.md",
            source_content_type="text/markdown",
            source_checksum_sha256="2" * 64,
            source_size_bytes=256,
            processing_status="queued",
        )
        db.add_all([version_one, version_two])
        db.flush()
        db.add(
            PortfolioVersionEdge(
                parent_version_id=version_one.id,
                child_version_id=version_two.id,
                relation_type="supersedes",
            )
        )
        material = PortfolioMaterial(
            portfolio_item_id=item.id,
            version_id=version_two.id,
            document_id=rubric_document.id,
            role="rubric",
            label="Course rubric",
            required_for_assessment=True,
        )
        db.add(material)
        item.current_version_id = version_two.id
        db.commit()

        loaded = db.query(PortfolioItem).filter(PortfolioItem.id == item.id).one()

        assert loaded.current_version_id == version_two.id
        assert [version.version_number for version in loaded.versions] == [2, 1]
        assert loaded.versions[0].parent_edges[0].parent_version_id == version_one.id
        assert loaded.materials[0].role == "rubric"
        assert loaded.materials[0].version_id == version_two.id
        assert loaded.materials[0].required_for_assessment is True


def test_portfolio_suggestions_and_assessment_use_library_context(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import create_portfolio_assessment, refresh_portfolio_suggestions
    from app.models import Document, PortfolioItem, PortfolioVersion
    from app.schemas import PortfolioAssessmentCreate

    with Session() as db:
        library = Document(
            title="Rubric-Aligned Evidence Synthesis",
            original_filename="library.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
            search_text="rubric evidence synthesis classroom writing assessment",
        )
        draft = Document(
            title="Portfolio Draft",
            document_kind="portfolio_version",
            original_filename="draft.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
            search_text="portfolio draft rubric evidence synthesis",
        )
        item = PortfolioItem(title="Writing Portfolio")
        db.add_all([library, draft, item])
        db.flush()
        version = PortfolioVersion(
            portfolio_item_id=item.id,
            document_id=draft.id,
            version_number=1,
            source_filename="draft.md",
            source_content_type="text/markdown",
            source_checksum_sha256="b" * 64,
            source_size_bytes=200,
            processing_status="ready",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.commit()

        suggestions = refresh_portfolio_suggestions(item.id, object(), db)
        assessment = create_portfolio_assessment(
            item.id,
            PortfolioAssessmentCreate(version_id=version.id, model_ids=["mock-assessor"]),
            object(),
            db,
        )

    assert suggestions.suggestion_count == 1
    assert suggestions.suggestions[0].library_document_id == library.id
    assert suggestions.suggestions[0].evidence["basis"] == "recon_retrieval"
    assert assessment.model_ids == ["mock-assessor"]
    assert assessment.status == "complete"
    assert assessment.assessment_metadata["library_evidence_count"] == 1
    assert any(finding.category in {"materials", "rubric", "resources"} for finding in assessment.findings)


def test_portfolio_audit_chain_signature_and_tamper_detection(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import PortfolioItem
    from app.services.portfolio_audit import append_portfolio_audit_event, maybe_anchor_portfolio_audit, verify_portfolio_audit_chain

    with Session() as db:
        item = PortfolioItem(title="Audit Portfolio")
        db.add(item)
        db.flush()
        first = append_portfolio_audit_event(
            db,
            portfolio_item_id=item.id,
            event_type="item_created",
            payload={"title": item.title},
        )
        second = append_portfolio_audit_event(
            db,
            portfolio_item_id=item.id,
            event_type="item_updated",
            payload={"status": "active"},
        )
        anchor = maybe_anchor_portfolio_audit(db, item.id)
        db.commit()

        verified = verify_portfolio_audit_chain(db, item.id)
        assert verified["ok"] is True
        assert verified["event_count"] == 2
        assert second.previous_event_hash == first.event_hash
        assert anchor is not None
        assert anchor.verification_status == "anchor_pending"
        assert anchor.root_hash == second.event_hash

        tampered_payload = dict(first.canonical_payload)
        tampered_payload["payload"] = {"title": "Changed after the fact"}
        first.canonical_payload = tampered_payload
        db.commit()

        tampered = verify_portfolio_audit_chain(db, item.id)
        assert tampered["ok"] is False
        assert any(error["error"] == "payload_sha256_mismatch" for error in tampered["errors"])


def test_portfolio_bundle_contains_sources_assessments_and_audit_without_private_key(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import export_portfolio_bundle
    from app.models import Document, PortfolioAssessmentFinding, PortfolioAssessmentRun, PortfolioItem, PortfolioMaterial, PortfolioVersion

    source_path = tmp_path / "draft-source.md"
    source_path.write_bytes(b"# Draft\n\nEvidence synthesis.")
    preview_path = tmp_path / "draft-preview.pdf"
    preview_path.write_bytes(b"%PDF-1.4 draft preview")
    rubric_path = tmp_path / "rubric.pdf"
    rubric_path.write_bytes(b"%PDF-1.4 rubric")

    with Session() as db:
        draft = Document(
            title="Draft",
            document_kind="portfolio_version",
            original_filename="draft-preview.pdf",
            checksum_sha256="d" * 64,
            processing_status="ready",
            gcs_uri=str(preview_path),
        )
        rubric = Document(
            title="Rubric",
            document_kind="portfolio_material",
            original_filename="rubric.pdf",
            checksum_sha256="e" * 64,
            processing_status="ready",
            gcs_uri=str(rubric_path),
        )
        item = PortfolioItem(title="Cybersecurity Paper", description="School assignment")
        db.add_all([draft, rubric, item])
        db.flush()
        version = PortfolioVersion(
            portfolio_item_id=item.id,
            document_id=draft.id,
            version_number=1,
            label="Draft 1",
            source_filename="draft-source.md",
            source_content_type="text/markdown",
            source_checksum_sha256="d" * 64,
            source_storage_uri=str(source_path),
            source_size_bytes=source_path.stat().st_size,
            processing_status="ready",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        material = PortfolioMaterial(
            portfolio_item_id=item.id,
            document_id=rubric.id,
            role="rubric",
            label="Course rubric",
            required_for_assessment=True,
            material_metadata={
                "source_filename": "rubric.pdf",
                "source_content_type": "application/pdf",
                "source_checksum_sha256": "e" * 64,
                "source_storage_uri": str(rubric_path),
                "source_size_bytes": rubric_path.stat().st_size,
            },
        )
        run = PortfolioAssessmentRun(
            portfolio_item_id=item.id,
            version_id=version.id,
            mode="quality_review",
            model_ids=["gpt-5.5"],
            status="complete",
            summary="Assessment summary",
            assessment_metadata={
                "scorecard": [{"criterion": "Evidence", "max_points": 10, "awarded_points": 8}],
                "grade_estimate": {"estimated_grade": "B+", "scale": "letter", "confidence": 0.7},
                "narrative_feedback": {"strengths": ["Clear evidence"], "revision_priorities": ["Tighten thesis"]},
            },
        )
        db.add_all([material, run])
        db.flush()
        db.add(
            PortfolioAssessmentFinding(
                assessment_run_id=run.id,
                category="rubric",
                severity="warning",
                title="Needs stronger thesis",
                body="Tie evidence back to the claim.",
            )
        )
        db.commit()

        response = export_portfolio_bundle(item.id, object(), db)

    archive = zipfile.ZipFile(BytesIO(response.body))
    names = set(archive.namelist())
    assert "manifest.json" in names
    assert "resources/library-suggestions.json" in names
    assert "audit/event-chain.jsonl" in names
    assert "audit/public-keys.json" in names
    assert "audit/timestamp-anchors.json" in names
    assert any(name.endswith("/source/draft-source.md") for name in names)
    assert any(name.endswith("/generated/draft-preview.pdf") for name in names)
    assert any(name.startswith("materials/rubric/") and name.endswith("/source/rubric.pdf") for name in names)
    assert any(name.startswith("assessments/") and name.endswith(".json") for name in names)
    assert any(name.startswith("assessments/") and name.endswith(".md") for name in names)

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["portfolio_item"]["title"] == "Cybersecurity Paper"
    assert manifest["file_entries"]
    assert b"PRIVATE KEY" not in response.body
