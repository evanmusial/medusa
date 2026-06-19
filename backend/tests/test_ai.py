import json
from types import SimpleNamespace


def test_ai_service_fallback_includes_reviewable_citation_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService

    get_settings.cache_clear()
    metadata = AiService().extract_metadata("sample-paper.pdf", "Example text.")

    assert metadata["apa_citation"] is None
    assert "OpenAI metadata extraction is not configured." in metadata["citation_warnings"]
    assert metadata["needs_review_reasons"]


def test_ai_page_text_normalization_falls_back_without_openai(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService

    get_settings.cache_clear()
    result = AiService().normalize_page_text("paper.pdf", 1, "The paper de-\nscribes a method .")

    assert result["source"] == "local"
    assert result["normalized_text"] == "The paper describes a method."


def test_ai_service_pdf_file_size_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_OPENAI_PDF_FILE_MAX_MB", "1")

    from app.config import get_settings
    from app.services.ai import AiService

    get_settings.cache_clear()
    service = AiService()

    assert service._should_send_pdf_file(b"x" * 1024) is True
    assert service._should_send_pdf_file(b"x" * (2 * 1024 * 1024)) is False


def test_ai_metadata_extraction_uses_task_specific_models(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService
    from app.services.analysis_models import MODEL_APA_CITATION, MODEL_KEYWORDS_TOPICS, MODEL_METADATA, MODEL_SUMMARY

    class FakeResponses:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def create(self, *, model, input, text, timeout):
            del input, timeout
            schema_name = text["format"]["name"]
            self.calls.append((schema_name, model))
            payloads = {
                "medusa_document_metadata": {
                    "title": "Paper",
                    "subtitle": None,
                    "authors": [],
                    "universities": [],
                    "publication_year": 2026,
                    "journal": None,
                    "publisher": None,
                    "doi": None,
                    "abstract": None,
                    "confidence": 0.9,
                    "needs_review_reasons": [],
                },
                "medusa_document_summary": {
                    "rich_summary": "Summary",
                    "confidence": 0.8,
                    "needs_review_reasons": [],
                },
                "medusa_apa_citation_candidate": {
                    "apa_citation": "Paper. (2026).",
                    "citation_warnings": [],
                    "confidence": 0.7,
                    "needs_review_reasons": [],
                },
                "medusa_keywords_topics": {
                    "topics": ["topic"],
                    "keywords": ["keyword"],
                    "confidence": 0.85,
                    "needs_review_reasons": [],
                },
            }
            return SimpleNamespace(output_text=json.dumps(payloads[schema_name]))

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)

    metadata = service.extract_metadata(
        "paper.pdf",
        "Extracted text",
        pdf_bytes=b"%PDF-1.4",
        models={
            MODEL_METADATA: "gpt-5.4-mini",
            MODEL_SUMMARY: "gpt-5.5",
            MODEL_APA_CITATION: "gpt-5.5-pro",
            MODEL_KEYWORDS_TOPICS: "gpt-5-nano",
        },
    )

    assert metadata["title"] == "Paper"
    assert metadata["rich_summary"] == "Summary"
    assert metadata["apa_citation"] == "Paper. (2026)."
    assert metadata["topics"] == ["topic"]
    assert metadata["_openai"]["models"][MODEL_METADATA] == "gpt-5.4-mini"
    assert ("medusa_document_metadata", "gpt-5.4-mini") in responses.calls
    assert ("medusa_apa_citation_candidate", "gpt-5.5-pro") in responses.calls
