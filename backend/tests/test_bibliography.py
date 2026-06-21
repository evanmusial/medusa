from pathlib import Path


def test_extract_document_bibliography_from_page_text():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="References Paper",
        original_filename="references.pdf",
        checksum_sha256="b" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=1,
            normalized_text=(
                "The paper body ends here.\n\n"
                "References\n"
                "Smith, A. (2024). A careful paper. *Journal of Tests*, 12(2), 1-9.\n"
                "Jones, B. (2023). Another source. Press."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"] == (
        "Smith, A. (2024). A careful paper. *Journal of Tests*, 12(2), 1-9.\n\n"
        "Jones, B. (2023). Another source. Press."
    )
    assert result["evidence"]["source"] == "page_text"
    assert result["evidence"]["entry_count_estimate"] == 2


def test_extract_document_bibliography_prefers_pdf_span_markdown(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Formatted References Paper",
        original_filename="references.pdf",
        checksum_sha256="c" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (3, "References"),
            (3, "Smith, A. (2024). *Journal of Tests*, 12(2), 1-9."),
            (3, "Jones, B. (2023). *Another Journal*, 2, 3-4."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))

    assert "*Journal of Tests*" in result["bibliography"]
    assert "*Another Journal*" in result["bibliography"]
    assert result["evidence"]["source"] == "pdf_span_layout"
    assert result["evidence"]["formatting"] == "markdown_italics_from_pdf_spans"
