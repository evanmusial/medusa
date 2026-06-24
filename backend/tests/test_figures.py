import struct
import zlib

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def png_bytes(width=120, height=100):
    raw_rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(((x * 3 + y) % 256, (x + y * 5) % 256, (x * y) % 256))
        raw_rows.append(b"\x00" + bytes(row))
    raw = b"".join(raw_rows)

    def chunk(kind, data):
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def write_pdf_with_image(path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((48, 48), "Figure fixture")
    page.insert_image(fitz.Rect(80, 90, 260, 240), stream=png_bytes())
    page.insert_text((86, 262), "Figure 1. Fixture diagram.")
    doc.save(path)
    doc.close()


def write_pdf_with_small_displayed_image(path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((48, 48), "Small figure fixture")
    page.insert_image(fitz.Rect(120, 90, 192, 180), stream=png_bytes(width=300, height=375))
    page.insert_text((86, 206), "Figure 3. Small displayed portrait.")
    doc.save(path)
    doc.close()


def write_pdf_with_vector_chart(path):
    doc = fitz.open()
    page = doc.new_page(width=420, height=420)
    page.draw_rect(fitz.Rect(80, 80, 300, 250), color=(0.1, 0.1, 0.1), width=1)
    page.draw_line(fitz.Point(105, 220), fitz.Point(280, 220), color=(0.1, 0.1, 0.1), width=1)
    page.draw_line(fitz.Point(105, 95), fitz.Point(105, 220), color=(0.1, 0.1, 0.1), width=1)
    page.draw_rect(fitz.Rect(125, 170, 150, 220), color=(0.2, 0.45, 0.85), fill=(0.2, 0.45, 0.85))
    page.draw_rect(fitz.Rect(170, 135, 195, 220), color=(0.2, 0.6, 0.5), fill=(0.2, 0.6, 0.5))
    page.draw_rect(fitz.Rect(215, 105, 240, 220), color=(0.8, 0.45, 0.2), fill=(0.8, 0.45, 0.2))
    page.insert_text((86, 274), "Figure 2. Model output by condition.")
    doc.save(path)
    doc.close()


def write_pdf_with_two_page_figures(path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((48, 48), "First figure fixture")
    page.insert_image(fitz.Rect(80, 90, 260, 240), stream=png_bytes())
    page.insert_text((86, 262), "Figure 1. First fixture.")
    page = doc.new_page(width=400, height=400)
    page.insert_text((48, 48), "Second figure fixture")
    page.insert_image(fitz.Rect(90, 95, 270, 245), stream=png_bytes(width=140, height=120))
    page.insert_text((86, 267), "Figure 2. Second fixture.")
    doc.save(path)
    doc.close()


def write_pdf_with_second_page_text_only(path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((48, 48), "First figure fixture")
    page.insert_image(fitz.Rect(80, 90, 260, 240), stream=png_bytes())
    page.insert_text((86, 262), "Figure 1. First fixture.")
    page = doc.new_page(width=400, height=400)
    page.insert_text((48, 48), "This page has no visual assets.")
    doc.save(path)
    doc.close()


def configure_local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.setenv("GCS_BUCKET", "")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    from app.config import get_settings

    get_settings.cache_clear()


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_extract_pdf_figures_reads_embedded_images(tmp_path):
    from app.services.extraction import extract_pdf_figures

    path = tmp_path / "figure.pdf"
    write_pdf_with_image(path)

    figures = extract_pdf_figures(path, min_bytes=1)

    assert len(figures) == 1
    assert figures[0].page_number == 1
    assert figures[0].width >= 740
    assert figures[0].height >= 615
    assert figures[0].bbox
    assert figures[0].label == "Figure 1"
    assert figures[0].caption == "Figure 1. Fixture diagram."


def test_extract_pdf_figures_prefers_rendered_small_displayed_images(tmp_path):
    from app.services.extraction import extract_pdf_figures

    path = tmp_path / "small-displayed-figure.pdf"
    write_pdf_with_small_displayed_image(path)

    figures = extract_pdf_figures(path, min_bytes=1)

    assert len(figures) == 1
    assert figures[0].source == "page_image"
    assert figures[0].width >= 295
    assert figures[0].height >= 370
    assert figures[0].bbox
    assert figures[0].label == "Figure 3"
    assert figures[0].caption == "Figure 3. Small displayed portrait."


def test_extract_pdf_figures_crops_vector_graphics(tmp_path):
    from app.services.extraction import extract_pdf_figures

    path = tmp_path / "vector-figure.pdf"
    write_pdf_with_vector_chart(path)

    figures = extract_pdf_figures(path, min_bytes=1)

    assert len(figures) == 1
    assert figures[0].source == "vector_graphic"
    assert figures[0].label == "Figure 2"
    assert figures[0].caption == "Figure 2. Model output by condition."
    assert figures[0].bbox


def test_extract_pdf_figures_for_page_scopes_to_one_page(tmp_path):
    from app.services.extraction import extract_pdf_figures_for_page

    path = tmp_path / "two-page-figures.pdf"
    write_pdf_with_two_page_figures(path)

    figures = extract_pdf_figures_for_page(path, 2, min_bytes=1)

    assert len(figures) == 1
    assert figures[0].page_number == 2
    assert figures[0].label == "Figure 2"
    assert figures[0].caption == "Figure 2. Second fixture."


def test_process_document_figures_stores_assets(monkeypatch, tmp_path):
    configure_local_storage(monkeypatch, tmp_path)

    from app.models import Document
    from app.services.figures import process_document_figures

    path = tmp_path / "figure.pdf"
    write_pdf_with_image(path)
    Session = make_session()
    with Session() as db:
        document = Document(title="Figure Paper", original_filename="figure.pdf", checksum_sha256="1" * 64)
        db.add(document)
        db.flush()

        result = process_document_figures(db, document, path)
        db.commit()
        db.refresh(document)

        assert result["figures"] == 1
        assert result["audit_warnings"] == []
        assert len(document.figures) == 1
        assert document.figures[0].asset_uri
        assert document.figures[0].figure_label == "Figure 1"
        assert document.figures[0].caption == "Figure 1. Fixture diagram."
        assert document.figures[0].geometry["source"] == "page_image"
        assert document.figures[0].geometry["bbox"]


def test_process_document_figures_page_replaces_only_target_page(monkeypatch, tmp_path):
    configure_local_storage(monkeypatch, tmp_path)

    from app.models import Document
    from app.services.figures import process_document_figures, process_document_figures_page

    path = tmp_path / "two-page-figures.pdf"
    write_pdf_with_two_page_figures(path)
    Session = make_session()
    with Session() as db:
        document = Document(title="Figure Paper", original_filename="figure.pdf", checksum_sha256="2" * 64, page_count=2)
        db.add(document)
        db.flush()

        process_document_figures(db, document, path)
        db.commit()
        original_page_two_id = next(figure.id for figure in document.figures if figure.page_number == 2)

        result = process_document_figures_page(db, document, path, 1)
        db.commit()
        db.refresh(document)

        assert result["figures"] == 1
        assert result["replaced_figures"] == 1
        assert len(document.figures) == 2
        assert any(figure.id == original_page_two_id for figure in document.figures)
        page_one = next(figure for figure in document.figures if figure.page_number == 1)
        assert page_one.geometry["extraction_scope"] == "page_scan"


def test_process_document_figures_page_preserves_existing_when_scan_finds_none(monkeypatch, tmp_path):
    configure_local_storage(monkeypatch, tmp_path)

    from app.models import Document
    from app.services.figures import process_document_figures, process_document_figures_page

    path = tmp_path / "second-page-text-only.pdf"
    write_pdf_with_second_page_text_only(path)
    Session = make_session()
    with Session() as db:
        document = Document(title="Figure Paper", original_filename="figure.pdf", checksum_sha256="3" * 64, page_count=2)
        db.add(document)
        db.flush()

        process_document_figures(db, document, path)
        db.commit()
        original_figure_ids = {figure.id for figure in document.figures}

        result = process_document_figures_page(db, document, path, 2)
        db.commit()
        db.refresh(document)

        assert result["figures"] == 0
        assert result["preserved_existing"] is False
        assert {figure.id for figure in document.figures} == original_figure_ids
