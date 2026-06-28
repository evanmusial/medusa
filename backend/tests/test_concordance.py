from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_create_concordance_run_skips_current_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability
    from app.services.concordance import CAPABILITY_BY_KEY, create_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Indexed",
            original_filename="already-indexed.pdf",
            checksum_sha256="a" * 64,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="search_index",
                version=CAPABILITY_BY_KEY["search_index"].version,
                status="complete",
            )
        )
        db.commit()

        run = create_concordance_run(db, capability_keys=["search_index"])

        assert run.total_jobs == 0
        assert run.status == "complete"


def test_forced_bibliography_refresh_reextracts_existing_bibliography(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCapability, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    cleanup_calls = []

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            cleanup_calls.append(
                {
                    "filename": filename,
                    "bibliography": bibliography,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "bibliography": "Smith, A. (2024). *Fresh source*. Journal.",
                "confidence": 0.93,
                "notes": [],
                "_openai": {"model": model, "configured": True},
            }

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="References Target",
            original_filename="references.pdf",
            checksum_sha256="r" * 64,
            processing_status="ready",
            bibliography="Old bibliography.",
        )
        document.pages.append(
            DocumentPage(
                page_number=1,
                normalized_text="Body text.\n\nReferences\nSmith, A. (2024). Fresh source. Journal.",
            )
        )
        db.add(document)
        run = ConcordanceRun(scope_type="documents", scope_data={}, capability_keys=["bibliography_extraction"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        assert document.bibliography == "Old bibliography."
        assert job.status == "complete"
        capability = db.query(DocumentCapability).filter_by(document_id=document.id, capability_key="bibliography_extraction").one()
        assert capability.evidence["status"] == "skipped_existing_bibliography"

        forced_run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(forced_run)
        db.flush()
        forced_job = ConcordanceJob(
            run=forced_run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(forced_job)
        db.commit()

        ConcordanceProcessor().process_job(db, forced_job)

        assert document.bibliography == "Smith, A. (2024). *Fresh source*. Journal."
        assert forced_job.status == "complete"
        db.refresh(capability)
        assert capability.evidence["status"] == "extracted"
        assert capability.evidence["model_cleanup"]["model"] == "gpt-5.4-nano"
        assert capability.evidence["model_cleanup"]["formatting"] == "alphabetized_apa_markdown_one_source_per_line"
        assert document.metadata_evidence["bibliography_extraction"]["status"] == "extracted"
        assert document.metadata_evidence["bibliography_extraction"]["generated_at"] == capability.evidence["generated_at"]
        assert datetime.fromisoformat(capability.evidence["generated_at"])
        assert len(cleanup_calls) == 1
        assert cleanup_calls[0]["model"] == "gpt-5.4-nano"
        assert cleanup_calls[0]["capability_key"] == "bibliography_extraction"


def test_forced_bibliography_refresh_clears_stale_machine_output_when_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCapability, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    monkeypatch.setattr(
        concordance_service,
        "extract_document_bibliography",
        lambda _document, _pdf_path=None: {
            "bibliography": None,
            "evidence": {
                "source": "page_text",
                "status": "not_found",
                "unreadable_text_pages": [11],
                "ocr_recommended": True,
            },
        },
    )

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Stale References Target",
            original_filename="stale-references.pdf",
            checksum_sha256="s" * 64,
            processing_status="ready",
            bibliography="References: this document contains references to 16 other documents. Publisher boilerplate.",
            metadata_evidence={
                "bibliography_extraction": {
                    "source": "pdf_span_layout",
                    "status": "extracted",
                    "page_start": 1,
                    "page_end": 12,
                }
            },
        )
        document.pages.append(DocumentPage(page_number=11, normalized_text="# $ BB == 4!!(# BB? ==!"))
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        assert job.status == "complete"
        assert document.bibliography is None
        evidence = document.metadata_evidence["bibliography_extraction"]
        assert evidence["status"] == "not_found"
        assert evidence["stale_bibliography_cleared"] is True
        assert evidence["stale_bibliography_characters"] > 0
        assert evidence["unreadable_text_pages"] == [11]
        capability = db.query(DocumentCapability).filter_by(document_id=document.id, capability_key="bibliography_extraction").one()
        assert capability.version == CAPABILITY_BY_KEY["bibliography_extraction"].version
        assert capability.evidence["stale_bibliography_cleared"] is True
        versions = [version for version in document.versions if version.change_note == "Concordance bibliography stale clear"]
        assert len(versions) == 1
        assert "bibliography" in versions[0].metadata_snapshot["changed_fields"]


def test_forced_bibliography_refresh_preserves_user_text_when_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    monkeypatch.setattr(
        concordance_service,
        "extract_document_bibliography",
        lambda _document, _pdf_path=None: {"bibliography": None, "evidence": {"source": "page_text", "status": "not_found"}},
    )

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Manual References Target",
            original_filename="manual-references.pdf",
            checksum_sha256="m" * 64,
            processing_status="ready",
            bibliography="User supplied bibliography.",
        )
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        assert job.status == "complete"
        assert document.bibliography == "User supplied bibliography."
        assert document.metadata_evidence["bibliography_extraction"]["status"] == "not_found"
        assert not document.versions


def test_forced_bibliography_refresh_cleans_preserved_existing_when_extraction_regresses(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCapability, DocumentCompositionRecord
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    cleanup_calls = []

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            cleanup_calls.append(bibliography)
            return {
                "bibliography": bibliography,
                "confidence": 0.88,
                "notes": [],
                "_openai": {"model": model, "configured": True},
            }

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())
    monkeypatch.setattr(
        concordance_service,
        "extract_document_bibliography",
        lambda _document, _pdf_path=None: {
            "bibliography": "Adams, A. (2024). Surviving source.\nBrown, B. (2023). Surviving source.",
            "evidence": {"source": "pdf_span_layout", "status": "extracted", "page_start": 10, "page_end": 11},
        },
    )

    existing_bibliography = "\n".join(
        [
            "Adams, A. (2024). Existing source.",
            "Brown, B. (2023). Existing source.",
            "Clark, C. (2022). Existing source.",
            "Davis, D. (2021). Existing source.",
        ]
    )
    Session = make_session()
    with Session() as db:
        document = Document(
            title="Regression Guard Target",
            original_filename="regression-guard.pdf",
            checksum_sha256="q" * 64,
            processing_status="ready",
            bibliography=existing_bibliography,
        )
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        assert job.status == "complete"
        assert document.bibliography == existing_bibliography
        evidence = document.metadata_evidence["bibliography_extraction"]
        assert evidence["status"] == "rejected_regression_existing_bibliography"
        assert evidence["existing_entry_count"] == 4
        assert evidence["extracted_entry_count"] == 2
        assert evidence["existing_bibliography_preserved"] is True
        assert evidence["model_cleanup_input_source"] == "existing_bibliography_preserved"
        assert evidence["model_cleanup"]["status"] == "formatted"
        capability = db.query(DocumentCapability).filter_by(document_id=document.id, capability_key="bibliography_extraction").one()
        assert capability.evidence["status"] == "rejected_regression_existing_bibliography"
        assert cleanup_calls == [existing_bibliography]
        assert DocumentCompositionRecord.__table__.c.status.type.length >= len("rejected_regression_existing_bibliography")
        composition = db.query(DocumentCompositionRecord).filter_by(document_id=document.id, record_kind="concordance").one()
        assert composition.status == "warning"
        assert composition.record_metadata["status"] == "rejected_regression_existing_bibliography"
        assert document.versions


def test_concordance_stage_status_uses_bounded_composition_statuses(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.services.concordance import concordance_stage_status

    assert concordance_stage_status({"status": "rejected_regression_existing_bibliography"}) == "warning"
    assert concordance_stage_status({"status": "model_no_op", "skipped": True}) == "skipped"
    assert concordance_stage_status({"status": "not_found"}) == "skipped"
    assert concordance_stage_status({"status": "a_future_detailed_evidence_label_that_should_not_become_db_state"}) == "complete"


def test_forced_bibliography_refresh_skips_model_cleanup_for_large_lists(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, BIBLIOGRAPHY_MODEL_CLEANUP_MAX_ENTRIES, ConcordanceProcessor

    cleanup_calls = []

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            cleanup_calls.append(bibliography)
            raise AssertionError("large bibliography should not be sent to model cleanup")

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    entries = [
        f"Zed, Z., 2024. Large bibliography source {index}. Journal of Tests."
        for index in range(BIBLIOGRAPHY_MODEL_CLEANUP_MAX_ENTRIES)
    ]
    entries.append("Adams, A., 2024. Large bibliography source. Journal of Tests.")
    Session = make_session()
    with Session() as db:
        document = Document(
            title="Large References Target",
            original_filename="large-references.pdf",
            checksum_sha256="l" * 64,
            processing_status="ready",
            bibliography="Old bibliography.",
        )
        document.pages.append(DocumentPage(page_number=1, normalized_text="Body text.\n\nReferences\n" + "\n".join(entries)))
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        bibliography_lines = [line for line in (document.bibliography or "").splitlines() if line.strip()]
        cleanup = document.metadata_evidence["bibliography_extraction"]["model_cleanup"]
        assert job.status == "complete"
        assert len(bibliography_lines) == BIBLIOGRAPHY_MODEL_CLEANUP_MAX_ENTRIES + 1
        assert bibliography_lines[0].startswith("Adams, A.")
        assert cleanup["status"] == "skipped_large_bibliography"
        assert cleanup["entry_count"] == BIBLIOGRAPHY_MODEL_CLEANUP_MAX_ENTRIES + 1
        assert cleanup_calls == []


def test_forced_bibliography_refresh_cleans_large_lists_within_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    cleanup_calls = []

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            cleanup_calls.append(bibliography)
            return {
                "bibliography": bibliography,
                "confidence": 0.88,
                "notes": [],
                "_openai": {"model": model, "configured": True},
            }

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    entries = [
        f"Zed, Z., 2024. Large bibliography source {index}. Journal of Tests."
        for index in range(80)
    ]
    entries.append("Adams, A., 2024. Large bibliography source. Journal of Tests.")
    Session = make_session()
    with Session() as db:
        document = Document(
            title="Large Cleanup Target",
            original_filename="large-cleanup.pdf",
            checksum_sha256="m" * 64,
            processing_status="ready",
            bibliography="Old bibliography.",
        )
        document.pages.append(DocumentPage(page_number=1, normalized_text="Body text.\n\nReferences\n" + "\n".join(entries)))
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        cleanup = document.metadata_evidence["bibliography_extraction"]["model_cleanup"]
        assert job.status == "complete"
        assert cleanup["status"] == "formatted"
        assert cleanup_calls
        assert cleanup_calls[0].splitlines()[0].startswith("Adams, A.")


def test_forced_bibliography_refresh_rejects_incomplete_model_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            return {
                "bibliography": "Adams, A. (2024). Only one source survived.",
                "confidence": 0.41,
                "notes": ["The model dropped entries."],
                "_openai": {"model": model, "configured": True},
            }

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    entries = [
        f"Zed, Z., 2024. Large bibliography source {index}. Journal of Tests."
        for index in range(80)
    ]
    entries.append("Adams, A., 2024. Large bibliography source. Journal of Tests.")
    Session = make_session()
    with Session() as db:
        document = Document(
            title="Incomplete Cleanup Target",
            original_filename="incomplete-cleanup.pdf",
            checksum_sha256="n" * 64,
            processing_status="ready",
            bibliography="Old bibliography.",
        )
        document.pages.append(DocumentPage(page_number=1, normalized_text="Body text.\n\nReferences\n" + "\n".join(entries)))
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        bibliography_lines = [line for line in (document.bibliography or "").splitlines() if line.strip()]
        cleanup = document.metadata_evidence["bibliography_extraction"]["model_cleanup"]
        assert job.status == "complete"
        assert len(bibliography_lines) == 81
        assert bibliography_lines[0].startswith("Adams, A.")
        assert cleanup["status"] == "rejected_incomplete"
        assert cleanup["input_entry_count"] == 81
        assert cleanup["output_entry_count"] == 1
        assert document.metadata_evidence["bibliography_extraction"]["formatting"] != "apa_markdown_model_cleanup"


def test_forced_bibliography_refresh_rejects_cleanup_that_drops_coauthor(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            return {
                "bibliography": "\n".join(
                    [
                        "Anderson, R. (1993). Why cryptosystems fail.",
                        "Neumann, P. G. (1989). A Summary of Computer Misuse Techniques.",
                    ]
                ),
                "confidence": 0.55,
                "notes": ["The model dropped a coauthor while keeping the entry count."],
                "_openai": {"model": model, "configured": True},
            }

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Author Loss Cleanup Target",
            original_filename="author-loss-cleanup.pdf",
            checksum_sha256="o" * 64,
            processing_status="ready",
            bibliography="Old bibliography.",
        )
        document.pages.append(
            DocumentPage(
                page_number=1,
                normalized_text=(
                    "References\n"
                    "[1] Neumann, P. G., and Parker, D. (1989). A Summary of Computer Misuse Techniques.\n"
                    "[2] Anderson, R. (1993). Why cryptosystems fail."
                ),
            )
        )
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        cleanup = document.metadata_evidence["bibliography_extraction"]["model_cleanup"]
        assert job.status == "complete"
        assert cleanup["status"] == "rejected_author_loss"
        assert cleanup["input_entry_count"] == 2
        assert cleanup["output_entry_count"] == 2
        assert cleanup["missing_author_sets"] == [["Neumann", "Parker"]]
        assert "Parker, D." in document.bibliography
        assert document.metadata_evidence["bibliography_extraction"]["formatting"] != "apa_markdown_model_cleanup"


def test_forced_bibliography_refresh_rejects_cleanup_that_adds_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    class FakeAiService:
        def normalize_bibliography(self, filename, bibliography, *, model=None, usage_context=None, prompt_cache_key=None):
            return {
                "bibliography": "\n".join(
                    [
                        "Anderson, R. (1993). Why cryptosystems fail.",
                        "Neumann, P. G., & Parker, D. (1989). A Summary of Computer Misuse Techniques.",
                        "Neumann, P. G., & Parker, D. (1989). A Summary of Computer Misuse Techniques.",
                    ]
                ),
                "confidence": 0.48,
                "notes": ["The model duplicated one entry."],
                "_openai": {"model": model, "configured": True},
            }

    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Duplicate Cleanup Target",
            original_filename="duplicate-cleanup.pdf",
            checksum_sha256="p" * 64,
            processing_status="ready",
            bibliography="Old bibliography.",
        )
        document.pages.append(
            DocumentPage(
                page_number=1,
                normalized_text=(
                    "References\n"
                    "[1] Neumann, P. G., and Parker, D. (1989). A Summary of Computer Misuse Techniques.\n"
                    "[2] Anderson, R. (1993). Why cryptosystems fail."
                ),
            )
        )
        db.add(document)
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"_force": True},
            capability_keys=["bibliography_extraction"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="bibliography_extraction",
            target_version=CAPABILITY_BY_KEY["bibliography_extraction"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        cleanup = document.metadata_evidence["bibliography_extraction"]["model_cleanup"]
        bibliography_lines = [line for line in (document.bibliography or "").splitlines() if line.strip()]
        assert job.status == "complete"
        assert cleanup["status"] == "rejected_duplicate_cleanup"
        assert cleanup["input_entry_count"] == 2
        assert cleanup["output_entry_count"] == 3
        assert len(cleanup["duplicate_entries"]) == 1
        assert len(bibliography_lines) == 2
        assert document.metadata_evidence["bibliography_extraction"]["formatting"] != "apa_markdown_model_cleanup"


def test_citation_refresh_discovers_missing_doi_from_title(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document
    from app.services import concordance as concordance_service
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor

    class FakeAiService:
        def generate_apa_citation_candidate(
            self,
            filename,
            text,
            metadata,
            *,
            model=None,
            usage_context=None,
            prompt_cache_key=None,
            crossref_candidates=None,
        ):
            return {
                "apa_citation": None,
                "apa_in_text_citation": None,
                "citation_warnings": [],
                "confidence": 0.75,
                "needs_review_reasons": [],
                "_openai": {"model": model, "configured": False},
            }

    monkeypatch.setattr(concordance_service, "crossref_lookup", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        concordance_service,
        "discover_doi_from_title",
        lambda *args, **kwargs: {
            "source": "title_web_search",
            "doi": "10.5555/1218112.1218218",
            "query": '"Modeling the Emergence of Insider Threat Vulnerabilities" DOI',
        },
    )
    monkeypatch.setattr(concordance_service, "get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Modeling the Emergence of Insider Threat Vulnerabilities",
            original_filename="insider-threat.pdf",
            checksum_sha256="d" * 64,
            authors=[{"given": "Ignacio J.", "family": "Martinez-Moyano"}],
            publication_year=2006,
            processing_status="ready",
            search_text="No visible DOI here.",
            metadata_evidence={},
        )
        run = ConcordanceRun(scope_type="documents", scope_data={}, capability_keys=["citation_refresh"], total_jobs=1)
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="citation_refresh",
            target_version=CAPABILITY_BY_KEY["citation_refresh"].version,
        )
        db.add_all([document, run, job])
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        assert document.doi == "10.5555/1218112.1218218"
        assert document.metadata_evidence["doi_discovery"]["source"] == "title_web_search"
        assert document.citation_status == "verified"
        assert "https://doi.org/10.5555/1218112.1218218" in document.apa_citation
        assert job.status == "complete"


def test_concordance_estimate_marks_same_model_summary_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.concordance import create_concordance_run, estimate_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Summarized",
            original_filename="already-summarized.pdf",
            checksum_sha256="m" * 64,
            processing_status="ready",
            rich_summary="This paper already has a summary.",
            page_count=12,
        )
        db.add(document)
        db.flush()
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="import",
                capability_key="summary_topics",
                task_key=MODEL_SUMMARY,
                operation="medusa_document_summary",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
            )
        )
        db.commit()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )
        run = create_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )

        assert estimate["planned_jobs"] == 0
        assert estimate["model_no_op_jobs"] == 1
        assert estimate["estimated_cost_usd"] == 0
        assert estimate["items"][0]["status"] == "model_no_op"
        assert run.total_jobs == 0
        assert run.status == "complete"


