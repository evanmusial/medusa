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
    from app.services.ai import strip_standalone_summary_heading, strip_summary_schema_trailer

    assert strip_standalone_summary_heading("Summary\n\nThis paper studies access control.") == (
        "The analysis studies access control."
    )
    assert strip_standalone_summary_heading("## Overview:\n- Finding one\n- Finding two") == "- Finding one\n- Finding two"
    assert strip_standalone_summary_heading("Summary statistics are central to the method.") == (
        "Summary statistics are central to the method."
    )
    leaked_schema_fields = """This paper evaluates a document parsing method.

confidence: 0.77 needs_review_reasons:

Structural equations are partially corrupted in the extracted text.
Figures are cited, but their visual content is unavailable."""
    assert strip_standalone_summary_heading(leaked_schema_fields) == (
        "The analysis evaluates a document parsing method."
    )
    assert strip_summary_schema_trailer(leaked_schema_fields) == "This paper evaluates a document parsing method."
    assert strip_standalone_summary_heading(
        "This paper reports confidence intervals as part of the method."
    ) == "The analysis reports confidence intervals as part of the method."
    assert strip_standalone_summary_heading(
        "In this article by Jane Smith, the argument links institutional trust to turnout."
    ) == "The argument links institutional trust to turnout."
    assert strip_standalone_summary_heading(
        "This 2013 chapter of the book Example Volume examines how audit culture changes fieldwork."
    ) == "The analysis examines how audit culture changes fieldwork."


def test_summary_prompts_default_to_plain_technical_paragraphs():
    from app.services.ai import ACCESSORY_SUMMARY_PROMPT, CORE_DOCUMENT_INTELLIGENCE_PROMPT, DOCUMENT_SUMMARY_PROMPT

    for prompt in [DOCUMENT_SUMMARY_PROMPT, CORE_DOCUMENT_INTELLIGENCE_PROMPT, ACCESSORY_SUMMARY_PROMPT]:
        normalized_prompt = prompt.lower()
        assert "few technical, on-topic plain-text paragraphs" in prompt
        assert "Use complete sentences throughout" in prompt
        assert "graduate academic level" in prompt
        assert "master's-degree reader" in prompt
        assert "Put key findings and concrete facts early" in prompt
        assert "Avoid starting sentences with prepositions" in prompt
        assert "Do not begin with Summary, Overview" in prompt
        assert "a single-word opening" in prompt
        assert "Open with the document's substantive claim, problem, method, finding, or conceptual contribution" in prompt
        assert "Do not spend the opening naming authors, publication year, document type" in prompt
        assert "Metadata already stores that context" in prompt
        assert "original ideas or concepts introduced" in prompt
        assert "interesting research questions raised" in prompt
        assert "surprising or counterintuitive results" in prompt
        assert "document's academic context" in prompt
        assert "Toward the end, state the main takeaways" in prompt
        assert "related topics worth pursuing for continued reading" in prompt
        assert "Do not use bold, italics, bullet points" in prompt
        assert "em dashes" in prompt
        assert "curly or fancy quotes" in prompt
        assert "Return confidence and needs_review_reasons only through the structured response fields" in prompt
        assert "metadata trailers inside the summary body" in prompt
        assert "unless the user explicitly requests another format" in normalized_prompt
        assert "labeled bullets" not in prompt


