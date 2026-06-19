from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings


@dataclass(frozen=True)
class LayoutBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    kind: str = "text"


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    low_text: bool
    source: str = "pymupdf"


@dataclass
class ExtractedDocument:
    page_count: int
    pages: list[ExtractedPage]
    full_text: str
    source: str = "pymupdf"
    fallback_reason: str | None = None


@dataclass
class ExtractedFigure:
    page_number: int
    index: int
    extension: str
    content_type: str
    data: bytes
    width: int
    height: int
    bbox: tuple[float, float, float, float] | None = None
    label: str | None = None
    caption: str | None = None
    source: str = "image"


@dataclass(frozen=True)
class CaptionCandidate:
    bbox: tuple[float, float, float, float]
    text: str
    label: str


def _block_area(block: LayoutBlock) -> float:
    return max(0.0, block.x1 - block.x0) * max(0.0, block.y1 - block.y0)


def _intersection_ratio(block: LayoutBlock, bbox: tuple[float, float, float, float]) -> float:
    x0 = max(block.x0, bbox[0])
    y0 = max(block.y0, bbox[1])
    x1 = min(block.x1, bbox[2])
    y1 = min(block.y1, bbox[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = _block_area(block)
    return intersection / area if area else 0.0


def _bbox_width(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _bbox_height(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return _bbox_width(bbox) * _bbox_height(bbox)


def _bbox_intersection_area(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _bbox_overlap_ratio(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    smaller = min(_bbox_area(left), _bbox_area(right))
    return _bbox_intersection_area(left, right) / smaller if smaller else 0.0


def _bbox_union(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _expanded_bbox(
    bbox: tuple[float, float, float, float],
    amount: float,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, bbox[0] - amount),
        max(0.0, bbox[1] - amount),
        min(page_width, bbox[2] + amount),
        min(page_height, bbox[3] + amount),
    )


def _is_usable_graphic_bbox(
    bbox: tuple[float, float, float, float],
    *,
    min_width: int,
    min_height: int,
) -> bool:
    return _bbox_width(bbox) >= min_width and _bbox_height(bbox) >= min_height


_UNSAFE_TEXT_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKER_PAGE_BREAK_RE = re.compile(r"(?:^|\n)\s*(?P<page>\d+)\s*\n-{10,}\s*(?:\n|$)")
RAW_TEXT_EXTRACTOR_MARKER = "marker"
RAW_TEXT_EXTRACTOR_PYMUPDF = "pymupdf"
RAW_TEXT_EXTRACTOR_DOCLING = "docling"


def sanitize_extracted_text(text: str | None) -> str:
    """Remove PDF control bytes that can break or pollute persisted text."""
    if not text:
        return ""
    return _UNSAFE_TEXT_CONTROL_RE.sub("", text)


def _cell(value: Any) -> str:
    text = "" if value is None else sanitize_extracted_text(str(value))
    return " ".join(text.replace("|", "\\|").split())


def rows_to_markdown(rows: list[list[Any]]) -> str:
    cleaned = [[_cell(cell) for cell in row] for row in rows if any(_cell(cell) for cell in row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    normalized = [row + [""] * (width - len(row)) for row in cleaned]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:]
    table_rows = [header, separator, *body]
    return "\n".join("| " + " | ".join(row) + " |" for row in table_rows)


def _extract_table_blocks(page: Any) -> list[LayoutBlock]:
    if not hasattr(page, "find_tables"):
        return []
    try:
        finder = page.find_tables()
    except Exception:
        return []
    tables = getattr(finder, "tables", finder)
    blocks: list[LayoutBlock] = []
    for index, table in enumerate(tables or [], start=1):
        rows = table.extract()
        markdown = rows_to_markdown(rows)
        if not markdown:
            continue
        bbox = tuple(float(part) for part in table.bbox)
        blocks.append(
            LayoutBlock(
                x0=bbox[0],
                y0=bbox[1],
                x1=bbox[2],
                y1=bbox[3],
                text=f"Table {index}\n{markdown}",
                kind="table",
            )
        )
    return blocks


def extract_layout_blocks(page: Any) -> list[LayoutBlock]:
    table_blocks = _extract_table_blocks(page)
    table_bboxes = [(block.x0, block.y0, block.x1, block.y1) for block in table_blocks]
    blocks: list[LayoutBlock] = []
    for raw in page.get_text("blocks"):
        if len(raw) < 5:
            continue
        block_type = raw[6] if len(raw) > 6 else 0
        if block_type != 0:
            continue
        block = LayoutBlock(
            x0=float(raw[0]),
            y0=float(raw[1]),
            x1=float(raw[2]),
            y1=float(raw[3]),
            text=sanitize_extracted_text(str(raw[4])).strip(),
        )
        if not block.text:
            continue
        if any(_intersection_ratio(block, bbox) > 0.45 for bbox in table_bboxes):
            continue
        blocks.append(block)
    return [*blocks, *table_blocks]


_FIGURE_LABEL_RE = re.compile(
    r"^\s*(?P<label>(?:fig(?:ure)?\.?|chart|photo|plate|image)\s*[A-Z0-9][A-Z0-9.\-]*)\s*[:.\-]?\s*(?P<caption>.*)$",
    re.IGNORECASE,
)


def _caption_candidates(page: Any) -> list[CaptionCandidate]:
    candidates: list[CaptionCandidate] = []
    for raw in page.get_text("blocks"):
        if len(raw) < 5:
            continue
        block_type = raw[6] if len(raw) > 6 else 0
        if block_type != 0:
            continue
        text = " ".join(sanitize_extracted_text(str(raw[4])).split())
        if not text:
            continue
        match = _FIGURE_LABEL_RE.match(text)
        if not match:
            continue
        candidates.append(
            CaptionCandidate(
                bbox=(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])),
                text=text,
                label=match.group("label").strip().rstrip(".:-"),
            )
        )
    return candidates


def _horizontal_overlap_ratio(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    smaller = min(_bbox_width(left), _bbox_width(right))
    return overlap / smaller if smaller else 0.0


def _nearest_caption(
    captions: list[CaptionCandidate],
    bbox: tuple[float, float, float, float],
) -> CaptionCandidate | None:
    best: tuple[float, CaptionCandidate] | None = None
    for caption in captions:
        if _horizontal_overlap_ratio(caption.bbox, bbox) < 0.25:
            continue
        gap_below = caption.bbox[1] - bbox[3]
        gap_above = bbox[1] - caption.bbox[3]
        if 0 <= gap_below <= 140:
            score = gap_below
        elif 0 <= gap_above <= 100:
            score = gap_above + 35
        else:
            continue
        if best is None or score < best[0]:
            best = (score, caption)
    return best[1] if best else None


def _rect_to_bbox(rect: Any) -> tuple[float, float, float, float] | None:
    try:
        x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
    except AttributeError:
        try:
            x0, y0, x1, y1 = (float(part) for part in rect)
        except Exception:
            return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _image_bboxes(page: Any) -> list[tuple[float, float, float, float]]:
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        return []
    bboxes: list[tuple[float, float, float, float]] = []
    for block in blocks:
        if block.get("type") != 1:
            continue
        bbox = _rect_to_bbox(block.get("bbox"))
        if bbox:
            bboxes.append(bbox)
    return bboxes


def _close_enough(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    gap: float,
    page_width: float,
    page_height: float,
) -> bool:
    return _bbox_intersection_area(
        _expanded_bbox(left, gap, page_width, page_height),
        _expanded_bbox(right, gap, page_width, page_height),
    ) > 0


def _cluster_bboxes(
    bboxes: list[tuple[float, float, float, float]],
    *,
    gap: float,
    page_width: float,
    page_height: float,
) -> list[tuple[float, float, float, float]]:
    clusters = bboxes[:]
    changed = True
    while changed:
        changed = False
        next_clusters: list[tuple[float, float, float, float]] = []
        while clusters:
            current = clusters.pop(0)
            index = 0
            while index < len(clusters):
                candidate = clusters[index]
                if _close_enough(current, candidate, gap=gap, page_width=page_width, page_height=page_height):
                    current = _bbox_union(current, candidate)
                    clusters.pop(index)
                    changed = True
                else:
                    index += 1
            next_clusters.append(current)
        clusters = next_clusters
    return clusters


def _drawing_bboxes(page: Any, *, min_width: int, min_height: int) -> list[tuple[float, float, float, float]]:
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    raw_bboxes: list[tuple[float, float, float, float]] = []
    for drawing in drawings:
        bbox = _rect_to_bbox(drawing.get("rect"))
        if not bbox:
            continue
        if _bbox_width(bbox) < 3 or _bbox_height(bbox) < 3:
            continue
        raw_bboxes.append(bbox)
    clusters = _cluster_bboxes(raw_bboxes, gap=20.0, page_width=page_width, page_height=page_height)
    return [
        _expanded_bbox(cluster, 4.0, page_width, page_height)
        for cluster in clusters
        if _is_usable_graphic_bbox(cluster, min_width=min_width, min_height=min_height) and _bbox_area(cluster) >= 4_800
    ]


def _column_split(blocks: list[LayoutBlock], page_width: float) -> float | None:
    if len(blocks) < 4:
        return None
    centers = sorted((block.x0 + block.x1) / 2 for block in blocks)
    if centers[-1] - centers[0] < page_width * 0.25:
        return None
    gaps = [(centers[index + 1] - centers[index], index) for index in range(len(centers) - 1)]
    largest_gap, gap_index = max(gaps, default=(0.0, 0))
    if largest_gap < page_width * 0.12:
        return None
    left_count = gap_index + 1
    right_count = len(centers) - left_count
    if left_count < 2 or right_count < 2:
        return None
    return (centers[gap_index] + centers[gap_index + 1]) / 2


def _emit_columns(blocks: list[LayoutBlock], split_at: float) -> list[LayoutBlock]:
    left = [block for block in blocks if (block.x0 + block.x1) / 2 <= split_at]
    right = [block for block in blocks if (block.x0 + block.x1) / 2 > split_at]
    return sorted(left, key=lambda block: (block.y0, block.x0)) + sorted(right, key=lambda block: (block.y0, block.x0))


def order_blocks_for_reading(blocks: list[LayoutBlock], page_width: float) -> list[LayoutBlock]:
    if not blocks:
        return []
    full_width = [block for block in blocks if (block.x1 - block.x0) >= page_width * 0.65]
    full_width_ids = {id(block) for block in full_width}
    column_candidates = [block for block in blocks if id(block) not in full_width_ids]
    split_at = _column_split(column_candidates, page_width)
    if split_at is None:
        return sorted(blocks, key=lambda block: (block.y0, block.x0))

    ordered: list[LayoutBlock] = []
    remaining_columns = sorted(column_candidates, key=lambda block: (block.y0, block.x0))
    for wide in sorted(full_width, key=lambda block: (block.y0, block.x0)):
        before = [block for block in remaining_columns if block.y0 < wide.y0]
        if before:
            ordered.extend(_emit_columns(before, split_at))
            before_ids = {id(block) for block in before}
            remaining_columns = [block for block in remaining_columns if id(block) not in before_ids]
        ordered.append(wide)
    if remaining_columns:
        ordered.extend(_emit_columns(remaining_columns, split_at))
    return ordered


def blocks_to_text(blocks: list[LayoutBlock], page_width: float) -> str:
    return sanitize_extracted_text(
        "\n\n".join(block.text for block in order_blocks_for_reading(blocks, page_width) if block.text)
    ).strip()


_SPACED_LETTERS_RE = re.compile(r"\b(?:[A-Za-z]\s+){2,}[A-Za-z]\b")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?%\]\)])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([\[\(])\s+")
_BROKEN_HYPHEN_RE = re.compile(r"(\w)-\s+(\w)")


def _join_spaced_letters(match: re.Match[str]) -> str:
    return match.group(0).replace(" ", "")


def _normalize_inline_spacing(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", sanitize_extracted_text(text))
    normalized = normalized.replace("\u00ad", "")
    normalized = normalized.replace("\u200b", "")
    normalized = normalized.replace("\u200c", "")
    normalized = normalized.replace("\u200d", "")
    normalized = normalized.replace("\ufeff", "")
    normalized = normalized.replace("\t", " ")
    normalized = _SPACED_LETTERS_RE.sub(_join_spaced_letters, normalized)
    normalized = _BROKEN_HYPHEN_RE.sub(r"\1\2", normalized)
    normalized = re.sub(r"[ ]{2,}", " ", normalized)
    normalized = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", normalized)
    normalized = _SPACE_AFTER_OPEN_RE.sub(r"\1", normalized)
    return normalized.strip()


def _join_paragraph_lines(lines: list[str]) -> str:
    joined = ""
    for line in lines:
        clean = _normalize_inline_spacing(line)
        if not clean:
            continue
        if not joined:
            joined = clean
            continue
        if joined.endswith("-") and clean[:1].islower():
            joined = f"{joined[:-1]}{clean}"
        else:
            joined = f"{joined} {clean}"
    return _normalize_inline_spacing(joined)


def _is_markdown_table(lines: list[str]) -> bool:
    table_lines = [line for line in lines if line.strip().startswith("|") and line.strip().endswith("|")]
    return len(table_lines) >= 2


def normalize_extracted_text(text: str | None) -> str:
    """Turn layout-oriented PDF text into readable paragraph-oriented text."""
    if not text:
        return ""
    source = sanitize_extracted_text(text).replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n+", source):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if _is_markdown_table(lines):
            paragraphs.append("\n".join(_normalize_inline_spacing(line) for line in lines))
            continue
        paragraph = _join_paragraph_lines(lines)
        if paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs).strip()


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("PyMuPDF is required for PDF page counting") from exc

    with fitz.open(path) as pdf:
        return len(pdf)


def _extract_pdf_text_with_pymupdf(path: Path, *, fallback_reason: str | None = None) -> ExtractedDocument:
    settings = get_settings()
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("PyMuPDF is required for PDF extraction") from exc

    pages: list[ExtractedPage] = []
    with fitz.open(path) as pdf:
        for index, page in enumerate(pdf, start=1):
            text = sanitize_extracted_text(blocks_to_text(extract_layout_blocks(page), float(page.rect.width)))
            low_text = len(text) < settings.low_text_page_threshold
            pages.append(ExtractedPage(page_number=index, text=text, low_text=low_text))
    full_text = sanitize_extracted_text("\n\n".join(page.text for page in pages if page.text))
    return ExtractedDocument(
        page_count=len(pages),
        pages=pages,
        full_text=full_text,
        source=RAW_TEXT_EXTRACTOR_PYMUPDF,
        fallback_reason=fallback_reason,
    )


def _split_marker_paginated_markdown(markdown: str, page_count: int) -> list[ExtractedPage]:
    settings = get_settings()
    clean = sanitize_extracted_text(markdown)
    matches = list(_MARKER_PAGE_BREAK_RE.finditer(clean))
    if not matches:
        raise RuntimeError("Marker did not return paginated Markdown.")

    raw_page_numbers = [int(match.group("page")) for match in matches]
    offset = 1 if 0 in raw_page_numbers else 0
    by_page: dict[int, str] = {}
    for index, match in enumerate(matches):
        page_number = int(match.group("page")) + offset
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
        if page_number < 1:
            continue
        by_page[page_number] = clean[start:end].strip()

    if not by_page:
        raise RuntimeError("Marker pagination did not contain any page text.")

    pages: list[ExtractedPage] = []
    for page_number in range(1, max(page_count, max(by_page)) + 1):
        text = by_page.get(page_number, "")
        pages.append(
            ExtractedPage(
                page_number=page_number,
                text=text,
                low_text=len(text) < settings.low_text_page_threshold,
                source=RAW_TEXT_EXTRACTOR_MARKER,
            )
        )
    return pages


def _extract_pdf_text_with_marker(path: Path) -> ExtractedDocument:
    settings = get_settings()
    marker_binary = shutil.which("marker_single")
    if not marker_binary:
        raise RuntimeError("Marker is not installed in this worker image.")

    page_count = _pdf_page_count(path)
    with tempfile.TemporaryDirectory(prefix="medusa-marker-") as output_dir:
        command = [
            marker_binary,
            str(path),
            "--output_dir",
            output_dir,
            "--output_format",
            "markdown",
            "--paginate_output",
            "--disable_image_extraction",
        ]
        env = os.environ.copy()
        subprocess.run(
            command,
            check=True,
            cwd=output_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=settings.raw_text_extraction_timeout_seconds,
        )
        markdown_files = sorted(Path(output_dir).rglob("*.md"))
        if not markdown_files:
            raise RuntimeError("Marker did not write Markdown output.")
        markdown = markdown_files[0].read_text(encoding="utf-8", errors="replace")

    pages = _split_marker_paginated_markdown(markdown, page_count)
    full_text = sanitize_extracted_text("\n\n".join(page.text for page in pages if page.text))
    return ExtractedDocument(
        page_count=max(page_count, len(pages)),
        pages=pages,
        full_text=full_text,
        source=RAW_TEXT_EXTRACTOR_MARKER,
    )


def extract_pdf_text(path: Path, extractor: str | None = None) -> ExtractedDocument:
    selected = (extractor or RAW_TEXT_EXTRACTOR_PYMUPDF).strip().lower()
    if selected == RAW_TEXT_EXTRACTOR_MARKER:
        try:
            return _extract_pdf_text_with_marker(path)
        except Exception as exc:
            return _extract_pdf_text_with_pymupdf(path, fallback_reason=f"Marker unavailable: {exc}")
    if selected == RAW_TEXT_EXTRACTOR_DOCLING:
        return _extract_pdf_text_with_pymupdf(path, fallback_reason="Docling raw extraction is not wired yet.")
    if selected == RAW_TEXT_EXTRACTOR_PYMUPDF:
        return _extract_pdf_text_with_pymupdf(path)
    return _extract_pdf_text_with_pymupdf(path, fallback_reason=f"Raw extraction model {selected!r} is not wired yet.")


def _render_page_crop(page: Any, bbox: tuple[float, float, float, float]) -> tuple[bytes, int, int]:
    import fitz

    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(*bbox), alpha=False)
    return pixmap.tobytes("png"), int(pixmap.width), int(pixmap.height)


def _unique_graphic_candidates(
    candidates: list[tuple[tuple[float, float, float, float], str]],
) -> list[tuple[tuple[float, float, float, float], str]]:
    unique: list[tuple[tuple[float, float, float, float], str]] = []
    for bbox, source in sorted(candidates, key=lambda item: (item[0][1], item[0][0], item[0][3], item[0][2])):
        if any(_bbox_overlap_ratio(bbox, existing) > 0.72 for existing, _ in unique):
            continue
        unique.append((bbox, source))
    return unique


def _fallback_embedded_images(
    pdf: Any,
    page: Any,
    page_index: int,
    *,
    min_width: int,
    min_height: int,
    min_bytes: int,
) -> list[ExtractedFigure]:
    figures: list[ExtractedFigure] = []
    seen: set[int] = set()
    for image_index, image in enumerate(page.get_images(full=True), start=1):
        xref = int(image[0])
        if xref in seen:
            continue
        seen.add(xref)
        try:
            extracted = pdf.extract_image(xref)
        except Exception:
            continue
        data = extracted.get("image") or b""
        width = int(extracted.get("width") or 0)
        height = int(extracted.get("height") or 0)
        if width < min_width or height < min_height or len(data) < min_bytes:
            continue
        extension = str(extracted.get("ext") or "png").lower()
        content_type = "image/jpeg" if extension in {"jpg", "jpeg"} else f"image/{extension}"
        figures.append(
            ExtractedFigure(
                page_number=page_index,
                index=image_index,
                extension=extension,
                content_type=content_type,
                data=data,
                width=width,
                height=height,
                source="embedded_image",
            )
        )
    return figures


def extract_pdf_figures(path: Path, *, min_width: int = 80, min_height: int = 80, min_bytes: int = 1500) -> list[ExtractedFigure]:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("PyMuPDF is required for figure extraction") from exc

    figures: list[ExtractedFigure] = []
    with fitz.open(path) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            captions = _caption_candidates(page)
            image_candidates = [(bbox, "page_image") for bbox in _image_bboxes(page)]
            drawing_candidates = [(bbox, "vector_graphic") for bbox in _drawing_bboxes(page, min_width=min_width, min_height=min_height)]
            candidates = _unique_graphic_candidates([*image_candidates, *drawing_candidates])
            page_figures: list[ExtractedFigure] = []
            for figure_index, (bbox, source) in enumerate(candidates, start=1):
                if source != "page_image" and not _is_usable_graphic_bbox(bbox, min_width=min_width, min_height=min_height):
                    continue
                try:
                    data, width, height = _render_page_crop(page, bbox)
                except Exception:
                    continue
                if width < min_width or height < min_height:
                    continue
                if len(data) < min_bytes:
                    continue
                caption = _nearest_caption(captions, bbox)
                page_figures.append(
                    ExtractedFigure(
                        page_number=page_index,
                        index=figure_index,
                        extension="png",
                        content_type="image/png",
                        data=data,
                        width=width,
                        height=height,
                        bbox=bbox,
                        label=caption.label if caption else None,
                        caption=caption.text if caption else None,
                        source=source,
                    )
                )
            figures.extend(
                page_figures
                or _fallback_embedded_images(
                    pdf,
                    page,
                    page_index,
                    min_width=min_width,
                    min_height=min_height,
                    min_bytes=min_bytes,
                )
            )
    return figures


def split_text_into_chunks(text: str, target_chars: int = 3200) -> list[str]:
    text = sanitize_extracted_text(text)
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if current and size + len(paragraph) > target_chars:
            chunks.append("\n\n".join(current))
            current = []
            size = 0
        current.append(paragraph)
        size += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    if not chunks and text.strip():
        chunks.append(text.strip()[:target_chars])
    return chunks
