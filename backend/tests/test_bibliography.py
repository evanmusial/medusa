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


def test_extract_document_bibliography_handles_numbered_uppercase_section_heading():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Numbered Uppercase References Paper",
        original_filename="numbered-uppercase-references.pdf",
        checksum_sha256="1" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=3,
            normalized_text=(
                "The paper body ends here.\n"
                "IV. ACKNOWLEDGEMENT\n"
                "Authors thank the supporting staff.\n"
                "V. REFERENCES [1] John McHugh, Alan Christie, Julia Allen,: The Role of Intrusion "
                "Detection Systems, CERT coordination center, IEEE Software, Sep-Oct 2000, "
                "0740-7459, pg 42-51. [2] Julia Allen, Alan Christie, William Fithen, "
                "John McHugh, Jed Pickel, Ed Stoner,: State of the practice of Intrusion Detection "
                "Technologies, Carnegie Melon Software Engineering Institute, Pittsburgh, PA 15213-3890. "
                "[3] J.P. Anderson, Computer Security Threat Monitoring and Surveillance, tech. report, "
                "James P. Anderson Co., Fort Washington, Pa.1980."
            ),
        )
    )
    document.pages.append(
        DocumentPage(
            page_number=4,
            normalized_text=(
                "[4] D.E. Denning, \"An Intrusion Detection Model,\" IEEE Trans. Software Eng., "
                "Vol. SE-13, No. 2, Feb. 1987, pp. 222-232. [5] J. Allen et al., State of the "
                "Practice of Intrusion Detection Technologies, Tech Report CMU/SEI-99-TR-028, "
                "Carnegie Mellon Univ., Software Engineering Inst., Pittsburgh, 2000."
            ),
        )
    )
    document.pages.append(
        DocumentPage(
            page_number=5,
            normalized_text=(
                "*[6]* Snort---The open source intrusion detection system. (2002). Retrieved "
                "February 13, 2003, from http://www.snort.org."
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["source"] == "page_text"
    assert result["evidence"]["page_start"] == 3
    assert result["evidence"]["page_end"] == 5
    assert result["evidence"]["entry_count_estimate"] == 6
    assert len(entries) == 6
    assert entries[0].startswith("John McHugh")
    assert entries[1].startswith("Julia Allen")
    assert entries[-1].startswith("Snort---The open source intrusion detection system")
    assert not any(entry.startswith("[") or entry.startswith("*[") for entry in entries)
    assert "ACKNOWLEDGEMENT" not in result["bibliography"]


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


def test_extract_document_bibliography_uses_visual_ocr_tail_pages(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Graphical References Paper",
        original_filename="graphical-references.pdf",
        checksum_sha256="4" * 64,
    )
    document.pages.append(DocumentPage(page_number=6, normalized_text="2068\nRunning header only."))
    document.pages.append(DocumentPage(page_number=7, normalized_text="2069\nRunning header only."))
    pdf_path = tmp_path / "references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(bibliography_service, "_formatted_bibliography_from_pdf", lambda _path: None)
    monkeypatch.setattr(
        bibliography_service,
        "_visual_ocr_pdf_page_lines",
        lambda _path: (
            [
                (6, "6. REFERENCES"),
                (6, "1. D. Denning, An Intrusion-Detection Model, Proc. 1986 EEE Symp. Sec. Privacy, 1986, pp. 118-31."),
                (7, "2. W. Lee, S. Stolfo, and K. Mok, Mining Audit Data to Build Intrusion Detection Models, Proc. KDD, 1998."),
            ],
            [4, 5, 6, 7],
        ),
    )

    result = extract_document_bibliography(document, Path(pdf_path), visual_ocr=True)

    assert result["evidence"]["source"] == "visual_ocr"
    assert result["evidence"]["status"] == "extracted"
    assert result["evidence"]["page_start"] == 6
    assert result["evidence"]["page_end"] == 7
    assert result["evidence"]["entry_count_estimate"] == 2
    assert result["bibliography"].splitlines()[0].startswith("D. Denning")


def test_extract_document_bibliography_splits_ocr_bare_initial_entry_and_strips_footer(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="OCR Running Footer References Paper",
        original_filename="ocr-running-footer-references.pdf",
        checksum_sha256="9" * 64,
    )
    document.pages.append(DocumentPage(page_number=6, normalized_text="2068\nRunning header only."))
    document.pages.append(DocumentPage(page_number=7, normalized_text="2069\nRunning header only."))
    pdf_path = tmp_path / "references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(bibliography_service, "_formatted_bibliography_from_pdf", lambda _path: None)
    monkeypatch.setattr(
        bibliography_service,
        "_visual_ocr_pdf_page_lines",
        lambda _path: (
            [
                (6, "6. REFERENCES"),
                (
                    6,
                    "5. R. Agrawal, T. Imielinski, and A. Swami, Mining Association Rules between "
                    "Sets of Items in Large Databases, Proc. ACM SIGMOD, vol. 22, no. 2, pp. 207-216, "
                    "1993. Khosravifar B and Bentahar J 2008) An experience improving intrusion "
                    "detection systems false alarm ratio by using honeypot. IEEE, 22nd Intl. Conf. "
                    "on Advanced Information Networking and Applications.pp: 997-1004. "
                    "A. J. Deepa and V. Kavitha / Procedia Engineering 38 (2012) 2063 - 2069 2069",
                ),
                (6, "A."),
                (6, "J. Deepa and V. Kavitha / Procedia Engineering 38 (2012) 2063 - 2069 2069"),
                (
                    7,
                    "7. W. Lee, S. Stolfo, and K. Mok, Mining Audit Data to Build Intrusion "
                    "Detection Models, Proc. Fourth Int'l Conf. Knowledge Discovery and Data Mining "
                    "(KDD '98), pp. 66-72, 1998.",
                ),
            ],
            [4, 5, 6, 7],
        ),
    )

    result = extract_document_bibliography(document, Path(pdf_path), visual_ocr=True)
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["entry_count_estimate"] == 3
    assert len(entries) == 3
    assert entries[0].startswith("R. Agrawal")
    assert entries[1].startswith("Khosravifar B and Bentahar J 2008")
    assert entries[2].startswith("W. Lee")
    assert "A." not in entries
    assert "Procedia Engineering" not in entries[1]


def test_extract_document_bibliography_records_visual_ocr_error(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Unavailable OCR References Paper",
        original_filename="unavailable-ocr-references.pdf",
        checksum_sha256="5" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="No extracted reference text."))
    pdf_path = tmp_path / "references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    def raise_ocr_error(_path):
        raise RuntimeError("Cloud Vision API is disabled")

    monkeypatch.setattr(bibliography_service, "_formatted_bibliography_from_pdf", lambda _path: None)
    monkeypatch.setattr(bibliography_service, "_visual_ocr_pdf_page_lines", raise_ocr_error)

    result = extract_document_bibliography(document, Path(pdf_path), visual_ocr=True)

    assert result["bibliography"] is None
    assert result["evidence"]["source"] == "page_text"
    assert result["evidence"]["status"] == "not_found"
    assert result["evidence"]["fallback_sources_attempted"] == ["pdf_span_layout", "page_text", "visual_ocr"]
    assert result["evidence"]["visual_ocr"]["status"] == "ocr_error"
    assert "disabled" in result["evidence"]["visual_ocr"]["error"]


def test_extract_document_bibliography_prefers_late_complete_references_over_table_label(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Appendix Table References Paper",
        original_filename="appendix-table-references.pdf",
        checksum_sha256="e" * 64,
    )
    document.pages.append(DocumentPage(page_number=15, normalized_text="References\n[32,46,55]\nAppendix A"))
    pdf_path = tmp_path / "references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (15, "References"),
            (16, "Table 4. Definitions of statistical measures."),
            (16, "TP Number of malicious insiders correctly classified."),
            (23, "Appendix A"),
            (32, "References"),
            (32, "1. Homoliak, I.; Toffalini, F.; Guarnizo, J. Insight into Insiders. ACM Comput. Surv. 2019, 52."),
            (32, "2. Al-Mhiqani, M.N.; Ahmad, R.; Abidin, Z.Z. A new taxonomy of insider threats. 2018, 1, 343-359."),
            (32, "3. Kim, J.; Park, M.; Kim, H. Insider threat detection based on user behavior modeling. Appl. Sci. 2019, 9, 4018."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))

    assert result["evidence"]["page_start"] == 32
    assert result["evidence"]["entry_count_estimate"] == 3
    assert result["bibliography"].splitlines()[0].startswith("Homoliak, I.")
    assert "Definitions of statistical measures" not in result["bibliography"]


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


def test_extract_document_bibliography_splits_standalone_number_markers():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Standalone Number Marker References Paper",
        original_filename="standalone-number-marker-references.pdf",
        checksum_sha256="3" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=6,
            normalized_text=(
                "References\n"
                "[1]\n"
                "Apache benchmark. https://httpd.apache.org/docs/2.2/programs/ab.html.\n"
                "[2]\n"
                "Irs phishing email.\n"
                "https://www.spamstopshere.com/blog/spam-news/alert-irs-scam-email-links-malicious-code.\n"
                "[3]\n"
                "Proftp backdoor. http://www.osvdb.org/69562."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        "Apache benchmark. https://httpd.apache.org/docs/2.2/programs/ab.html.",
        "Irs phishing email. https://www.spamstopshere.com/blog/spam-news/alert-irs-scam-email-links-malicious-code.",
        "Proftp backdoor. http://www.osvdb.org/69562.",
    ]
    assert result["evidence"]["entry_count_estimate"] == 3


def test_extract_document_bibliography_splits_ocr_glued_number_markers():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Glued Number Marker References Paper",
        original_filename="glued-number-marker-references.pdf",
        checksum_sha256="6" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=3,
            normalized_text=(
                "References\n"
                "1R. Power, “2002 CSI/FBI Computer Crime and Security Survey,” Computer Security Issues and Trends Vol. VIII, No. 1, Spring 2002.\n"
                "2E.D. Shaw, J.M. Post and K.G. Ruby, “Inside the Mind of the Insider” SecurityManagement.com, 2002.\n"
                "3H.H. Thompson and J.A. Whittaker, “Testing for software security,” Dr. Dobbs Journal, November 2002.\n"
                "About the authors\n"
                "Herbert H. Thompson is Director of Security Technology."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        "R. Power, “2002 CSI/FBI Computer Crime and Security Survey,” Computer Security Issues and Trends Vol. VIII, No. 1, Spring 2002.",
        "E.D. Shaw, J.M. Post and K.G. Ruby, “Inside the Mind of the Insider” SecurityManagement.com, 2002.",
        "H.H. Thompson and J.A. Whittaker, “Testing for software security,” Dr. Dobbs Journal, November 2002.",
    ]
    assert result["evidence"]["entry_count_estimate"] == 3


def test_extract_document_bibliography_stops_before_new_document_title_after_references():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="References Followed By Slides",
        original_filename="references-followed-by-slides.pdf",
        checksum_sha256="7" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=4,
            normalized_text=(
                "References\n"
                "[1] McAfee (2009). Unsecured economies: protecting vital information. http://example.com/report.\n"
                "[2] Neumann PG and Parker D (1989). A Summary of Computer Misuse Techniques. "
                "Proceedings of the 12th National Computer Security Conference.\n"
                "[3] Anderson R (1993). Why cryptosystems fail. 1st ACM conference on computer and communications security, ACM Press.\n"
                "Combating the Insider Threat with a Systematic Security Architecture\n"
                "Clive Blackwell\n"
                "Information Security Group\n"
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        "McAfee (2009). Unsecured economies: protecting vital information. http://example.com/report.",
        "Neumann PG and Parker D (1989). A Summary of Computer Misuse Techniques. Proceedings of the 12th National Computer Security Conference.",
        "Anderson R (1993). Why cryptosystems fail. 1st ACM conference on computer and communications security, ACM Press.",
    ]
    assert "Combating the Insider Threat" not in result["bibliography"]


def test_extract_document_bibliography_splits_after_doi_url_without_terminal_punctuation():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Doi Terminal References Paper",
        original_filename="doi-terminal-references.pdf",
        checksum_sha256="4" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=10,
            normalized_text=(
                "References\n"
                "Alenezi, M. N., Alabdulrazzaq, H. K., Alshaher, A. A., & Alkharang, M. M. (2020).\n"
                "Evolution of malware threats and techniques: A review. International Journal of Communication Networks, 12(3), 326-337. https://doi.org/\n"
                "10.17762/ijcnis.v12i3.4723\n"
                "Bar, A., Shapira, B., Rokach, L., & Unger, M. (2016). Identifying attack propagation\n"
                "patterns in honeypots using Markov chains modeling and complex networks analysis.\n"
                "https://doi.org/10.1109/SWSTE.2016.13"
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        (
            "Alenezi, M. N., Alabdulrazzaq, H. K., Alshaher, A. A., & Alkharang, M. M. (2020). "
            "Evolution of malware threats and techniques: A review. International Journal of Communication Networks, "
            "12(3), 326-337. https://doi.org/ 10.17762/ijcnis.v12i3.4723"
        ),
        (
            "Bar, A., Shapira, B., Rokach, L., & Unger, M. (2016). Identifying attack propagation "
            "patterns in honeypots using Markov chains modeling and complex networks analysis. "
            "https://doi.org/10.1109/SWSTE.2016.13"
        ),
    ]
    assert result["evidence"]["entry_count_estimate"] == 2


def test_extract_document_bibliography_splits_uppercase_acm_author_lists():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Uppercase ACM References Paper",
        original_filename="uppercase-acm-references.pdf",
        checksum_sha256="5" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=26,
            normalized_text=(
                "References\n"
                "ANDERSEN, D. F., CAPPELLI, D., GONZALEZ, J. J., MOORE, A. P., AND ZAGONEL, A.\n"
                "2004.\n"
                "Preliminary system dynamics maps of the insider cyber-threat problem. In Proceedings of the 22nd International Conference.\n"
                "ATKINSON, R. C. AND SHIFFRIN, R. M.\n"
                "1968.\n"
                "Human memory: A proposed system and its control processes. Academic Press, New York, NY.\n"
                "HAMMOND, K. R.\n"
                "1996.\n"
                "Human Judgment and Social Policy. Oxford University Press, New York, NY."
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"].splitlines() == [
        (
            "ANDERSEN, D. F., CAPPELLI, D., GONZALEZ, J. J., MOORE, A. P., AND ZAGONEL, A. "
            "2004. Preliminary system dynamics maps of the insider cyber-threat problem. "
            "In Proceedings of the 22nd International Conference."
        ),
        (
            "ATKINSON, R. C. AND SHIFFRIN, R. M. 1968. Human memory: A proposed system and its control "
            "processes. Academic Press, New York, NY."
        ),
        "HAMMOND, K. R. 1996. Human Judgment and Social Policy. Oxford University Press, New York, NY.",
    ]
    assert result["evidence"]["entry_count_estimate"] == 3


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


def test_extract_document_bibliography_ignores_book_chapter_running_headers(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Book Chapter References Paper",
        original_filename="book-chapter-references.pdf",
        checksum_sha256="8" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "book-chapter-references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (12, "REFERENCES"),
            (12, "[46] M. Khurram, H. Kumar, A. Chandak, V. Sarwade, N. Arora,"),
            (12, "T. Quach, Enhancing connected car adoption: security and over the"),
            (12, "air update framework, in: WF-IoT, 2016."),
            (12, "[47] M. La Manna, L. Treccozzi, P. Perazzo, S. Saponara, G. Dini,"),
            (12, "Performance evaluation of attribute-based encryption in automotive"),
            (12, "embedded platform for secure software over-the-air update, Sensors"),
            (12, "21 (2) (2021) 515."),
            (12, "An Overview of Cyber Attacks and Defenses on Intelligent Connected Vehicles Chapter | 93"),
            (12, "1493"),
            (13, "PART | XV Cyber Security of Connected and Automated Vehicles"),
            (13, "[48] M. Baza, M. Nabil, N. Lasla, K. Fidan, M. Mahmoud, M. Abdallah,"),
            (13, "Blockchain-based firmware update scheme tailored for autonomous"),
            (13, "vehicles, in: WCNC, IEEE, 2019, pp. 1-7."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))

    assert result["bibliography"].splitlines() == [
        (
            "M. Khurram, H. Kumar, A. Chandak, V. Sarwade, N. Arora, T. Quach, "
            "Enhancing connected car adoption: security and over the air update framework, in: WF-IoT, 2016."
        ),
        (
            "M. La Manna, L. Treccozzi, P. Perazzo, S. Saponara, G. Dini, Performance evaluation "
            "of attribute-based encryption in automotive embedded platform for secure software over-the-air update, "
            "Sensors 21 (2) (2021) 515."
        ),
        (
            "M. Baza, M. Nabil, N. Lasla, K. Fidan, M. Mahmoud, M. Abdallah, Blockchain-based "
            "firmware update scheme tailored for autonomous vehicles, in: WCNC, IEEE, 2019, pp. 1-7."
        ),
    ]
    assert "Chapter | 93" not in result["bibliography"]
    assert "PART | XV" not in result["bibliography"]
    assert result["evidence"]["entry_count_estimate"] == 3


def test_extract_document_bibliography_splits_bracketed_author_year_keys(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Citation Key Bibliography Paper",
        original_filename="citation-key-bibliography.pdf",
        checksum_sha256="9" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="Bibliography\nPlain fallback."))
    pdf_path = tmp_path / "citation-key-bibliography.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (169, "CMU/SEI-2015-TR-010 | SOFTWARE ENGINEERING INSTITUTE | CARNEGIE MELLON UNIVERSITY"),
            (169, "152"),
            (169, "Distribution Statement A: Approved for Public Release; Distribution is Unlimited"),
            (169, "Bibliography"),
            (169, "[Ariani 2013]"),
            (
                169,
                "Ariani, Dorothea Wahyu. “The Relationship Between Employee Engagement, Organizational",
            ),
            (169, "Citizenship Behavior, and Counterproductive Work Behavior.” *International Journal of Business*"),
            (169, "*Administration 4,* 2 (2013)."),
            (169, "[Boudreaux 2009]"),
            (169, "Boudreaux, Chris. *Online Database of Social Media Policies.*"),
            (169, "http://socialmediagovernance.com/policies/ (2012)."),
            (169, "[Caralli et al. 2010]"),
            (169, "Caralli, Richard A.; Allen, Julia H; & White David W. *CERT Resilience Management Model: A*"),
            (169, "*Maturity Model for Managing Operational Resilience*. Addison-Wesley Professional, 2010."),
            (170, "CMU/SEI-2015-TR-010 | SOFTWARE ENGINEERING INSTITUTE | CARNEGIE MELLON UNIVERSITY"),
            (170, "153"),
            (170, "Distribution Statement A: Approved for Public Release; Distribution is Unlimited"),
            (170, "[Hanley et al.2011a]"),
            (170, "Hanley, Michael; Dean, Tyler; Schroeder, Will; Houy, Matt; Trzeciak, Randall F.; &"),
            (170, "Montelibano, Joji. *An Analysis of Technical Observations in Insider Theft of Intellectual Property*"),
            (170, "*Cases* (CMU/SEI-2011-TN-006). Software Engineering Institute, Carnegie Mellon University,"),
            (170, "2011. http://www.sei.cmu.edu/library/abstracts/reports/11tn006.cfm"),
            (173, "[Zetter 2008]"),
            (173, "Zetter, Kim. Palin E-Mail Hacker Says It Was Easy. Wired, September 18, 2008."),
            (173, "http://www.wired.com/2008/09/palin-e-mail-ha/"),
            (174, "CMU/SEI-2015-TR-010 | SOFTWARE ENGINEERING INSTITUTE | CARNEGIE MELLON UNIVERSITY 157"),
            (174, "Distribution Statement A: Approved for Public Release; Distribution is Unlimited"),
            (175, "Table 1"),
            (175, "REPORT DOCUMENTATION PAGE"),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["page_start"] == 169
    assert result["evidence"]["entry_count_estimate"] == 5
    assert entries == [
        (
            "Ariani, Dorothea Wahyu. “The Relationship Between Employee Engagement, Organizational "
            "Citizenship Behavior, and Counterproductive Work Behavior.” *International Journal of Business* "
            "*Administration 4,* 2 (2013)."
        ),
        "Boudreaux, Chris. *Online Database of Social Media Policies.* http://socialmediagovernance.com/policies/ (2012).",
        (
            "Caralli, Richard A.; Allen, Julia H; & White David W. *CERT Resilience Management Model: A* "
            "*Maturity Model for Managing Operational Resilience*. Addison-Wesley Professional, 2010."
        ),
        (
            "Hanley, Michael; Dean, Tyler; Schroeder, Will; Houy, Matt; Trzeciak, Randall F.; & "
            "Montelibano, Joji. *An Analysis of Technical Observations in Insider Theft of Intellectual Property* "
            "*Cases* (CMU/SEI-2011-TN-006). Software Engineering Institute, Carnegie Mellon University, "
            "2011. http://www.sei.cmu.edu/library/abstracts/reports/11tn006.cfm"
        ),
        "Zetter, Kim. Palin E-Mail Hacker Says It Was Easy. Wired, September 18, 2008. http://www.wired.com/2008/09/palin-e-mail-ha/",
    ]
    assert not any(entry.startswith("[") for entry in entries)
    assert not any("Distribution Statement" in entry or "REPORT DOCUMENTATION PAGE" in entry for entry in entries)


