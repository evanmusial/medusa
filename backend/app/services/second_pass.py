from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.models import Document, DocumentPage
from app.services.extraction import sanitize_extracted_text
from app.services.preferences import normalize_bool


PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d{1,4}(?:\s*(?:/|of)\s*\d{1,4})?$", re.IGNORECASE)
TEXT_ART_RE = re.compile(r"^[\s\-_=*~^#|.:;`'\"•·]{5,}$")
FRONT_MATTER_NOISE_RE = re.compile(
    r"^(?:downloaded\s+from|retrieved\s+from|copyright\b|all\s+rights\s+reserved\b|"
    r"this\s+content\s+downloaded\s+from|terms\s+of\s+use\b)",
    re.IGNORECASE,
)
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+•·]|\(?[a-zA-Z0-9]{1,3}[.)])\s+")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass(frozen=True)
class PageCleanup:
    page_id: str
    page_number: int
    text: str
    removed: list[dict[str, Any]]
    warnings: list[str]
    table_blocks: list[dict[str, Any]]


def _line_key(line: str) -> str:
    candidate = re.sub(r"\d+", "#", line).strip().lower()
    candidate = re.sub(r"\s+", " ", candidate)
    candidate = re.sub(r"[\W_]+", " ", candidate).strip()
    return candidate


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in sanitize_extracted_text(text).replace("\r\n", "\n").replace("\r", "\n").splitlines() if line.strip()]


def _candidate_repeated_lines(pages: list[DocumentPage], *, position: str) -> set[str]:
    if len(pages) < 3:
        return set()
    counter: Counter[str] = Counter()
    samples: dict[str, str] = {}
    for page in pages:
        lines = _meaningful_lines(page.text or "")
        edge = lines[:2] if position == "header" else lines[-2:]
        for line in edge:
            key = _line_key(line)
            if len(key) < 4:
                continue
            counter[key] += 1
            samples[key] = line
    threshold = max(3, int(len(pages) * 0.55))
    return {key for key, count in counter.items() if count >= threshold}


def _looks_like_text_art(line: str) -> bool:
    stripped = line.strip()
    if TEXT_ART_RE.match(stripped):
        return True
    if len(stripped) < 8:
        return False
    non_alnum = sum(1 for char in stripped if not char.isalnum() and not char.isspace())
    return non_alnum / max(1, len(stripped)) >= 0.68


def _repair_drop_cap(lines: list[str]) -> tuple[list[str], list[str]]:
    repaired: list[str] = []
    warnings: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if len(line) == 1 and line.isalpha() and line.isupper() and next_line[:1].islower():
            repaired.append(f"{line}{next_line}")
            warnings.append("drop_cap_repaired")
            index += 2
            continue
        repaired.append(line)
        index += 1
    return repaired, warnings


def _repair_bullet_lines(lines: list[str]) -> list[str]:
    repaired: list[str] = []
    for line in lines:
        if LIST_MARKER_RE.match(line):
            marker, body = line.split(maxsplit=1)
            normalized_marker = "-" if marker in {"•", "·", "*", "+"} else marker
            repaired.append(f"{normalized_marker} {body.strip()}")
        else:
            repaired.append(line)
    return repaired


