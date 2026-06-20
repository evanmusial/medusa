from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.services.extraction import sanitize_extracted_text


PDF_CONTENT_TYPE = "application/pdf"
HTML_EXTENSIONS = {".html", ".htm"}
TEXT_EXTENSIONS = {".txt", ".text", ".md", ".markdown"}
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
TEXT_CONTENT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
SUPPORTED_SOURCE_KINDS = {"pdf", "html", "text"}


class ImportSourceError(ValueError):
    pass


@dataclass(frozen=True)
class SourceProbe:
    source_kind: str
    filename: str
    checksum_sha256: str
    file_size_bytes: int
    stored_filename: str


@dataclass(frozen=True)
class SemanticBlock:
    kind: str
    text: str
    level: int = 0


@dataclass(frozen=True)
class PreparedImportSource:
    source_kind: str
    source_filename: str
    source_content_type: str
    source_checksum_sha256: str
    source_size_bytes: int
    stored_filename: str
    stored_content_type: str
    stored_data: bytes
    stored_checksum_sha256: str
    title: str
    metadata: dict[str, Any]


def _normalized_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _safe_filename(filename: str | None, fallback: str = "document") -> str:
    candidate = Path(filename or fallback).name.strip()
    candidate = re.sub(r"[\x00-\x1f\x7f/\\:]+", "_", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")
    return candidate or fallback


def _pdf_filename(filename: str) -> str:
    source = Path(_safe_filename(filename)).with_suffix("")
    stem = re.sub(r"\s+", " ", source.name).strip(" .") or "document"
    return f"{stem}.pdf"


def classify_import_source(filename: str | None, content_type: str | None = None) -> str:
    clean_type = _normalized_content_type(content_type)
    suffix = Path(filename or "").suffix.lower()
    if clean_type == PDF_CONTENT_TYPE or suffix == ".pdf":
        return "pdf"
    if clean_type in HTML_CONTENT_TYPES or suffix in HTML_EXTENSIONS:
        return "html"
    if clean_type in TEXT_CONTENT_TYPES or suffix in TEXT_EXTENSIONS:
        return "text"
    raise ImportSourceError("Unsupported import file type. Use PDF, HTML, or plain text.")


def probe_import_source(data: bytes, filename: str | None, content_type: str | None = None) -> SourceProbe:
    source_kind = classify_import_source(filename, content_type)
    safe_name = _safe_filename(filename, f"document.{source_kind}")
    return SourceProbe(
        source_kind=source_kind,
        filename=safe_name,
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        file_size_bytes=len(data),
        stored_filename=safe_name if source_kind == "pdf" else _pdf_filename(safe_name),
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clean_text(value: str, *, preserve_lines: bool = False) -> str:
    value = sanitize_extracted_text(unescape(value)).replace("\r\n", "\n").replace("\r", "\n")
    if preserve_lines:
        return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()).strip()
    return re.sub(r"\s+", " ", value).strip()


class _SemanticHTMLParser(HTMLParser):
    block_tags = {
        "title",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "blockquote",
        "pre",
        "figcaption",
        "caption",
        "td",
        "th",
    }
    ignored_tags = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[SemanticBlock] = []
        self._current_tag: str | None = None
        self._current_parts: list[str] = []
        self._orphan_parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self.ignored_tags:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "br":
            self._append("\n")
            return
        if tag in self.block_tags:
            self._flush_current()
            self._flush_orphans()
            self._current_tag = tag
            self._current_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if self._current_tag == tag:
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self._append(data)

    def close(self) -> None:
        super().close()
        self._flush_current()
        self._flush_orphans()

    def _append(self, data: str) -> None:
        if self._current_tag:
            self._current_parts.append(data)
        else:
            self._orphan_parts.append(data)

    def _flush_current(self) -> None:
        if not self._current_tag:
            return
        preserve = self._current_tag == "pre"
        text = _clean_text("".join(self._current_parts), preserve_lines=preserve)
        tag = self._current_tag
        self._current_tag = None
        self._current_parts = []
        if not text:
            return
        if tag == "title":
            self.blocks.append(SemanticBlock(kind="title", text=text, level=1))
        elif tag.startswith("h") and tag[1:].isdigit():
            self.blocks.append(SemanticBlock(kind="heading", text=text, level=int(tag[1:])))
        elif tag == "li":
            self.blocks.append(SemanticBlock(kind="list_item", text=text))
        elif tag == "pre":
            self.blocks.append(SemanticBlock(kind="pre", text=text))
        else:
            self.blocks.append(SemanticBlock(kind="paragraph", text=text))

    def _flush_orphans(self) -> None:
        text = _clean_text("".join(self._orphan_parts))
        self._orphan_parts = []
        if text:
            self.blocks.append(SemanticBlock(kind="paragraph", text=text))


def _parse_html(text: str, fallback_title: str) -> tuple[str, list[SemanticBlock], list[dict[str, Any]]]:
    parser = _SemanticHTMLParser()
    parser.feed(text)
    parser.close()
    blocks = parser.blocks or [SemanticBlock(kind="paragraph", text=_clean_text(text))]
    title_block = next((block for block in blocks if block.kind == "heading" and block.level == 1), None)
    if not title_block:
        title_block = next((block for block in blocks if block.kind == "title"), None)
    if not title_block:
        title_block = next((block for block in blocks if block.kind == "heading"), None)
    title = title_block.text if title_block else fallback_title
    outline = [
        {"level": block.level, "text": block.text[:240]}
        for block in blocks
        if block.kind in {"title", "heading"}
    ][:40]
    return title[:600], blocks, outline


def _parse_plain_text(text: str, fallback_title: str) -> tuple[str, list[SemanticBlock], list[dict[str, Any]]]:
    clean = sanitize_extracted_text(text).replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [_clean_text(block, preserve_lines=True) for block in re.split(r"\n\s*\n+", clean)]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        paragraphs = [_clean_text(clean) or fallback_title]
    first_line = next((line.strip() for line in clean.splitlines() if line.strip()), fallback_title)
    title = first_line[:600] if len(first_line) <= 180 else fallback_title
    blocks: list[SemanticBlock] = []
    title_used = False
    for paragraph in paragraphs:
        if not title_used and paragraph == first_line and len(first_line) <= 180:
            blocks.append(SemanticBlock(kind="heading", text=paragraph, level=1))
            title_used = True
        else:
            blocks.append(SemanticBlock(kind="paragraph", text=paragraph))
    outline = [{"level": 1, "text": title[:240]}] if title else []
    return title, blocks, outline


def _wrap_for_pdf(text: str, *, font_size: float, width: float) -> list[str]:
    lines: list[str] = []
    max_chars = max(24, int(width / max(font_size * 0.52, 1)))
    for raw_line in text.splitlines() or [text]:
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        wrapped = textwrap.wrap(line, width=max_chars, replace_whitespace=True, drop_whitespace=True)
        lines.extend(wrapped or [""])
    return lines


def _render_blocks_to_pdf(title: str, blocks: list[SemanticBlock]) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - exercised only without optional dependency
        raise ImportSourceError("PyMuPDF is required to convert HTML or text imports to PDF.") from exc

    doc = fitz.open()
    page_width = 612
    page_height = 792
    margin_x = 54
    margin_y = 54
    content_width = page_width - (2 * margin_x)
    bottom = page_height - margin_y
    page = doc.new_page(width=page_width, height=page_height)
    y = margin_y
    page_texts: list[list[str]] = [[]]

    def new_page() -> None:
        nonlocal page, y
        page = doc.new_page(width=page_width, height=page_height)
        page_texts.append([])
        y = margin_y

    def add_vertical(amount: float) -> None:
        nonlocal y
        y += amount
        if page_texts[-1] and page_texts[-1][-1] != "":
            page_texts[-1].append("")

    def add_text(text: str, *, font_size: float, indent: float = 0, fontname: str = "helv") -> None:
        nonlocal y
        line_height = font_size * 1.35
        for line in _wrap_for_pdf(text, font_size=font_size, width=content_width - indent):
            if y + line_height > bottom:
                new_page()
            if line:
                page.insert_text((margin_x + indent, y), line, fontsize=font_size, fontname=fontname, color=(0, 0, 0))
                page_texts[-1].append(line)
            y += line_height

    for index, block in enumerate(blocks):
        if index > 0:
            add_vertical(8)
        if block.kind == "title":
            add_text(block.text, font_size=18)
            add_vertical(6)
        elif block.kind == "heading":
            font_size = 17 if block.level <= 1 else 15 if block.level == 2 else 13
            add_text(block.text, font_size=font_size)
            add_vertical(4)
        elif block.kind == "list_item":
            add_text(f"- {block.text}", font_size=11, indent=12)
        elif block.kind == "pre":
            add_text(block.text, font_size=9.5, fontname="cour")
        else:
            add_text(block.text, font_size=11)

    doc.set_metadata({"title": title, "creator": "Medusa", "producer": "PyMuPDF"})
    pdf_bytes = doc.tobytes(garbage=4, deflate=True, clean=True)
    pages = []
    for index, lines in enumerate(page_texts, start=1):
        text = sanitize_extracted_text("\n".join(lines)).strip()
        if text:
            pages.append({"page_number": index, "text": text, "low_text": len(text) < 120, "source": "source_semantics"})
    if not pages:
        pages.append({"page_number": 1, "text": title, "low_text": len(title) < 120, "source": "source_semantics"})
    return pdf_bytes, pages


def prepare_import_source(data: bytes, filename: str | None, content_type: str | None = None) -> PreparedImportSource:
    probe = probe_import_source(data, filename, content_type)
    source_content_type = _normalized_content_type(content_type)
    if probe.source_kind == "pdf":
        return PreparedImportSource(
            source_kind="pdf",
            source_filename=probe.filename,
            source_content_type=source_content_type or PDF_CONTENT_TYPE,
            source_checksum_sha256=probe.checksum_sha256,
            source_size_bytes=probe.file_size_bytes,
            stored_filename=probe.stored_filename,
            stored_content_type=PDF_CONTENT_TYPE,
            stored_data=data,
            stored_checksum_sha256=probe.checksum_sha256,
            title=Path(probe.filename).stem.replace("_", " ").replace("-", " "),
            metadata={"kind": "pdf"},
        )

    text = _decode_text(data)
    fallback_title = Path(probe.filename).stem.replace("_", " ").replace("-", " ")
    if probe.source_kind == "html":
        title, blocks, outline = _parse_html(text, fallback_title)
    else:
        title, blocks, outline = _parse_plain_text(text, fallback_title)
    pdf_bytes, pages = _render_blocks_to_pdf(title, blocks)
    stored_checksum = hashlib.sha256(pdf_bytes).hexdigest()
    metadata = {
        "kind": probe.source_kind,
        "original_filename": probe.filename,
        "original_content_type": source_content_type or ("text/html" if probe.source_kind == "html" else "text/plain"),
        "source_checksum_sha256": probe.checksum_sha256,
        "source_size_bytes": probe.file_size_bytes,
        "parsed_title": title,
        "semantic_outline": outline,
        "extracted_pages": pages,
        "mezzanine": {
            "format": "pdf",
            "filename": probe.stored_filename,
            "content_type": PDF_CONTENT_TYPE,
            "checksum_sha256": stored_checksum,
            "size_bytes": len(pdf_bytes),
            "tool": "pymupdf",
        },
    }
    return PreparedImportSource(
        source_kind=probe.source_kind,
        source_filename=probe.filename,
        source_content_type=metadata["original_content_type"],
        source_checksum_sha256=probe.checksum_sha256,
        source_size_bytes=probe.file_size_bytes,
        stored_filename=probe.stored_filename,
        stored_content_type=PDF_CONTENT_TYPE,
        stored_data=pdf_bytes,
        stored_checksum_sha256=stored_checksum,
        title=title,
        metadata=metadata,
    )