def test_extract_document_bibliography_prefers_real_heading_over_table_reference_labels(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="False Table References Paper",
        original_filename="false-table-references.pdf",
        checksum_sha256="1" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "false-table-references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (9, "Specific challenge"),
            (9, "Impact on attribution"),
            (9, "References"),
            (9, "Anonymization tools"),
            (9, "Obfuscation of attacker origin"),
            (9, "Advanced network forensics detects anonymized traffic."),
            (10, "Specific challenge"),
            (10, "Proposed solutions"),
            (10, "References"),
            (10, "Shortage of skilled professionals"),
            (10, "Education and training initiatives develop analyst capacity."),
            (10, "References"),
            (10, "Cross-border investigations & jurisdictional issues"),
            (10, "Legal frameworks and MLATs facilitate evidence sharing."),
            (27, "References"),
            (27, "Abo El Rob, M.F., Islam, M.A., Gondi, S., Mansour, O., 2024. The application of MITRE"),
            (27, "ATT&CK framework in mitigating cybersecurity threats in the public sector.. Issues"),
            (27, "Inf. Syst. 25 (3)."),
            (27, "Abu, M.S., Selamat, S.R., Ariffin, A., Yusof, R., 2018. Cyber threat intelligence–issue"),
            (27, "and challenges. Indones. J. Electr. Eng. Comput. Sci. 10 (1), 371–379."),
            (27, "Ali, I., Ahmed, A.I.A., Almogren, A., Raza, M.A., Shah, S.A., Khan, A., Gani, A.,"),
            (27, "2020. Systematic literature review on IoT-based botnet attack. IEEE Access 8,"),
            (27, "212220–212232."),
            (27, "AliAhmad, A., Eleyan, D., Eleyan, A., Bejaoui, T., Zolkipli, M.F., Al-Khalidi, M.,"),
            (27, "2023. Malware detection issues, future trends and challenges: A survey. In: 2023"),
            (27, "International Symposium on Networks, Computers and Communications. ISNCC,"),
            (27, "pp. 1–6."),
            (27, "Allison, D., Smith, P., Mclaughlin, K., 2023. Digital twin-enhanced incident response"),
            (27, "for cyber-physical systems. In: Proceedings of the 18th International Conference"),
            (27, "on Availability, Reliability and Security. ARES '23, Association for Computing"),
            (27, "Machinery, New York, NY, USA, [Online]. Available: https://doi.org/10.1145/"),
            (27, "3600160.3600195."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["page_start"] == 27
    assert result["evidence"]["entry_count_estimate"] == 5
    assert len(entries) == 5
    assert entries[0].startswith("Abo El Rob")
    assert entries[2].startswith("Ali, I.")
    assert "2020. Systematic literature review" in entries[2]
    assert entries[3].startswith("AliAhmad")
    assert entries[4].startswith("Allison")
    assert not any(entry.startswith(("Anonymization tools", "Cross-border investigations", "2020.", "Machinery,")) for entry in entries)


def test_extract_document_bibliography_handles_mid_page_two_column_references(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Mid Page Two Column References Paper",
        original_filename="mid-page-two-column-references.pdf",
        checksum_sha256="6" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="No standalone reference heading in fallback text."))
    pdf_path = tmp_path / "mid-page-two-column-references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (6, "Table 3 Geographical location where the analysed studies were conducted."),
            (6, "No. of studies"),
            (6, "References"),
            (
                6,
                "Australia Shedden et al. (2011), Ahmad et al. (2012), Ahmad et al. (2015), "
                "Ahmad et al. (2020), Lakshmi et al. (2021)",
            ),
            (6, "Case study Evans et al. (2019), Ahmad et al. (2012), Line (2013), Baskerville et al. (2014)"),
            (
                14,
                "Funding This research is funded by a PhD scholarship. Appendix A. Literature search queries "
                "All databases were queried in September 2022. Source Search query The ACM Guide to Computing "
                "Literature AllField:(security incident) References Ahmad, A., Hadgkiss, J., Ruighaver, A.B., "
                "2012. Incident response teams - Challenges in supporting the organisational security function. "
                "Comput. Secur. 31 (5), 643-",
            ),
            (
                14,
                "652. doi: 10.1016/j.cose.2012.04.001. Ahmad, A., Maynard, S.B., Shanks, G., 2015. "
                "A case analysis of information systems and security incident responses. Int. J. Inf. Manag. "
                "35 (6), 717-723. doi: 10.1016/j.ijinfomgt.2015.08.001. Baskerville, R., Spagnoletti, P., "
                "Kim, J., 2014. Incident-centered information security: managing a strategic balance between "
                "prevention and response. Inf. Manag. 51 (1), 138-151.",
            ),
            (
                15,
                "He, Y., Johnson, C., 2017. Challenges of information security incident learning: an industrial "
                "case study in a Chinese healthcare organization. Inf. Health Soc. Care 42 (4), 393-408.",
            ),
            (
                15,
                "Line, M.B., Albrechtsen, E., Jaatun, M.G., 2016. Information security incident management: "
                "planning for failure. Comput. Secur. 62, 188-201.",
            ),
            (
                16,
                "Zwetsloot, G.I.J.M., Kines, P., Ruotsala, R., Drupsteen, L., Merivirta, M.L., Bezemer, R.A., "
                "2017. The importance of commitment, communication, culture and learning for the implementation "
                "of the zero accident vision in 27 companies in Europe. Saf. Sci. 96, 22-32. Clare M. Patterson "
                "is a research student in cyber security in the School of Computing.",
            ),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["page_start"] == 14
    assert result["evidence"]["page_end"] == 16
    assert result["evidence"]["entry_count_estimate"] == 6
    assert entries[0].startswith("Ahmad, A.")
    assert entries[1].startswith("Ahmad, A., Maynard")
    assert entries[2].startswith("Baskerville")
    assert entries[-1].startswith("Zwetsloot")
    assert "Geographical location" not in result["bibliography"]
    assert "All databases were queried" not in result["bibliography"]
    assert "Clare M. Patterson" not in result["bibliography"]


def test_extract_document_bibliography_ignores_inline_references_word_before_real_heading(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Inline References Word Paper",
        original_filename="inline-references-word.pdf",
        checksum_sha256="2" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "inline-references-word.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (21, "Although select models offer cursory"),
            (21, "references to specific digital forensics tools, a coherent explication of"),
            (21, "the whys and wherefores of their judicious employment remains absent."),
            (25, "References"),
            (25, "Acquisition, A.D., 2022.Smart for linux.〈http://www.asrdata.com/?page_id=40〉."),
            (25, "AI, L., 2021.Lyrebird.〈https://www.descript.com/lyrebird〉."),
            (25, "Alabdan, R., 2020. Phishing attacks survey: types, vectors, and technical approaches. Future Internet 12, 168. Anderson, R., Barton, C., Böhme, R., Clayton, R., Van Eeten, M.J., Levi, M., Moore, T.,"),
            (25, "Savage, S., 2013. Measuring the cost of cybercrime. Econ. Inf. Secur. Priv. 265–300."),
            (25, "Arpana, M., Chauhan, M., Gjimt, P., 2012. Preventing cybercrime: a study regarding awareness of cybercrime in tricity. Int. J. Enterp. Comput. Bus. Syst. 2, 1–10. ATT&CK, 2015.Mitre att&ck.〈https://attack.mitre.org/〉."),
            (25, "Bekkers, L.M., Moneva, A., Leukfeldt, E., 2022. Understanding cybercrime involvement: a quasi-experiment. J. Exp. Criminol. 1–20. CAPEC®, 2007.Mitre capec®.〈https://capec.mitre.org/〉."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["page_start"] == 25
    assert result["evidence"]["entry_count_estimate"] == 7
    assert len(entries) == 7
    assert entries[0].startswith("Acquisition")
    assert entries[2].startswith("Alabdan")
    assert "Anderson, R." in entries[2]
    assert "Savage, S., 2013" in entries[2]
    assert entries[4].startswith("ATT&CK")
    assert entries[6].startswith("CAPEC")
    assert not any(entry.startswith(("references to", "Savage,")) for entry in entries)


def test_extract_document_bibliography_uses_page_text_when_pdf_spans_stop_before_later_pages(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Page Boundary References Paper",
        original_filename="page-boundary-references.pdf",
        checksum_sha256="3" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=16,
            normalized_text=(
                "Body text ends here.\n"
                "References\n"
                "Anderson, A. (2014). Alpha source. Journal of Tests, 1, 1-9.\n"
                "Baker, B. (2013). Beta source. Journal of Tests, 2, 10-19.\n"
                "Clark, C. (2012). Gamma source. Journal of Tests, 3, 20-29."
            ),
        )
    )
    document.pages.append(
        DocumentPage(
            page_number=17,
            normalized_text=(
                "Dorsey, D. (2011). Delta source. Journal of Tests, 4, 30-39.\n"
                "Edwards, E. (2010). Epsilon source. Journal of Tests, 5, 40-49.\n"
                "Foster, F. (2009). Zeta source. Journal of Tests, 6, 50-59.\n"
                "Garcia, G. (2008). Eta source. Journal of Tests, 7, 60-69.\n"
                "Zimmer, Z. (2007). Omega source. Journal of Tests, 8, 70-79."
            ),
        )
    )
    pdf_path = tmp_path / "page-boundary-references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_formatted_bibliography_from_pdf",
        lambda _path: {
            "bibliography": (
                "Anderson, A. (2014). *Alpha source.* Journal of Tests, 1, 1-9.\n"
                "Baker, B. (2013). *Beta source.* Journal of Tests, 2, 10-19.\n"
                "Clark, C. (2012). *Gamma source.* Journal of Tests, 3, 20-29."
            ),
            "evidence": {
                "source": "pdf_span_layout",
                "status": "extracted",
                "page_start": 16,
                "page_end": 16,
                "formatting": "markdown_italics_from_pdf_spans",
                "entry_count_estimate": 3,
            },
        },
    )

    result = extract_document_bibliography(document, pdf_path)
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["source"] == "page_text"
    assert result["evidence"]["page_end"] == 17
    assert result["evidence"]["fallback_reason"] == "page_text_more_complete_than_pdf_span_layout"
    assert result["evidence"]["fallback_from_pdf_span_layout"]["page_end"] == 16
    assert result["evidence"]["entry_count_estimate"] == 8
    assert len(entries) == 8
    assert entries[0].startswith("Anderson")
    assert entries[-1].startswith("Zimmer")


def test_extract_document_bibliography_rejects_publisher_reference_count_front_matter(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Publisher Front Matter Paper",
        original_filename="publisher-front-matter.pdf",
        checksum_sha256="7" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "publisher-front-matter.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (1, "References: this document contains references to 16 other documents."),
            (1, "Users who downloaded this article also downloaded:"),
            (1, '(2005), "Unrelated publisher recommendation", Management Decision, Vol. 43.'),
            (11, "References"),
            (11, "Anderson, J.P. (1980), Computer Security Threat Monitoring and Surveillance, James P."),
            (11, "Anderson Co., April, Fort Washington, PA."),
            (11, "Bishop, C.M. (1995), Neural Networks for Pattern Recognition, Oxford University Press, Oxford."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))

    assert result["evidence"]["page_start"] == 11
    assert result["bibliography"].splitlines() == [
        "Anderson, J.P. (1980), Computer Security Threat Monitoring and Surveillance, James P. Anderson Co., April, Fort Washington, PA.",
        "Bishop, C.M. (1995), Neural Networks for Pattern Recognition, Oxford University Press, Oxford.",
    ]
    assert "Users who downloaded" not in result["bibliography"]


def test_extract_document_bibliography_marks_symbol_heavy_text_for_ocr():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Symbol Heavy Paper",
        original_filename="symbol-heavy.pdf",
        checksum_sha256="8" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=11,
            normalized_text=(
                '@ H%\',, 4!!(# BB? ==!" A & -? I.A"A\n'
                "- -/!\".# BB$ #,/ I8# 888I8 - >,%,4 8(((# BB/ *== $%&&&' I; >%,4!!<# "
                "BB- / == >- 9 > 9H) '!!(# BB$ == (& (8 1 A!<<. ' & F 4!! # BBJ == E;:"
            ),
        )
    )

    result = extract_document_bibliography(document)

    assert result["bibliography"] is None
    assert result["evidence"]["status"] == "not_found"
    assert result["evidence"]["unreadable_text_pages"] == [11]
    assert result["evidence"]["ocr_recommended"] is True


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


