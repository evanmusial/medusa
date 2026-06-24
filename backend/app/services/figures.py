from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
import re

from sqlalchemy.orm import Session

from app.models import Document, Figure
from app.services.extraction import normalize_extracted_text
from app.services.extraction import ExtractedFigure, extract_pdf_figures, extract_pdf_figures_for_page
from app.services.storage import get_storage_service


def figure_asset_key(document: Document, page_number: int, figure_index: int, extension: str) -> str:
    checksum = document.checksum_sha256
    return f"figures/{checksum[:2]}/{checksum}/page-{page_number:04d}-figure-{figure_index:03d}.{extension}"


def _page_text(document: Document, page_number: int | None) -> str:
    if not page_number:
        return ""
    page = next((candidate for candidate in document.pages if candidate.page_number == page_number), None)
    if not page:
        return ""
    return normalize_extracted_text(page.normalized_text if page.normalized_text is not None else page.text)


def _context_window(text: str, caption: str | None) -> str:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text) if paragraph.strip()]
    if not paragraphs:
        return ""
    if caption:
        caption_key = re.sub(r"\s+", " ", caption).lower()[:80]
        for index, paragraph in enumerate(paragraphs):
            if caption_key and caption_key in re.sub(r"\s+", " ", paragraph).lower():
                return "\n\n".join(paragraphs[max(0, index - 1) : index + 2])[:2000]
    return "\n\n".join(paragraphs[:3])[:2000]


def enrich_figure_context(document: Document) -> dict[str, int]:
    context_count = 0
    explicit_mentions = 0
    pages_by_number = {page.page_number: _page_text(document, page.page_number) for page in document.pages}
    for figure in document.figures:
        text = pages_by_number.get(figure.page_number or 0, "")
        mentions: list[str] = []
        if figure.figure_label:
            label_pattern = re.escape(figure.figure_label.strip())
            mentions.extend(match.group(0) for match in re.finditer(label_pattern, text, flags=re.IGNORECASE))
        mentions.extend(match.group(0) for match in re.finditer(r"\b(?:figure|fig\.?|table)\s+\d+[a-z]?\b", text, flags=re.IGNORECASE))
        unique_mentions = sorted(set(mentions))[:12]
        context = {
            "context_source": "local_page_text",
            "nearby_text": _context_window(text, figure.caption),
            "explicit_mentions": unique_mentions,
            "caption_present": bool(figure.caption),
        }
        geometry = dict(figure.geometry or {})
        geometry["context"] = context
        figure.geometry = geometry
        if not figure.gist and context["nearby_text"]:
            figure.gist = context["nearby_text"][:500]
        if context["nearby_text"] or unique_mentions:
            context_count += 1
            explicit_mentions += len(unique_mentions)
    return {"figures_with_context": context_count, "explicit_mentions": explicit_mentions}


def _figure_payload(figure: Figure) -> dict[str, object]:
    return {
        "id": figure.id,
        "page_number": figure.page_number,
        "figure_label": figure.figure_label,
        "caption": figure.caption,
        "gist": figure.gist,
        "asset_uri": figure.asset_uri,
        "geometry": figure.geometry or {},
    }


def _store_extracted_figures(
    db: Session,
    document: Document,
    extracted: list[ExtractedFigure],
    *,
    extraction_scope: str,
) -> list[Figure]:
    storage = get_storage_service()
    stored_figures: list[Figure] = []
    for index, figure in enumerate(extracted, start=1):
        key = figure_asset_key(document, figure.page_number, index, figure.extension)
        stored = storage.put_bytes(key, figure.data, figure.content_type)
        label = figure.label or f"Figure {index}"
        caption = figure.caption
        gist = caption or f"Extracted {figure.source.replace('_', ' ')} on page {figure.page_number} ({figure.width}x{figure.height})."
        stored_figure = Figure(
            document_id=document.id,
            page_number=figure.page_number,
            figure_label=label,
            caption=caption,
            gist=gist,
            asset_uri=stored.uri,
            geometry={
                "source": figure.source,
                "bbox": list(figure.bbox or []),
                "width": figure.width,
                "height": figure.height,
                "content_type": figure.content_type,
                "orientation": "landscape" if figure.width >= figure.height else "portrait",
                "extraction_scope": extraction_scope,
            },
        )
        document.figures.append(stored_figure)
        stored_figures.append(stored_figure)
    return stored_figures


def process_document_figures(db: Session, document: Document, pdf_path: Path) -> dict[str, int | list[dict[str, str]]]:
    extracted = extract_pdf_figures(pdf_path)
    document.figures.clear()
    db.flush()
    _store_extracted_figures(db, document, extracted, extraction_scope="document")
    db.flush()
    context = enrich_figure_context(document)
    warnings: list[dict[str, str]] = []
    if not extracted and document.page_count:
        warnings.append({"code": "no_visual_assets_found", "message": "No extractable figure, chart, photo, or diagram regions were found."})
    return {"figures": len(extracted), **context, "audit_warnings": warnings}


def process_document_figures_page(db: Session, document: Document, pdf_path: Path, page_number: int) -> dict[str, object]:
    extracted = extract_pdf_figures_for_page(pdf_path, page_number)
    existing_page_figures = [figure for figure in document.figures if figure.page_number == page_number]
    before = [_figure_payload(figure) for figure in existing_page_figures]
    replaced = 0
    if extracted:
        for figure in existing_page_figures:
            document.figures.remove(figure)
            db.delete(figure)
        replaced = len(existing_page_figures)
        db.flush()
        stored = _store_extracted_figures(db, document, extracted, extraction_scope="page_scan")
        db.flush()
        created = [_figure_payload(figure) for figure in stored]
    else:
        created = []
    context = enrich_figure_context(document)
    warnings: list[dict[str, str]] = []
    if not extracted:
        warnings.append(
            {
                "code": "no_visual_assets_found_on_page",
                "message": f"No extractable figure, chart, photo, diagram, or table-like visual regions were found on page {page_number}.",
            }
        )
    return {
        "page_number": page_number,
        "figures": len(extracted),
        "replaced_figures": replaced,
        "preserved_existing": bool(existing_page_figures and not extracted),
        "created_figures": created,
        "replaced_page_figures": before if replaced else [],
        **context,
        "audit_warnings": warnings,
    }


def process_document_figures_from_storage(db: Session, document: Document) -> dict[str, int | list[dict[str, str]]]:
    if not document.gcs_uri:
        return {"figures": 0}
    storage = get_storage_service()
    data = storage.get_bytes(document.gcs_uri)
    with NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        return process_document_figures(db, document, Path(handle.name))


def process_document_figures_page_from_storage(db: Session, document: Document, page_number: int) -> dict[str, object]:
    if not document.gcs_uri:
        return {
            "page_number": page_number,
            "figures": 0,
            "replaced_figures": 0,
            "preserved_existing": False,
            "audit_warnings": [{"code": "original_unavailable", "message": "The original PDF is unavailable for page visual scanning."}],
        }
    storage = get_storage_service()
    data = storage.get_bytes(document.gcs_uri)
    with NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        return process_document_figures_page(db, document, Path(handle.name), page_number)
