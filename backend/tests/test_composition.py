from datetime import datetime, timezone

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


def test_document_composition_summary_reports_not_available(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document
    from app.services.composition import document_composition_summary

    with Session() as db:
        document = Document(title="Legacy", original_filename="legacy.pdf", checksum_sha256="a" * 64)
        db.add(document)
        db.commit()

        summary = document_composition_summary(db, document)

    assert summary["available"] is False
    assert summary["cost_entries"] == []
    assert summary["pipeline"] == []


def test_composition_syncs_usage_costs_and_local_duration(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, ImportBatch, ImportJob, OpenAIUsageRecord
    from app.services.composition import (
        active_import_cost_usd,
        document_composition_summary,
        record_import_cost_estimate,
        record_import_stage,
        sync_import_usage_composition,
    )

    with Session() as db:
        document = Document(title="Costed", original_filename="costed.pdf", checksum_sha256="b" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="enriching")
        db.add_all([document, batch, job])
        db.flush()
        record_import_cost_estimate(
            db,
            document=document,
            job=job,
            estimated_cost_usd=3.0,
            estimate_basis="task_exemplar",
            estimated_page_count=20,
            model_preferences={"summary": "gpt-5.4"},
        )
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="summary_topics",
            label="Metadata, summary, citation, and topics",
            method="routed_document_intelligence",
            duration_ms=120_000,
        )
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="summary_topics",
                task_key="summary",
                operation="medusa_document_summary",
                provider="openai",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
                input_tokens=1_000_000,
                output_tokens=100_000,
                total_tokens=1_100_000,
                created_at=datetime(2026, 6, 19, 15, tzinfo=timezone.utc),
                usage_metadata={},
            )
        )
        db.commit()

        assert active_import_cost_usd(db, [job.id]) == 4.0
        assert sync_import_usage_composition(db, document=document, job=job) == 1
        summary = document_composition_summary(db, document)

    assert summary["available"] is True
    assert summary["total_duration_seconds"] == 120
    assert summary["total_estimated_cost_usd"] == 4.0
    assert summary["cost_entries"][0]["model"] == "gpt-5.4"
    assert summary["provider_breakdown"][0]["provider"] == "OpenAI"
    assert summary["local_duration_entries"][0]["duration_ms"] == 120_000
    assert any(item["record_kind"] == "llm" for item in summary["pipeline"])
    assert not any(item["record_kind"] == "estimate" for item in summary["cost_entries"])
    assert summary["estimate_comparison"]["estimated_cost_usd"] == 3.0
    assert summary["estimate_comparison"]["actual_cost_usd"] == 4.0
    assert summary["estimate_comparison"]["variance_usd"] == 1.0
    assert summary["estimate_comparison"]["status"] == "over"


def test_composition_includes_tiny_usage_costs_from_raw_usage(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, DocumentCompositionRecord, ImportBatch, ImportJob, OpenAIUsageRecord
    from app.services.composition import document_composition_summary, sync_import_usage_composition

    with Session() as db:
        document = Document(title="Tiny", original_filename="tiny.pdf", checksum_sha256="c" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="enriching")
        db.add_all([document, batch, job])
        db.flush()
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                import_job_id=job.id,
                source="import",
                capability_key="tag_governance",
                task_key="text_chunk_encoding",
                operation="text_chunk_embedding",
                provider="openai",
                endpoint="embeddings",
                model="text-embedding-3-small",
                status="success",
                input_tokens=427,
                output_tokens=0,
                total_tokens=427,
                created_at=datetime(2026, 6, 19, 15, tzinfo=timezone.utc),
                usage_metadata={},
            )
        )
        db.commit()

        assert sync_import_usage_composition(db, document=document, job=job) == 1
        db.query(DocumentCompositionRecord).filter(DocumentCompositionRecord.document_id == document.id).update(
            {"amount_usd": 0.0}
        )
        db.commit()
        summary = document_composition_summary(db, document)

    embedding_entry = next(entry for entry in summary["cost_entries"] if entry["record_kind"] == "embedding")
    assert embedding_entry["amount_usd"] == 0.00000854
    assert embedding_entry["stage_key"] == "tag_governance"
    assert embedding_entry["stage_label"] == "Tag governance"
    assert summary["provider_breakdown"][0]["amount_usd"] == 0.00000854
    assert summary["total_estimated_cost_usd"] == 0.00000854


