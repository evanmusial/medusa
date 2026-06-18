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
    doc.save(path)
    doc.close()


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
    assert figures[0].width == 120
    assert figures[0].height == 100


def test_process_document_figures_stores_assets(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    monkeypatch.delenv("GCS_BUCKET", raising=False)

    from app.config import get_settings
    from app.models import Document
    from app.services.figures import process_document_figures

    get_settings.cache_clear()
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

        assert result == {"figures": 1}
        assert len(document.figures) == 1
        assert document.figures[0].asset_uri
        assert document.figures[0].gist.startswith("Extracted image")
