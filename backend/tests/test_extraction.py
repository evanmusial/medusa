from app.services.extraction import LayoutBlock, blocks_to_text, rows_to_markdown, split_text_into_chunks


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
