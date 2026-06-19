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


def test_normalize_obfuscated_email_variants():
    from app.services.ai import normalize_obfuscated_email

    assert normalize_obfuscated_email("someone{at}university{dot}edu") == "someone@university.edu"
    assert normalize_obfuscated_email("someone [at] University [dot] EDU") == "someone@university.edu"
    assert normalize_obfuscated_email("contact: first.last at lab dot example dot org") == "first.last@lab.example.org"


def test_ai_metadata_extraction_uses_task_specific_models(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService
    from app.services.analysis_models import MODEL_APA_CITATION, MODEL_KEYWORDS_TOPICS, MODEL_METADATA, MODEL_SUMMARY
    from app.services.openai_usage import OpenAIUsageContext

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
                    "authors": [
                        {
                            "given": "Ada",
                            "family": "Lovelace",
                            "affiliation": "Example University",
                            "email": "ada{at}Example{dot}EDU",
                        }
                    ],
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
            return SimpleNamespace(
                id=f"resp_{schema_name}",
                output_text=json.dumps(payloads[schema_name]),
                usage=SimpleNamespace(
                    input_tokens=100,
                    input_tokens_details=SimpleNamespace(cached_tokens=25),
                    output_tokens=10,
                    output_tokens_details=SimpleNamespace(reasoning_tokens=2),
                    total_tokens=110,
                ),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)
    usage_records: list[dict] = []

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
        usage_context=OpenAIUsageContext(document_id="doc-1", source="test", recorder=usage_records.append),
    )

    assert metadata["title"] == "Paper"
    assert metadata["authors"][0]["email"] == "ada@example.edu"
    assert metadata["rich_summary"] == "Summary"
    assert metadata["apa_citation"] == "Paper. (2026)."
    assert metadata["topics"] == ["topic"]
    assert metadata["_openai"]["models"][MODEL_METADATA] == "gpt-5.4-mini"
    assert ("medusa_document_metadata", "gpt-5.4-mini") in responses.calls
    assert ("medusa_apa_citation_candidate", "gpt-5.5-pro") in responses.calls
    assert {record["task_key"] for record in usage_records} == {
        MODEL_METADATA,
        MODEL_SUMMARY,
        MODEL_APA_CITATION,
        MODEL_KEYWORDS_TOPICS,
    }
    assert all(record["document_id"] == "doc-1" for record in usage_records)
    assert all(record["status"] == "success" for record in usage_records)
    assert usage_records[0]["input_tokens"] == 100
    assert usage_records[0]["cached_input_tokens"] == 25
    assert usage_records[0]["input_file_bytes"] == len(b"%PDF-1.4")


def test_ai_page_normalization_prompt_protects_graphic_assets(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT", "true")

    from app.config import get_settings
    from app.services.ai import AiService
    from app.services.openai_usage import OpenAIUsageContext

    class FakeResponses:
        def __init__(self):
            self.system_prompt = ""

        def create(self, *, model, input, text, timeout):
            del model, text, timeout
            self.system_prompt = input[0]["content"]
            return SimpleNamespace(
                id="resp_page_norm",
                output_text=json.dumps(
                    {
                        "normalized_text": "Figure 1. System diagram.\n\nThe paper describes the system.",
                        "confidence": 0.9,
                        "notes": [],
                    }
                ),
                usage={
                    "input_tokens": 40,
                    "input_tokens_details": {"cached_tokens": 10},
                    "output_tokens": 8,
                    "total_tokens": 48,
                },
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)
    usage_records: list[dict] = []

    result = service.normalize_page_text(
        "paper.pdf",
        1,
        "Figure 1. System diagram.\nThe paper describes the system.",
        usage_context=OpenAIUsageContext(document_id="doc-page", source="test", recorder=usage_records.append),
    )

    assert result["source"] == "openai"
    assert "Do not convert charts, photos, diagrams, or figure graphics into Markdown" in responses.system_prompt
    assert "standard readable format" in responses.system_prompt
    assert usage_records[0]["task_key"] == "page_text_normalization"
    assert usage_records[0]["page_number"] == 1
    assert usage_records[0]["cached_input_tokens"] == 10
