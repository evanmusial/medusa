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
