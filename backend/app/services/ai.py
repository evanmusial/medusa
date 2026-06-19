from __future__ import annotations

import base64
import html
import signal
import threading
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.analysis_models import (
    MODEL_APA_CITATION,
    MODEL_ACCESSORY_SUMMARIES,
    MODEL_CORE_DOCUMENT_INTELLIGENCE,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_SUMMARY,
    MODEL_TEXT_CHUNK_ENCODING,
    default_analysis_models,
)
from app.services.extraction import normalize_extracted_text
from app.services.openai_usage import OpenAIUsageContext, record_openai_usage


METADATA_EXTRACTION_PROMPT = (
    "Extract scholarly identity metadata from this PDF context. The beginning may contain unrelated cover "
    "or front matter before the true article/chapter begins. Prefer DOI and publisher metadata when present. "
    "Extract every visible author, affiliation, and author contact email. Normalize deliberately obfuscated "
    "email addresses such as someone{at}university{dot}edu, someone [at] university [dot] edu, and "
    "someone at university dot edu into standard someone@university.edu form. Store an email only when it is "
    "visible in the PDF context; never infer one. Return cautious confidence and review reasons. If a field "
    "is uncertain, leave it null or empty."
)

PAGE_TEXT_NORMALIZATION_PROMPT = (
    "You normalize PDF-extracted scholarly text for a research reading pane. Preserve the original wording, "
    "order, citations, equations, section headings, lists, figure/table labels, captions, and tables. Do not "
    "summarize, paraphrase, omit substantive content, or add facts. Fix extraction artifacts only: strange "
    "spaces inside words, hyphenated line breaks, line-wrapped paragraphs, inconsistent whitespace, and obvious "
    "reading-flow breaks. Reconstruct logical reading flow across multiple columns and around unusually shaped "
    "graphics when the sequence is clear. Use a standard readable format: headings on their own lines, paragraphs "
    "separated by one blank line, list items on separate lines, and no extra whitespace. Keep paragraph breaks "
    "where they reflect the document's logical flow. Preserve tables as plain-text or Markdown-style tables when "
    "a table is evident. Do not convert charts, photos, diagrams, or figure graphics into Markdown or prose; those "
    "assets are stored separately as cropped page graphics. Keep visible labels/captions such as 'Figure 1.' as "
    "text anchors near the surrounding discussion."
)


METADATA_IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": ["string", "null"]},
        "authors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "given": {"type": "string"},
                    "family": {"type": "string"},
                    "affiliation": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]},
                },
                "required": ["given", "family", "affiliation", "email"],
            },
        },
        "universities": {"type": "array", "items": {"type": "string"}},
        "publication_year": {"type": ["integer", "null"]},
        "journal": {"type": ["string", "null"]},
        "publisher": {"type": ["string", "null"]},
        "doi": {"type": ["string", "null"]},
        "abstract": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "needs_review_reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "subtitle",
        "authors",
        "universities",
        "publication_year",
        "journal",
        "publisher",
        "doi",
        "abstract",
        "confidence",
        "needs_review_reasons",
    ],
}

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rich_summary": {"type": "string"},
        "confidence": {"type": "number"},
        "needs_review_reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rich_summary", "confidence", "needs_review_reasons"],
}

APA_CITATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "apa_citation": {"type": ["string", "null"]},
        "citation_warnings": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "needs_review_reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["apa_citation", "citation_warnings", "confidence", "needs_review_reasons"],
}

KEYWORDS_TOPICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topics": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "needs_review_reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics", "keywords", "confidence", "needs_review_reasons"],
}

CORE_DOCUMENT_INTELLIGENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "metadata": METADATA_IDENTITY_SCHEMA,
        "summary": SUMMARY_SCHEMA,
        "apa_citation": APA_CITATION_SCHEMA,
        "keywords_topics": KEYWORDS_TOPICS_SCHEMA,
    },
    "required": ["metadata", "summary", "apa_citation", "keywords_topics"],
}

