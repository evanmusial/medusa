from __future__ import annotations

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


@dataclass
class ExtractedDocument:
    page_count: int
    pages: list[ExtractedPage]
    full_text: str


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


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
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
            text=str(raw[4]).strip(),
        )
        if not block.text:
            continue
        if any(_intersection_ratio(block, bbox) > 0.45 for bbox in table_bboxes):
            continue
        blocks.append(block)
    return [*blocks, *table_blocks]


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
    return "\n\n".join(block.text for block in order_blocks_for_reading(blocks, page_width) if block.text).strip()


def extract_pdf_text(path: Path) -> ExtractedDocument:
    settings = get_settings()
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("PyMuPDF is required for PDF extraction") from exc

    pages: list[ExtractedPage] = []
    with fitz.open(path) as pdf:
        for index, page in enumerate(pdf, start=1):
            text = blocks_to_text(extract_layout_blocks(page), float(page.rect.width))
            low_text = len(text) < settings.low_text_page_threshold
            pages.append(ExtractedPage(page_number=index, text=text, low_text=low_text))
    full_text = "\n\n".join(page.text for page in pages if page.text)
    return ExtractedDocument(page_count=len(pages), pages=pages, full_text=full_text)


def split_text_into_chunks(text: str, target_chars: int = 3200) -> list[str]:
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
