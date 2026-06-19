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