def test_bibliography_cleanup_alphabetizes_model_output(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import BIBLIOGRAPHY_CLEANUP_PROMPT, AiService

    class FakeResponses:
        def __init__(self):
            self.system_prompt = ""
            self.user_text = ""

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del model, text, timeout, prompt_cache_key, prompt_cache_retention
            self.system_prompt = input[0]["content"]
            self.user_text = input[1]["content"][0]["text"]
            return SimpleNamespace(
                id="resp_bibliography_cleanup",
                output_text=json.dumps(
                    {
                        "references": [
                            "Zed, Z. (2024). *Zeta systems*. Journal.",
                            "[Ariani 2013] Ariani, D. W. (2013). *Employee engagement*. Journal.",
                            "[2] Adams, A. (2022). *Alpha methods*. Press.",
                            "Brown, B. (2023). *Beta analysis*. Journal.",
                        ]
                    }
                    | {"confidence": 0.91, "notes": []}
                ),
                usage=SimpleNamespace(input_tokens=20, output_tokens=15, total_tokens=35),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)

    result = service.normalize_bibliography(
        "references.pdf",
        "Zed, Z. (2024). Zeta systems.\nAdams, A. (2022). Alpha methods.",
        model="gpt-5.4-nano",
    )

    assert "Sort the returned references in APA reference-list order" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert "selected reference/source style" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert "Surname, Initials" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert "first author surname" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert "Do not sort by author initials" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert "bracketed author/year source keys" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert result["bibliography"].splitlines() == [
        "Adams, A. (2022). *Alpha methods*. Press.",
        "Ariani, D. W. (2013). *Employee engagement*. Journal.",
        "Brown, B. (2023). *Beta analysis*. Journal.",
        "Zed, Z. (2024). *Zeta systems*. Journal.",
    ]
    assert "Selected reference/source style: APA 7 (apa_7)" in responses.user_text
    assert responses.system_prompt == BIBLIOGRAPHY_CLEANUP_PROMPT


def test_bibliography_author_loss_repair_includes_missing_author_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import BIBLIOGRAPHY_AUTHOR_REPAIR_PROMPT, AiService

    class FakeResponses:
        def __init__(self):
            self.system_prompt = ""
            self.user_text = ""

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del model, text, timeout, prompt_cache_key, prompt_cache_retention
            self.system_prompt = input[0]["content"]
            self.user_text = input[1]["content"][0]["text"]
            return SimpleNamespace(
                id="resp_bibliography_author_repair",
                output_text=json.dumps(
                    {
                        "references": [
                            "Anderson, R. (1993). Why cryptosystems fail.",
                            "Neumann, P. G., & Parker, D. (1989). A summary of computer misuse techniques.",
                        ],
                        "confidence": 0.91,
                        "notes": ["Restored the missing coauthor from the extracted source."],
                    }
                ),
                usage=SimpleNamespace(input_tokens=28, output_tokens=18, total_tokens=46),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)

    result = service.repair_bibliography_cleanup(
        "references.pdf",
        "Neumann, P. G., and Parker, D. (1989). A Summary of Computer Misuse Techniques.\n"
        "Anderson, R. (1993). Why cryptosystems fail.",
        rejected_bibliography=(
            "Anderson, R. (1993). Why cryptosystems fail.\n"
            "Neumann, P. G. (1989). A Summary of Computer Misuse Techniques."
        ),
        missing_author_sets=[["Neumann", "Parker"]],
        model="gpt-5.4-nano",
    )

    assert "Repair mode" in BIBLIOGRAPHY_AUTHOR_REPAIR_PROMPT
    assert "dropped visible author names" in BIBLIOGRAPHY_AUTHOR_REPAIR_PROMPT
    assert "Visible author token groups" in responses.user_text
    assert "- Neumann, Parker" in responses.user_text
    assert "Rejected cleanup output for formatting context only" in responses.user_text
    assert responses.system_prompt == BIBLIOGRAPHY_AUTHOR_REPAIR_PROMPT
    assert "Parker, D." in result["bibliography"]


def test_bibliography_sort_fallback_uses_surname_for_initials_first_entries():
    from app.services.ai import sorted_bibliography_entries

    entries = [
        "S. Jakobwitz, & V. Egan. (2006). The dark triad and normal personality traits.",
        "T. Buchanan, J. A. Johnson, & L. R. Goldberg. (2005). Implementing a five-factor inventory.",
        "W. H. Hendrix, N. K. Ovalle, & R. G. Troxler. (1985). Behavioral consequences of stress.",
        "A. Fülöp, L. Kovács, T. Kurics, and E. Windhager-Pokol. (2016). Balabit mouse dynamics challenge data set.",
        "(2001). The famous cases and criminals archive.",
        "S. S. Russell, M. J. Cullen, & M. J. Bosshardt. (2009). Cyber behavior and personnel security.",
        "S. R. Band, D. M. Cappelli, & L. F. Fischer. (1995). A typology of deviant workplace behaviors.",
        "Z.-K. Zhang, M. C. Y. Cho, C.-W. Wang, C.-W. Hsu, C.-K. Chen, and S. Shieh. (2014). IoT security.",
    ]

    assert sorted_bibliography_entries(entries) == [
        "S. R. Band, D. M. Cappelli, & L. F. Fischer. (1995). A typology of deviant workplace behaviors.",
        "T. Buchanan, J. A. Johnson, & L. R. Goldberg. (2005). Implementing a five-factor inventory.",
        "(2001). The famous cases and criminals archive.",
        "A. Fülöp, L. Kovács, T. Kurics, and E. Windhager-Pokol. (2016). Balabit mouse dynamics challenge data set.",
        "W. H. Hendrix, N. K. Ovalle, & R. G. Troxler. (1985). Behavioral consequences of stress.",
        "S. Jakobwitz, & V. Egan. (2006). The dark triad and normal personality traits.",
        "S. S. Russell, M. J. Cullen, & M. J. Bosshardt. (2009). Cyber behavior and personnel security.",
        "Z.-K. Zhang, M. C. Y. Cho, C.-W. Wang, C.-W. Hsu, C.-K. Chen, and S. Shieh. (2014). IoT security.",
    ]


def test_bibliography_sort_fallback_ignores_spacing_artifacts_for_group_authors():
    from app.services.ai import sorted_bibliography_entries

    entries = [
        "B News. (2014). Edward Snowden: Leaks that exposed US spy programme.",
        "D. J. Barret, Mediawiki. Sebastopol, CA, USA: O'Reilly Media 2008.",
        "V C 2008. (2008). Mc3-Cell Phone Calls.",
        "Y. Vardi, M. Theusan, A. F. Karr, W.-H. Ju, W. DuMouchel, and M. Schonlau. (2001). Computer intrusion.",
        "ZDNet. (2019). Alexa and Google Home devices leveraged to phish.",
    ]

    assert sorted_bibliography_entries(entries) == [
        "D. J. Barret, Mediawiki. Sebastopol, CA, USA: O'Reilly Media 2008.",
        "B News. (2014). Edward Snowden: Leaks that exposed US spy programme.",
        "Y. Vardi, M. Theusan, A. F. Karr, W.-H. Ju, W. DuMouchel, and M. Schonlau. (2001). Computer intrusion.",
        "V C 2008. (2008). Mc3-Cell Phone Calls.",
        "ZDNet. (2019). Alexa and Google Home devices leveraged to phish.",
    ]


def test_bibliography_cleanup_strips_missing_page_placeholders():
    from app.services.ai import BIBLIOGRAPHY_CLEANUP_PROMPT, normalize_model_bibliography_entry

    assert "Omit missing fields instead of writing placeholders" in BIBLIOGRAPHY_CLEANUP_PROMPT
    assert (
        normalize_model_bibliography_entry("[Ariani 2013] Ariani, D. W. (2013). Employee engagement. Journal.")
        == "Ariani, D. W. (2013). Employee engagement. Journal."
    )
    assert normalize_model_bibliography_entry(
        "Anderson, R. (1993). Why cryptosystems fail. In Proceedings of the ACM conference (pp. n/a). ACM Press."
    ) == "Anderson, R. (1993). Why cryptosystems fail. In Proceedings of the ACM conference. ACM Press."
    assert normalize_model_bibliography_entry(
        "Anderson, R. (1993). Why cryptosystems fail. In Proceedings of the ACM conference (pp.?). ACM Press."
    ) == "Anderson, R. (1993). Why cryptosystems fail. In Proceedings of the ACM conference. ACM Press."
    assert normalize_model_bibliography_entry(
        "Anderson, R. (1993). Why cryptosystems fail. In Proceedings of the ACM conference (pp. 1-?). ACM Press."
    ) == "Anderson, R. (1993). Why cryptosystems fail. In Proceedings of the ACM conference. ACM Press."


def test_formula_capture_returns_latex_entries(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import FORMULA_CAPTURE_PROMPT, AiService
    from app.services.analysis_models import MODEL_FORMULA_CAPTURE
    from app.services.openai_usage import OpenAIUsageContext

    class FakeResponses:
        def __init__(self):
            self.calls = []
            self.system_prompt = ""

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del text, timeout, prompt_cache_retention
            self.calls.append((model, prompt_cache_key, input[1]["content"][0]["text"]))
            self.system_prompt = input[0]["content"]
            return SimpleNamespace(
                id="resp_formula_capture",
                output_text=json.dumps(
                    {
                        "formulas": [
                            {
                                "page_number": 2,
                                "latex": "$$E = mc^2$$",
                                "display": True,
                                "label": "Equation 1",
                                "surrounding_text": "Mass-energy relation.",
                                "confidence": 0.94,
                            }
                        ],
                        "confidence": 0.94,
                        "notes": [],
                    }
                ),
                usage=SimpleNamespace(input_tokens=20, output_tokens=15, total_tokens=35),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)

    result = service.capture_formulas(
        "physics.pdf",
        "[Page 2]\nThe paper states E = mc^2.",
        model="gpt-5.4",
        usage_context=OpenAIUsageContext(document_id="doc-1", source="test"),
        prompt_cache_key="medusa-doc:abc123:formulas",
    )

    assert "LaTeX/MathJax-compatible" in FORMULA_CAPTURE_PROMPT
    assert result["formulas"][0]["latex"] == "E = mc^2"
    assert result["formulas"][0]["page_number"] == 2
    assert result["_openai"]["model"] == "gpt-5.4"
    assert responses.calls[0][0] == "gpt-5.4"
    assert responses.calls[0][1] == "medusa-doc:abc123:formulas"
    assert MODEL_FORMULA_CAPTURE == "formula_capture"


def test_ai_prompt_cache_key_uses_api_safe_length_for_document_checksums(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import AiService

    get_settings.cache_clear()
    service = AiService()

    short_key = service._normalize_prompt_cache_key("medusa-doc:abc123")
    long_key = service._normalize_prompt_cache_key(f"medusa-doc:{'a' * 64}:apa")

    assert short_key == "medusa-doc:abc123"
    assert long_key is not None
    assert long_key.startswith("medusa:")
    assert len(long_key) == 64
    assert long_key == service._normalize_prompt_cache_key(f"medusa-doc:{'a' * 64}:apa")


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
            self.prompts: dict[str, str] = {}

        def create(self, *, model, input, text, timeout, prompt_cache_key=None, prompt_cache_retention=None):
            del timeout
            schema_name = text["format"]["name"]
            has_file = any(item.get("type") == "input_file" for item in input[1]["content"])
            self.calls.append((schema_name, model, prompt_cache_key, prompt_cache_retention, has_file))
            self.prompts[schema_name] = input[0]["content"]
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
        existing_tags=["access control", "insider threat"],
        usage_context=OpenAIUsageContext(document_id="doc-1", source="test", recorder=usage_records.append),
        prompt_cache_key="medusa-doc:abc123",
    )

    assert metadata["title"] == "Paper"
    assert metadata["authors"][0]["email"] == "ada@example.edu"
    assert metadata["rich_summary"] == "The analysis evaluates a research method."
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
    assert "Existing Medusa tags manifest" in responses.prompts["medusa_keywords_topics"]
    assert '"access control"' in responses.prompts["medusa_keywords_topics"]
    assert "scan the existing manifest for every candidate concept" in responses.prompts["medusa_keywords_topics"]
    assert "Add a new concise tag only" in responses.prompts["medusa_keywords_topics"]
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


def test_ai_responses_cache_retention_is_omitted_when_sdk_lacks_parameter(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MEDUSA_OPENAI_PROMPT_CACHE_RETENTION", "24h")

    from app.config import get_settings
    from app.services.ai import METADATA_IDENTITY_SCHEMA, METADATA_EXTRACTION_PROMPT, AiService

    class FakeResponses:
        def __init__(self):
            self.cache_key = None

        def create(self, *, model, input, text, timeout, prompt_cache_key=None):
            del model, input, text, timeout
            self.cache_key = prompt_cache_key
            return SimpleNamespace(
                id="resp_metadata",
                output_text=json.dumps(
                    {
                        "title": "Paper",
                        "subtitle": None,
                        "authors": [],
                        "universities": [],
                        "publication_year": None,
                        "journal": None,
                        "publisher": None,
                        "doi": None,
                        "abstract": None,
                        "confidence": 0.8,
                        "needs_review_reasons": [],
                    }
                ),
                usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12),
            )

    get_settings.cache_clear()
    service = AiService()
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)

    result = service._responses_json(
        model="gpt-5.5",
        schema_name="medusa_document_metadata",
        schema=METADATA_IDENTITY_SCHEMA,
        prompt=METADATA_EXTRACTION_PROMPT,
        input_content=[{"type": "input_text", "text": "Extracted text"}],
        timeout=12,
        prompt_cache_key="medusa-doc:abc123",
    )

    assert result["title"] == "Paper"
    assert responses.cache_key == "medusa-doc:abc123"


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
    assert metadata["rich_summary"] == "The analysis evaluates a legacy combined route."
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


def test_ai_service_routes_gemini_json_calls_with_service_account(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    from app.config import get_settings
    from app.services.ai import SUMMARY_SCHEMA, AiService
    from app.services.analysis_models import MODEL_SUMMARY
    from app.services.openai_usage import OpenAIUsageContext

    class FakeCredentials:
        project_id = "managed-project"

    monkeypatch.setattr("app.services.ai.get_active_google_project_id", lambda: "managed-project")
    monkeypatch.setattr("app.services.ai.get_active_google_service_account_path", lambda: "/tmp/service-account.json")
    monkeypatch.setattr("app.services.ai.load_service_account_credentials", lambda _: FakeCredentials())

    get_settings.cache_clear()
    service = AiService()
    assert service.gemini_api_key is None
    assert service.google_credentials is not None
    assert service._can_call_text_model("gemini-2.5-flash") is True

    def fake_generate_content(*, model, schema, prompt, input_text, timeout):
        assert model == "gemini-2.5-flash"
        assert schema == SUMMARY_SCHEMA
        assert "Summarize" in prompt
        assert "Extracted text" in input_text
        assert timeout == 12
        return {
            "responseId": "vertex-response-1",
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "rich_summary": "This paper uses managed Vertex credentials.",
                                        "confidence": 0.86,
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

    assert result["rich_summary"] == "This paper uses managed Vertex credentials."
    assert usage_records[0]["provider"] == "google"
    assert usage_records[0]["endpoint"] == "generateContent"
