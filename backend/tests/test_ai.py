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
    assert "AI metadata extraction is not configured for the selected models." in metadata["citation_warnings"]
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


def test_strip_standalone_summary_heading():
    from app.services.ai import strip_standalone_summary_heading

    assert strip_standalone_summary_heading("Summary\n\nThis paper studies access control.") == (
        "This paper studies access control."
    )
    assert strip_standalone_summary_heading("## Overview:\n- Finding one\n- Finding two") == "- Finding one\n- Finding two"
    assert strip_standalone_summary_heading("Summary statistics are central to the method.") == (
        "Summary statistics are central to the method."
    )


def test_ai_metadata_extraction_routes_summary_and_keywords_to_cheaper_text_only_models(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService
    from app.services.analysis_models import (
        MODEL_APA_CITATION,
        MODEL_KEYWORDS_TOPICS,
        MODEL_METADATA,
        MODEL_SUMMARY,
    )
    from app.services.openai_usage import OpenAIUsageContext

    class FakeResponses:
        def __init__(self):
            self.calls: list[tuple[str, str, str | None, str | None, bool]] = []

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del timeout
            schema_name = text["format"]["name"]
            has_file = any(item.get("type") == "input_file" for item in input[1]["content"])
            self.calls.append((schema_name, model, prompt_cache_key, prompt_cache_retention, has_file))
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
                    "rich_summary": "Summary\n\nThis paper evaluates a research method.",
                    "confidence": 0.8,
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
            MODEL_METADATA: "gpt-5.5",
            MODEL_SUMMARY: "gpt-5.4",
            MODEL_APA_CITATION: "gpt-5.5",
            MODEL_KEYWORDS_TOPICS: "gpt-5.4-mini",
        },
        usage_context=OpenAIUsageContext(document_id="doc-1", source="test", recorder=usage_records.append),
        prompt_cache_key="medusa-doc:abc123",
    )

    assert metadata["title"] == "Paper"
    assert metadata["authors"][0]["email"] == "ada@example.edu"
    assert metadata["rich_summary"] == "This paper evaluates a research method."
    assert metadata["apa_citation"] is None
    assert metadata["topics"] == ["topic"]
    assert metadata["_openai"]["models"][MODEL_METADATA] == "gpt-5.5"
    assert metadata["_openai"]["models"][MODEL_SUMMARY] == "gpt-5.4"
    assert metadata["_openai"]["models"][MODEL_KEYWORDS_TOPICS] == "gpt-5.4-mini"
    assert metadata["_openai"]["combined_document_intelligence"] is False
    assert metadata["_openai"]["document_intelligence_route"] == "routed"
    assert responses.calls == [
        ("medusa_document_metadata", "gpt-5.5", "medusa-doc:abc123", "24h", True),
        ("medusa_document_summary", "gpt-5.4", "medusa-doc:abc123", "24h", False),
        ("medusa_keywords_topics", "gpt-5.4-mini", "medusa-doc:abc123", "24h", False),
    ]
    assert {record["task_key"] for record in usage_records} == {
        MODEL_METADATA,
        MODEL_SUMMARY,
        MODEL_KEYWORDS_TOPICS,
    }
    assert all(record["document_id"] == "doc-1" for record in usage_records)
    assert all(record["status"] == "success" for record in usage_records)
    assert usage_records[0]["input_tokens"] == 100
    assert usage_records[0]["cached_input_tokens"] == 25
    assert usage_records[0]["input_file_bytes"] == len(b"%PDF-1.4")
    assert all(record["input_file_bytes"] == 0 for record in usage_records[1:])