def test_extract_document_bibliography_keeps_numeric_continuations_in_bracketed_lists():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Bracketed Numeric Continuations Paper",
        original_filename="bracketed-numeric-continuations.pdf",
        checksum_sha256="9" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=60,
            normalized_text=(
                "References\n"
                "[52] T. OConnor, C. Stricklan, Teaching a hands-on mobile and wireless cyber-\n"
                "security course, in: Proceedings of the 26th ACM Conference on Innovation\n"
                "and Technology in Computer Science Education V. 1, ACM, 2021, pp. 296-\n"
                "302. doi:10.1145/3430665.3456346.\n"
                "URL https://dl.acm.org/doi/10.1145/3430665.3456346\n"
                "[56] A. Papanikolaou, V. Karakoidas, V. Vlachos, A. Venieris, C. Ilioudis,\n"
                "G. Zouganelis, A hacker's perspective on educating future security experts,\n"
                "in: 2011 15th Panhellenic Conference on Informatics, IEEE, 2011, pp. 68-\n"
                "72. doi:10.1109/PCI.2011.47.\n"
                "URL http://ieeexplore.ieee.org/document/6065066/\n"
                "[57] D. R. Krathwohl, L. W. Anderson, B. Benjamin Samuel, A taxonomy for\n"
                "learning, teaching, and assessing: a revision of Bloom's taxonomy of educational objectives."
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert len(entries) == 3
    assert result["evidence"]["entry_count_estimate"] == 3
    assert entries[0].startswith("T. OConnor")
    assert "296-302" in entries[0]
    assert "302. doi:10.1145/3430665.3456346" in entries[0]
    assert entries[1].startswith("A. Papanikolaou")
    assert "68-72" in entries[1]
    assert "72. doi:10.1109/PCI.2011.47" in entries[1]
    assert not any(entry.startswith(("302. doi", "72. doi")) for entry in entries)


def test_extract_document_bibliography_ignores_reference_list_search_method_section(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Systematic Review",
        original_filename="systematic-review.pdf",
        checksum_sha256="0" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "systematic-review.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (10, "3.4. Step 4: Reference List Search References cited in articles identified from the initial evaluation were screened."),
            (10, "References: cited in articles identified from the initial evaluation were included if they matched."),
            (10, "1. Date Range and Cutoff: Must post-date the year 2000."),
            (10, "2. Full Text Appraisal: Must discuss adversarial thinking."),
            (53, "References"),
            (53, "[1] R. Derbyshire, B. Green, D. Hutchison, Talking a different language, Computers & Security 103 (2021) 102163."),
            (53, "[2] F. B. Schneider, Cybersecurity education in universities, IEEE Security & Privacy 11 (2013) 3-4."),
            (53, "[3] J. T. F. on Cybersecurity Education, Cybersecurity Curricula 2017, ACM, 2018."),
        ],
    )

    result = extract_document_bibliography(document, pdf_path)

    assert result["evidence"]["page_start"] == 53
    assert result["evidence"]["entry_count_estimate"] == 3
    assert result["bibliography"].splitlines()[0].startswith("R. Derbyshire")
    assert "Reference List Search" not in result["bibliography"]
    assert "Full Text Appraisal" not in result["bibliography"]


