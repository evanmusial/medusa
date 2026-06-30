from __future__ import annotations

import base64
from pathlib import Path
from tempfile import NamedTemporaryFile
import re

from sqlalchemy.orm import Session

from app.models import Document, Figure
from app.services.extraction import normalize_extracted_text
from app.services.extraction import ExtractedFigure, extract_pdf_figures, extract_pdf_figures_for_page
from app.services.storage import get_storage_service

FIGURE_MARKER_LINE_RE = re.compile(r"^\s*!\[[^\]\n]*\]\(medusa-figure:[A-Za-z0-9-]+\)\s*$")


def figure_asset_key(document: Document, page_number: int, figure_index: int, extension: str) -> str:
    checksum = document.checksum_sha256
    return f"figures/{checksum[:2]}/{checksum}/page-{page_number:04d}-figure-{figure_index:03d}.{extension}"


def _figure_marker(figure: Figure) -> str:
    label = (figure.figure_label or figure.caption or f"Page {figure.page_number or '?'} figure").strip()
    label = re.sub(r"\s+", " ", label).replace("[", "(").replace("]", ")")
    return f"![{label}](medusa-figure:{figure.id})"


def _strip_figure_markers(text: str | None) -> tuple[str, int]:
    if not text:
        return "", 0
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    removed = 0
    kept_lines: list[str] = []
    for line in normalized_text.split("\n"):
        if FIGURE_MARKER_LINE_RE.match(line):
            removed += 1
            continue
        kept_lines.append(line)
    if not removed:
        return normalized_text, 0
    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, removed


def strip_figure_markers_from_text(text: str | None) -> str:
    return _strip_figure_markers(text)[0]


