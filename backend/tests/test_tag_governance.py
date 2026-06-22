from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    import app.models  # noqa: F401

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_import_tag_governance_prefers_existing_but_keeps_supported_new_candidates(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.models import Document, DocumentTagAssessment, Tag
    from app.services.tag_governance import apply_import_tag_governance

    with Session() as db:
        existing = Tag(name="access control", kind="tag", status="canonical")
        document = Document(
            title="Access Control Study",
            original_filename="access-control.pdf",
            checksum_sha256="a" * 64,
            search_text="This paper studies access control and a zero trust mesh for campus systems.",
        )
        db.add_all([existing, document])
        db.commit()

        summary = apply_import_tag_governance(
            db,
            document=document,
            topics=["access control model"],
            keywords=["zero trust mesh"],
            source="import",
        )
        db.commit()

        assert summary["attached_count"] == 2
        assert summary["new_candidate_count"] == 1
        assert summary["covered_by_count"] == 1
        assert sorted(tag.name for tag in document.tags) == ["access control", "zero trust mesh"]
        assert next(tag for tag in document.tags if tag.name == "zero trust mesh").status == "candidate"

        rows = db.query(DocumentTagAssessment).order_by(DocumentTagAssessment.candidate_name).all()
        assert [(row.candidate_name, row.decision, row.status) for row in rows] == [
            ("access control model", "covered_by", "attached"),
            ("zero trust mesh", "new_candidate", "attached"),
        ]
        assert document.metadata_evidence["tag_governance"]["score_axes"] == [
            "document_relevance",
            "library_fit",
            "novelty_value",
        ]


def test_import_tag_governance_replace_existing_removes_stale_tags(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.models import Document, Tag
    from app.services.tag_governance import apply_import_tag_governance

    with Session() as db:
        stale = Tag(name="stale manual tag", kind="tag", status="canonical")
        existing = Tag(name="access control", kind="tag", status="canonical")
        document = Document(
            title="Access Control Study",
            original_filename="access-control.pdf",
            checksum_sha256="d" * 64,
            search_text="This paper studies access control and a zero trust mesh for campus systems.",
            tags=[stale],
        )
        db.add_all([stale, existing, document])
        db.commit()

        summary = apply_import_tag_governance(
            db,
            document=document,
            topics=["access control model"],
            keywords=["zero trust mesh"],
            source="tag_refresh",
            replace_existing=True,
        )
        db.commit()

        assert summary["replace_existing"] is True
        assert summary["replaced_tags"] == ["stale manual tag"]
        assert summary["attached_count"] == 2
        assert summary["new_candidate_count"] == 1
        assert sorted(tag.name for tag in document.tags) == ["access control", "zero trust mesh"]


def test_import_tag_governance_caps_new_tags_and_suppresses_low_value_candidates(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.models import Document, DocumentTagAssessment
    from app.services.tag_governance import apply_import_tag_governance

    with Session() as db:
        document = Document(
            title="Zero Trust Mesh Telemetry",
            original_filename="zero-trust.pdf",
            checksum_sha256="0" * 64,
            search_text="zero trust mesh ransomware telemetry overview model",
        )
        db.add(document)
        db.commit()

        summary = apply_import_tag_governance(
            db,
            document=document,
            topics=[],
            keywords=["zero trust mesh", "ransomware telemetry", "overview", "model"],
            source="import",
        )
        db.commit()

        rows = {row.candidate_name: row for row in db.query(DocumentTagAssessment).all()}

        assert summary["attached_count"] == 1
        assert summary["new_candidate_count"] == 1
        assert len(document.tags) == 1
        assert rows["model"].decision == "low_value"
        assert rows["overview"].decision == "low_value"
        assert sorted(
            row.assessment_metadata.get("selection_skip_reason")
            for row in rows.values()
            if row.decision == "new_candidate" and row.status == "not_attached"
        ) == ["max_new_candidates"]


def test_import_tag_governance_blocks_new_tags_near_existing_concepts(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.models import Document, DocumentTagAssessment, Tag
    from app.services.tag_governance import apply_import_tag_governance

    with Session() as db:
        existing = Tag(name="cyber threat attribution", kind="tag", status="canonical")
        document = Document(
            title="Threat Attribution Analysis",
            original_filename="threat-attribution.pdf",
            checksum_sha256="1" * 64,
            search_text="threat attribution analysis",
        )
        db.add_all([existing, document])
        db.commit()

        summary = apply_import_tag_governance(
            db,
            document=document,
            topics=[],
            keywords=["threat attribution analysis"],
            source="import",
        )
        db.commit()

        row = db.query(DocumentTagAssessment).one()

        assert summary["new_candidate_count"] == 0
        assert document.tags == []
        assert row.decision == "near_existing_not_attached"
        assert row.assessment_metadata["nearest_existing_tag"] == "cyber threat attribution"


def test_prune_tag_assignment_records_document_history(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import prune_tag_assignment
    from app.models import Document, DocumentTagAssessment, Tag
    from app.schemas import TagAssignmentPruneCreate

    with Session() as db:
        tag = Tag(name="miscellaneous", kind="tag", status="candidate")
        document = Document(
            title="Target",
            original_filename="target.pdf",
            checksum_sha256="b" * 64,
            search_text="Target text miscellaneous",
            processing_status="ready",
            tags=[tag],
        )
        db.add_all([tag, document])
        db.flush()
        assessment = DocumentTagAssessment(
            document_id=document.id,
            tag_id=tag.id,
            candidate_name=tag.name,
            source="import",
            decision="new_candidate",
            status="attached",
            relevance_score=0.2,
            library_fit_score=0.1,
            novelty_score=0.4,
            overall_score=0.24,
            rationale="Weak assignment.",
        )
        db.add(assessment)
        db.commit()

        result = prune_tag_assignment(
            TagAssignmentPruneCreate(document_id=document.id, tag_id=tag.id, rationale="Too broad here."),
            object(),
            db,
        )

        assert result.updated_documents == 1
        assert document.tags == []
        assert assessment.status == "pruned"
        assert document.versions[-1].change_note == 'Pruned tag "miscellaneous"'
        assert document.versions[-1].metadata_snapshot["operation"] == "tag_assignment_prune"


def test_optimize_includes_relationship_status_and_pruning_suggestions(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import optimize_tags
    from app.models import Document, DocumentTagAssessment, Tag
    from app.schemas import TagOptimizationCreate

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, *_, **__):
            return {"suggestions": [], "singleton_suggestions": []}

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    with Session() as db:
        broad = Tag(name="insider threat", kind="tag", status="canonical")
        specific = Tag(name="insider threat detection", kind="tag", status="candidate")
        weak = Tag(name="miscellaneous", kind="tag", status="candidate")
        first = Document(title="First", original_filename="first.pdf", checksum_sha256="c" * 64, processing_status="ready", tags=[specific])
        second = Document(title="Second", original_filename="second.pdf", checksum_sha256="d" * 64, processing_status="ready", tags=[specific])
        weak_document = Document(title="Weak", original_filename="weak.pdf", checksum_sha256="e" * 64, processing_status="ready", tags=[weak])
        db.add_all([broad, specific, weak, first, second, weak_document])
        db.flush()
        db.add_all(
            [
                DocumentTagAssessment(
                    document_id=first.id,
                    tag_id=specific.id,
                    candidate_name=specific.name,
                    source="import",
                    decision="new_candidate",
                    status="attached",
                    relevance_score=0.7,
                    library_fit_score=0.4,
                    novelty_score=0.7,
                    overall_score=0.65,
                ),
                DocumentTagAssessment(
                    document_id=second.id,
                    tag_id=specific.id,
                    candidate_name=specific.name,
                    source="import",
                    decision="new_candidate",
                    status="attached",
                    relevance_score=0.7,
                    library_fit_score=0.4,
                    novelty_score=0.7,
                    overall_score=0.65,
                ),
                DocumentTagAssessment(
                    document_id=weak_document.id,
                    tag_id=weak.id,
                    candidate_name=weak.name,
                    source="import",
                    decision="new_candidate",
                    status="attached",
                    relevance_score=0.2,
                    library_fit_score=0.1,
                    novelty_score=0.3,
                    overall_score=0.22,
                    rationale="Weak.",
                ),
            ]
        )
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[broad.id, specific.id, weak.id]), object(), db)

        assert any(item.relationship_type == "covered_by" for item in result.relationship_suggestions)
        assert any(item.tag.id == specific.id and item.suggested_status == "canonical" for item in result.status_suggestions)
        assert any(item.document_id == weak_document.id and item.tag.id == weak.id for item in result.pruning_suggestions)
        assert result.health_summary["candidate_tags"] == 2


def test_optimize_uses_import_tag_creation_model(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import optimize_tags
    from app.models import Tag
    from app.schemas import TagOptimizationCreate
    from app.services.analysis_models import MODEL_KEYWORDS_TOPICS
    from app.services.preferences import update_app_preferences

    seen: dict[str, object] = {}

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, tags, *, model, primary_limit, singleton_limit, usage_context):
            seen["model"] = model
            seen["primary_limit"] = primary_limit
            seen["singleton_limit"] = singleton_limit
            return {"suggestions": [], "singleton_suggestions": []}

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    with Session() as db:
        first = Tag(name="access control", kind="tag", status="canonical")
        second = Tag(name="access controls", kind="tag", status="candidate")
        db.add_all([first, second])
        update_app_preferences(db, analysis_models={MODEL_KEYWORDS_TOPICS: "gpt-5.4"})
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[first.id, second.id]), object(), db)

        assert seen["model"] == "gpt-5.4"
        assert seen["primary_limit"] >= 60
        assert seen["singleton_limit"] >= 120
        assert result.model == "gpt-5.4"


def test_optimize_skips_model_planner_for_broad_scope(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import TAG_OPTIMIZATION_MODEL_SCOPE_LIMIT, optimize_tags
    from app.models import Tag
    from app.schemas import TagOptimizationCreate

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, tags, **_):
            raise AssertionError("Broad tag scopes should use the local deterministic planner.")

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    with Session() as db:
        tags = [
            Tag(name=f"legacy singleton family {index}", kind="tag", status="candidate")
            for index in range(TAG_OPTIMIZATION_MODEL_SCOPE_LIMIT + 25)
        ]
        db.add_all(tags)
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[tag.id for tag in tags]), object(), db)

        assert result.considered_tags == TAG_OPTIMIZATION_MODEL_SCOPE_LIMIT + 25
        assert result.health_summary["ai_planner_skipped"] == 1