def test_pdf_line_sort_orders_two_column_reference_page_by_column():
    from app.services.bibliography import _sort_pdf_page_line_items

    items = [
        (303.0, 49.0, 549.0, 60.0, "Lee, S. (2008). Special report."),
        (303.0, 70.0, 549.0, 81.0, "LinkedIn Group Partners. (2015). Insider threat spotlight report 2015."),
        (48.0, 68.0, 232.0, 80.0, "Inhyun Cho http://orcid.org/0000-0001-6066-1140"),
        (48.0, 96.0, 99.0, 109.0, "References"),
        (48.0, 114.0, 293.0, 126.0, "Anderson, R. H., Bozek, T., Longstaff, T., Meitzler, W., & Skroch, M. (2000)."),
        (48.0, 130.0, 293.0, 142.0, "BBC. (2014). Edward Snowden: Leaks that exposed US Spy Programme."),
        (48.0, 490.0, 293.0, 502.0, "Humphreys, E. (2007). Implementing the ISO/IEC 27001 information security management system standard."),
        (48.0, 512.0, 293.0, 524.0, "Kroll. (2014). Global Fraud Report 2013-2014."),
    ]

    sorted_text = [item[4] for item in _sort_pdf_page_line_items(595.0, items)]

    assert sorted_text.index("References") < sorted_text.index(
        "Anderson, R. H., Bozek, T., Longstaff, T., Meitzler, W., & Skroch, M. (2000)."
    )
    assert sorted_text.index("Kroll. (2014). Global Fraud Report 2013-2014.") < sorted_text.index(
        "Lee, S. (2008). Special report."
    )
    assert sorted_text[-1] == "LinkedIn Group Partners. (2015). Insider threat spotlight report 2015."


