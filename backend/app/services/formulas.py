from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models import Document, DocumentPage
from app.services.extraction import sanitize_extracted_text
from app.services.openai_usage import OpenAIUsageContext
from app.services.processing import document_reading_text


FORMULA_CAPTURE_HEADING = "Formula capture:"


def formula_capture_input_text(document: Document, *, max_chars: int = 90_000) -> str:
    pages: list[str] = []
    for page in sorted(document.pages, key=lambda item: item.page_number):
        text = page.normalized_text if page.normalized_text is not None else page.text or ""
        text = sanitize_extracted_text(text).strip()
        if text:
            pages.append(f"[Page {page.page_number}]\n{text}")
    page_text = "\n\n".join(pages).strip()
    if page_text:
        return page_text[:max_chars]
    return sanitize_extracted_text(document_reading_text(document) or document.search_text or "")[:max_chars]


def formula_capture_search_text(document: Document) -> str:
    evidence = document.metadata_evidence or {}
    capture = evidence.get("formula_capture")
    if not isinstance(capture, dict):
        return ""
    formulas = capture.get("formulas")
    if not isinstance(formulas, list):
        return ""
    parts: list[str] = []
    for item in formulas:
        if not isinstance(item, dict):
            continue
        for key in ("label", "latex", "surrounding_text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(parts)


def _strip_existing_formula_capture_block(text: str) -> str:
    marker = f"\n\n{FORMULA_CAPTURE_HEADING}\n"
    if marker not in text:
        return text.rstrip()
    before, _marker, _after = text.rpartition(marker)
    return before.rstrip()


def _formula_note_lines(formulas: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for formula in formulas:
        latex = sanitize_extracted_text(str(formula.get("latex") or "")).strip()
        if not latex:
            continue
        label = sanitize_extracted_text(str(formula.get("label") or "")).strip()
        context = sanitize_extracted_text(str(formula.get("surrounding_text") or "")).strip()
        prefix = f"- {label}: " if label else "- "
        suffix = f" -- {context}" if context else ""
        lines.append(f"{prefix}\\({latex}\\){suffix}")
    return lines


def _append_formula_capture_to_page(page: DocumentPage, formulas: list[dict[str, Any]]) -> bool:
    lines = _formula_note_lines(formulas)
    if not lines:
        return False
    base = page.normalized_text if page.normalized_text is not None else page.text or ""
    base = _strip_existing_formula_capture_block(sanitize_extracted_text(base))
    next_text = f"{base}\n\n{FORMULA_CAPTURE_HEADING}\n" + "\n".join(lines)
    if (page.normalized_text or "") == next_text:
        return False
    page.normalized_text = next_text
    return True


def capture_document_formulas(
    document: Document,
    *,
    ai: Any,
    model: str,
    pdf_bytes: bytes | None = None,
    usage_context: OpenAIUsageContext | None = None,
    prompt_cache_key: str | None = None,
    append_to_page_text: bool = True,
    protect_manual: bool = True,
) -> dict[str, Any]:
    input_text = formula_capture_input_text(document)
    result = ai.capture_formulas(
        document.original_filename,
        input_text,
        pdf_bytes=pdf_bytes,
        model=model,
        usage_context=usage_context,
        prompt_cache_key=prompt_cache_key,
    )
    formulas = result.get("formulas") if isinstance(result.get("formulas"), list) else []
    formulas_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for formula in formulas:
        if not isinstance(formula, dict):
            continue
        try:
            page_number = max(1, int(formula.get("page_number") or 1))
        except (TypeError, ValueError):
            page_number = 1
        formulas_by_page[page_number].append(formula)

    changed_page_ids: list[str] = []
    manual_pages_protected = 0
    if append_to_page_text:
        pages_by_number = {page.page_number: page for page in document.pages}
        for page_number, page_formulas in formulas_by_page.items():
            page = pages_by_number.get(page_number)
            if not page:
                continue
            if protect_manual and page.text_source == "manual":
                manual_pages_protected += 1
                continue
            if _append_formula_capture_to_page(page, page_formulas):
                changed_page_ids.append(page.id)

    openai = result.get("_openai") if isinstance(result.get("_openai"), dict) else {}
    configured = openai.get("configured", True)
    formula_count = len(formulas)
    status = "captured" if formula_count else "no_formulas"
    if configured is False:
        status = "unconfigured"
    evidence = {
        "status": status,
        "model": openai.get("model") or model,
        "configured": configured,
        "formula_count": formula_count,
        "pages_with_formulas": sorted(formulas_by_page),
        "manual_pages_protected": manual_pages_protected,
        "changed_pages": len(changed_page_ids),
        "changed_page_ids": changed_page_ids,
        "append_to_page_text": append_to_page_text,
        "formulas": formulas,
        "confidence": result.get("confidence"),
        "notes": result.get("notes") or [],
        "used_pdf_file": bool(openai.get("used_pdf_file")),
        "pdf_file_bytes": openai.get("pdf_file_bytes", 0),
    }
    if openai.get("prompt_cache_key"):
        evidence["prompt_cache_key"] = openai["prompt_cache_key"]
    return evidence
