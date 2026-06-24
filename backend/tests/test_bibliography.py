from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_medusa_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")


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
        "Smith, A. (2024). A careful paper. *Journal of Tests*, 12(2), 1-9.\n"
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


def test_extract_document_bibliography_folds_blank_bullet_continuation():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Numbered References Paper",
        original_filename="numbered-references.pdf",
        checksum_sha256="d" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=8,
            normalized_text=(
                "References\n"
                "[9] P. Barrett and P. Rolland, \"The meta-analytic correlation between two Big Five factors: "
                "Something is not quite right in the woodshed,\"\n\n"
                "- Retrieved on 1/12/2012 from http://www.pbarrett.net/stratpapers/metacorr.pdf.\n\n"
                "[10] D.M. Cappelli, A. Moore, and R. Trzeciak, The CERT Guide to Insider Threats: "
                "How to Prevent, Detect, and Respond to Information Technology Crimes (Theft, Sabotage, Fraud), "
                "SEI Series in Software Engineering. Upper Saddle River, NJ: Pearson Education, Inc, 2012."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"] == (
        "P. Barrett and P. Rolland, \"The meta-analytic correlation between two Big Five factors: "
        "Something is not quite right in the woodshed,\" Retrieved on 1/12/2012 from "
        "http://www.pbarrett.net/stratpapers/metacorr.pdf.\n"
        "D.M. Cappelli, A. Moore, and R. Trzeciak, The CERT Guide to Insider Threats: "
        "How to Prevent, Detect, and Respond to Information Technology Crimes (Theft, Sabotage, Fraud), "
        "SEI Series in Software Engineering. Upper Saddle River, NJ: Pearson Education, Inc, 2012."
    )
    assert not result["bibliography"].startswith("[9]")
    assert "\n-" not in result["bibliography"]
    assert result["evidence"]["entry_count_estimate"] == 2