def test_pdf_line_sort_preserves_marker_heavy_reference_page_order():
    from app.services.bibliography import _sort_pdf_page_line_items

    items = [
        (48.0, 92.0, 54.0, 103.0, "1."),
        (72.0, 92.0, 288.0, 103.0, "Homoliak, I.; Toffalini, F. Insight into insiders."),
        (48.0, 112.0, 54.0, 123.0, "2."),
        (72.0, 112.0, 288.0, 123.0, "Al-Mhiqani, M.N.; Ahmad, R. A new taxonomy."),
        (48.0, 132.0, 54.0, 143.0, "3."),
        (72.0, 132.0, 288.0, 143.0, "Kim, J.; Park, M. User behavior modeling."),
        (48.0, 152.0, 54.0, 163.0, "4."),
        (72.0, 152.0, 288.0, 163.0, "Liu, L.; Zhang, X. Insider threat survey."),
        (48.0, 172.0, 54.0, 183.0, "5."),
        (72.0, 172.0, 288.0, 183.0, "Magklaras, G.B.; Furnell, S.M. Threat prediction."),
        (48.0, 192.0, 54.0, 203.0, "6."),
        (72.0, 192.0, 288.0, 203.0, "Park, J.; Stolfo, S. Masquerade detection."),
        (318.0, 92.0, 326.0, 103.0, "7."),
        (342.0, 92.0, 558.0, 103.0, "Pfleeger, S.L.; Caputo, D. Leveraging behavioral science."),
    ]

    sorted_text = [item[4] for item in _sort_pdf_page_line_items(595.0, items)]

    assert sorted_text == [item[4] for item in items]
    assert sorted_text.index("1.") + 1 == sorted_text.index(
        "Homoliak, I.; Toffalini, F. Insight into insiders."
    )