def test_ai_metadata_extraction_can_use_legacy_combined_call(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE", "true")

    from app.config import get_settings
    from app.services.ai import AiService
    from app.services.analysis_models import (
        MODEL_APA_CITATION,
        MODEL_CORE_DOCUMENT_INTELLIGENCE,
        MODEL_KEYWORDS_TOPICS,
        MODEL_METADATA,
        MODEL_SUMMARY,
    )
    from app.services.openai_usage import OpenAIUsageContext

    class FakeResponses:
        def __init__(self):
            self.calls: list[tuple[str, str, str | None]] = []

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del input, timeout, prompt_cache_retention
            schema_name = text["format"]["name"]
            self.calls.append((schema_name, model, prompt_cache_key))
            payloads = {
                "medusa_core_document_intelligence": {
                    "metadata": {
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
                    "summary": {
                        "rich_summary": "Overview\n\nThis paper evaluates a legacy combined route.",
                        "confidence": 0.8,
                        "needs_review_reasons": [],
                    },
                    "apa_citation": {
                        "apa_citation": "Paper. (2026).",
                        "apa_in_text_citation": "(Paper, 2026)",
                        "citation_warnings": [],
                        "confidence": 0.7,
                        "needs_review_reasons": [],
                    },
                    "keywords_topics": {
                        "topics": ["topic"],
                        "keywords": ["keyword"],
                        "confidence": 0.85,
                        "needs_review_reasons": [],
                    },
                }
            }
            return SimpleNamespace(
                id=f"resp_{schema_name}",
                output_text=json.dumps(payloads[schema_name]),
                usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)
    usage_records: list[dict] = []

    metadata = service.extract_metadata(
        "paper.pdf",
        "Extracted text",
        models={
            MODEL_METADATA: "gpt-5.4-mini",
            MODEL_SUMMARY: "gpt-5.5",
            MODEL_APA_CITATION: "gpt-5.5-pro",
            MODEL_KEYWORDS_TOPICS: "gpt-5-nano",
        },
        usage_context=OpenAIUsageContext(document_id="doc-1", source="test", recorder=usage_records.append),
        prompt_cache_key="medusa-doc:abc123",
    )

    assert metadata["_openai"]["combined_document_intelligence"] is True
    assert metadata["_openai"]["document_intelligence_route"] == "combined"
    assert metadata["rich_summary"] == "This paper evaluates a legacy combined route."
    assert metadata["apa_citation"] == "Paper. (2026)."
    assert responses.calls == [("medusa_core_document_intelligence", "gpt-5.4-mini", "medusa-doc:abc123")]
    assert {record["task_key"] for record in usage_records} == {MODEL_CORE_DOCUMENT_INTELLIGENCE}


def test_ai_apa_citation_candidate_uses_compact_text_only_context(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService
    from app.services.analysis_models import MODEL_APA_CITATION
    from app.services.openai_usage import OpenAIUsageContext

    class FakeResponses:
        def __init__(self):
            self.calls: list[tuple[str, str, bool]] = []
            self.user_text = ""

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del timeout, prompt_cache_key, prompt_cache_retention
            schema_name = text["format"]["name"]
            has_file = any(item.get("type") == "input_file" for item in input[1]["content"])
            self.user_text = input[1]["content"][0]["text"]
            self.calls.append((schema_name, model, has_file))
            return SimpleNamespace(
                id=f"resp_{schema_name}",
                output_text=json.dumps(
                    {
                        "apa_citation": "Lovelace, A. (1843). Notes.",
                        "apa_in_text_citation": "(Lovelace, 1843)",
                        "citation_warnings": [],
                        "confidence": 0.82,
                        "needs_review_reasons": [],
                    }
                ),
                usage=SimpleNamespace(input_tokens=20, output_tokens=5, total_tokens=25),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)
    usage_records: list[dict] = []

    result = service.generate_apa_citation_candidate(
        "paper.pdf",
        "Title page paragraph.\n\nDOI: 10.1000/example\n\nReferences\nExample reference.",
        {"title": "Notes", "authors": [{"given": "Ada", "family": "Lovelace"}], "publication_year": 1843},
        model="gpt-5.5",
        usage_context=OpenAIUsageContext(document_id="doc-1", source="test", recorder=usage_records.append),
        prompt_cache_key="medusa-doc:abc123:apa",
    )

    assert result["apa_citation"] == "Lovelace, A. (1843). Notes."
    assert result["apa_in_text_citation"] == "(Lovelace, 1843)"
    assert responses.calls == [("medusa_apa_citation_candidate", "gpt-5.5", False)]
    assert "Known citation metadata" in responses.user_text
    assert "Document excerpts" in responses.user_text
    assert {record["task_key"] for record in usage_records} == {MODEL_APA_CITATION}
    assert usage_records[0]["input_file_bytes"] == 0


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

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del model, text, timeout, prompt_cache_key, prompt_cache_retention
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


def test_ai_service_routes_gemini_json_calls_and_records_google_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    from app.config import get_settings
    from app.services.ai import SUMMARY_SCHEMA, AiService
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.openai_usage import OpenAIUsageContext

    get_settings.cache_clear()
    service = AiService()

    def fake_generate_content(*, model, schema, prompt, input_text, timeout):
        assert model == "gemini-2.5-flash"
        assert schema == SUMMARY_SCHEMA
        assert "Summarize" in prompt
        assert "Extracted text" in input_text
        assert timeout == 12
        return {
            "responseId": "gemini-response-1",
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "rich_summary": "This paper studies model routing.",
                                        "confidence": 0.84,
                                        "needs_review_reasons": [],
                                    }
                                )
                            }
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 30,
                "candidatesTokenCount": 9,
                "totalTokenCount": 39,
            },
        }

    service._gemini_generate_content = fake_generate_content  # type: ignore[method-assign]
    usage_records: list[dict] = []

    result = service._responses_json(
        model="gemini-2.5-flash",
        schema_name="medusa_document_summary",
        schema=SUMMARY_SCHEMA,
        prompt="Summarize this document.",
        input_content=[{"type": "input_text", "text": "Extracted text"}],
        timeout=12,
        usage_context=OpenAIUsageContext(document_id="doc-google", source="test", recorder=usage_records.append),
        task_key=MODEL_SUMMARY,
        input_text_characters=14,
    )

    assert result["rich_summary"] == "This paper studies model routing."
    assert usage_records[0]["provider"] == "google"
    assert usage_records[0]["endpoint"] == "generateContent"
    assert usage_records[0]["model"] == "gemini-2.5-flash"
    assert usage_records[0]["input_tokens"] == 30
    assert usage_records[0]["output_tokens"] == 9