def test_forced_tag_refresh_queues_even_when_same_model_current(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_KEYWORDS_TOPICS
    from app.services.concordance import CAPABILITY_BY_KEY, create_concordance_run, estimate_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Tagged",
            original_filename="already-tagged.pdf",
            checksum_sha256="t" * 64,
            processing_status="ready",
            page_count=6,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="tag_refresh",
                version=CAPABILITY_BY_KEY["tag_refresh"].version,
                status="complete",
            )
        )
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="concordance",
                capability_key="tag_refresh",
                task_key=MODEL_KEYWORDS_TOPICS,
                operation="medusa_keywords_topics",
                endpoint="responses",
                model="gpt-5.4-mini",
                status="success",
            )
        )
        db.commit()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["tag_refresh"],
            force=True,
        )
        run = create_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["tag_refresh"],
            force=True,
        )

        assert estimate["planned_jobs"] == 1
        assert estimate["items"][0]["status"] == "planned"
        assert run.total_jobs == 1
        assert run.scope_data["_force"] is True


def test_forced_bibliography_estimate_includes_cleanup_model_without_broad_noop_breakage(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability
    from app.services.analysis_models import MODEL_BIBLIOGRAPHY_CLEANUP
    from app.services.concordance import CAPABILITY_BY_KEY, estimate_concordance_run

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Already Extracted Bibliography",
            original_filename="already-extracted-bibliography.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
            bibliography="Old stored bibliography.",
            page_count=9,
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

        default_estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["bibliography_extraction"],
        )
        forced_estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["bibliography_extraction"],
            force=True,
        )

        assert default_estimate["planned_jobs"] == 0
        assert default_estimate["items"][0]["status"] == "current_version"
        assert forced_estimate["planned_jobs"] == 1
        assert forced_estimate["items"][0]["status"] == "planned"
        assert forced_estimate["items"][0]["requirements"][0]["task_key"] == MODEL_BIBLIOGRAPHY_CLEANUP
        assert forced_estimate["items"][0]["cost_steps"][0]["task_key"] == MODEL_BIBLIOGRAPHY_CLEANUP