def _extract_table_blocks(lines: list[str], page_number: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: list[str] = []
    start_line = 0
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        is_table_line = (
            stripped.startswith("|")
            or TABLE_SEPARATOR_RE.match(stripped) is not None
            or (len(re.split(r"\s{2,}", stripped)) >= 3 and not LIST_MARKER_RE.match(stripped))
        )
        if is_table_line:
            if not current:
                start_line = line_number
            current.append(stripped)
            continue
        if len(current) >= 2:
            blocks.append({"page_number": page_number, "start_line": start_line, "end_line": line_number - 1, "text": "\n".join(current)})
        current = []
    if len(current) >= 2:
        blocks.append({"page_number": page_number, "start_line": start_line, "end_line": start_line + len(current) - 1, "text": "\n".join(current)})
    return blocks


def _remove_boilerplate_from_page(
    page: DocumentPage,
    *,
    repeated_headers: set[str],
    repeated_footers: set[str],
    cleanup: dict[str, Any],
) -> PageCleanup:
    lines = _meaningful_lines(page.text or "")
    removed: list[dict[str, Any]] = []
    warnings: list[str] = []
    kept: list[str] = []
    for index, line in enumerate(lines):
        line_key = _line_key(line)
        at_header_edge = index <= 1
        at_footer_edge = index >= max(0, len(lines) - 2)
        reason: str | None = None
        if normalize_bool(cleanup.get("remove_headers_footers"), True) and at_header_edge and line_key in repeated_headers:
            reason = "repeated_header"
        elif normalize_bool(cleanup.get("remove_headers_footers"), True) and at_footer_edge and line_key in repeated_footers:
            reason = "repeated_footer"
        elif normalize_bool(cleanup.get("remove_page_numbers"), True) and PAGE_NUMBER_RE.match(line.strip()):
            reason = "page_number"
        elif normalize_bool(cleanup.get("remove_text_art"), True) and _looks_like_text_art(line):
            reason = "text_art"
        elif normalize_bool(cleanup.get("front_matter_noise"), True) and FRONT_MATTER_NOISE_RE.match(line.strip()):
            reason = "front_matter_noise"

        if reason:
            removed.append({"page_number": page.page_number, "line": index + 1, "reason": reason, "text": line[:500]})
            continue
        kept.append(line)

    if normalize_bool(cleanup.get("repair_drop_caps"), True):
        kept, drop_cap_warnings = _repair_drop_cap(kept)
        warnings.extend(drop_cap_warnings)
    if normalize_bool(cleanup.get("repair_bullets"), True):
        kept = _repair_bullet_lines(kept)
    text = "\n".join(kept)
    if normalize_bool(cleanup.get("normalize_whitespace"), True):
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    return PageCleanup(
        page_id=page.id,
        page_number=page.page_number,
        text=text.strip(),
        removed=removed,
        warnings=warnings,
        table_blocks=_extract_table_blocks(kept, page.page_number),
    )


def clean_document_structure(document: Document, preset: dict[str, Any] | None = None) -> dict[str, Any]:
    preset = preset or {}
    cleanup = preset.get("cleanup") if isinstance(preset.get("cleanup"), dict) else {}
    if not normalize_bool(cleanup.get("enabled"), True) or not normalize_bool(cleanup.get("deterministic"), True):
        return {"enabled": False, "pages": len(document.pages), "cleaned_text_by_page_id": {}}

    pages = sorted(document.pages, key=lambda page: page.page_number)
    repeated_headers = _candidate_repeated_lines(pages, position="header")
    repeated_footers = _candidate_repeated_lines(pages, position="footer")
    page_results = [
        _remove_boilerplate_from_page(page, repeated_headers=repeated_headers, repeated_footers=repeated_footers, cleanup=cleanup)
        for page in pages
    ]
    removed = [item for page in page_results for item in page.removed]
    warnings = sorted({warning for page in page_results for warning in page.warnings})
    table_blocks = [block for page in page_results for block in page.table_blocks]
    cleaned_text_by_page_id = {page.page_id: page.text for page in page_results}
    return {
        "enabled": True,
        "preset_id": preset.get("id"),
        "preset_name": preset.get("name"),
        "pages": len(pages),
        "cleaned_pages": sum(1 for page in page_results if page.text.strip()),
        "removed_boilerplate_count": len(removed),
        "removed_boilerplate": removed[:200],
        "repeated_header_keys": sorted(repeated_headers),
        "repeated_footer_keys": sorted(repeated_footers),
        "warnings": warnings,
        "structured_tables": {
            "detected_count": len(table_blocks),
            "blocks": table_blocks[:100],
        },
        "cleaned_text_by_page_id": cleaned_text_by_page_id,
    }
