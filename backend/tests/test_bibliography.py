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


def test_extract_document_bibliography_does_not_stop_on_wrapped_index_word():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Wrapped Index References Paper",
        original_filename="wrapped-index-references.pdf",
        checksum_sha256="e" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=17,
            normalized_text=(
                "References\n"
                "[1] D. Ding, Q.-L. Han, Y. Xiang, X. Ge, and X.-M. Zhang, \"A survey on security "
                "control and attack detection for industrial cyber-physical systems,\" Neurocomputing, "
                "vol. 275, pp. 1674-1683, 2018.\n"
                "[2] Clearswift, \"Clearswift insider\n"
                "threat\n"
                "index\n"
                "(citi),\" http:\n"
                "//pages.clearswift.com/insider-threat-index.pdf, 2015, (Accessed on 09/06/2016).\n"
                "[3] D. L. Costa, M. J. Albrethsen, M. L. Collins, S. J. Perl, G. J. Silowash, "
                "and D. L. Spooner, \"An insider threat indicator ontology,\" TECHNICAL REPORT "
                "CMU/SEI, 2016."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        (
            'D. Ding, Q.-L. Han, Y. Xiang, X. Ge, and X.-M. Zhang, "A survey on security control '
            'and attack detection for industrial cyber-physical systems," Neurocomputing, vol. 275, '
            "pp. 1674-1683, 2018."
        ),
        (
            'Clearswift, "Clearswift insider threat index (citi)," http: '
            "//pages.clearswift.com/insider-threat-index.pdf, 2015, (Accessed on 09/06/2016)."
        ),
        (
            'D. L. Costa, M. J. Albrethsen, M. L. Collins, S. J. Perl, G. J. Silowash, and D. L. '
            'Spooner, "An insider threat indicator ontology," TECHNICAL REPORT CMU/SEI, 2016.'
        ),
    ]
    assert result["evidence"]["entry_count_estimate"] == 3


def test_extract_document_bibliography_ignores_page_furniture_and_author_bios(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Multi Page References Paper",
        original_filename="multi-page-references.pdf",
        checksum_sha256="f" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "multi-page-references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (17, "REFERENCES"),
            (17, "[1] D. Ding, Q.-L. Han, Y. Xiang, X. Ge, and X.-M. Zhang, \"A survey"),
            (17, "on security control and attack detection for industrial cyber-physical"),
            (17, "systems,\" Neurocomputing, vol. 275, pp. 1674-1683, 2018."),
            (
                18,
                "1553-877X (c) 2018 IEEE. Personal use is permitted, but republication/redistribution requires permission.",
            ),
            (18, "This article has been accepted for publication in a future issue of this journal."),
            (18, "Communications Surveys & Tutorials"),
            (18, "IEEE COMMUNICATIONS SURVEY & TUTORIALS"),
            (18, "18"),
            (18, "[2] Clearswift, \"Clearswift insider threat index,\" http://example.test, 2015."),
            (20, "[145] Distributed Management Task Force, \"Cim | dmtf,\" http://www.dmtf.org/standards/cim,"),
            (20, "(Accessed on 11/11/2017)."),
            (20, "Liu Liu is currently working toward her Ph.D. degree in Software Engineering."),
            (21, "Olivier de Vel obtained a PhD in Electronic Engineering from INPG, France."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))

    assert result["bibliography"].splitlines() == [
        (
            'D. Ding, Q.-L. Han, Y. Xiang, X. Ge, and X.-M. Zhang, "A survey on security control '
            'and attack detection for industrial cyber-physical systems," Neurocomputing, vol. 275, '
            "pp. 1674-1683, 2018."
        ),
        'Clearswift, "Clearswift insider threat index," http://example.test, 2015.',
        'Distributed Management Task Force, "Cim | dmtf," http://www.dmtf.org/standards/cim, (Accessed on 11/11/2017).',
    ]
    assert "1553-877X" not in result["bibliography"]
    assert "Liu Liu" not in result["bibliography"]
    assert "Olivier de Vel" not in result["bibliography"]
    assert result["evidence"]["page_start"] == 17
    assert result["evidence"]["page_end"] == 20


def test_extract_document_bibliography_numbered_entries_ignore_author_initial_continuations():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Numbered Initial Continuation Paper",
        original_filename="numbered-initial-continuation.pdf",
        checksum_sha256="a" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=18,
            normalized_text=(
                "References\n"
                "[110] C. Rossow, C. J. Dietrich, H. Bos, L. Cavallaro, M. Van Steen,\n"
                "F. C. Freiling, and N. Pohlmann, \"Sandnet: Network traffic analysis of malicious software,\"\n"
                "in Proceedings of the First Workshop on Building Analysis Datasets and Gathering Experience Returns for Security. ACM, 2011, pp. 78-88.\n"
                "[111] J. Zhang, X. Chen, Y. Xiang, W. Zhou, and J. Wu, \"Robust network traffic classification,\"\n"
                "IEEE/ACM Transactions on Networking (TON), vol. 23, no. 4, pp. 1257-1270, 2015."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        (
            'C. Rossow, C. J. Dietrich, H. Bos, L. Cavallaro, M. Van Steen, F. C. Freiling, and '
            'N. Pohlmann, "Sandnet: Network traffic analysis of malicious software," in Proceedings '
            "of the First Workshop on Building Analysis Datasets and Gathering Experience Returns for "
            "Security. ACM, 2011, pp. 78-88."
        ),
        (
            'J. Zhang, X. Chen, Y. Xiang, W. Zhou, and J. Wu, "Robust network traffic classification," '
            "IEEE/ACM Transactions on Networking (TON), vol. 23, no. 4, pp. 1257-1270, 2015."
        ),
    ]
    assert result["evidence"]["entry_count_estimate"] == 2
