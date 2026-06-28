from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.models import Document
from app.services.extraction import normalize_extracted_text, sanitize_extracted_text


REFERENCE_HEADING_RE = re.compile(r"^\s*(?:references|bibliography|works\s+cited|literature\s+cited)\s*$", re.IGNORECASE)
REFERENCE_HEADING_INLINE_RE = re.compile(
    r"^\s*(?:references|bibliography|works\s+cited|literature\s+cited)\s*[:\-\u2013\u2014]\s+",
    re.IGNORECASE,
)
REFERENCE_COUNT_BOILERPLATE_RE = re.compile(
    r"^\s*references\s*:\s*this\s+document\s+contains\s+references\s+to\s+\d+\s+other\s+documents?\.?\s*$",
    re.IGNORECASE,
)
REFERENCE_METHOD_SECTION_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:step\s+\d+[a-z]?\s*:\s*)?"
    r"(?:reference\s+list\s+search|references\s*[:\-\u2013\u2014]?\s+cited\b)",
    re.IGNORECASE,
)
STOP_HEADING_RE = re.compile(r"^\s*(?:appendix|appendices|acknowledg(?:e)?ments?|notes?|about\s+the\s+authors?)\b", re.IGNORECASE)
REFERENCE_CITATION_KEY_ENTRY_MARKER_RE = re.compile(
    r"^\s*\[[^\]\n]{0,80}[A-Za-z][^\]\n]{0,80}(?:18|19|20)\d{2}[a-z]?\](?:\s+|(?=[A-Z])|$)"
)
REFERENCE_ENTRY_MARKER_RE = re.compile(
    r"^\s*(?:\[\d{1,4}\]|\[[IVXLC]{1,6}\]|\d{1,3}[.)]?)(?:\s+|(?=[A-Z])|$)"
)
REFERENCE_BRACKETED_ENTRY_MARKER_RE = re.compile(r"^\s*(?:\[\d{1,4}\]|\[[IVXLC]{1,6}\])(?:\s+|(?=[A-Z])|$)")
REFERENCE_NUMBERED_ENTRY_MARKER_RE = re.compile(r"^\s*\d{1,3}[.)]?(?:\s+|(?=[A-Z])|$)")
REFERENCE_ENTRY_PREFIX_RE = re.compile(
    r"^\s*(?:\[\d{1,4}\]|\[[IVXLC]{1,6}\]|"
    r"\[[^\]\n]{0,80}[A-Za-z][^\]\n]{0,80}(?:18|19|20)\d{2}[a-z]?\]|"
    r"\d{1,3}[.)]?)(?:\s+|(?=[A-Z])|$)"
)
REFERENCE_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*]|\u2013|\u2014|\u2022|\u2023|\u2043|\u25e6)\s+")
REFERENCE_AUTHOR_WORD = r"[A-Z][A-Za-z\u00c0-\u024f'`\u2019.-]+"
REFERENCE_ORGANIZATION_NAME = rf"{REFERENCE_AUTHOR_WORD}(?:\s+(?:{REFERENCE_AUTHOR_WORD}|of|the|and|for|in|on|&)){{0,10}}"
REFERENCE_INITIAL_TOKEN = r"[A-Z](?:\.-[A-Z])?\."
REFERENCE_INITIALS = rf"(?:{REFERENCE_INITIAL_TOKEN}\s*){{1,5}}"
REFERENCE_AUTHOR_YEAR_RE = re.compile(
    rf"^\s*{REFERENCE_AUTHOR_WORD}(?:\s+{REFERENCE_AUTHOR_WORD}){{0,4}},\s+.+?\b(?:18|19|20)\d{{2}}[a-z]?\b"
)
REFERENCE_AUTHOR_LIST_CONTINUED_RE = re.compile(
    rf"^\s*{REFERENCE_AUTHOR_WORD}(?:\s+{REFERENCE_AUTHOR_WORD}){{0,4}},\s+"
    rf"(?:[A-Z]\.[A-Z.]*|et\s+al\.)(?:,|\s+and\b).*,\s*$",
    re.IGNORECASE,
)
REFERENCE_INITIAL_AUTHOR_YEAR_RE = re.compile(
    rf"^\s*{REFERENCE_INITIALS}{REFERENCE_AUTHOR_WORD}.+?\b(?:18|19|20)\d{{2}}[a-z]?\b"
)
REFERENCE_INITIAL_AUTHOR_START_RE = re.compile(
    rf"^\s*{REFERENCE_INITIALS}{REFERENCE_AUTHOR_WORD}(?:,|\.|\s+and\b|\s+et\s+al\.,?|\s+{REFERENCE_INITIALS})",
    re.IGNORECASE,
)
REFERENCE_SURNAME_INITIALS_START_RE = re.compile(
    rf"^\s*{REFERENCE_AUTHOR_WORD},\s+(?:[A-Z]\.\s*){{1,5}}(?:,|\s+and\b).+",
    re.IGNORECASE,
)
REFERENCE_ORGANIZATION_YEAR_RE = re.compile(r"^\s*[A-Z][A-Z0-9&()./\-\s\u00ae\u2122]{1,60},\s*(?:18|19|20)\d{2}[a-z]?\b")
REFERENCE_ORGANIZATION_DOT_YEAR_RE = re.compile(
    rf"^\s*(?:[A-Z]{{2,}}|{REFERENCE_ORGANIZATION_NAME})\.\s+"
    r".{0,240}\b(?:18|19|20)\d{2}[a-z]?\b"
)
REFERENCE_ORGANIZATION_PAREN_YEAR_RE = re.compile(
    rf"^\s*(?:[A-Z]{{2,}}|{REFERENCE_ORGANIZATION_NAME})\s+"
    r"\((?:18|19|20)\d{2}[a-z]?\)\.?\s+"
)
REFERENCE_UPPER_AUTHOR_LIST_RE = re.compile(
    r"^\s*[A-Z][A-Z'`.-]+,\s+[A-Z].*(?:\bAND\b|(?:,\s+[A-Z][A-Z'`.-]+,\s+[A-Z]))"
)
REFERENCE_UPPER_SINGLE_AUTHOR_RE = re.compile(r"^\s*[A-Z][A-Z'`.-]+,\s+(?:[A-Z]\.\s*){1,5}$")
INLINE_REFERENCE_START_CANDIDATE_RE = re.compile(
    rf"\s+(?={REFERENCE_AUTHOR_WORD}(?:\s+{REFERENCE_AUTHOR_WORD}){{0,4}},\s+[^.?!]{{0,220}}\b(?:18|19|20)\d{{2}}[a-z]?\b)"
)
INLINE_ORGANIZATION_START_CANDIDATE_RE = re.compile(
    r"\s+(?=[A-Z][A-Z0-9&()./\-\s\u00ae\u2122]{1,60},\s*(?:18|19|20)\d{2}[a-z]?\b)"
)
INLINE_ORGANIZATION_DOT_START_CANDIDATE_RE = re.compile(
    rf"\s+(?=(?:[A-Z]{{2,}}|{REFERENCE_ORGANIZATION_NAME})\.\s+"
    r"\(?(?:18|19|20)\d{2}[a-z]?\b)"
)
INLINE_ORGANIZATION_PAREN_START_CANDIDATE_RE = re.compile(
    rf"\s+(?=(?:[A-Z]{{2,}}|{REFERENCE_ORGANIZATION_NAME})\s+"
    r"\((?:18|19|20)\d{2}[a-z]?\)\.?\s+)"
)
INLINE_CITATION_KEY_START_CANDIDATE_RE = re.compile(
    r"\s+(?=\[[^\]\n]{0,80}[A-Za-z][^\]\n]{0,80}(?:18|19|20)\d{2}[a-z]?\](?:\s+|(?=[A-Z])|$))"
)
REFERENCE_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}[a-z]?\b")
REFERENCE_URL_DOI_RE = re.compile(r"(?:https?://|doi:|10\.\d{4,9}/)", re.IGNORECASE)
NON_REFERENCE_SECTION_TITLE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'`\u2019-]*")
REFERENCE_CONTINUATION_PREFIX_RE = re.compile(
    r"^\s*(?:in\s+proceedings|proceedings\b|retrieved\b|available\b|accessed\b|from\b|"
    r"https?://|doi:|url\b|vol\.?\b|pp\.?\b)",
    re.IGNORECASE,
)
ITALIC_FONT_RE = re.compile(r"(?:italic|oblique|kursiv)", re.IGNORECASE)
AUTHOR_BIO_START_RE = re.compile(
    r"^[A-Z][A-Za-z'`.-]+(?:\s+[A-Z][A-Za-z'`.-]+){1,4}\s+"
    r"(?:is|was|received|obtained|currently|has\s+worked|joined)\b",
)
PAGE_FURNITURE_RE = re.compile(
    r"^(?:"
    r"\d{4}-\d{3,4}X\s+\(c\)|"
    r"\d{4}-\d{4}\s+\(c\)\s+\d{4}\s+IEEE|"
    r"Authorized\s+licensed\s+use\s+limited\s+to:|"
    r"Downloaded\s+by\s+\[.+?\]\s+at\s+\d{1,2}:\d{2}\s+\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|"
    r"This article has been accepted for publication|"
    r"Citation information:\s*DOI|"
    r"Engineering\s+Management\s+Review|"
    r"Intelligent\s+Automation\s+And\s+Soft\s+Computing|"
    r"Communications Surveys\s*&\s*Tutorials|"
    r"IEEE COMMUNICATIONS SURVEY\s*&\s*TUTORIALS|"
    r"ACM Transactions on .+Publication date|"
    r"CMU/SEI-\d{4}-[A-Z]{2}-\d{3}\s+\|\s+SOFTWARE ENGINEERING INSTITUTE\s+\|\s+CARNEGIE MELLON UNIVERSITY|"
    r"Distribution Statement A:\s+Approved for Public Release; Distribution is Unlimited|"
    r"PART\s*\|\s*[IVXLC]+\b.*|"
    r".+\s+Chapter\s*\|\s*\d+\s*$|"
    r"Computers\s*&\s*Security\s+\d+\s+\(\d{4}\)\s+\d+|"
    r"Computers\s+in\s+Human\s+Behavior\s+Reports\s+\d+\s+\(\d{4}\)\s+\d+|"
    r"Journal\s+of\s+.+\s+\d+\s+\(\d{4}\)\s+\d+|"
    r"[A-Z]\.\s+[A-Z][A-Za-z'`.-]+\s+and\s+[A-Z]\.(?:[A-Z]\.)?\s+[A-Z][A-Za-z'`.-]+$|"
    r"[A-Z]\.\s+[A-Z][A-Za-z'`.-]+\s+et\s+al\.$|"
    r"[A-Z]\.\s+[A-Z][A-Za-z'`.-]+$|"
    r"[A-Z]\.\s+[A-Z][A-Za-z'`.-]+(?:\s+and\s+[A-Z]\.(?:[A-Z]\.)?\s+[A-Z][A-Za-z'`.-]+)?\s+Journal\s+of\s+.+\s+\d+\s+\(\d{4}\)\s+\d+|"
    r"(?:©|\(c\))\s*\d{4}\s+by\s+the\s+authors|"
    r"Licensee\s+MDPI|"
    r"This article is an open access article distributed|"
    r"Received\s+[A-Z][a-z]+\s+\d{4};\s+revised"
    r")",
    re.IGNORECASE,
)
PAGE_NUMBER_RE = re.compile(r"^(?:\d{1,3}|1[0-7]\d{2})$")
PDF_STANDALONE_REFERENCE_MARKER_RE = re.compile(r"^\s*(?:\[\d{1,4}\]|\d{1,4}[.)])\s*$")
READABLE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'`\u2019-]{2,}")
GARBLED_SYMBOL_RE = re.compile(r"[#@$%^&*=<>\\|~]{2,}|(?:[!?][!?#<>{}=])")