def test_concordance_estimate_queues_current_capability_when_model_changed(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, DocumentCapability, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.concordance import CAPABILITY_BY_KEY, create_concordance_run, estimate_concordance_run
    from app.services.preferences import update_app_preferences

    Session = make_session()
    with Session() as db:
        update_app_preferences(db, analysis_models={MODEL_SUMMARY: "gpt-5.5"})
        document = Document(
            title="Model Changed",
            original_filename="model-changed.pdf",
            checksum_sha256="n" * 64,
            processing_status="ready",
            rich_summary="This summary used the old model.",
            page_count=10,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentCapability(
                document_id=document.id,
                capability_key="summary_refresh",
                version=CAPABILITY_BY_KEY["summary_refresh"].version,
                status="complete",
            )
        )
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="concordance",
                capability_key="summary_refresh",
                task_key=MODEL_SUMMARY,
                operation="medusa_document_summary",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
            )
        )
        db.commit()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )
        run = create_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_refresh"],
        )

        assert estimate["planned_jobs"] == 1
        assert estimate["items"][0]["status"] == "planned"
        assert estimate["items"][0]["estimated_cost_usd"] > 0
        assert run.total_jobs == 1


def test_concordance_formula_capture_is_manual_refinement(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage, DocumentVersion
    from app.services.concordance import CAPABILITY_BY_KEY, ConcordanceProcessor, estimate_concordance_run

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def capture_formulas(self, filename, text, pdf_bytes=None, *, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "filename": filename,
                    "text": text,
                    "pdf_bytes": pdf_bytes,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "formulas": [
                    {
                        "page_number": 1,
                        "latex": "E = mc^2",
                        "display": True,
                        "label": "Equation 1",
                        "surrounding_text": "Mass-energy relation.",
                        "confidence": 0.94,
                    },
                    {
                        "page_number": 2,
                        "latex": "a^2 + b^2 = c^2",
                        "display": True,
                        "label": None,
                        "surrounding_text": "Manual page formula.",
                        "confidence": 0.9,
                    },
                ],
                "confidence": 0.92,
                "notes": [],
                "_openai": {"model": model, "configured": True, "used_pdf_file": False, "pdf_file_bytes": 0},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Formula Target",
            original_filename="formula-target.pdf",
            checksum_sha256="f" * 64,
            processing_status="ready",
            page_count=2,
        )
        document.pages.append(DocumentPage(page_number=1, normalized_text="The paper states an equation.", text_source="pymupdf"))
        document.pages.append(DocumentPage(page_number=2, normalized_text="Manual correction text.", text_source="manual"))
        db.add(document)
        db.flush()

        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["formula_capture"],
        )
        assert estimate["planned_jobs"] == 1
        assert estimate["items"][0]["requirements"][0]["model"] == "gpt-5.4"
        default_estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
        )
        assert "formula_capture" not in default_estimate["capability_keys"]

        run = ConcordanceRun(scope_type="documents", scope_data={}, capability_keys=["formula_capture"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run=run,
            document=document,
            capability_key="formula_capture",
            target_version=CAPABILITY_BY_KEY["formula_capture"].version,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()
        page_one = next(page for page in document.pages if page.page_number == 1)
        page_two = next(page for page in document.pages if page.page_number == 2)

        assert job.status == "complete"
        assert document.metadata_evidence["formula_capture"]["status"] == "captured"
        assert document.metadata_evidence["formula_capture"]["model"] == "gpt-5.4"
        assert document.metadata_evidence["formula_capture"]["formula_count"] == 2
        assert document.metadata_evidence["formula_capture"]["manual_pages_protected"] == 1
        assert "Formula capture:" in (page_one.normalized_text or "")
        assert "\\(E = mc^2\\)" in (page_one.normalized_text or "")
        assert page_two.normalized_text == "Manual correction text."
        assert "a^2 + b^2 = c^2" in (document.search_text or "")
        assert version.change_note == "Concordance formula capture"
        assert "pages" in version.metadata_snapshot["changed_fields"]
        assert calls == [
            {
                "filename": "formula-target.pdf",
                "text": "[Page 1]\nThe paper states an equation.\n\n[Page 2]\nManual correction text.",
                "pdf_bytes": None,
                "model": "gpt-5.4",
                "capability_key": "formula_capture",
                "prompt_cache_key": f"medusa-doc:{'f' * 64}:formulas",
            }
        ]


def test_concordance_worker_completes_same_model_noop_without_model_call(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentCompositionRecord, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.concordance import ConcordanceProcessor

    class ExplodingAiService:
        def generate_document_summary(self, *_args, **_kwargs):
            raise AssertionError("same-model summary should not be regenerated")

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: ExplodingAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Worker No-op",
            original_filename="worker-noop.pdf",
            checksum_sha256="o" * 64,
            processing_status="ready",
            rich_summary="This summary is already current.",
            page_count=8,
        )
        db.add(document)
        run = ConcordanceRun(scope_type="documents", scope_data={"document_ids": []}, capability_keys=["summary_refresh"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_refresh",
            target_version=1,
        )
        db.add(job)
        db.add(
            OpenAIUsageRecord(
                document_id=document.id,
                source="import",
                capability_key="summary_topics",
                task_key=MODEL_SUMMARY,
                operation="medusa_document_summary",
                endpoint="responses",
                model="gpt-5.4",
                status="success",
            )
        )
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        record = (
            db.query(DocumentCompositionRecord)
            .filter(
                DocumentCompositionRecord.document_id == document.id,
                DocumentCompositionRecord.record_kind == "concordance",
            )
            .one()
        )
        assert job.status == "complete"
        assert run.status == "complete"
        assert record.stage_key == "summary_refresh"
        assert record.status == "skipped"
        assert record.record_metadata["status"] == "model_no_op"


def test_concordance_search_index_job_marks_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import (
        AttributeDefinition,
        ConcordanceJob,
        ConcordanceRun,
        Document,
        DocumentAttributeValue,
        DocumentPage,
        Note,
    )
    from app.services.concordance import ConcordanceProcessor

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Tabled Reading",
            original_filename="tabled-reading.pdf",
            checksum_sha256="b" * 64,
            rich_summary="A paper about tabular evidence.",
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, text="Two-column text and a markdown table."))
        db.add(Note(document_id=document.id, title="Reminder", body="Use this in the methods section."))
        definition = AttributeDefinition(name="Aspect summary", value_type="markdown")
        db.add(definition)
        db.flush()
        db.add(
            DocumentAttributeValue(
                document_id=document.id,
                attribute_definition_id=definition.id,
                value={"value": "This aspect tracks experimental design."},
            )
        )
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["search_index"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="search_index",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert run.status == "complete"
        assert "methods section" in (document.search_text or "")
        assert "experimental design" in (document.search_text or "")
        assert document.capabilities[0].capability_key == "search_index"


def test_concordance_page_text_normalization_updates_pages_and_search(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentPage
    from app.services.concordance import ConcordanceProcessor

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Readable Flow",
            original_filename="readable-flow.pdf",
            checksum_sha256="c" * 64,
        )
        db.add(document)
        db.flush()
        db.add(DocumentPage(document_id=document.id, page_number=1, text="The article de-\nscribes normal flow ."))
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["page_text_normalization"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="page_text_normalization",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert document.pages[0].normalized_text == "The article describes normal flow."
        assert "normal flow." in (document.search_text or "")
        assert document.metadata_evidence["page_text_normalization"]["pages"] == 1


def test_create_concordance_run_from_saved_search(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import Document, SavedSearch
    from app.services.concordance import create_concordance_run

    Session = make_session()
    with Session() as db:
        matching = Document(
            title="Cybernetics Reader",
            original_filename="cybernetics.pdf",
            checksum_sha256="d" * 64,
            read_status="unread",
            processing_status="ready",
        )
        other = Document(
            title="Garden Notes",
            original_filename="garden.pdf",
            checksum_sha256="e" * 64,
            read_status="read",
            processing_status="ready",
        )
        db.add_all([matching, other])
        db.flush()
        saved_search = SavedSearch(name="Unread cybernetics", query="cybernetics", filters={"read_status": "unread"})
        db.add(saved_search)
        db.commit()

        run = create_concordance_run(
            db,
            scope_type="saved_search",
            scope_data={"saved_search_id": saved_search.id},
            capability_keys=["search_index"],
        )

        assert run.total_jobs == 1
        assert run.jobs[0].document_id == matching.id


def test_concordance_citation_refresh_fills_missing_fields_from_stored_crossref(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("app.services.concordance.crossref_lookup", lambda *_args, **_kwargs: None)

    from app.models import CitationCandidate, ConcordanceJob, ConcordanceRun, Document
    from app.services.concordance import ConcordanceProcessor

    Session = make_session()
    with Session() as db:
        document = Document(
            title="A Bayesian Network Model for Predicting Insider Threats",
            original_filename="bayesian-network.pdf",
            checksum_sha256="f" * 64,
            apa_citation="(n.d.). A Bayesian Network Model for Predicting Insider Threats.",
            citation_status="needs_review",
            metadata_evidence={
                "crossref": {
                    "DOI": "10.1109/spw.2013.35",
                    "URL": "https://doi.org/10.1109/spw.2013.35",
                    "title": ["A Bayesian Network Model for Predicting Insider Threats"],
                    "author": [
                        {"given": "Elise T.", "family": "Axelrad"},
                        {"given": "Paul J.", "family": "Sticha"},
                        {"given": "Oliver", "family": "Brdiczka"},
                        {"family": "Jianqiang Shen"},
                    ],
                    "published": {"date-parts": [[2013, 5]]},
                    "container-title": ["2013 IEEE Security and Privacy Workshops"],
                    "publisher": "IEEE",
                }
            },
        )
        db.add(document)
        db.flush()
        stale_candidate = CitationCandidate(
            document_id=document.id,
            source="medusa-importer",
            citation_text="(n.d.). A Bayesian Network Model for Predicting Insider Threats.",
            status="needs_review",
        )
        db.add(stale_candidate)
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["citation_refresh"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="citation_refresh",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert document.publication_year == 2013
        assert document.doi == "10.1109/spw.2013.35"
        assert document.authors[0]["family"] == "Axelrad"
        assert document.citation_status == "verified"
        assert "Axelrad, E. T." in (document.apa_citation or "")
        assert "(2013)" in (document.apa_citation or "")
        assert "https://doi.org/10.1109/spw.2013.35" in (document.apa_citation or "")
        assert document.apa_in_text_citation == "(Axelrad et al., 2013)"
        assert document.apa_citation_model == "gpt-5.5"
        assert document.apa_in_text_citation_model == "gpt-5.5"
        db.refresh(stale_candidate)
        assert stale_candidate.status == "superseded"


def test_concordance_summary_refresh_uses_summary_only_model(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document
    from app.services.concordance import ConcordanceProcessor
    from app.services.preferences import update_app_preferences

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def generate_document_summary(self, filename, text, *, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "rich_summary": "**Fresh** summary\n\n- Method: close read",
                "confidence": 0.91,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        update_app_preferences(db, analysis_models={"summary": "gpt-5.4-mini"})
        document = Document(
            title="Summary Target",
            original_filename="summary-target.pdf",
            checksum_sha256="9" * 64,
            rich_summary="Old summary",
            search_text="Original searchable document text.",
        )
        db.add(document)
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["summary_refresh"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_refresh",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert run.status == "complete"
        assert document.rich_summary == "**Fresh** summary\n\n- Method: close read"
        assert "Fresh" in (document.search_text or "")
        assert "Method: close read" in (document.search_text or "")
        assert document.metadata_evidence["summary_refresh"]["model"] == "gpt-5.4-mini"
        assert document.capabilities[0].capability_key == "summary_refresh"
        assert calls == [
            {
                "filename": "summary-target.pdf",
                "text": "Original searchable document text.",
                "model": "gpt-5.4-mini",
                "capability_key": "summary_refresh",
                "prompt_cache_key": f"medusa-doc:{'9' * 64}:summary",
            }
        ]


def test_concordance_summary_topics_prefers_manifest_and_keeps_existing_document_tags(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, Tag
    from app.services.concordance import ConcordanceProcessor

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def extract_document_identity(self, filename, text, *, pdf_bytes=None, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "task": "metadata",
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "title": "Tagged Target",
                "subtitle": None,
                "authors": [],
                "universities": [],
                "publication_year": None,
                "journal": None,
                "publisher": None,
                "doi": None,
                "abstract": None,
                "confidence": 0.88,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

        def generate_document_summary(self, filename, text, *, model=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "task": "summary",
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "rich_summary": "Fresh summary.",
                "confidence": 0.9,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

        def extract_keywords_topics(self, filename, text, *, model=None, existing_tags=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "task": "tags",
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "existing_tags": existing_tags,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "topics": ["shared concept"],
                "keywords": ["new concept"],
                "confidence": 0.88,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        manual_tag = Tag(name="manual keep", kind="tag")
        shared_tag = Tag(name="shared concept", kind="tag")
        document = Document(
            title="Tagged Target",
            original_filename="tagged-target.pdf",
            checksum_sha256="8" * 64,
            search_text="Original searchable document text about a new concept.",
            tags=[manual_tag],
        )
        db.add_all([manual_tag, shared_tag, document])
        run = ConcordanceRun(scope_type="library", scope_data={}, capability_keys=["summary_topics"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_topics",
            target_version=8,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        assert job.status == "complete"
        assert document.rich_summary == "Fresh summary."
        assert sorted(tag.name for tag in document.tags) == ["manual keep", "shared concept"]
        assert document.metadata_evidence["concordance_tag_governance"]["new_candidate_count"] == 0
        assert document.metadata_evidence["concordance_tag_governance"]["decisions"][1]["candidate_name"] == "new concept"
        assert document.metadata_evidence["concordance_tag_governance"]["decisions"][1]["status"] == "not_attached"
        assert calls == [
            {
                "task": "metadata",
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "model": "gpt-5.5",
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}:metadata",
            },
            {
                "task": "summary",
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "model": "gpt-5.4",
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}:summary",
            },
            {
                "task": "tags",
                "filename": "tagged-target.pdf",
                "text": "Original searchable document text about a new concept.",
                "model": "gpt-5.4-mini",
                "existing_tags": ["manual keep", "shared concept"],
                "capability_key": "summary_topics",
                "prompt_cache_key": f"medusa-doc:{'8' * 64}:tags",
            },
        ]


def test_concordance_tag_refresh_replaces_document_tags_with_governed_suggestions(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, DocumentVersion, Tag
    from app.services.concordance import ConcordanceProcessor

    calls: list[dict[str, object]] = []

    class FakeAiService:
        def extract_keywords_topics(self, filename, text, *, model=None, existing_tags=None, usage_context=None, prompt_cache_key=None):
            calls.append(
                {
                    "filename": filename,
                    "text": text,
                    "model": model,
                    "existing_tags": existing_tags,
                    "capability_key": usage_context.capability_key if usage_context else None,
                    "prompt_cache_key": prompt_cache_key,
                }
            )
            return {
                "topics": ["shared concept"],
                "keywords": ["zero trust mesh"],
                "confidence": 0.91,
                "needs_review_reasons": [],
                "_openai": {"model": model, "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        stale_tag = Tag(name="stale manual tag", kind="tag", status="canonical")
        shared_tag = Tag(name="shared concept", kind="tag", status="canonical")
        document = Document(
            title="Tagged Target",
            original_filename="tagged-target.pdf",
            checksum_sha256="7" * 64,
            search_text="This document is about a shared concept and a zero trust mesh.",
            processing_status="ready",
            tags=[stale_tag],
        )
        db.add_all([stale_tag, shared_tag, document])
        db.flush()
        run = ConcordanceRun(
            scope_type="documents",
            scope_data={"document_ids": [document.id], "_force": True},
            capability_keys=["tag_refresh"],
            total_jobs=1,
        )
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="tag_refresh",
            target_version=1,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)
        db.refresh(document)

        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()

        assert job.status == "complete"
        assert sorted(tag.name for tag in document.tags) == ["shared concept", "zero trust mesh"]
        assert "stale manual tag" not in (document.search_text or "")
        assert "shared concept" in (document.search_text or "")
        assert "zero trust mesh" in (document.search_text or "")
        assert document.metadata_evidence["tag_refresh_tag_governance"]["replace_existing"] is True
        assert document.metadata_evidence["tag_refresh_tag_governance"]["replaced_tags"] == ["stale manual tag"]
        assert version.change_note == "Concordance tag refresh"
        assert "tags" in version.metadata_snapshot["changed_fields"]
        assert calls == [
            {
                "filename": "tagged-target.pdf",
                "text": "This document is about a shared concept and a zero trust mesh.",
                "model": "gpt-5.4-mini",
                "existing_tags": ["shared concept", "stale manual tag"],
                "capability_key": "tag_refresh",
                "prompt_cache_key": f"medusa-doc:{'7' * 64}:tag-refresh",
            }
        ]


def test_concordance_summary_topics_skips_same_model_subtasks(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.models import ConcordanceJob, ConcordanceRun, Document, OpenAIUsageRecord
    from app.services.analysis_models import MODEL_KEYWORDS_TOPICS, MODEL_METADATA, MODEL_SUMMARY
    from app.services.concordance import ConcordanceProcessor, estimate_concordance_run

    calls: list[str] = []

    class FakeAiService:
        def extract_document_identity(self, *_args, **_kwargs):
            raise AssertionError("metadata should be same-model no-op")

        def generate_document_summary(self, *_args, **_kwargs):
            raise AssertionError("summary should be same-model no-op")

        def extract_keywords_topics(self, *_args, **_kwargs):
            calls.append("tags")
            return {
                "topics": [],
                "keywords": [],
                "confidence": 0.8,
                "needs_review_reasons": [],
                "_openai": {"model": "gpt-5.4-mini", "used_pdf_file": False},
            }

    monkeypatch.setattr("app.services.concordance.get_ai_service", lambda: FakeAiService())

    Session = make_session()
    with Session() as db:
        document = Document(
            title="Partial No-op",
            original_filename="partial-noop.pdf",
            checksum_sha256="7" * 64,
            processing_status="ready",
            authors=[{"family": "Researcher"}],
            publication_year=2025,
            rich_summary="Already current summary.",
            search_text="Document text.",
            page_count=4,
        )
        db.add(document)
        db.flush()
        for task_key, model in [(MODEL_METADATA, "gpt-5.5"), (MODEL_SUMMARY, "gpt-5.4")]:
            db.add(
                OpenAIUsageRecord(
                    document_id=document.id,
                    source="import",
                    capability_key="summary_topics",
                    task_key=task_key,
                    operation=f"medusa_{task_key}",
                    endpoint="responses",
                    model=model,
                    status="success",
                )
            )
        db.commit()
        estimate = estimate_concordance_run(
            db,
            scope_type="documents",
            scope_data={"document_ids": [document.id]},
            capability_keys=["summary_topics"],
        )
        run = ConcordanceRun(scope_type="documents", scope_data={"document_ids": [document.id]}, capability_keys=["summary_topics"], total_jobs=1)
        db.add(run)
        db.flush()
        job = ConcordanceJob(
            run_id=run.id,
            document_id=document.id,
            capability_key="summary_topics",
            target_version=8,
        )
        db.add(job)
        db.commit()

        ConcordanceProcessor().process_job(db, job)

        planned = estimate["items"][0]
        assert estimate["planned_jobs"] == 1
        assert [step["task_key"] for step in planned["cost_steps"]] == [MODEL_KEYWORDS_TOPICS]
        assert calls == ["tags"]
        assert document.metadata_evidence["concordance_ai"]["skipped_fields"] == ["metadata", "rich_summary"]