def test_composition_local_page_normalization_does_not_claim_fallback_model(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, ImportBatch, ImportJob
    from app.services.composition import document_composition_summary, record_import_stage

    with Session() as db:
        document = Document(title="Local Pages", original_filename="local-pages.pdf", checksum_sha256="e" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="extracting")
        db.add_all([document, batch, job])
        db.flush()
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="page_text_normalization",
            method="local_first_auto",
            model="gpt-5.4-mini",
            duration_ms=34,
            metadata={"sources": {"local_auto": 7}, "auto_cloud_pages": 0},
        )
        db.commit()

        summary = document_composition_summary(db, document)

    page_node = summary["pipeline"][0]
    assert page_node["stage_key"] == "page_text_normalization"
    assert page_node["method"] == "local_auto"
    assert page_node["model"] is None
    assert page_node["provider"] == "Local"


def test_composition_pipeline_preserves_import_execution_order(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, ImportBatch, ImportJob, OpenAIUsageRecord
    from app.services.composition import document_composition_summary, record_import_stage, sync_import_usage_composition

    with Session() as db:
        document = Document(title="Ordered", original_filename="ordered.pdf", checksum_sha256="d" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="enriching")
        db.add_all([document, batch, job])
        db.flush()
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="raw_text_extraction",
            label="Text extraction and page normalization",
            method="pymupdf",
            model="gpt-5.5",
            duration_ms=51_000,
        )
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="visual_asset_extraction",
            method="pymupdf",
            duration_ms=100,
        )
        record_import_stage(
            db,
            document=document,
            job=job,
            stage_key="summary_topics",
            label="Metadata, summary, citation, and topics",
            method="routed_document_intelligence",
            duration_ms=26_000,
        )
        usage_rows = [
            ("page_text_normalization", "page_text_normalization", "medusa_page_text_normalization", "gpt-5.5", 1),
            ("summary_topics", "metadata", "medusa_document_metadata", "gpt-5.5", 2),
            ("summary_topics", "summary", "medusa_document_summary", "gpt-5.4", 3),
            ("summary_topics", "keywords_topics", "medusa_keywords_topics", "gpt-5.4-mini", 4),
            ("citation_refresh", "apa_citation", "medusa_apa_citation_candidate", "gpt-5.5", 5),
        ]
        for capability_key, task_key, operation, model, minute in usage_rows:
            db.add(
                OpenAIUsageRecord(
                    document_id=document.id,
                    import_job_id=job.id,
                    source="import",
                    capability_key=capability_key,
                    task_key=task_key,
                    operation=operation,
                    provider="openai",
                    endpoint="responses",
                    model=model,
                    status="success",
                    input_tokens=100,
                    output_tokens=10,
                    total_tokens=110,
                    created_at=datetime(2026, 6, 19, 15, minute, tzinfo=timezone.utc),
                    usage_metadata={},
                )
            )
        db.commit()

        assert sync_import_usage_composition(db, document=document, job=job) == len(usage_rows)
        summary = document_composition_summary(db, document)

    pipeline_order = [(item["stage_key"], item["record_kind"], item.get("model"), item.get("method")) for item in summary["pipeline"]]
    assert pipeline_order == [
        ("raw_text_extraction", "local", "gpt-5.5", "pymupdf"),
        ("page_text_normalization", "llm", "gpt-5.5", "medusa_page_text_normalization"),
        ("visual_asset_extraction", "local", None, "pymupdf"),
        ("summary_topics", "llm", "gpt-5.5", "medusa_document_metadata"),
        ("summary_topics", "llm", "gpt-5.4", "medusa_document_summary"),
        ("summary_topics", "llm", "gpt-5.4-mini", "medusa_keywords_topics"),
        ("summary_topics", "local", None, "routed_document_intelligence"),
        ("citation_refresh", "llm", "gpt-5.5", "medusa_apa_citation_candidate"),
    ]


