from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone


def test_openai_usage_summary_rolls_up_task_model_and_recent(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import OpenAIUsageRecord
    from app.services.openai_usage import openai_usage_summary

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session() as db:
        db.add(
            OpenAIUsageRecord(
                task_key="metadata",
                operation="medusa_document_metadata",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
                source="import",
                input_tokens=100,
                cached_input_tokens=25,
                output_tokens=20,
                total_tokens=120,
                input_file_bytes=1024,
                input_text_characters=500,
                output_text_characters=200,
                used_pdf_file=True,
                usage_metadata={},
            )
        )
        db.add(
            OpenAIUsageRecord(
                task_key="metadata",
                operation="medusa_document_metadata",
                endpoint="responses",
                model="gpt-5.4",
                status="failed",
                source="import",
                input_tokens=50,
                cached_input_tokens=0,
                output_tokens=0,
                total_tokens=50,
                input_file_bytes=1024,
                input_text_characters=500,
                output_text_characters=0,
                used_pdf_file=True,
                error_message="timeout",
                usage_metadata={},
            )
        )
        db.add(
            OpenAIUsageRecord(
                task_key="summary",
                operation="medusa_document_summary",
                endpoint="responses",
                model="unknown-model",
                status="success",
                source="import",
                input_tokens=1000,
                cached_input_tokens=0,
                output_tokens=100,
                total_tokens=1100,
                input_file_bytes=0,
                input_text_characters=500,
                output_text_characters=200,
                used_pdf_file=False,
                created_at=datetime.now(timezone.utc) - timedelta(days=40),
                usage_metadata={},
            )
        )
        db.commit()

        summary = openai_usage_summary(db)

        assert summary["summary"]["request_count"] == 3
        assert summary["summary"]["failed_request_count"] == 1
        assert summary["summary"]["input_tokens"] == 1150
        assert summary["summary"]["cached_input_tokens"] == 25
        assert summary["summary"]["input_file_bytes"] == 2048
        assert summary["summary"]["estimated_cost_usd"] == 0.000619
        assert summary["summary"]["priced_request_count"] == 2
        assert summary["summary"]["unpriced_request_count"] == 1
        metadata_row = next(row for row in summary["by_task"] if row["task_key"] == "metadata")
        gpt_row = next(row for row in summary["by_model"] if row["model"] == "gpt-5.4")
        assert metadata_row["total_tokens"] == 170
        assert metadata_row["estimated_cost_usd"] == 0.000619
        assert gpt_row["priced_request_count"] == 2
        assert summary["recent"][0]["task_key"] == "metadata"

        recent_summary = openai_usage_summary(db, period="last_day")

        assert recent_summary["period"] == "last_day"
        assert recent_summary["summary"]["request_count"] == 2
        assert recent_summary["summary"]["unpriced_request_count"] == 0


def test_openai_usage_summary_prices_google_and_groups_document_calendar(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.database import Base
    from app.models import Document, OpenAIUsageRecord
    from app.services.openai_usage import openai_usage_summary

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    created_at = datetime(2026, 6, 19, 14, 27, tzinfo=timezone.utc)
    with Session() as db:
        document = Document(
            id="doc-google-1",
            title="Gemini Cost Study",
            original_filename="gemini-cost.pdf",
            checksum_sha256="a" * 64,
            storage_status="stored",
            processing_status="completed",
        )
        db.add(document)
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                task_key="summary",
                operation="medusa_document_summary",
                provider="google",
                endpoint="generateContent",
                model="gemini-2.5-flash",
                status="success",
                source="test",
                input_tokens=1_000_000,
                cached_input_tokens=0,
                output_tokens=100_000,
                total_tokens=1_100_000,
                input_file_bytes=0,
                input_text_characters=500,
                output_text_characters=200,
                used_pdf_file=False,
                created_at=created_at,
                usage_metadata={},
            )
        )
        db.commit()

        summary = openai_usage_summary(db, period="all_time")

    assert summary["summary"]["estimated_cost_usd"] == 0.55
    assert summary["summary"]["priced_request_count"] == 1
    model_row = next(row for row in summary["by_model"] if row["model"] == "gemini-2.5-flash")
    document_row = next(row for row in summary["by_document"] if row["document_id"] == "doc-google-1")
    day_row = summary["by_calendar_day"][0]
    hour_row = summary["by_calendar_hour"][0]
    assert model_row["estimated_cost_usd"] == 0.55
    assert document_row["label"] == "Gemini Cost Study"
    assert document_row["estimated_cost_usd"] == 0.55
    assert day_row["calendar_start"].isoformat() == "2026-06-19T00:00:00+00:00"
    assert hour_row["calendar_start"].isoformat() == "2026-06-19T14:00:00+00:00"
    assert summary["pricing"]["source_urls"]["Google"] == "https://ai.google.dev/gemini-api/docs/pricing"