def test_optimize_flags_legacy_singleton_canonical_tags(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import optimize_tags
    from app.models import Document, Tag
    from app.schemas import TagOptimizationCreate

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, *_, **__):
            return {"suggestions": [], "singleton_suggestions": []}

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    with Session() as db:
        noisy = Tag(name="method", kind="tag", status="canonical")
        other = Tag(name="access control", kind="tag", status="canonical")
        document = Document(title="Legacy", original_filename="legacy.pdf", checksum_sha256="f" * 64, processing_status="ready", tags=[noisy])
        db.add_all([noisy, other, document])
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[noisy.id, other.id]), object(), db)

        assert any(item.tag.id == noisy.id and item.suggested_status == "retired" for item in result.status_suggestions)
        assert any(item.document_id == document.id and item.tag.id == noisy.id for item in result.pruning_suggestions)


def test_optimize_returns_cleanup_actions_for_low_use_scope_without_ai_merges(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import optimize_tags
    from app.models import Document, Tag
    from app.schemas import TagOptimizationCreate

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, *_, **__):
            return {"suggestions": [], "singleton_suggestions": []}

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    with Session() as db:
        zero_candidate = Tag(name="unused candidate", kind="tag", status="candidate")
        singleton_candidate = Tag(name="single use candidate", kind="tag", status="candidate")
        singleton_canonical = Tag(name="single use canonical", kind="tag", status="canonical")
        candidate_document = Document(
            title="Candidate Document",
            original_filename="candidate.pdf",
            checksum_sha256="7" * 64,
            processing_status="ready",
            tags=[singleton_candidate],
        )
        canonical_document = Document(
            title="Canonical Document",
            original_filename="canonical.pdf",
            checksum_sha256="8" * 64,
            processing_status="ready",
            tags=[singleton_canonical],
        )
        db.add_all([zero_candidate, singleton_candidate, singleton_canonical, candidate_document, canonical_document])
        db.commit()

        result = optimize_tags(
            TagOptimizationCreate(tag_ids=[zero_candidate.id, singleton_candidate.id, singleton_canonical.id]),
            object(),
            db,
        )

        status_pairs = {(item.tag.id, item.suggested_status) for item in result.status_suggestions}
        prune_pairs = {(item.document_id, item.tag.id) for item in result.pruning_suggestions}

        assert any(item.tag.id == zero_candidate.id for item in result.orphan_prune_suggestions)
        assert (zero_candidate.id, "retired") not in status_pairs
        assert (singleton_candidate.id, "retired") in status_pairs
        assert (singleton_canonical.id, "candidate") in status_pairs
        assert (candidate_document.id, singleton_candidate.id) in prune_pairs
        assert (canonical_document.id, singleton_canonical.id) in prune_pairs
        assert result.health_summary["singletons"] == 3