def test_composition_issues_exclude_completed_manual_edits(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, ImportBatch, ImportJob
    from app.services.composition import document_composition_summary, record_import_erratum, record_manual_edit

    with Session() as db:
        document = Document(title="Issues", original_filename="issues.pdf", checksum_sha256="c" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="complete", current_step="complete")
        db.add_all([document, batch, job])
        db.flush()
        record_manual_edit(db, document=document, message="Manual correction", metadata={"changed_fields": ["title"]})
        record_import_erratum(
            db,
            document=document,
            job=job,
            stage_key="text_chunk_encoding",
            message="Embedding request timed out.",
            level="warning",
        )
        db.commit()

        summary = document_composition_summary(db, document)

    assert [item["message"] for item in summary["errata"]] == ["Embedding request timed out."]
    assert summary["errata"][0]["status"] == "warning"


def test_composition_pipeline_uses_estimate_steps_for_unrecorded_import_steps(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, ImportBatch, ImportJob
    from app.services.composition import document_composition_summary, record_import_cost_estimate, record_import_stage

    with Session() as db:
        document = Document(title="Estimated", original_filename="estimated.pdf", checksum_sha256="e" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="staged", current_step="staged")
        db.add_all([document, batch, job])
        db.flush()
        record_import_cost_estimate(
            db,
            document=document,
            job=job,
            estimated_cost_usd=0.25,
            estimate_basis="preset_steps",
            estimated_page_count=12,
            metadata={
                "step_estimates": [
                    {"task_key": "raw_text_extraction", "label": "Raw text extraction", "model": "marker", "status": "local"},
                    {"task_key": "ocr_fallback", "label": "OCR fallback", "model": "google_vision", "status": "pending_provider_integration"},
                    {"task_key": "visual_asset_context", "label": "Visual context", "model": "gemini-3.1-flash-lite", "status": "pending_provider_integration"},
                ]
            },
        )
        record_import_stage(db, document=document, job=job, stage_key="raw_text_extraction", method="marker")
        db.commit()

        summary = document_composition_summary(db, document)

    pipeline = [(item["stage_key"], item["record_kind"], item.get("model"), item["status"]) for item in summary["pipeline"]]
    assert ("raw_text_extraction", "local", None, "complete") in pipeline
    assert ("raw_text_extraction", "estimate_step", "marker", "local") not in pipeline
    assert ("ocr_fallback", "estimate_step", "google_vision", "pending_provider_integration") in pipeline
    assert ("visual_asset_context", "estimate_step", "gemini-3.1-flash-lite", "pending_provider_integration") in pipeline


def test_composition_pipeline_appends_concordance_runs(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import ConcordanceJob, ConcordanceRun, Document, OpenAIUsageRecord
    from app.services.composition import document_composition_summary, record_concordance_stage, record_import_stage, sync_import_usage_composition

    with Session() as db:
        document = Document(title="Concorded", original_filename="concorded.pdf", checksum_sha256="f" * 64)
        run = ConcordanceRun(scope_type="documents", scope_data={"document_ids": []}, capability_keys=["summary_refresh"], total_jobs=1)
        job = ConcordanceJob(run=run, document=document, capability_key="summary_refresh", target_version=1, status="complete")
        db.add_all([document, run, job])
        db.flush()
        record_import_stage(db, document=document, job=None, stage_key="raw_text_extraction", method="marker")
        record_concordance_stage(
            db,
            document=document,
            concordance_job=job,
            stage_key="summary_refresh",
            label="Summary refresh",
            method="summary_refresh",
            model="gpt-5.4",
            duration_ms=1_500,
        )
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                concordance_run_id=run.id,
                concordance_job_id=job.id,
                source="concordance",
                capability_key="summary_refresh",
                task_key="summary",
                operation="medusa_document_summary",
                provider="openai",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
                input_tokens=100,
                output_tokens=10,
                total_tokens=110,
                usage_metadata={},
            )
        )
        db.commit()

        sync_import_usage_composition(db, document=document, job=None)
        summary = document_composition_summary(db, document)

    pipeline_order = [(item["stage_label"], item["record_kind"], item.get("model"), item.get("method")) for item in summary["pipeline"]]
    assert pipeline_order[0] == ("Text extraction", "local", None, "marker")
    assert pipeline_order[-2:] == [
        ("Concordance: Summary refresh", "concordance", "gpt-5.4", "summary_refresh"),
        ("Concordance: Summary refresh", "llm", "gpt-5.4", "medusa_document_summary"),
    ]