CORE_DOCUMENT_INTELLIGENCE_PROMPT = (
    "Analyze this scholarly PDF context once and return all core Medusa document-intelligence outputs. "
    "Use only the supplied original PDF context and extracted text. First, extract scholarly identity metadata: "
    "title, subtitle, authors, visible affiliations, visible author contact emails, universities, publication year, "
    "journal/venue, publisher, DOI, and abstract. Normalize deliberately obfuscated visible emails such as "
    "someone{at}university{dot}edu, someone [at] university [dot] edu, and someone at university dot edu into "
    "standard someone@university.edu form. Never infer an email when it is absent. Second, generate rich_summary "
    "as concise Markdown with a short opening paragraph plus 3-5 labeled bullets for methods, findings, usefulness, "
    "and caveats when supported by the document. Do not start rich_summary with a standalone heading such as Summary, "
    "Overview, Abstract, Synopsis, or similar; begin with the semantic substance of the summary itself. Third, generate "
    "an APA 7 citation candidate as Markdown-compatible text with "
    "italicized publication titles where APA requires italics; return null or warnings when exact fields are uncertain. "
    "Fourth, extract concise topic tags and keywords useful for organizing and searching the scholarly document. "
    "Do not invent claims or bibliographic fields beyond the supplied context; leave uncertain fields null/empty and "
    "explain ambiguity in the relevant review reasons or citation warnings."
)

APA_CITATION_JUDGMENT_PROMPT = (
    "Generate and check an APA 7 citation candidate from the supplied citation metadata, matching evidence, "
    "and short document excerpts. Use only the supplied evidence. Prefer DOI-backed or publisher metadata when "
    "present. If the evidence is insufficient or internally conflicting, return null for apa_citation and explain "
    "the uncertainty in citation_warnings. Do not invent authors, year, venue, DOI, volume, issue, pages, or URLs. "
    "Use Markdown-compatible italics where APA requires italicized publication elements."
)

PAGE_TEXT_NORMALIZATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "normalized_text": {"type": "string"},
        "confidence": {"type": "number"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["normalized_text", "confidence", "notes"],
}

ACCESSORY_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
        "needs_review_reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "confidence", "needs_review_reasons"],
}

ACCESSORY_SUMMARY_PROMPT = (
    "Generate a focused accessory summary for a research-library document. Use only the supplied original PDF "
    "context and extracted text. The user will provide a question or precise topic. Answer that request directly "
    "with concise Markdown suitable for display under the document's main summary. Prefer specific evidence, "
    "methods, findings, caveats, and terminology from the document. If the document does not support part of the "
    "request, say so plainly instead of inventing details. Return a short optional title when one is natural."
)


class OpenAIHardTimeoutError(TimeoutError):
    pass


_EMAIL_RE = re.compile(r"([A-Z0-9._%+\-]+)@([A-Z0-9.\-]+\.[A-Z]{2,})", re.IGNORECASE)
_BRACKETED_AT_RE = re.compile(r"\s*(?:\{|\[|\(|<)\s*at\s*(?:\}|\]|\)|>)\s*", re.IGNORECASE)
_BRACKETED_DOT_RE = re.compile(r"\s*(?:\{|\[|\(|<)\s*dot\s*(?:\}|\]|\)|>)\s*", re.IGNORECASE)
_WORD_AT_RE = re.compile(r"(?<=[A-Z0-9._%+\-])\s+at\s+(?=[A-Z0-9._%+\-])", re.IGNORECASE)
_WORD_DOT_RE = re.compile(r"(?<=[A-Z0-9_\-])\s+dot\s+(?=[A-Z0-9_\-])", re.IGNORECASE)
_STANDALONE_SUMMARY_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:(?:brief|short|concise|executive|research|paper|article|document|study|scientific)\s+)?"
    r"(?:summary|overview|abstract|synopsis)"
    r"\s*[:.\-–—]?\s*(?:\*\*)?$",
    re.IGNORECASE,
)