def test_optimize_returns_deterministic_plan_when_ai_planner_fails(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import optimize_tags
    from app.models import Document, Tag
    from app.schemas import TagOptimizationCreate

    class FailingAiService:
        def generate_tag_optimization_suggestions(self, *_, **__):
            raise RuntimeError("planner unavailable")

    monkeypatch.setattr("app.main.get_ai_service", lambda: FailingAiService())

    with Session() as db:
        base = Tag(name="access control", kind="tag", status="canonical")
        plural = Tag(name="access controls", kind="tag", status="candidate")
        document = Document(
            title="Access",
            original_filename="access.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
            tags=[plural],
        )
        db.add_all([base, plural, document])
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[base.id, plural.id]), object(), db)

        assert result.suggestions == []
        assert result.health_summary["ai_planner_failed"] == 1
        assert any(base.id in item.source_tag_ids and plural.id in item.source_tag_ids for item in result.singleton_suggestions)


def test_optimize_merges_orphaned_tags_into_used_targets(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import optimize_tags
    from app.models import Document, Tag
    from app.schemas import TagOptimizationCreate

    class FakeAiService:
        def generate_tag_optimization_suggestions(self, *_, **__):
            return {"suggestions": [], "singleton_suggestions": []}

    monkeypatch.setattr("app.main.get_ai_service", lambda: FakeAiService())

    with Session() as db:
        useful = Tag(name="access control", kind="tag", status="canonical")
        orphan = Tag(name="access controls", kind="tag", status="canonical")
        fallback = Tag(name="abandoned note", kind="tag", status="candidate")
        document = Document(
            title="Useful Document",
            original_filename="useful.pdf",
            checksum_sha256="6" * 64,
            processing_status="ready",
            tags=[useful],
        )
        db.add_all([useful, orphan, fallback, document])
        db.commit()

        result = optimize_tags(TagOptimizationCreate(tag_ids=[orphan.id, fallback.id]), object(), db)

        assert any(item.target_tag_id == useful.id and orphan.id in item.source_tag_ids for item in result.orphan_merge_suggestions)
        assert any(item.tag.id == fallback.id for item in result.orphan_prune_suggestions)
        assert all(item.tag.id != orphan.id for item in result.status_suggestions)


def test_approve_all_tag_optimizations_applies_actions_and_reports_stale_skips(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)

    from app.main import approve_all_tag_optimizations
    from app.models import Document, Tag, TagAlias
    from app.schemas import (
        TagOptimizationApproveAllCreate,
        TagOptimizationMergeApproval,
        TagOptimizationOrphanPruneApproval,
        TagOptimizationPruneApproval,
        TagOptimizationRelationshipApproval,
        TagOptimizationStatusApproval,
    )

    with Session() as db:
        keep = Tag(name="access control", kind="tag", status="canonical")
        duplicate = Tag(name="access controls", kind="tag", status="canonical")
        weak = Tag(name="miscellaneous", kind="tag", status="candidate")
        unused = Tag(name="unused candidate", kind="tag", status="candidate")
        orphan_variant = Tag(name="access control model", kind="tag", status="candidate")
        orphan = Tag(name="orphaned tag", kind="tag", status="candidate")
        duplicate_document = Document(
            title="Duplicate Tag",
            original_filename="duplicate.pdf",
            checksum_sha256="9" * 64,
            processing_status="ready",
            tags=[duplicate],
        )
        weak_document = Document(
            title="Weak Tag",
            original_filename="weak.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
            tags=[weak],
        )
        db.add_all([keep, duplicate, weak, unused, orphan_variant, orphan, duplicate_document, weak_document])
        db.commit()

        result = approve_all_tag_optimizations(
            TagOptimizationApproveAllCreate(
                merge_suggestions=[
                    TagOptimizationMergeApproval(
                        id="merge-duplicate",
                        source_tag_ids=[keep.id, duplicate.id],
                        target_name=keep.name,
                    ),
                    TagOptimizationMergeApproval(
                        id="merge-orphan-variant",
                        source_tag_ids=[orphan_variant.id],
                        target_tag_id=keep.id,
                        target_name=keep.name,
                    )
                ],
                relationship_suggestions=[
                    TagOptimizationRelationshipApproval(
                        id="stale-relationship",
                        source_tag_id=duplicate.id,
                        target_tag_id=keep.id,
                        relationship_type="covered_by",
                    )
                ],
                status_suggestions=[
                    TagOptimizationStatusApproval(id="retire-unused", tag_id=unused.id, suggested_status="retired"),
                    TagOptimizationStatusApproval(id="stale-status", tag_id=duplicate.id, suggested_status="candidate"),
                ],
                pruning_suggestions=[
                    TagOptimizationPruneApproval(
                        id="prune-weak",
                        document_id=weak_document.id,
                        tag_id=weak.id,
                        rationale="Weak assignment.",
                    )
                ],
                orphan_prune_suggestions=[
                    TagOptimizationOrphanPruneApproval(id="prune-orphan", tag_id=orphan.id, rationale="Unused."),
                    TagOptimizationOrphanPruneApproval(id="stale-orphan", tag_id=duplicate.id, rationale="No longer unused."),
                ],
            ),
            object(),
            db,
        )

        assert result.merges_applied == 2
        assert result.statuses_applied == 1
        assert result.prunes_applied == 1
        assert result.orphans_pruned == 1
        assert result.relationships_applied == 0
        assert duplicate.id in result.removed_tag_ids
        assert orphan_variant.id in result.removed_tag_ids
        assert orphan.id in result.removed_tag_ids
        assert {item["id"] for item in result.skipped} == {"stale-relationship", "stale-status", "stale-orphan"}
        assert unused.status == "retired"
        assert db.get(Tag, orphan_variant.id) is None
        assert db.get(TagAlias, "access control model").target_tag_id == keep.id
        assert db.get(Tag, orphan.id) is None
        assert [tag.name for tag in duplicate_document.tags] == ["access control"]
        assert weak_document.tags == []
