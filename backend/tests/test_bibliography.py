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