def _normalized_for_match(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _target_line_for_figure(lines: list[str], figure: Figure) -> int | None:
    candidates = [_normalized_for_match(figure.caption), _normalized_for_match(figure.figure_label)]
    candidates = [candidate for candidate in candidates if candidate]
    for candidate in candidates:
        for index, line in enumerate(lines):
            normalized_line = _normalized_for_match(line)
            if candidate in normalized_line or normalized_line in candidate:
                return index

    geometry = figure.geometry or {}
    bbox = geometry.get("bbox")
    page_height = geometry.get("page_height")
    try:
        if isinstance(bbox, list) and len(bbox) >= 2 and page_height:
            ratio = max(0.0, min(1.0, float(bbox[1]) / float(page_height)))
            return min(len(lines), max(0, round(ratio * len(lines))))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def _insert_figure_marker(text: str, figure: Figure) -> str:
    marker = _figure_marker(figure)
    lines = text.split("\n") if text else []
    target = _target_line_for_figure(lines, figure)
    if target is None:
        target = len(lines)

    while target > 0 and lines[target - 1].strip():
        target -= 1
    if target > 0 and lines[target - 1].strip() != "":
        lines.insert(target, "")
        target += 1
    lines.insert(target, marker)
    if target + 1 < len(lines) and lines[target + 1].strip():
        lines.insert(target + 1, "")
    elif target + 1 == len(lines):
        lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _figure_sort_y(figure: Figure) -> float:
    bbox = (figure.geometry or {}).get("bbox")
    try:
        return float(bbox[1]) if isinstance(bbox, list) and len(bbox) >= 2 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _page_reading_text(page: object) -> str:
    normalized_text = getattr(page, "normalized_text", None)
    if normalized_text is not None:
        return normalized_text or ""
    return getattr(page, "text", None) or ""


def _set_page_reading_text(page: object, text: str) -> None:
    if getattr(page, "normalized_text", None) is not None:
        setattr(page, "normalized_text", text)
    else:
        setattr(page, "text", text)


def document_reader_text_by_page_number(document: Document) -> dict[int, str]:
    """Return page reading text with live figure markers derived from current Figure rows."""
    pages_by_number = {page.page_number: page for page in sorted(document.pages, key=lambda item: item.page_number)}
    text_by_page: dict[int, str] = {
        page_number: _strip_figure_markers(_page_reading_text(page))[0]
        for page_number, page in pages_by_number.items()
    }
    figures = sorted(
        (figure for figure in document.figures if figure.id and figure.page_number in pages_by_number),
        key=lambda figure: (figure.page_number or 0, _figure_sort_y(figure), figure.figure_label or "", figure.id),
    )
    for figure in figures:
        page_number = int(figure.page_number or 0)
        text_by_page[page_number] = _insert_figure_marker(text_by_page.get(page_number, ""), figure)
    return text_by_page


def sync_document_figure_markers(document: Document) -> dict[str, int]:
    """Keep Markdown figure markers in page text aligned with the current Figure rows."""
    pages_by_number = {page.page_number: page for page in sorted(document.pages, key=lambda item: item.page_number)}
    text_by_page: dict[int, str] = {}
    removed_markers = 0
    for page_number, page in pages_by_number.items():
        cleaned, removed = _strip_figure_markers(_page_reading_text(page))
        text_by_page[page_number] = cleaned
        removed_markers += removed

    marked = 0
    figures = sorted(
        (figure for figure in document.figures if figure.id and figure.page_number in pages_by_number),
        key=lambda figure: (figure.page_number or 0, _figure_sort_y(figure), figure.figure_label or "", figure.id),
    )
    for figure in figures:
        page_number = int(figure.page_number or 0)
        text_by_page[page_number] = _insert_figure_marker(text_by_page.get(page_number, ""), figure)
        marked += 1

    pages_changed = 0
    for page_number, page in pages_by_number.items():
        next_text = text_by_page.get(page_number, "")
        if next_text != _page_reading_text(page):
            _set_page_reading_text(page, next_text)
            pages_changed += 1

    return {"figures_marked": marked, "markers_removed": removed_markers, "pages_changed": pages_changed}


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


def _figure_data_url(content_type: str, data: bytes) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def _candidate_payload(figure: ExtractedFigure, index: int, *, page_dimensions: dict[str, float]) -> dict[str, object]:
    label = figure.label or f"Candidate {index}"
    geometry = {
        "source": figure.source,
        "bbox": list(figure.bbox or []),
        "width": figure.width,
        "height": figure.height,
        "content_type": figure.content_type,
        "orientation": "landscape" if figure.width >= figure.height else "portrait",
        "extraction_scope": "page_scan_candidate",
        **page_dimensions,
    }
    return {
        "candidate_id": f"page-{figure.page_number:04d}-candidate-{index:03d}",
        "page_number": figure.page_number,
        "figure_label": label,
        "caption": figure.caption,
        "gist": figure.caption or f"Candidate {index} from {figure.source.replace('_', ' ')} on page {figure.page_number}.",
        "geometry": geometry,
        "image_data_url": _figure_data_url(figure.content_type, figure.data),
    }


def _decode_candidate_image(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:") or "," not in data_url:
        raise ValueError("Candidate image data is missing or invalid.")
    header, encoded = data_url.split(",", 1)
    content_type = header[5:].split(";", 1)[0] or "image/png"
    return content_type, base64.b64decode(encoded)


def _extension_for_content_type(content_type: str) -> str:
    if content_type in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if content_type == "image/webp":
        return "webp"
    return "png"


def _pdf_page_dimensions(path: Path, page_number: int) -> dict[str, float]:
    try:
        import fitz

        with fitz.open(path) as pdf:
            if page_number < 1 or page_number > pdf.page_count:
                return {}
            rect = pdf.load_page(page_number - 1).rect
            return {"page_width": float(rect.width), "page_height": float(rect.height)}
    except Exception:
        return {}


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


def process_document_figures(db: Session, document: Document, pdf_path: Path) -> dict[str, object]:
    extracted = extract_pdf_figures(pdf_path)
    document.figures.clear()
    db.flush()
    _store_extracted_figures(db, document, extracted, extraction_scope="document")
    db.flush()
    context = enrich_figure_context(document)
    inline_markers = sync_document_figure_markers(document)
    db.flush()
    warnings: list[dict[str, str]] = []
    if not extracted and document.page_count:
        warnings.append({"code": "no_visual_assets_found", "message": "No extractable figure, chart, photo, or diagram regions were found."})
    return {"figures": len(extracted), **context, "inline_markers": inline_markers, "audit_warnings": warnings}


def preview_document_figures_page_from_storage(db: Session, document: Document, page_number: int) -> dict[str, object]:
    existing_page_figures = [figure for figure in document.figures if figure.page_number == page_number]
    before = [_figure_payload(figure) for figure in existing_page_figures]
    if not document.gcs_uri:
        return {
            "page_number": page_number,
            "figures": 0,
            "replaced_figures": 0,
            "preserved_existing": bool(existing_page_figures),
            "candidates": [],
            "replaced_page_figures": before,
            "audit_warnings": [{"code": "original_unavailable", "message": "The original PDF is unavailable for page visual scanning."}],
        }
    storage = get_storage_service()
    data = storage.get_bytes(document.gcs_uri)
    with NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        pdf_path = Path(handle.name)
        extracted = extract_pdf_figures_for_page(pdf_path, page_number)
        page_dimensions = _pdf_page_dimensions(pdf_path, page_number)
    candidates = [_candidate_payload(figure, index, page_dimensions=page_dimensions) for index, figure in enumerate(extracted, start=1)]
    warnings: list[dict[str, str]] = []
    if not candidates:
        warnings.append(
            {
                "code": "no_visual_assets_found_on_page",
                "message": f"No extractable figure, chart, photo, diagram, or table-like visual regions were found on page {page_number}.",
            }
        )
    return {
        "page_number": page_number,
        "figures": len(candidates),
        "replaced_figures": len(existing_page_figures) if candidates else 0,
        "preserved_existing": bool(existing_page_figures and not candidates),
        "candidates": candidates,
        "replaced_page_figures": before if candidates else [],
        "audit_warnings": warnings,
    }


def apply_document_figures_page_candidates(
    db: Session,
    document: Document,
    page_number: int,
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    existing_page_figures = [figure for figure in document.figures if figure.page_number == page_number]
    before = [_figure_payload(figure) for figure in existing_page_figures]
    stored_figures: list[Figure] = []
    replaced = 0
    if candidates:
        for figure in existing_page_figures:
            document.figures.remove(figure)
            db.delete(figure)
        replaced = len(existing_page_figures)
        db.flush()
        storage = get_storage_service()
        for index, candidate in enumerate(candidates, start=1):
            content_type, data = _decode_candidate_image(str(candidate.get("image_data_url") or ""))
            geometry = dict(candidate.get("geometry") or {})
            geometry["content_type"] = content_type
            geometry["extraction_scope"] = "page_scan"
            geometry["review_status"] = "kept"
            extension = _extension_for_content_type(content_type)
            stored = storage.put_bytes(figure_asset_key(document, page_number, index, extension), data, content_type)
            label = str(candidate.get("figure_label") or f"Figure {index}")
            caption = candidate.get("caption")
            gist = candidate.get("gist") or caption or f"Reviewed page-scan visual candidate on page {page_number}."
            stored_figure = Figure(
                document_id=document.id,
                page_number=page_number,
                figure_label=label,
                caption=str(caption) if caption else None,
                gist=str(gist) if gist else None,
                asset_uri=stored.uri,
                geometry=geometry,
            )
            document.figures.append(stored_figure)
            stored_figures.append(stored_figure)
        db.flush()
    context = enrich_figure_context(document)
    inline_markers = sync_document_figure_markers(document)
    db.flush()
    warnings: list[dict[str, str]] = []
    if not candidates:
        warnings.append({"code": "page_scan_discarded", "message": f"No page-scan candidates were kept for page {page_number}."})
    return {
        "page_number": page_number,
        "figures": len(stored_figures),
        "replaced_figures": replaced,
        "preserved_existing": bool(existing_page_figures and not candidates),
        "created_figures": [_figure_payload(figure) for figure in stored_figures],
        "replaced_page_figures": before if replaced else [],
        **context,
        "inline_markers": inline_markers,
        "audit_warnings": warnings,
    }


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
    inline_markers = sync_document_figure_markers(document)
    db.flush()
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
        "inline_markers": inline_markers,
        "audit_warnings": warnings,
    }


def process_document_figures_from_storage(db: Session, document: Document) -> dict[str, object]:
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
