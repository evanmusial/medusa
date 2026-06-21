from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.models import Document
from app.services.extraction import normalize_extracted_text, sanitize_extracted_text


REFERENCE_HEADING_RE = re.compile(r"^\s*(?:references|bibliography|works\s+cited|literature\s+cited)\s*$", re.IGNORECASE)
REFERENCE_HEADING_INLINE_RE = re.compile(r"^\s*(?:references|bibliography|works\s+cited|literature\s+cited)\b[:\s-]*", re.IGNORECASE)
STOP_HEADING_RE = re.compile(r"^\s*(?:appendix|appendices|acknowledg(?:e)?ments?|notes?|index|about\s+the\s+author)\b", re.IGNORECASE)
REFERENCE_ENTRY_RE = re.compile(r"^\s*(?:\[\d+\]|\d+\.|[A-Z][A-Za-z'`-]+,\s+[A-Z])")
ITALIC_FONT_RE = re.compile(r"(?:italic|oblique|kursiv)", re.IGNORECASE)


def _strip_markdown(value: str) -> str:
    return value.replace("*", "").replace("_", "").replace("`", "")


def _line_is_reference_heading(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    return bool(REFERENCE_HEADING_RE.match(plain))


def _line_starts_reference_section(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    return bool(REFERENCE_HEADING_INLINE_RE.match(plain))


def _line_stops_reference_section(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    return bool(STOP_HEADING_RE.match(plain)) and len(plain.split()) <= 8


def _extract_reference_lines(lines: list[str]) -> tuple[list[str], int | None, int | None]:
    start: int | None = None
    for index, line in enumerate(lines):
        if _line_is_reference_heading(line):
            start = index + 1
            break
        if _line_starts_reference_section(line):
            start = index
            lines[index] = REFERENCE_HEADING_INLINE_RE.sub("", line).strip()
            break
    if start is None:
        return [], None, None
    selected: list[str] = []
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index].strip()
        if not line:
            if selected and selected[-1]:
                selected.append("")
            continue
        if selected and _line_stops_reference_section(line):
            end = index
            break
        selected.append(line)
    while selected and not selected[0]:
        selected.pop(0)
    while selected and not selected[-1]:
        selected.pop()
    return selected, start, end


def _page_lines(document: Document) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for page in sorted(document.pages, key=lambda item: item.page_number):
        text = page.normalized_text if page.normalized_text is not None else page.text
        for line in sanitize_extracted_text(text).replace("\r\n", "\n").replace("\r", "\n").splitlines():
            if line.strip():
                rows.append((page.page_number, line.strip()))
    return rows


def _plain_bibliography_from_pages(document: Document) -> dict[str, Any]:
    page_rows = _page_lines(document)
    lines = [line for _, line in page_rows]
    selected, start, end = _extract_reference_lines(lines)
    if not selected:
        return {"bibliography": None, "evidence": {"source": "page_text", "status": "not_found"}}
    page_numbers = [page for page, _ in page_rows[start:end] if page] if start is not None and end is not None else []
    text = _format_reference_lines(selected)
    return {
        "bibliography": text or None,
        "evidence": {
            "source": "page_text",
            "status": "extracted" if text else "empty",
            "page_start": min(page_numbers) if page_numbers else None,
            "page_end": max(page_numbers) if page_numbers else None,
            "formatting": "plain_or_existing_markdown",
            "entry_count_estimate": _entry_count(text),
        },
    }


def _is_italic_span(span: dict[str, Any]) -> bool:
    font = str(span.get("font") or "")
    flags = int(span.get("flags") or 0)
    return bool(ITALIC_FONT_RE.search(font) or flags & 2)


def _markdown_span(text: str, italic: bool) -> str:
    if not italic:
        return text
    if not text.strip():
        return text
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    core = text.strip()
    if not core:
        return text
    return f"{leading}*{core}*{trailing}"


def _pdf_markdown_lines(path: Path) -> list[tuple[int, str]]:
    import fitz

    rows: list[tuple[int, str]] = []
    with fitz.open(path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    parts = [
                        _markdown_span(str(span.get("text") or ""), _is_italic_span(span))
                        for span in line.get("spans", [])
                    ]
                    text = sanitize_extracted_text("".join(parts)).strip()
                    if text:
                        rows.append((page_number, text))
    return rows


def _formatted_bibliography_from_pdf(path: Path) -> dict[str, Any] | None:
    try:
        page_rows = _pdf_markdown_lines(path)
    except Exception:
        return None
    lines = [line for _, line in page_rows]
    selected, start, end = _extract_reference_lines(lines)
    if not selected:
        return None
    page_numbers = [page for page, _ in page_rows[start:end] if page] if start is not None and end is not None else []
    text = _format_reference_lines(selected)
    if not text:
        return None
    return {
        "bibliography": text,
        "evidence": {
            "source": "pdf_span_layout",
            "status": "extracted",
            "page_start": min(page_numbers) if page_numbers else None,
            "page_end": max(page_numbers) if page_numbers else None,
            "formatting": "markdown_italics_from_pdf_spans",
            "italic_marker_count": text.count("*") // 2,
            "entry_count_estimate": _entry_count(text),
        },
    }


def _entry_count(text: str | None) -> int:
    if not text:
        return 0
    lines = [line for line in text.splitlines() if line.strip()]
    matches = sum(1 for line in lines if REFERENCE_ENTRY_RE.match(_strip_markdown(line)))
    return matches or max(1, len([part for part in re.split(r"\n\s*\n+", text) if part.strip()]))


def _format_reference_lines(lines: list[str]) -> str:
    entries: list[str] = []
    current = ""
    for raw_line in lines:
        line = sanitize_extracted_text(raw_line).strip()
        if not line:
            if current:
                entries.append(current.strip())
                current = ""
            continue
        if REFERENCE_ENTRY_RE.match(_strip_markdown(line)) and current:
            entries.append(current.strip())
            current = line
            continue
        if not current:
            current = line
        else:
            current = f"{current.rstrip()} {line.lstrip()}"
    if current:
        entries.append(current.strip())
    return "\n\n".join(normalize_extracted_text(entry) for entry in entries if entry.strip()).strip()


def extract_document_bibliography(document: Document, pdf_path: Path | None = None) -> dict[str, Any]:
    if pdf_path and pdf_path.exists():
        formatted = _formatted_bibliography_from_pdf(pdf_path)
        if formatted and formatted.get("bibliography"):
            return formatted
    return _plain_bibliography_from_pages(document)
