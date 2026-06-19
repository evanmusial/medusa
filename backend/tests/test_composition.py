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