def test_extract_document_bibliography_splits_single_word_organization_dot_year_entries():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Single Word Organization References Paper",
        original_filename="single-word-organization-references.pdf",
        checksum_sha256="1" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=10,
            normalized_text=(
                "References\n"
                "Humphreys, E. (2007). Implementing the ISO/IEC 27001 information security management system standard. "
                "Norwood, MA: Artech House Inc.\n"
                "Downloaded by [University of Sussex Library] at 20:37 12 May 2016\n"
                "Kroll. (2014). Global Fraud Report 2013-2014. Retrieved from http://fraud.example/report.pdf.\n"
                "Intelligent Automation And Soft Computing\n"
                "Lee, S. (2008). Special report. IT Standard & Test TTA Journal, 118, 82-88."
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert entries == [
        (
            "Humphreys, E. (2007). Implementing the ISO/IEC 27001 information security management system standard. "
            "Norwood, MA: Artech House Inc."
        ),
        "Kroll. (2014). Global Fraud Report 2013-2014. Retrieved from http://fraud.example/report.pdf.",
        "Lee, S. (2008). Special report. IT Standard & Test TTA Journal, 118, 82-88.",
    ]
    assert result["evidence"]["entry_count_estimate"] == 3


def test_extract_document_bibliography_keeps_in_proceedings_continuation_before_next_org_entry():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Proceedings Continuation References Paper",
        original_filename="proceedings-continuation-references.pdf",
        checksum_sha256="2" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=10,
            normalized_text=(
                "References\n"
                "Ottis, R. & Lorents, P. (2010). Cyberspace: Definition and implications.\n"
                "In Proceedings of the 5th International Conference on Information\n"
                "Warfare and Security, pp. 267-270.\n"
                "PwC. (2012). 2012 global economic crime survey. Retrieved from http://example.test/report.pdf.\n"
                "Probst, C. W., Hunker, J., Gollmann, D., and Bishop, M. (2010). Aspects of insider threats.\n"
                "In Probst et al. (Ed.), Insider Threats in Cyber Security (pp. 1-15). US: Springer.\n"
                "Randazzo, M. R., Keeney, M., Kowalski, E., Cappelli, D., and Moore, A.\n"
                "(2005). Insider threat study: Illicit cyber activity in the banking and finance sector.\n"
                "United States Army (2010). Cyberspace operations concept capability plan 2016-2028.\n"
                "United States Department of Defense. (2009). Joint Pub 1-02 2009: Department of Defense Dictionary."
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert entries == [
        (
            "Ottis, R. & Lorents, P. (2010). Cyberspace: Definition and implications. "
            "In Proceedings of the 5th International Conference on Information Warfare and Security, pp. 267-270."
        ),
        "PwC. (2012). 2012 global economic crime survey. Retrieved from http://example.test/report.pdf.",
        (
            "Probst, C. W., Hunker, J., Gollmann, D., and Bishop, M. (2010). Aspects of insider threats. "
            "In Probst et al. (Ed.), Insider Threats in Cyber Security (pp. 1-15). US: Springer."
        ),
        (
            "Randazzo, M. R., Keeney, M., Kowalski, E., Cappelli, D., and Moore, A. (2005). Insider threat study: "
            "Illicit cyber activity in the banking and finance sector."
        ),
        "United States Army (2010). Cyberspace operations concept capability plan 2016-2028.",
        "United States Department of Defense. (2009). Joint Pub 1-02 2009: Department of Defense Dictionary.",
    ]
    assert result["evidence"]["entry_count_estimate"] == 6


def test_extract_document_bibliography_filters_ieee_footer_after_final_reference():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="IEEE Footer References Paper",
        original_filename="ieee-footer-references.pdf",
        checksum_sha256="3" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=15,
            normalized_text=(
                "REFERENCES\n"
                "[77] C. H. Mason and W. D. Perreault, “Collinearity, Power, and Interpretation of Multiple Regression Analysis,” "
                "Journal of Marketing Research, vol. XXVIII, pp. 268-280, Aug. 1991.\n"
                "[78] StataCorp, Stata Statistical Software: Release 12. College Station, TX: StataCorp LP, 2011.\n"
                "15\n"
                "0360-8581 (c) 2020 IEEE. Personal use is permitted, but republication/redistribution requires IEEE permission.\n"
                "Authorized licensed use limited to: University of Newcastle. Downloaded on June 01,2020 at 15:53:08 UTC from IEEE Xplore. Restrictions apply.\n"
                "This article has been accepted for publication in a future issue of this journal.\n"
                "Engineering Management Review\n"
                "Michele Maasberg is an Assistant Professor of Computer Science."
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert entries == [
        (
            "C. H. Mason and W. D. Perreault, “Collinearity, Power, and Interpretation of Multiple Regression Analysis,” "
            "Journal of Marketing Research, vol. XXVIII, pp. 268-280, Aug. 1991."
        ),
        "StataCorp, Stata Statistical Software: Release 12. College Station, TX: StataCorp LP, 2011.",
    ]
    assert "IEEE" not in result["bibliography"]
    assert "Authorized licensed use" not in result["bibliography"]
    assert result["evidence"]["entry_count_estimate"] == 2


def test_extract_document_bibliography_continues_after_repeated_references_header(monkeypatch, tmp_path):
    from app.models import Document, DocumentPage
    from app.services import bibliography as bibliography_service
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Repeated Header References Paper",
        original_filename="repeated-header-references.pdf",
        checksum_sha256="4" * 64,
    )
    document.pages.append(DocumentPage(page_number=1, normalized_text="References\nPlain fallback."))
    pdf_path = tmp_path / "repeated-header-references.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")

    monkeypatch.setattr(
        bibliography_service,
        "_pdf_markdown_lines",
        lambda _path: [
            (2, "References"),
            (2, "Cyberterrorism e the spectre that is the convergence Introduction body text " * 80),
            (24, "References"),
            (24, "Ahmad, R., & Yunos, Z. (2012). A dynamic cyber terrorism framework."),
            (24, "Denning, D. (2001). Activism, hacktivism, and cyberterrorism: The Internet as a tool"),
            (24, "for influencing foreign policy. In Networks and netwars: The future"),
            (25, "References"),
            (25, "of terror, crime (pp. 239-288). RAND. Retrieved from https://www.rand.org/content/"),
            (25, "Denning, D. (2012). Stuxnet: What has changed? Future Internet, 4(3), 672-687."),
            (25, "Klausen, J. (2015). Tweeting the Jihad: Social media networks."),
        ],
    )

    result = extract_document_bibliography(document, Path(pdf_path))
    entries = result["bibliography"].splitlines()

    assert result["evidence"]["page_start"] == 24
    assert result["evidence"]["page_end"] == 25
    assert entries == [
        "Ahmad, R., & Yunos, Z. (2012). A dynamic cyber terrorism framework.",
        (
            "Denning, D. (2001). Activism, hacktivism, and cyberterrorism: The Internet as a tool "
            "for influencing foreign policy. In Networks and netwars: The future of terror, crime "
            "(pp. 239-288). RAND. Retrieved from https://www.rand.org/content/"
        ),
        "Denning, D. (2012). Stuxnet: What has changed? Future Internet, 4(3), 672-687.",
        "Klausen, J. (2015). Tweeting the Jihad: Social media networks.",
    ]


def test_extract_document_bibliography_keeps_marker_list_italic_title_continuations():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Bracketed Marker Continuation Paper",
        original_filename="bracketed-marker-continuation.pdf",
        checksum_sha256="5" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=7,
            normalized_text=(
                "REFERENCES\n"
                "[8] Fei Tony Liu, Kai Ming Ting, and Zhi-Hua Zhou.\n"
                "Isolation forest. In Data Mining, 2008. ICDM'08.\n"
                "Eighth IEEE International Conference on, pages\n"
                "413-422. IEEE, 2008.\n"
                "[9] Teresa F Lunt. A survey of intrusion detection\n"
                "techniques. Computers & Security, 12(4):405-418,\n"
                "1993.\n"
                "[10] GB Magklaras and SM Furnell. Insider threat\n"
                "prediction tool: Evaluating the probability of it\n"
                "misuse. Computers & Security, 21(1):62-73, 2001.\n"
                "APPENDIX\n"
                "A. RED TEAM SCENARIOS"
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert entries == [
        (
            "Fei Tony Liu, Kai Ming Ting, and Zhi-Hua Zhou. Isolation forest. In Data Mining, "
            "2008. ICDM'08. Eighth IEEE International Conference on, pages 413-422. IEEE, 2008."
        ),
        "Teresa F Lunt. A survey of intrusion detection techniques. Computers & Security, 12(4):405-418, 1993.",
        (
            "GB Magklaras and SM Furnell. Insider threat prediction tool: Evaluating the probability of it "
            "misuse. Computers & Security, 21(1):62-73, 2001."
        ),
    ]
    assert result["evidence"]["entry_count_estimate"] == 3


def test_extract_document_bibliography_splits_legal_and_news_references():
    from app.models import Document, DocumentPage
    from app.services.bibliography import extract_document_bibliography

    document = Document(
        title="Legal News References Paper",
        original_filename="legal-news-references.pdf",
        checksum_sha256="6" * 64,
    )
    document.pages.append(
        DocumentPage(
            page_number=16,
            normalized_text=(
                "References\n"
                "Albert Abed, v Wei Lin, Melis, Case 1:23-cv-21059, Plaintiff's Memorandum of Law in\n"
                "Support of his Motion for a Preliminary Injunction (U.S. District Court, October 11, 2023).\n"
                "Access Wire, 2022. The Slaughtered Love: RealCall's Survey Finds Americans Were Targeted.\n"
                "Governance, Risk & Compliance Monitor Worldwide. NJ attorney general announces\n"
                "crackdown on pig butchering schemes (NexisUni database). 7 February 2023.\n"
                "Gurung, Anjita v. Metaquotes LTD, a Cyprus Corporation; Metaquotes Software corp., a\n"
                "Bahamas Corporation; OPSO, Case 1:23-cv-06362, Plaintiff's Opposition to Defendants' Motions\n"
                "to Dismiss the Complaint (United States District Court Eastern District of New York, 2023).\n"
                "Zuo, M., 2021. Online love scams have gone global. South China Morning Post."
            ),
        )
    )

    result = extract_document_bibliography(document)
    entries = result["bibliography"].splitlines()

    assert entries == [
        (
            "Albert Abed, v Wei Lin, Melis, Case 1:23-cv-21059, Plaintiff's Memorandum of Law in "
            "Support of his Motion for a Preliminary Injunction (U.S. District Court, October 11, 2023)."
        ),
        "Access Wire, 2022. The Slaughtered Love: RealCall's Survey Finds Americans Were Targeted.",
        (
            "Governance, Risk & Compliance Monitor Worldwide. NJ attorney general announces "
            "crackdown on pig butchering schemes (NexisUni database). 7 February 2023."
        ),
        (
            "Gurung, Anjita v. Metaquotes LTD, a Cyprus Corporation; Metaquotes Software corp., a "
            "Bahamas Corporation; OPSO, Case 1:23-cv-06362, Plaintiff's Opposition to Defendants' Motions "
            "to Dismiss the Complaint (United States District Court Eastern District of New York, 2023)."
        ),
        "Zuo, M., 2021. Online love scams have gone global. South China Morning Post.",
    ]
    assert result["evidence"]["entry_count_estimate"] == 5
