def test_prepare_pdf_source_records_page_count():
    import fitz

    from app.services.import_sources import prepare_import_source

    document = fitz.open()
    for index in range(3):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    document.set_metadata({"title": "Three Page Source"})
    pdf_data = document.tobytes()
    document.close()

    prepared = prepare_import_source(pdf_data, "three-page.pdf", "application/pdf")

    assert prepared.source_kind == "pdf"
    assert prepared.stored_page_count == 3
    assert prepared.metadata["estimated_page_count"] == 3
    assert prepared.title == "Three Page Source"


def test_prepare_pdf_source_ignores_generic_metadata_title():
    import fitz

    from app.services.import_sources import prepare_import_source

    document = fitz.open()
    document.new_page().insert_text((72, 72), "Network attack survey")
    document.set_metadata({"title": "untitled"})
    pdf_data = document.tobytes()
    document.close()

    prepared = prepare_import_source(
        pdf_data,
        "A Survey on Network Attacks and Intrusion Detection Systems (2017).pdf",
        "application/pdf",
    )

    assert prepared.title == "A Survey on Network Attacks and Intrusion Detection Systems (2017)"


def test_prepare_pdf_source_uses_hash_title_when_filename_is_generic_too():
    import hashlib

    import fitz

    from app.services.import_sources import prepare_import_source

    document = fitz.open()
    document.new_page().insert_text((72, 72), "Specific document body")
    document.set_metadata({"title": "Untitled"})
    pdf_data = document.tobytes()
    document.close()

    prepared = prepare_import_source(pdf_data, "untitled.pdf", "application/pdf")

    assert prepared.title == f"Document {hashlib.sha256(pdf_data).hexdigest()[:12]}"


def test_prepare_html_source_ignores_generic_title():
    from app.services.import_sources import prepare_import_source

    html = b"<html><head><title>Untitled</title></head><body><h1>Untitled</h1><p>Actual content.</p></body></html>"

    prepared = prepare_import_source(html, "network-survey.html", "text/html")

    assert prepared.title == "network survey"


def test_prepare_text_source_ignores_generic_first_line():
    from app.services.import_sources import prepare_import_source

    text = b"Untitled\n\nActual content."

    prepared = prepare_import_source(text, "field-notes.md", "text/markdown")

    assert prepared.title == "field notes"


def test_prepare_docx_source_preserves_original_and_generates_pdf():
    import io
    import zipfile

    from app.services.import_sources import prepare_import_source

    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Portfolio Essay Draft</w:t></w:r></w:p>
        <w:p><w:r><w:t>Evidence connects the rubric to the body.</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    prepared = prepare_import_source(
        buffer.getvalue(),
        "portfolio-draft.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert prepared.source_kind == "docx"
    assert prepared.source_filename == "portfolio-draft.docx"
    assert prepared.stored_filename == "portfolio-draft.pdf"
    assert prepared.stored_content_type == "application/pdf"
    assert prepared.title == "Portfolio Essay Draft"
    assert prepared.metadata["original_content_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert prepared.metadata["mezzanine"]["format"] == "pdf"


def test_prepare_rtf_source_preserves_original_and_generates_pdf():
    from app.services.import_sources import prepare_import_source

    rtf = b"{\\rtf1\\ansi Portfolio Rubric\\par Evidence and analysis are required.}"

    prepared = prepare_import_source(rtf, "rubric.rtf", "application/rtf")

    assert prepared.source_kind == "rtf"
    assert prepared.source_filename == "rubric.rtf"
    assert prepared.stored_filename == "rubric.pdf"
    assert prepared.stored_content_type == "application/pdf"
    assert prepared.title == "Portfolio Rubric"
    assert prepared.metadata["original_content_type"] == "application/rtf"
