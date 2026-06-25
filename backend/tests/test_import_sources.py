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
