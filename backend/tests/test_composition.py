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
    from app.services.composition import active_import_cost_usd, document_composition_summary, record_import_stage, sync_import_usage_composition

    with Session() as db:
        document = Document(title="Costed", original_filename="costed.pdf", checksum_sha256="b" * 64)
        batch = ImportBatch(total_files=1, shared_defaults={})
        job = ImportJob(batch=batch, document=document, status="running", current_step="enriching")
        db.add_all([document, batch, job])
        db.flush()
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
            stage_key="figure_assets",
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
        ("raw_text_extraction", "llm", "gpt-5.5", "medusa_page_text_normalization"),
        ("figure_assets", "local", None, "pymupdf"),
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
