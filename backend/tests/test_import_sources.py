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