def normalize_obfuscated_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = html.unescape(value).strip()
    if not normalized:
        return None
    normalized = _BRACKETED_AT_RE.sub("@", normalized)
    normalized = _BRACKETED_DOT_RE.sub(".", normalized)
    normalized = _WORD_AT_RE.sub("@", normalized)
    normalized = _WORD_DOT_RE.sub(".", normalized)
    normalized = re.sub(r"\s*@\s*", "@", normalized)
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    match = _EMAIL_RE.search(normalized)
    if not match:
        return None
    local, domain = match.groups()
    return f"{local}@{domain.lower()}"


def normalize_author_contact_details(authors: Any) -> list[dict[str, Any]]:
    if not isinstance(authors, list):
        return []
    normalized_authors: list[dict[str, Any]] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        next_author = dict(author)
        next_author["email"] = normalize_obfuscated_email(next_author.get("email"))
        normalized_authors.append(next_author)
    return normalized_authors


def strip_standalone_summary_heading(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    lines = text.splitlines()
    first_content_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_content_index is None:
        return ""
    first_line = lines[first_content_index].strip()
    if _STANDALONE_SUMMARY_HEADING_RE.match(first_line):
        return "\n".join(lines[first_content_index + 1 :]).strip()
    return text


@contextmanager
def hard_timeout(seconds: float):
    if seconds <= 0 or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _raise_timeout(_: int, __: object) -> None:
        raise OpenAIHardTimeoutError(f"OpenAI request exceeded {seconds:g} seconds")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


class AiService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        if self.settings.openai_api_key:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.openai_request_timeout_seconds,
            )

    def extract_metadata(
        self,
        filename: str,
        text: str,
        pdf_bytes: bytes | None = None,
        *,
        models: dict[str, str] | None = None,
        usage_context: OpenAIUsageContext | None = None,
        prompt_cache_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.client:
            title = Path(filename).stem.replace("_", " ").replace("-", " ").strip() or "Untitled document"
            return {
                "title": title,
                "subtitle": None,
                "authors": [],
                "universities": [],
                "publication_year": None,
                "journal": None,
                "publisher": None,
                "doi": None,
                "abstract": None,
                "rich_summary": "Metadata extraction is pending. Add an OpenAI API key to generate a scientific summary.",
                "apa_citation": None,
                "citation_warnings": ["OpenAI metadata extraction is not configured."],
                "topics": [],
                "keywords": [],
                "confidence": 0.2,
                "needs_review_reasons": ["OpenAI metadata extraction is not configured."],
            }

        models = {**default_analysis_models(), **(models or {})}
        input_content, used_pdf_file, input_text_characters, input_file_bytes = self._document_input_content(
            filename,
            text,
            pdf_bytes,
        )
        if self.settings.openai_combine_document_intelligence:
            try:
                core = self._responses_json(
                    model=models[MODEL_METADATA],
                    schema_name="medusa_core_document_intelligence",
                    schema=CORE_DOCUMENT_INTELLIGENCE_SCHEMA,
                    prompt=CORE_DOCUMENT_INTELLIGENCE_PROMPT,
                    input_content=input_content,
                    timeout=self.settings.openai_request_timeout_seconds,
                    usage_context=usage_context,
                    task_key=MODEL_CORE_DOCUMENT_INTELLIGENCE,
                    input_text_characters=input_text_characters,
                    input_file_bytes=input_file_bytes,
                    used_pdf_file=used_pdf_file,
                    prompt_cache_key=prompt_cache_key,
                )
                return self._merge_document_intelligence(
                    core.get("metadata") or {},
                    core.get("summary") or {},
                    core.get("apa_citation") or {},
                    core.get("keywords_topics") or {},
                    models=models,
                    used_pdf_file=used_pdf_file,
                    pdf_bytes=pdf_bytes,
                    combined=True,
                    combined_model=models[MODEL_METADATA],
                    prompt_cache_key=prompt_cache_key,
                    route="combined",
                )
            except Exception:
                # Preserve import durability: if the legacy combined response path fails, retry the routed calls.
                pass

        return self._extract_metadata_routed(
            filename=filename,
            text=text,
            input_content=input_content,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            models=models,
            pdf_bytes=pdf_bytes,
            usage_context=usage_context,
            prompt_cache_key=prompt_cache_key,
        )

    def _extract_metadata_routed(
        self,
        *,
        filename: str,
        text: str,
        input_content: list[dict[str, Any]],
        input_text_characters: int,
        input_file_bytes: int,
        used_pdf_file: bool,
        models: dict[str, str],
        pdf_bytes: bytes | None,
        usage_context: OpenAIUsageContext | None,
        prompt_cache_key: str | None,
    ) -> dict[str, Any]:
        identity = self._responses_json(
            model=models[MODEL_METADATA],
            schema_name="medusa_document_metadata",
            schema=METADATA_IDENTITY_SCHEMA,
            prompt=METADATA_EXTRACTION_PROMPT,
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_METADATA,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            prompt_cache_key=prompt_cache_key,
        )
        summary_input, _, summary_input_text_characters, _ = self._document_input_content(
            filename,
            text,
            None,
            max_text_chars=60_000,
        )
        summary = self._responses_json(
            model=models[MODEL_SUMMARY],
            schema_name="medusa_document_summary",
            schema=SUMMARY_SCHEMA,
            prompt=(
                "Generate rich_summary as concise Markdown from only the supplied extracted document text. Use a short "
                "opening paragraph plus 3-5 labeled bullets for methods, findings, usefulness, and caveats when the "
                "evidence supports them. Do not start with a standalone heading such as Summary, Overview, Abstract, "
                "Synopsis, or similar; begin with the semantic substance of the summary itself. Do not invent claims "
                "beyond the text."
            ),
            input_content=summary_input,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_SUMMARY,
            input_text_characters=summary_input_text_characters,
            input_file_bytes=0,
            used_pdf_file=False,
            prompt_cache_key=prompt_cache_key,
        )
        keywords_input, _, keywords_input_text_characters, _ = self._document_input_content(
            filename,
            text,
            None,
            max_text_chars=60_000,
        )
        keywords = self._responses_json(
            model=models[MODEL_KEYWORDS_TOPICS],
            schema_name="medusa_keywords_topics",
            schema=KEYWORDS_TOPICS_SCHEMA,
            prompt=(
                "Extract concise topic tags and keywords that would help organize and search this scholarly document. "
                "Use only the supplied extracted document text. Prefer short reusable concepts over long phrases."
            ),
            input_content=keywords_input,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_KEYWORDS_TOPICS,
            input_text_characters=keywords_input_text_characters,
            input_file_bytes=0,
            used_pdf_file=False,
            prompt_cache_key=prompt_cache_key,
        )
        return self._merge_document_intelligence(
            identity,
            summary,
            {
                "apa_citation": None,
                "citation_warnings": [],
                "confidence": identity.get("confidence"),
                "needs_review_reasons": [],
            },
            keywords,
            models=models,
            used_pdf_file=used_pdf_file,
            pdf_bytes=pdf_bytes,
            combined=False,
            combined_model=None,
            prompt_cache_key=prompt_cache_key,
            route="routed",
        )

    def _extract_metadata_separate(
        self,
        *,
        input_content: list[dict[str, Any]],
        input_text_characters: int,
        input_file_bytes: int,
        used_pdf_file: bool,
        models: dict[str, str],
        pdf_bytes: bytes | None,
        usage_context: OpenAIUsageContext | None,
        prompt_cache_key: str | None,
    ) -> dict[str, Any]:
        identity = self._responses_json(
            model=models[MODEL_METADATA],
            schema_name="medusa_document_metadata",
            schema=METADATA_IDENTITY_SCHEMA,
            prompt=METADATA_EXTRACTION_PROMPT,
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_METADATA,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            prompt_cache_key=prompt_cache_key,
        )
        summary = self._responses_json(
            model=models[MODEL_SUMMARY],
            schema_name="medusa_document_summary",
            schema=SUMMARY_SCHEMA,
            prompt=(
                "Generate rich_summary as concise Markdown from only the supplied document context. Use a short opening "
                "paragraph plus 3-5 labeled bullets for methods, findings, usefulness, and caveats when the evidence "
                "supports them. Do not start with a standalone heading such as Summary, Overview, Abstract, Synopsis, "
                "or similar; begin with the semantic substance of the summary itself. Do not invent claims beyond the "
                "original PDF context."
            ),
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_SUMMARY,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            prompt_cache_key=prompt_cache_key,
        )
        citation = self._responses_json(
            model=models[MODEL_APA_CITATION],
            schema_name="medusa_apa_citation_candidate",
            schema=APA_CITATION_SCHEMA,
            prompt=(
                "Generate an APA 7 citation candidate as Markdown-compatible text with italicized publication titles where APA "
                "requires italics, using only evidence visible in the supplied document context. If exact citation fields are "
                "uncertain, return null or explain the ambiguity in citation_warnings."
            ),
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_APA_CITATION,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            prompt_cache_key=prompt_cache_key,
        )
        keywords = self._responses_json(
            model=models[MODEL_KEYWORDS_TOPICS],
            schema_name="medusa_keywords_topics",
            schema=KEYWORDS_TOPICS_SCHEMA,
            prompt=(
                "Extract concise topic tags and keywords that would help organize and search this scholarly document. "
                "Use only the supplied original PDF context and extracted text."
            ),
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_KEYWORDS_TOPICS,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            prompt_cache_key=prompt_cache_key,
        )
        return self._merge_document_intelligence(
            identity,
            summary,
            citation,
            keywords,
            models=models,
            used_pdf_file=used_pdf_file,
            pdf_bytes=pdf_bytes,
            combined=False,
            combined_model=None,
            prompt_cache_key=prompt_cache_key,
            route="separate",
        )

    def _merge_document_intelligence(
        self,
        identity: dict[str, Any],
        summary: dict[str, Any],
        citation: dict[str, Any],
        keywords: dict[str, Any],
        *,
        models: dict[str, str],
        used_pdf_file: bool,
        pdf_bytes: bytes | None,
        combined: bool,
        combined_model: str | None,
        prompt_cache_key: str | None,
        route: str,
    ) -> dict[str, Any]:
        identity["authors"] = normalize_author_contact_details(identity.get("authors"))
        confidences = [
            value
            for value in [
                identity.get("confidence"),
                summary.get("confidence"),
                citation.get("confidence"),
                keywords.get("confidence"),
            ]
            if isinstance(value, (int, float))
        ]
        model_map = {
            MODEL_METADATA: models[MODEL_METADATA],
            MODEL_SUMMARY: models[MODEL_SUMMARY],
            MODEL_APA_CITATION: models[MODEL_APA_CITATION],
            MODEL_KEYWORDS_TOPICS: models[MODEL_KEYWORDS_TOPICS],
        }
        metadata = {
            **identity,
            "rich_summary": strip_standalone_summary_heading(summary.get("rich_summary")),
            "apa_citation": citation.get("apa_citation"),
            "citation_warnings": citation.get("citation_warnings") or [],
            "topics": keywords.get("topics") or [],
            "keywords": keywords.get("keywords") or [],
            "confidence": min(confidences) if confidences else identity.get("confidence"),
            "needs_review_reasons": self._unique_strings(
                [
                    *(identity.get("needs_review_reasons") or []),
                    *(summary.get("needs_review_reasons") or []),
                    *(citation.get("needs_review_reasons") or []),
                    *(keywords.get("needs_review_reasons") or []),
                ]
            ),
            "_openai": {
                "model": combined_model or models[MODEL_METADATA],
                "models": model_map,
                "combined_document_intelligence": combined,
                "combined_model": combined_model,
                "document_intelligence_route": route,
                "prompt_cache_key": self._normalize_prompt_cache_key(prompt_cache_key),
                "used_pdf_file": used_pdf_file,
                "pdf_file_bytes": len(pdf_bytes or b"") if used_pdf_file else 0,
            },
        }
        return metadata

    def _document_input_content(
        self,
        filename: str,
        text: str,
        pdf_bytes: bytes | None,
        *,
        page_number: int | None = None,
        max_text_chars: int = 28_000,
    ) -> tuple[list[dict[str, Any]], bool, int, int]:
        sample = text[:max_text_chars]
        input_content: list[dict[str, Any]] = []
        used_pdf_file = self._should_send_pdf_file(pdf_bytes)
        input_file_bytes = len(pdf_bytes or b"") if used_pdf_file else 0
        if used_pdf_file and pdf_bytes:
            input_content.append(
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('ascii')}",
                }
            )
        heading = f"Filename: {filename}"
        if page_number is not None:
            heading = f"{heading}\nPage: {page_number}"
        input_text = f"{heading}\n\nExtracted PDF text:\n{sample}"
        input_content.append({"type": "input_text", "text": input_text})
        return input_content, used_pdf_file, len(input_text), input_file_bytes

    def generate_apa_citation_candidate(
        self,
        filename: str,
        text: str,
        metadata: dict[str, Any],
        *,
        model: str | None = None,
        crossref_candidates: list[dict[str, Any]] | None = None,
        usage_context: OpenAIUsageContext | None = None,
        prompt_cache_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.client:
            return {
                "apa_citation": None,
                "citation_warnings": ["OpenAI APA citation matching is not configured."],
                "confidence": 0.0,
                "needs_review_reasons": ["OpenAI APA citation matching is not configured."],
            }
        selected_model = model or default_analysis_models()[MODEL_APA_CITATION]
        evidence_text = self._citation_evidence_text(text)
        input_text = (
            f"Filename: {filename}\n\n"
            "Known citation metadata:\n"
            f"{json.dumps(metadata, ensure_ascii=True, sort_keys=True)}\n\n"
            "Crossref or DOI candidate evidence:\n"
            f"{json.dumps(crossref_candidates or [], ensure_ascii=True, sort_keys=True)[:10_000]}\n\n"
            "Document excerpts:\n"
            f"{evidence_text}"
        )
        input_content = [{"type": "input_text", "text": input_text}]
        result = self._responses_json(
            model=selected_model,
            schema_name="medusa_apa_citation_candidate",
            schema=APA_CITATION_SCHEMA,
            prompt=APA_CITATION_JUDGMENT_PROMPT,
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_APA_CITATION,
            input_text_characters=len(input_text),
            input_file_bytes=0,
            used_pdf_file=False,
            prompt_cache_key=prompt_cache_key,
        )
        result["_openai"] = {
            "model": selected_model,
            "prompt_cache_key": self._normalize_prompt_cache_key(prompt_cache_key),
            "used_pdf_file": False,
        }
        return result

    def generate_accessory_summary(
        self,
        filename: str,
        text: str,
        prompt: str,
        *,
        model: str | None = None,
        pdf_bytes: bytes | None = None,
        usage_context: OpenAIUsageContext | None = None,
        prompt_cache_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError("OpenAI accessory summaries are not configured.")
        selected_model = model or default_analysis_models()[MODEL_ACCESSORY_SUMMARIES]
        document_content, used_pdf_file, input_text_characters, input_file_bytes = self._document_input_content(
            filename,
            text,
            pdf_bytes,
            max_text_chars=80_000,
        )
        request_text = f"Accessory summary request:\n{prompt.strip()}"
        input_content = [{"type": "input_text", "text": request_text}, *document_content]
        result = self._responses_json(
            model=selected_model,
            schema_name="medusa_accessory_summary",
            schema=ACCESSORY_SUMMARY_SCHEMA,
            prompt=ACCESSORY_SUMMARY_PROMPT,
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_ACCESSORY_SUMMARIES,
            input_text_characters=input_text_characters + len(request_text),
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
            prompt_cache_key=prompt_cache_key,
        )
        result["_openai"] = {
            "model": selected_model,
            "prompt_cache_key": self._normalize_prompt_cache_key(prompt_cache_key),
            "used_pdf_file": used_pdf_file,
            "pdf_file_bytes": input_file_bytes,
        }
        return result

    def _responses_json(
        self,
        *,
        model: str,
        schema_name: str,
        schema: dict[str, Any],
        prompt: str,
        input_content: list[dict[str, Any]],
        timeout: float,
        usage_context: OpenAIUsageContext | None = None,
        task_key: str | None = None,
        input_text_characters: int = 0,
        input_file_bytes: int = 0,
        used_pdf_file: bool = False,
        prompt_cache_key: str | None = None,
    ) -> dict[str, Any]:
        response = None
        cache_key = self._normalize_prompt_cache_key(prompt_cache_key)
        cache_retention = self._normalize_prompt_cache_retention(self.settings.openai_prompt_cache_retention)
        cache_params: dict[str, Any] = {}
        if cache_key:
            cache_params["prompt_cache_key"] = cache_key
        if cache_key and cache_retention:
            cache_params["prompt_cache_retention"] = cache_retention
        try:
            with hard_timeout(timeout):
                response = self.client.responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": input_content},
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": schema_name,
                            "schema": schema,
                            "strict": True,
                        }
                    },
                    timeout=timeout,
                    **cache_params,
                )
            payload = json.loads(response.output_text)
            record_openai_usage(
                usage_context,
                task_key=task_key or schema_name,
                operation=schema_name,
                endpoint="responses",
                model=model,
                status="success",
                response=response,
                input_text_characters=input_text_characters,
                input_file_bytes=input_file_bytes,
                used_pdf_file=used_pdf_file,
            )
            return payload
        except Exception as exc:
            record_openai_usage(
                usage_context,
                task_key=task_key or schema_name,
                operation=schema_name,
                endpoint="responses",
                model=model,
                status="failed",
                response=response,
                error=exc,
                input_text_characters=input_text_characters,
                input_file_bytes=input_file_bytes,
                used_pdf_file=used_pdf_file,
            )
            raise

    @staticmethod
    def _unique_strings(values: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _normalize_prompt_cache_key(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", value.strip())
        return normalized[:128] or None

    @staticmethod
    def _normalize_prompt_cache_retention(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        return normalized if normalized in {"in_memory", "24h"} else None

    @staticmethod
    def _citation_evidence_text(text: str | None) -> str:
        normalized = normalize_extracted_text(text)
        if not normalized:
            return ""
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", normalized) if paragraph.strip()]
        first_paragraphs = "\n\n".join(paragraphs[:8])
        doi_contexts = [
            paragraph
            for paragraph in paragraphs
            if re.search(r"\bdoi\b|10\.\d{4,9}/", paragraph, re.IGNORECASE)
        ][:4]
        reference_heading_index = next(
            (
                index
                for index, paragraph in enumerate(paragraphs)
                if re.match(r"^(references|bibliography|works cited)\b", paragraph, re.IGNORECASE)
            ),
            None,
        )
        reference_context = ""
        if reference_heading_index is not None:
            reference_context = "\n\n".join(paragraphs[reference_heading_index : reference_heading_index + 6])
        parts = [first_paragraphs, "\n\n".join(doi_contexts), reference_context]
        return "\n\n".join(part for part in parts if part)[:16_000]

    def _should_send_pdf_file(self, pdf_bytes: bytes | None) -> bool:
        if not pdf_bytes or not self.settings.openai_send_pdf_file:
            return False
        return len(pdf_bytes) <= self.settings.openai_pdf_file_max_mb * 1024 * 1024

    def normalize_page_text(
        self,
        filename: str,
        page_number: int,
        text: str | None,
        *,
        model: str | None = None,
        pdf_bytes: bytes | None = None,
        usage_context: OpenAIUsageContext | None = None,
    ) -> dict[str, Any]:
        fallback = normalize_extracted_text(text)
        if not fallback:
            return {
                "normalized_text": "",
                "source": "empty",
                "confidence": 1.0,
                "notes": [],
            }
        if not self.client or not self.settings.openai_normalize_page_text:
            return {
                "normalized_text": fallback,
                "source": "local",
                "confidence": 0.55,
                "notes": ["OpenAI page text normalization is not configured."],
            }

        sample = fallback[: self.settings.openai_text_normalization_page_max_chars]
        input_content, used_pdf_file, input_text_characters, input_file_bytes = self._document_input_content(
            filename,
            sample,
            pdf_bytes,
            page_number=page_number,
        )
        selected_model = model or default_analysis_models()[MODEL_PAGE_TEXT_NORMALIZATION]
        page_usage_context = usage_context.for_page(page_number) if usage_context else None
        page_cache_key = None
        if usage_context and usage_context.document_id:
            page_cache_key = f"medusa-page:{usage_context.document_id}:{page_number}"
        cache_key = self._normalize_prompt_cache_key(page_cache_key)
        cache_retention = self._normalize_prompt_cache_retention(self.settings.openai_prompt_cache_retention)
        cache_params: dict[str, Any] = {}
        if cache_key:
            cache_params["prompt_cache_key"] = cache_key
        if cache_key and cache_retention:
            cache_params["prompt_cache_retention"] = cache_retention
        response = None
        try:
            with hard_timeout(self.settings.openai_page_normalization_timeout_seconds):
                response = self.client.responses.create(
                    model=selected_model,
                    input=[
                        {"role": "system", "content": PAGE_TEXT_NORMALIZATION_PROMPT},
                        {"role": "user", "content": input_content},
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "medusa_page_text_normalization",
                            "schema": PAGE_TEXT_NORMALIZATION_SCHEMA,
                            "strict": True,
                        }
                    },
                    timeout=self.settings.openai_page_normalization_timeout_seconds,
                    **cache_params,
                )
            result = json.loads(response.output_text)
            record_openai_usage(
                page_usage_context,
                task_key=MODEL_PAGE_TEXT_NORMALIZATION,
                operation="medusa_page_text_normalization",
                endpoint="responses",
                model=selected_model,
                status="success",
                response=response,
                input_text_characters=input_text_characters,
                input_file_bytes=input_file_bytes,
                used_pdf_file=used_pdf_file,
            )
            normalized = normalize_extracted_text(result.get("normalized_text") or fallback) or fallback
            return {
                "normalized_text": normalized,
                "source": "openai",
                "confidence": result.get("confidence"),
                "notes": result.get("notes") or [],
                "_openai": {
                    "model": selected_model,
                    "input_characters": len(sample),
                    "used_pdf_file": used_pdf_file,
                },
            }
        except Exception as exc:
            record_openai_usage(
                page_usage_context,
                task_key=MODEL_PAGE_TEXT_NORMALIZATION,
                operation="medusa_page_text_normalization",
                endpoint="responses",
                model=selected_model,
                status="failed",
                response=response,
                error=exc,
                input_text_characters=input_text_characters,
                input_file_bytes=input_file_bytes,
                used_pdf_file=used_pdf_file,
            )
            return {
                "normalized_text": fallback,
                "source": "local_fallback",
                "confidence": 0.45,
                "notes": [f"OpenAI page text normalization failed: {exc}"],
            }

    def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        usage_context: OpenAIUsageContext | None = None,
    ) -> list[float] | None:
        if not self.client or not text.strip():
            return None
        selected_model = model or default_analysis_models()[MODEL_TEXT_CHUNK_ENCODING]
        input_text = text[:24_000]
        try:
            with hard_timeout(self.settings.openai_embedding_timeout_seconds):
                response = self.client.embeddings.create(
                    model=selected_model,
                    input=input_text,
                    encoding_format="float",
                    timeout=self.settings.openai_embedding_timeout_seconds,
                )
            record_openai_usage(
                usage_context,
                task_key=MODEL_TEXT_CHUNK_ENCODING,
                operation="text_chunk_embedding",
                endpoint="embeddings",
                model=selected_model,
                status="success",
                response=response,
                input_text_characters=len(input_text),
            )
        except Exception as exc:
            record_openai_usage(
                usage_context,
                task_key=MODEL_TEXT_CHUNK_ENCODING,
                operation="text_chunk_embedding",
                endpoint="embeddings",
                model=selected_model,
                status="failed",
                error=exc,
                input_text_characters=len(input_text),
            )
            raise
        return response.data[0].embedding


def get_ai_service() -> AiService:
    return AiService()
