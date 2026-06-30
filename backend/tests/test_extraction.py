from app.services.extraction import (
    ExtractedDocument,
    ExtractedPage,
    LayoutBlock,
    blocks_to_text,
    extract_pdf_text,
    normalize_extracted_text,
    rows_to_markdown,
    sanitize_extracted_text,
    split_text_into_chunks,
    _is_first_page_publisher_furniture,
    _split_marker_paginated_markdown,
)


def test_split_text_into_chunks_preserves_paragraphs():
    text = "\n\n".join([f"Paragraph {index} " + ("x" * 60) for index in range(8)])

    chunks = split_text_into_chunks(text, target_chars=180)

    assert len(chunks) > 1
    assert chunks[0].startswith("Paragraph 0")
    assert chunks[-1].startswith("Paragraph")


def test_blocks_to_text_reads_two_columns_before_crossing_page():
    blocks = [
        LayoutBlock(50, 40, 550, 70, "Full width title"),
        LayoutBlock(55, 100, 260, 120, "Left one"),
        LayoutBlock(330, 98, 535, 118, "Right one"),
        LayoutBlock(55, 140, 260, 160, "Left two"),
        LayoutBlock(330, 138, 535, 158, "Right two"),
        LayoutBlock(55, 180, 260, 200, "Left three"),
        LayoutBlock(330, 178, 535, 198, "Right three"),
    ]

    text = blocks_to_text(blocks, page_width=600)

    assert text.split("\n\n") == [
        "Full width title",
        "Left one",
        "Left two",
        "Left three",
        "Right one",
        "Right two",
        "Right three",
    ]


def test_blocks_to_text_splits_front_matter_before_intro_columns():
    blocks = [
        LayoutBlock(50, 40, 550, 70, "Full width article title"),
        LayoutBlock(55, 100, 155, 110, "article info"),
        LayoutBlock(210, 100, 290, 110, "abstract"),
        LayoutBlock(55, 125, 155, 185, "Article history and keywords"),
        LayoutBlock(210, 125, 570, 190, "Abstract body"),
        LayoutBlock(55, 230, 120, 240, "1. Introduction"),
        LayoutBlock(55, 255, 300, 330, "Left introduction body"),
        LayoutBlock(325, 255, 570, 330, "Right introduction body"),
    ]

    text = blocks_to_text(blocks, page_width=600)
    parts = text.split("\n\n")

    assert parts[0] == "Full width article title"
    assert parts.index("Abstract body") < parts.index("1. Introduction")
    assert parts.index("Left introduction body") < parts.index("Right introduction body")


def test_first_page_publisher_furniture_requires_small_uncaptioned_header_region():
    assert _is_first_page_publisher_furniture((500, 60, 560, 130), page_width=600, page_height=800, has_caption=False)
    assert not _is_first_page_publisher_furniture((100, 260, 500, 430), page_width=600, page_height=800, has_caption=False)
    assert not _is_first_page_publisher_furniture((500, 60, 560, 130), page_width=600, page_height=800, has_caption=True)


def test_rows_to_markdown_preserves_table_shape_and_escapes_pipes():
    markdown = rows_to_markdown([["Term", "Meaning"], ["alpha|beta", "combined"], ["gamma", ""]])

    assert markdown == "\n".join(
        [
            "| Term | Meaning |",
            "| --- | --- |",
            "| alpha\\|beta | combined |",
            "| gamma |  |",
        ]
    )


def test_sanitize_extracted_text_removes_postgres_unsafe_controls():
    text = "\x00\x02Title\tline\nNext paragraph\x7f"

    sanitized = sanitize_extracted_text(text)

    assert sanitized == "Title\tline\nNext paragraph"


def test_normalize_extracted_text_conforms_line_wraps_and_spacing():
    text = "B a y e s i a n Network Model for Predicting Insider Threats\n\nThe model com-\npares insider threat signals .\nIt preserves paragraph flow ."

    normalized = normalize_extracted_text(text)

    assert "Bayesian Network Model" in normalized
    assert "compares insider threat signals." in normalized
    assert "paragraph flow." in normalized
    assert "com-\npares" not in normalized


def test_marker_paginated_markdown_splits_into_pages(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    markdown = "\n\n0\n------------------------------------------------\n# Title\n\nLeft then right\n\n1\n------------------------------------------------\nTable text"

    pages = _split_marker_paginated_markdown(markdown, page_count=2)

    assert [(page.page_number, page.source) for page in pages] == [(1, "marker"), (2, "marker")]
    assert pages[0].text.startswith("# Title")
    assert pages[1].text == "Table text"


def test_marker_extractor_falls_back_to_pymupdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")

    def fail_marker(path):
        raise RuntimeError("marker missing")

    def fake_pymupdf(path, *, fallback_reason=None):
        return ExtractedDocument(
            page_count=1,
            pages=[ExtractedPage(page_number=1, text="fallback", low_text=False)],
            full_text="fallback",
            source="pymupdf",
            fallback_reason=fallback_reason,
        )

    monkeypatch.setattr("app.services.extraction._extract_pdf_text_with_marker", fail_marker)
    monkeypatch.setattr("app.services.extraction._extract_pdf_text_with_pymupdf", fake_pymupdf)

    extracted = extract_pdf_text(pdf_path, extractor="marker")

    assert extracted.source == "pymupdf"
    assert extracted.fallback_reason == "Marker unavailable: marker missing"