def _strip_markdown(value: str) -> str:
    return value.replace("*", "").replace("_", "").replace("`", "")


def _strip_reference_list_marker(value: str) -> str:
    return REFERENCE_LIST_MARKER_RE.sub("", value, count=1).strip()


def _strip_reference_entry_prefix(value: str) -> str:
    return REFERENCE_ENTRY_PREFIX_RE.sub("", value, count=1).strip()


def _reference_match_text(value: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", value)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)
    return text


def _line_starts_reference_entry(line: str) -> bool:
    return bool(_line_starts_reference_marker(line) or _line_starts_unmarked_reference_entry(line))


def _line_starts_unmarked_reference_entry(line: str) -> bool:
    plain = _reference_match_text(_strip_markdown(_strip_reference_list_marker(line)).strip())
    return bool(
        REFERENCE_AUTHOR_YEAR_RE.match(plain)
        or REFERENCE_AUTHOR_LIST_CONTINUED_RE.match(plain)
        or REFERENCE_INITIAL_AUTHOR_YEAR_RE.match(plain)
        or REFERENCE_INITIAL_AUTHOR_START_RE.match(plain)
        or REFERENCE_SURNAME_INITIALS_START_RE.match(plain)
        or REFERENCE_ORGANIZATION_YEAR_RE.match(plain)
        or REFERENCE_ORGANIZATION_DOT_YEAR_RE.match(plain)
        or REFERENCE_ORGANIZATION_PAREN_YEAR_RE.match(plain)
        or REFERENCE_UPPER_AUTHOR_LIST_RE.match(plain)
        or REFERENCE_UPPER_SINGLE_AUTHOR_RE.match(plain)
    )


def _reference_marker_style(line: str) -> str | None:
    plain = _strip_markdown(_strip_reference_list_marker(line)).strip()
    if REFERENCE_BRACKETED_ENTRY_MARKER_RE.match(plain):
        return "bracketed"
    if REFERENCE_CITATION_KEY_ENTRY_MARKER_RE.match(plain):
        return "citation_key"
    if REFERENCE_NUMBERED_ENTRY_MARKER_RE.match(plain):
        return "numbered"
    return None


def _line_starts_reference_marker(line: str, marker_style: str | None = None) -> bool:
    style = _reference_marker_style(line)
    return bool(style and (marker_style is None or style == marker_style))


def _line_looks_like_method_reference_section(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    return bool(REFERENCE_METHOD_SECTION_RE.match(plain))


def _line_is_reference_heading(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    if _line_looks_like_method_reference_section(plain):
        return False
    return bool(REFERENCE_HEADING_RE.match(plain))


def _line_starts_reference_section(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    return bool(
        REFERENCE_HEADING_INLINE_RE.match(plain)
        and not REFERENCE_COUNT_BOILERPLATE_RE.match(plain)
        and not _line_looks_like_method_reference_section(plain)
    )


def _line_stops_reference_section(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    if plain.lower() in {"table 1", "report documentation page"}:
        return True
    if bool(STOP_HEADING_RE.match(plain)) and len(plain.split()) <= 8:
        return True
    return bool(AUTHOR_BIO_START_RE.match(plain))


def _line_is_page_furniture(line: str) -> bool:
    plain = _strip_markdown(line).strip()
    return bool(PAGE_FURNITURE_RE.match(plain) or PAGE_NUMBER_RE.match(plain))


def _reference_section_inline_text(line: str) -> str:
    return REFERENCE_HEADING_INLINE_RE.sub("", line, count=1).strip()


def _reference_heading_indexes(lines: list[str]) -> list[int]:
    return [
        index
        for index, line in enumerate(lines)
        if _line_is_reference_heading(line) or _line_starts_reference_section(line)
    ]


def _text_layer_looks_garbled(text: str) -> bool:
    compact = re.sub(r"\s+", "", _strip_markdown(text))
    if len(compact) < 120:
        return False
    symbol_count = sum(1 for char in compact if not char.isalnum())
    symbol_ratio = symbol_count / max(len(compact), 1)
    readable_words = READABLE_WORD_RE.findall(text)
    readable_word_chars = sum(len(word) for word in readable_words)
    readable_ratio = readable_word_chars / max(len(compact), 1)
    return bool(symbol_ratio >= 0.34 and readable_ratio < 0.52 and GARBLED_SYMBOL_RE.search(text))


def _unreadable_text_pages(document: Document) -> list[int]:
    pages: list[int] = []
    for page in sorted(document.pages, key=lambda item: item.page_number):
        text = page.normalized_text if page.normalized_text is not None else page.text
        if text and _text_layer_looks_garbled(text):
            pages.append(page.page_number)
    return pages


def _collect_reference_lines(lines: list[str], heading_index: int) -> tuple[list[str], int, int]:
    starts_inline = _line_starts_reference_section(lines[heading_index])
    start = heading_index if starts_inline else heading_index + 1
    selected: list[str] = []
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index].strip()
        if starts_inline and index == heading_index:
            line = _reference_section_inline_text(line)
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


def _reference_signal_count(lines: list[str]) -> int:
    signals = 0
    for raw_line in lines:
        line = _clean_reference_line(raw_line)
        if not line or _line_is_page_furniture(line) or _line_is_reference_heading(line) or _line_starts_reference_section(line):
            continue
        if _line_starts_reference_entry(line):
            signals += 2
            continue
        plain = _strip_markdown(line)
        if REFERENCE_YEAR_RE.search(plain):
            signals += 1
        if REFERENCE_URL_DOI_RE.search(plain):
            signals += 1
    return signals


def _first_future_reference_heading_offset(selected: list[str]) -> int | None:
    for index, line in enumerate(selected):
        if _line_is_reference_heading(line) or _line_starts_reference_section(line):
            return index
    return None


def _reference_candidate_score(
    selected: list[str], heading_line: str, heading_index: int, line_count: int
) -> tuple[float, str, int, list[str]] | None:
    future_heading_offset = _first_future_reference_heading_offset(selected)
    scored_lines = selected
    if future_heading_offset is not None:
        prefix = selected[:future_heading_offset]
        if _entry_count(_format_reference_lines(prefix)) < 2:
            return None
        scored_lines = prefix
    text = _format_reference_lines(scored_lines)
    entries = [line for line in text.splitlines() if line.strip()]
    entry_count = len(entries)
    if entry_count == 0:
        return None
    if entry_count <= 2 and not any(_line_starts_reference_entry(entry) for entry in entries):
        return None
    heading_plain = _strip_markdown(heading_line).strip()
    if heading_plain.islower() and entries and not _line_starts_reference_entry(entries[0]):
        return None
    nonempty_count = sum(1 for line in scored_lines if line.strip())
    signal_count = _reference_signal_count(scored_lines)
    density = signal_count / max(nonempty_count, 1)
    start_fraction = heading_index / max(line_count, 1)
    score = entry_count * 12 + signal_count * 2 + density * 8 + start_fraction
    return score, text, entry_count, scored_lines


def _extract_reference_lines(lines: list[str]) -> tuple[list[str], int | None, int | None]:
    candidates = _reference_heading_indexes(lines)
    if not candidates:
        return [], None, None
    best: tuple[float, list[str], int, int] | None = None
    for heading_index in candidates:
        selected, start, end = _collect_reference_lines(lines, heading_index)
        score = _reference_candidate_score(selected, lines[heading_index], heading_index, len(lines))
        if score is None:
            continue
        effective_selected = score[3]
        effective_end = start + len(effective_selected) if len(effective_selected) < len(selected) else end
        if best is None or score[0] > best[0]:
            best = (score[0], effective_selected, start, effective_end)
    if best is None:
        return [], None, None
    return best[1], best[2], best[3]


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
    unreadable_pages = _unreadable_text_pages(document)
    if not selected:
        evidence: dict[str, Any] = {"source": "page_text", "status": "not_found"}
        if unreadable_pages:
            evidence["unreadable_text_pages"] = unreadable_pages
            evidence["ocr_recommended"] = True
        return {"bibliography": None, "evidence": evidence}
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
            **({"unreadable_text_pages": unreadable_pages, "ocr_recommended": True} if unreadable_pages else {}),
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


PdfLineItem = tuple[float, float, float, float, str]


def _pdf_line_column(page_width: float, item: PdfLineItem) -> int | None:
    x0, _, x1, _, _ = item
    midpoint = page_width / 2
    width = max(0.0, x1 - x0)
    if width >= page_width * 0.68 or (x0 < midpoint < x1):
        return None
    return 0 if x0 < midpoint else 1


def _pdf_standalone_reference_marker_count(items: list[PdfLineItem]) -> int:
    return sum(1 for *_, text in items if PDF_STANDALONE_REFERENCE_MARKER_RE.match(_strip_markdown(text).strip()))


def _sort_pdf_page_line_items(page_width: float, items: list[PdfLineItem]) -> list[PdfLineItem]:
    if len(items) < 8 or page_width <= 0:
        return items
    if _pdf_standalone_reference_marker_count(items) >= 6:
        return items
    columns = [_pdf_line_column(page_width, item) for item in items]
    left_count = sum(1 for column in columns if column == 0)
    right_count = sum(1 for column in columns if column == 1)
    if left_count < 4 or right_count < 2:
        return items
    column_items = [item for item, column in zip(items, columns, strict=False) if column is not None]
    top = min(item[1] for item in column_items)
    bottom = max(item[3] for item in column_items)
    midpoint = page_width / 2

    def sort_key(item: PdfLineItem) -> tuple[int, float, float]:
        column = _pdf_line_column(page_width, item)
        if column is not None:
            return column + 1, item[1], item[0]
        if item[3] < top:
            return 0, item[1], item[0]
        if item[1] > bottom:
            return 3, item[1], item[0]
        center = (item[0] + item[2]) / 2
        return (1 if center < midpoint else 2), item[1], item[0]

    return sorted(items, key=sort_key)


def _pdf_markdown_lines(path: Path) -> list[tuple[int, str]]:
    import fitz

    rows: list[tuple[int, str]] = []
    with fitz.open(path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            page_dict = page.get_text("dict")
            page_items: list[PdfLineItem] = []
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    parts = [
                        _markdown_span(str(span.get("text") or ""), _is_italic_span(span))
                        for span in line.get("spans", [])
                    ]
                    text = sanitize_extracted_text("".join(parts)).strip()
                    if text:
                        x0, y0, x1, y1 = line.get("bbox") or block.get("bbox") or (0.0, 0.0, 0.0, 0.0)
                        page_items.append((float(x0), float(y0), float(x1), float(y1), text))
            rows.extend((page_number, text) for *_, text in _sort_pdf_page_line_items(float(page.rect.width), page_items))
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
    return len(lines)


def _clean_reference_line(raw_line: str) -> str:
    line = sanitize_extracted_text(raw_line).strip()
    if not line:
        return ""
    return _strip_reference_list_marker(line)


def _split_inline_reference_lines(line: str) -> list[str]:
    if _line_starts_reference_marker(line) and not REFERENCE_CITATION_KEY_ENTRY_MARKER_RE.match(
        _strip_markdown(line).strip()
    ):
        return [line]
    split_offsets: list[int] = []
    matches = sorted(
        [
            *INLINE_REFERENCE_START_CANDIDATE_RE.finditer(line),
            *INLINE_ORGANIZATION_START_CANDIDATE_RE.finditer(line),
            *INLINE_ORGANIZATION_DOT_START_CANDIDATE_RE.finditer(line),
            *INLINE_ORGANIZATION_PAREN_START_CANDIDATE_RE.finditer(line),
            *INLINE_CITATION_KEY_START_CANDIDATE_RE.finditer(line),
        ],
        key=lambda item: item.start(),
    )
    for match in matches:
        offset = match.start()
        prefix = line[:offset].strip()
        if not REFERENCE_YEAR_RE.search(prefix):
            continue
        if prefix.endswith((".", ".)", "〉", "}", "]")) or REFERENCE_URL_DOI_RE.search(prefix):
            split_offsets.append(offset)
    if not split_offsets:
        return [line]
    parts: list[str] = []
    start = 0
    for offset in split_offsets:
        part = line[start:offset].strip()
        if part:
            parts.append(part)
        start = offset
    final = line[start:].strip()
    if final:
        parts.append(final)
    return parts


def _normalize_reference_entry(parts: list[str]) -> str:
    entry = " ".join(part.strip() for part in parts if part.strip())
    entry = re.sub(r"(?<=\d)([-\u2010-\u2015])\s+(?=\d)", r"\1", entry)
    entry = _strip_reference_entry_prefix(normalize_extracted_text(entry).replace("\n", " ")).strip()
    return re.sub(r"(?<=\d)([-\u2010-\u2015])\s+(?=\d)", r"\1", entry)


def _reference_entry_has_terminal_evidence(parts: list[str]) -> bool:
    if not parts:
        return False
    text = _strip_markdown(" ".join(part.strip() for part in parts if part.strip())).strip()
    text_without_prefix = _strip_reference_entry_prefix(text).strip()
    if not text_without_prefix:
        return False
    if not REFERENCE_YEAR_RE.search(text_without_prefix):
        return False
    if text_without_prefix.endswith((",", ";", ":")):
        return False
    return bool(
        REFERENCE_URL_DOI_RE.search(text_without_prefix)
        or re.search(r"[.!?\]\)\u3009\u232a\u27e9\u300b]$", text_without_prefix)
    )


def _reference_parts_have_signal(parts: list[str]) -> bool:
    text = _strip_markdown(" ".join(part.strip() for part in parts if part.strip())).strip()
    if not text:
        return False
    return bool(
        _line_starts_reference_entry(text)
        or REFERENCE_YEAR_RE.search(text)
        or REFERENCE_URL_DOI_RE.search(text)
    )


def _line_looks_like_new_section_after_references(line: str) -> bool:
    plain = _reference_match_text(_strip_markdown(_strip_reference_list_marker(line)).strip())
    if not plain or len(plain) > 180:
        return False
    if REFERENCE_CONTINUATION_PREFIX_RE.match(plain):
        return False
    if _line_is_page_furniture(plain) or _line_is_reference_heading(plain) or _line_starts_reference_section(plain):
        return False
    if _line_starts_reference_entry(plain) or REFERENCE_YEAR_RE.search(plain) or REFERENCE_URL_DOI_RE.search(plain):
        return False
    if any(mark in plain for mark in ("@", ":", "/", "\\", "(", ")", "[", "]")):
        return False
    if plain.endswith((".", ",", ";")):
        return False
    words = NON_REFERENCE_SECTION_TITLE_WORD_RE.findall(plain)
    if not 5 <= len(words) <= 18:
        return False
    capitalized = sum(1 for word in words if word[:1].isupper())
    return capitalized >= 3


def _should_use_marker_bounded_mode(cleaned_lines: list[str], marker_offsets: list[int]) -> bool:
    if not marker_offsets:
        return False
    first_marker = marker_offsets[0]
    if first_marker <= 2:
        return True
    if first_marker > 8:
        return False
    prefix = cleaned_lines[:first_marker]
    return not any(
        _line_starts_unmarked_reference_entry(line)
        or REFERENCE_YEAR_RE.search(_strip_markdown(line))
        or REFERENCE_URL_DOI_RE.search(_strip_markdown(line))
        for line in prefix
    )


def _marker_bounded_style(cleaned_lines: list[str], marker_offsets: list[int]) -> str | None:
    if not marker_offsets:
        return None
    return _reference_marker_style(cleaned_lines[marker_offsets[0]])


def _format_reference_lines(lines: list[str]) -> str:
    entries: list[str] = []
    current: list[str] = []
    cleaned_lines: list[str] = []
    for raw_line in lines:
        cleaned = _clean_reference_line(raw_line)
        if (
            cleaned
            and not _line_is_page_furniture(cleaned)
            and not _line_is_reference_heading(cleaned)
            and not _line_starts_reference_section(cleaned)
        ):
            cleaned_lines.extend(_split_inline_reference_lines(cleaned))
    marker_offsets = [index for index, line in enumerate(cleaned_lines) if _line_starts_reference_marker(line)]
    marker_bounded = _should_use_marker_bounded_mode(cleaned_lines, marker_offsets)
    marker_style = _marker_bounded_style(cleaned_lines, marker_offsets) if marker_bounded else None
    for raw_line in lines:
        line = _clean_reference_line(raw_line)
        if not line:
            continue
        if _line_is_page_furniture(line) or _line_is_reference_heading(line) or _line_starts_reference_section(line):
            continue
        for part in _split_inline_reference_lines(line):
            if (
                not marker_bounded
                and _line_starts_reference_marker(part)
                and not _strip_reference_entry_prefix(part)
            ):
                continue
            starts_entry = (
                _line_starts_reference_marker(part, marker_style)
                if marker_bounded
                else _line_starts_unmarked_reference_entry(part)
            )
            if (
                current
                and len(entries) >= 2
                and _reference_entry_has_terminal_evidence(current)
                and _line_looks_like_new_section_after_references(part)
            ):
                entry = _normalize_reference_entry(current)
                if entry:
                    entries.append(entry)
                return "\n".join(entries).strip()
            if starts_entry and current:
                if not marker_bounded and not _reference_entry_has_terminal_evidence(current):
                    if _reference_parts_have_signal(current):
                        current.append(part)
                    else:
                        current = [part]
                    continue
                if marker_bounded and not _reference_parts_have_signal(current):
                    current = [part]
                    continue
                entry = _normalize_reference_entry(current)
                if entry:
                    entries.append(entry)
                current = [part]
                continue
            if current:
                current.append(part)
            else:
                current = [part]
    if current:
        entry = _normalize_reference_entry(current)
        if entry:
            entries.append(entry)
    return "\n".join(entries).strip()


def extract_document_bibliography(document: Document, pdf_path: Path | None = None) -> dict[str, Any]:
    if pdf_path and pdf_path.exists():
        formatted = _formatted_bibliography_from_pdf(pdf_path)
        if formatted and formatted.get("bibliography"):
            return formatted
    return _plain_bibliography_from_pages(document)
