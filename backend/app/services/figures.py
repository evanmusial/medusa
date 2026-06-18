from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy.orm import Session

from app.models import Document, Figure
from app.services.extraction import extract_pdf_figures
from app.services.storage import get_storage_service


def figure_asset_key(document: Document, page_number: int, figure_index: int, extension: str) -> str:
    checksum = document.checksum_sha256
    return f"figures/{checksum[:2]}/{checksum}/page-{page_number:04d}-figure-{figure_index:03d}.{extension}"


def process_document_figures(db: Session, document: Document, pdf_path: Path) -> dict[str, int]:
    storage = get_storage_service()
    extracted = extract_pdf_figures(pdf_path)
    document.figures.clear()
    db.flush()
    for index, figure in enumerate(extracted, start=1):
        key = figure_asset_key(document, figure.page_number, index, figure.extension)
        stored = storage.put_bytes(key, figure.data, figure.content_type)
        db.add(
            Figure(
                document_id=document.id,
                page_number=figure.page_number,
                figure_label=f"Figure {index}",
                caption=None,
                gist=f"Extracted image on page {figure.page_number} ({figure.width}x{figure.height}).",
                asset_uri=stored.uri,
            )
        )
    return {"figures": len(extracted)}


def process_document_figures_from_storage(db: Session, document: Document) -> dict[str, int]:
    if not document.gcs_uri:
        return {"figures": 0}
    storage = get_storage_service()
    data = storage.get_bytes(document.gcs_uri)
    with NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        return process_document_figures(db, document, Path(handle.name))
