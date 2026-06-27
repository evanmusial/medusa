from datetime import timedelta

import pytest
from fastapi import HTTPException
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


def test_import_jobs_list_keeps_active_jobs_visible_beyond_recent_limit(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_import_jobs
    from app.models import Document, ImportBatch, ImportJob, utc_now

    now = utc_now()
    with Session() as db:
        batch = ImportBatch(total_files=121, shared_defaults={})
        running_document = Document(
            title="Currently Running",
            original_filename="running.pdf",
            checksum_sha256="a" * 64,
            page_count=12,
        )
        running_job = ImportJob(
            batch=batch,
            document=running_document,
            status="running",
            current_step="normalizing_page_4",
            locked_at=now - timedelta(minutes=5),
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(minutes=5),
        )
        db.add_all([batch, running_document, running_job])
        for index in range(120):
            document = Document(
                title=f"Queued {index}",
                original_filename=f"queued-{index}.pdf",
                checksum_sha256=f"{index:064x}"[-64:],
            )
            db.add(
                ImportJob(
                    batch=batch,
                    document=document,
                    status="queued",
                    current_step="stored",
                    created_at=now + timedelta(seconds=index),
                    updated_at=now + timedelta(seconds=index),
                )
            )
        db.commit()

        rows = list_import_jobs(object(), db)

    assert rows[0]["id"] == running_job.id
    assert rows[0]["status"] == "running"
    assert rows[0]["current_step"] == "normalizing_page_4"
    assert len(rows) == 121


def test_staged_import_job_has_default_cost_estimate(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_import_jobs
    from app.models import Document, ImportBatch, ImportJob

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(
            title="Staged",
            original_filename="staged.pdf",
            checksum_sha256="d" * 64,
            page_count=12,
            processing_status="staged",
            metadata_evidence={"upload_cost_estimate": {"estimated_page_count": 12}},
        )
        job = ImportJob(batch=batch, document=document, status="staged", current_step="staged")
        db.add_all([batch, document, job])
        db.commit()

        rows = list_import_jobs(object(), db)

    assert rows[0]["id"] == job.id
    assert rows[0]["status"] == "staged"
    assert rows[0]["estimated_cost_basis"] == "preset_steps"
    assert rows[0]["estimated_cost_page_count"] == 12
    assert rows[0]["estimated_cost_usd"] > 0


def test_staged_documents_stay_out_of_library_surfaces(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import dashboard, domain_out, get_document, list_documents, list_import_jobs, tag_out
    from app.models import Document, Domain, ImportBatch, ImportJob, Tag

    with Session() as db:
        domain = Domain(name="Security")
        tag = Tag(name="insider threat")
        ready_document = Document(
            title="Ready Needs Review",
            original_filename="ready.pdf",
            checksum_sha256="r" * 64,
            processing_status="ready",
            citation_status="needs_review",
            search_text="ready searchable text",
            domains=[domain],
            tags=[tag],
        )
        staged_document = Document(
            title="Staged Needs Review",
            original_filename="staged.pdf",
            checksum_sha256="s" * 64,
            processing_status="staged",
            citation_status="needs_review",
            search_text="staged searchable text",
            domains=[domain],
            tags=[tag],
        )
        batch = ImportBatch(total_files=1, shared_defaults={})
        staged_job = ImportJob(batch=batch, document=staged_document, status="staged", current_step="staged")
        db.add_all([ready_document, staged_document, batch, staged_job])
        db.commit()

        documents = list_documents(object(), db)
        staged_search = list_documents(object(), db, q="staged")
        counts = dashboard(object(), db)
        queue_rows = list_import_jobs(object(), db)

        with pytest.raises(HTTPException) as exc_info:
            get_document(staged_document.id, object(), db)

        assert [document.id for document in documents] == [ready_document.id]
        assert staged_search == []
        assert counts.documents == 1
        assert counts.needs_review == 1
        assert domain_out(domain, db).document_count == 1
        assert tag_out(tag, db).document_count == 1
        assert queue_rows[0]["id"] == staged_job.id
        assert queue_rows[0]["status"] == "staged"
        assert exc_info.value.status_code == 404


def test_dashboard_surfaces_recent_failed_ai_calls(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import dashboard
    from app.models import Document, OpenAIUsageRecord, utc_now

    with Session() as db:
        document = Document(
            title="Bibliography Trouble",
            original_filename="bibliography.pdf",
            checksum_sha256="f" * 64,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        db.add_all(
            [
                OpenAIUsageRecord(
                    document_id=document.id,
                    task_key="bibliography_cleanup",
                    operation="cleanup_bibliography",
                    endpoint="responses",
                    model="gpt-5.4-nano",
                    status="failed",
                    source="concordance",
                    error_message="context_length_exceeded",
                    created_at=utc_now(),
                    usage_metadata={},
                ),
                OpenAIUsageRecord(
                    document_id=document.id,
                    task_key="summary",
                    operation="document_summary",
                    endpoint="responses",
                    model="gpt-5.4",
                    status="success",
                    source="concordance",
                    created_at=utc_now() - timedelta(minutes=5),
                    usage_metadata={},
                ),
                OpenAIUsageRecord(
                    document_id=document.id,
                    task_key="metadata",
                    operation="document_metadata",
                    endpoint="responses",
                    model="gpt-5.4",
                    status="failed",
                    source="concordance",
                    error_message="old quota error",
                    created_at=utc_now() - timedelta(hours=2),
                    usage_metadata={},
                ),
            ]
        )
        db.commit()

        counts = dashboard(object(), db)

        assert len(counts.recent_failed_ai_calls) == 1
        notice = counts.recent_failed_ai_calls[0]
        assert notice.task_key == "bibliography_cleanup"
        assert notice.model == "gpt-5.4-nano"
        assert notice.document_title == "Bibliography Trouble"
        assert notice.error_message == "context_length_exceeded"


def test_process_staged_import_jobs_promotes_rows(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import process_staged_import_jobs
    from app.models import Document, ImportBatch, ImportJob, ProcessingEvent

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(title="Staged", original_filename="staged.pdf", checksum_sha256="e" * 64, processing_status="staged")
        job = ImportJob(batch=batch, document=document, status="staged", current_step="staged")
        db.add_all([batch, document, job])
        db.commit()

        result = process_staged_import_jobs(object(), db)

        assert result.matched_count == 1
        assert result.updated_count == 1
        assert job.status == "queued"
        assert job.current_step == "stored"
        assert document.processing_status == "queued"
        assert batch.status == "running"
        assert (
            db.query(ProcessingEvent)
            .filter(
                ProcessingEvent.import_job_id == job.id,
                ProcessingEvent.event_type == "manual_import_process_uploads",
            )
            .count()
            == 1
        )


def test_clear_staged_import_jobs_deletes_records_cache_and_original(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import clear_staged_import_jobs, list_import_jobs
    from app.models import Document, ImportBatch, ImportJob, Project, ProjectItem
    from app.services.document_cache import document_cache_path, register_document_cache

    stored_original = tmp_path / "stored" / "staged.pdf"
    stored_original.parent.mkdir(parents=True)
    stored_original.write_bytes(b"original")

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        project = Project(name="Cleanup Project")
        document = Document(
            title="Staged",
            original_filename="staged.pdf",
            checksum_sha256="e" * 64,
            processing_status="staged",
            storage_status="local",
            gcs_uri=str(stored_original),
        )
        job = ImportJob(batch=batch, document=document, status="staged", current_step="staged")
        db.add_all([batch, project, document, job])
        db.flush()
        db.add(ProjectItem(project=project, document=document))
        cache_path = document_cache_path(document.id)
        cache_path.write_bytes(b"cache")
        register_document_cache(document, cache_path, source="upload")
        db.commit()
        db.expunge_all()

        result = clear_staged_import_jobs(object(), db)

        assert result.matched_count == 1
        assert result.updated_count == 1
        assert result.deleted_documents == 1
        assert result.deleted_cache_files == 1
        assert result.deleted_original_objects == 1
        assert db.query(Document).count() == 0
        assert db.query(ImportJob).count() == 0
        assert db.query(ImportBatch).count() == 0
        assert db.query(ProjectItem).count() == 0
        assert list_import_jobs(object(), db) == []
        assert not cache_path.exists()
        assert not stored_original.exists()


def test_import_estimates_use_prior_estimate_accuracy(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_import_jobs
    from app.models import Document, DocumentCompositionRecord, ImportBatch, ImportJob

    with Session() as db:
        completed_batch = ImportBatch(total_files=1, shared_defaults={})
        completed_document = Document(
            title="Completed",
            original_filename="completed.pdf",
            checksum_sha256="f" * 64,
            page_count=10,
            processing_status="ready",
        )
        completed_job = ImportJob(batch=completed_batch, document=completed_document, status="complete", current_step="complete")
        db.add_all([completed_batch, completed_document, completed_job])
        db.flush()
        db.add_all(
            [
                DocumentCompositionRecord(
                    document_id=completed_document.id,
                    import_job_id=completed_job.id,
                    sequence=1,
                    record_kind="estimate",
                    stage_key="import_cost_estimate",
                    stage_label="Import cost estimate",
                    provider="medusa",
                    method="default",
                    status="estimated",
                    amount_usd=0.10,
                    record_metadata={"estimate_basis": "default", "estimated_page_count": 10},
                ),
                DocumentCompositionRecord(
                    document_id=completed_document.id,
                    import_job_id=completed_job.id,
                    sequence=30,
                    record_kind="llm",
                    stage_key="summary_topics",
                    stage_label="Metadata, summary, and topics",
                    provider="openai",
                    method="medusa_document_summary",
                    model="gpt-5.4",
                    status="success",
                    amount_usd=0.20,
                ),
            ]
        )

        staged_batch = ImportBatch(total_files=1, shared_defaults={})
        staged_document = Document(title="Staged", original_filename="staged.pdf", checksum_sha256="0" * 64, page_count=10)
        staged_job = ImportJob(batch=staged_batch, document=staged_document, status="staged", current_step="staged")
        db.add_all([staged_batch, staged_document, staged_job])
        db.commit()

        rows = list_import_jobs(object(), db)

    staged_row = next(row for row in rows if row["id"] == staged_job.id)
    assert staged_row["estimated_cost_basis"] == "calibrated_preset_steps"
    assert staged_row["estimated_cost_usd"] > 0


def test_import_estimates_reflect_processing_preset_steps(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import estimate_import_job_cost
    from app.models import Document, ImportBatch, ImportJob
    from app.services.preferences import built_in_import_processing_presets, get_analysis_models

    presets = {preset["id"]: preset for preset in built_in_import_processing_presets()}
    rates = {"estimate_calibration_factor": 1.0, "estimate_calibration_sample_count": 0}

    with Session() as db:
        model_preferences = get_analysis_models(db)
        strict_batch = ImportBatch(total_files=1, shared_defaults={"processing_preset_snapshot": presets["strict_local"]})
        strict_document = Document(
            title="Strict",
            original_filename="strict.pdf",
            checksum_sha256="1" * 64,
            page_count=40,
            metadata_evidence={"import_processing_preset": presets["strict_local"]},
        )
        strict_job = ImportJob(batch=strict_batch, document=strict_document, status="staged", current_step="staged")
        deep_batch = ImportBatch(total_files=1, shared_defaults={"processing_preset_snapshot": presets["deep_review"]})
        deep_document = Document(
            title="Deep",
            original_filename="deep.pdf",
            checksum_sha256="2" * 64,
            page_count=40,
            metadata_evidence={"import_processing_preset": presets["deep_review"]},
        )
        deep_job = ImportJob(batch=deep_batch, document=deep_document, status="staged", current_step="staged")
        db.add_all([strict_batch, strict_document, strict_job, deep_batch, deep_document, deep_job])
        db.commit()

        strict_estimate = estimate_import_job_cost(strict_job, model_preferences=model_preferences, rates=rates, db=db)
        deep_estimate = estimate_import_job_cost(deep_job, model_preferences=model_preferences, rates=rates, db=db)

    strict_steps = {step["task_key"]: step for step in strict_estimate["steps"]}
    deep_steps = {step["task_key"]: step for step in deep_estimate["steps"]}
    assert strict_steps["page_text_normalization"]["estimated_cost_usd"] == 0
    assert deep_steps["page_text_normalization"]["estimated_page_count"] == 20
    assert deep_steps["page_text_normalization"]["estimated_cost_usd"] > 0
    assert deep_steps["ocr_fallback"]["basis"] == "pending_provider_integration"
    assert deep_steps["ocr_fallback"]["estimated_cost_usd"] == 0
    assert deep_steps["visual_asset_context"]["basis"] == "pending_cropped_region_model_calls"
    assert deep_steps["visual_asset_context"]["estimated_cost_usd"] == 0
    assert deep_estimate["estimated_cost_usd"] > strict_estimate["estimated_cost_usd"]


def test_ingestion_history_aggregates_batch_costs_and_preset(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app import main as main_module
    from app.main import list_ingestion_history
    from app.models import Document, DocumentCompositionRecord, ImportBatch, ImportJob, OpenAIUsageRecord, ProcessingEvent, utc_now

    monkeypatch.setattr(main_module, "estimated_cost_usd_for_record", lambda _record, _db=None: 0.42)
    started = utc_now() - timedelta(minutes=12)
    completed = utc_now() - timedelta(minutes=2)
    with Session() as db:
        batch = ImportBatch(
            label="filename sync 2026-06-25",
            status="complete",
            total_files=1,
            completed_files=1,
            shared_defaults={"processing_preset_snapshot": {"id": "balanced", "name": "Balanced", "mode": "balanced"}},
        )
        document = Document(
            title="Completed",
            original_filename="completed.pdf",
            checksum_sha256="a" * 64,
            metadata_evidence={"file_size_bytes": 2048},
            processing_status="ready",
        )
        job = ImportJob(
            batch=batch,
            document=document,
            status="complete",
            current_step="complete",
            created_at=started,
            updated_at=completed,
        )
        db.add_all([batch, document, job])
        db.flush()
        db.add_all(
            [
                ProcessingEvent(import_job_id=job.id, document_id=document.id, event_type="manual_import_process_uploads", message="released", created_at=started),
                DocumentCompositionRecord(
                    document_id=document.id,
                    import_job_id=job.id,
                    sequence=1,
                    record_kind="estimate",
                    stage_key="import_cost_estimate",
                    stage_label="Import cost estimate",
                    provider="medusa",
                    method="preset",
                    status="estimated",
                    amount_usd=0.75,
                ),
                OpenAIUsageRecord(
                    document_id=document.id,
                    import_job_id=job.id,
                    source="import",
                    task_key="summary_topics",
                    operation="summary",
                    endpoint="responses",
                    model="gpt-5.4",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                ),
            ]
        )
        db.commit()

        rows = list_ingestion_history(object(), db)

    row = rows[0]
    assert row["label"] == "filename sync 2026-06-25"
    assert row["total_files"] == 1
    assert row["completed_files"] == 1
    assert row["estimated_cost_usd"] == 0.75
    assert row["actual_cost_usd"] == 0.42
    assert row["cost_per_document_usd"] == 0.42
    assert row["total_size_bytes"] == 2048
    assert row["processing_preset_name"] == "Balanced"
    assert row["duration_seconds"] is not None


def test_refresh_import_batch_progress_logs_completion_event_once(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.models import Document, ImportBatch, ImportJob, ProcessingEvent
    from app.services.processing import refresh_import_batch_progress

    with Session() as db:
        batch = ImportBatch(label="finished", total_files=1, shared_defaults={})
        document = Document(title="Done", original_filename="done.pdf", checksum_sha256="b" * 64)
        job = ImportJob(batch=batch, document=document, status="complete", current_step="complete")
        db.add_all([batch, document, job])
        db.commit()

        refresh_import_batch_progress(db, batch)
        refresh_import_batch_progress(db, batch)
        db.flush()

        events = db.query(ProcessingEvent).filter(ProcessingEvent.event_type == "import_batch_complete").all()

    assert len(events) == 1
    assert events[0].payload["batch_id"] == batch.id
    assert events[0].payload["completed_files"] == 1


def test_import_exemplar_estimates_keep_per_document_model_floor(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import estimate_import_job_cost
    from app.models import Document, ImportBatch, ImportJob
    from app.services.analysis_models import MODEL_METADATA, MODEL_PAGE_TEXT_NORMALIZATION
    from app.services.preferences import built_in_import_processing_presets, get_analysis_models

    presets = {preset["id"]: preset for preset in built_in_import_processing_presets()}
    tiny_rate = 0.000001

    with Session() as db:
        model_preferences = get_analysis_models(db)
        rates = {
            "task_model_rates": {
                (task_key, model): tiny_rate
                for task_key, model in model_preferences.items()
                if model
            },
            "task_rates": {},
            "estimate_calibration_factor": 0.25,
            "estimate_calibration_sample_count": 12,
        }
        batch = ImportBatch(total_files=1, shared_defaults={"processing_preset_snapshot": presets["balanced"]})
        document = Document(
            title="Short staged paper",
            original_filename="short.pdf",
            checksum_sha256="3" * 64,
            page_count=1,
            metadata_evidence={"import_processing_preset": presets["balanced"]},
        )
        job = ImportJob(batch=batch, document=document, status="staged", current_step="staged")
        db.add_all([batch, document, job])
        db.commit()

        estimate = estimate_import_job_cost(job, model_preferences=model_preferences, rates=rates, db=db)

    steps = {step["task_key"]: step for step in estimate["steps"]}
    assert steps[MODEL_METADATA]["basis"] == "task_model_exemplar_model_floor"
    assert steps[MODEL_METADATA]["estimated_cost_usd"] > steps[MODEL_METADATA]["exemplar_cost_usd"]
    assert steps[MODEL_PAGE_TEXT_NORMALIZATION]["estimated_cost_usd"] > 0
    assert estimate["basis"] == "calibrated_preset_steps_model_floor"
    assert estimate["estimated_cost_usd"] > 0.07
    assert estimate["minimum_cloud_call_cost_usd"] == estimate["estimated_cost_usd"]


def test_list_import_jobs_repairs_missing_staged_pdf_page_estimates(monkeypatch, tmp_path):
    import fitz

    Session = make_session(monkeypatch, tmp_path)
    from app.main import list_import_jobs
    from app.models import Document, ImportBatch, ImportJob

    pdf = fitz.open()
    for index in range(3):
        page = pdf.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    cache_path = tmp_path / "staged.pdf"
    cache_path.write_bytes(pdf.tobytes())
    pdf.close()

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(
            title="Needs page repair",
            original_filename="staged.pdf",
            checksum_sha256="4" * 64,
            page_count=0,
            processing_status="staged",
            metadata_evidence={
                "document_cache_path": str(cache_path),
                "source_import": {"kind": "pdf", "estimated_page_count": None},
                "upload_cost_estimate": {
                    "estimated_cost_usd": 0.01,
                    "estimated_page_count": 1,
                    "basis": "stale_one_page_estimate",
                },
            },
        )
        job = ImportJob(batch=batch, document=document, status="staged", current_step="staged")
        db.add_all([batch, document, job])
        db.commit()

        rows = list_import_jobs(object(), db)

    row = next(item for item in rows if item["id"] == job.id)
    assert document.page_count == 3
    assert document.metadata_evidence["source_import"]["estimated_page_count"] == 3
    assert document.metadata_evidence["upload_cost_estimate"]["estimated_page_count"] == 3
    assert document.metadata_evidence["upload_cost_estimate"]["estimated_cost_usd"] > 0.01
    assert row["document_page_count"] == 3
    assert row["estimated_cost_page_count"] == 3


def test_cancel_import_job_clears_queued_row(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import cancel_import_job
    from app.models import Document, ImportBatch, ImportJob

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(title="Queued", original_filename="queued.pdf", checksum_sha256="b" * 64, processing_status="queued")
        job = ImportJob(batch=batch, document=document, status="queued", current_step="stored")
        db.add_all([batch, document, job])
        db.commit()

        row = cancel_import_job(job.id, object(), db)

        assert row["status"] == "cleared"
        assert row["current_step"] == "cleared"
        assert document.processing_status == "cleared"


def test_cancel_import_job_rejects_running_row(monkeypatch, tmp_path):
    Session = make_session(monkeypatch, tmp_path)
    from app.main import cancel_import_job
    from app.models import Document, ImportBatch, ImportJob, utc_now

    with Session() as db:
        batch = ImportBatch(total_files=1, shared_defaults={})
        document = Document(title="Running", original_filename="running.pdf", checksum_sha256="c" * 64, processing_status="running")
        job = ImportJob(batch=batch, document=document, status="running", current_step="enriching", locked_at=utc_now())
        db.add_all([batch, document, job])
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            cancel_import_job(job.id, object(), db)

        assert exc_info.value.status_code == 409
        assert job.status == "running"
        assert document.processing_status == "running"
