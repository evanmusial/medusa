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


class OpenAIHardTimeoutError(TimeoutError):
    pass


_EMAIL_RE = re.compile(r"([A-Z0-9._%+\-]+)@([A-Z0-9.\-]+\.[A-Z]{2,})", re.IGNORECASE)
_BRACKETED_AT_RE = re.compile(r"\s*(?:\{|\[|\(|<)\s*at\s*(?:\}|\]|\)|>)\s*", re.IGNORECASE)
_BRACKETED_DOT_RE = re.compile(r"\s*(?:\{|\[|\(|<)\s*dot\s*(?:\}|\]|\)|>)\s*", re.IGNORECASE)
_WORD_AT_RE = re.compile(r"(?<=[A-Z0-9._%+\-])\s+at\s+(?=[A-Z0-9._%+\-])", re.IGNORECASE)
_WORD_DOT_RE = re.compile(r"(?<=[A-Z0-9_\-])\s+dot\s+(?=[A-Z0-9_\-])", re.IGNORECASE)


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
        )
        identity["authors"] = normalize_author_contact_details(identity.get("authors"))
        summary = self._responses_json(
            model=models[MODEL_SUMMARY],
            schema_name="medusa_document_summary",
            schema=SUMMARY_SCHEMA,
            prompt=(
                "Generate rich_summary as concise Markdown from only the supplied document context. Use a short overview "
                "plus 3-5 labeled bullets for methods, findings, usefulness, and caveats when the evidence supports them. "
                "Do not invent claims beyond the original PDF context."
            ),
            input_content=input_content,
            timeout=self.settings.openai_request_timeout_seconds,
            usage_context=usage_context,
            task_key=MODEL_SUMMARY,
            input_text_characters=input_text_characters,
            input_file_bytes=input_file_bytes,
            used_pdf_file=used_pdf_file,
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
        )
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
        metadata = {
            **identity,
            "rich_summary": summary.get("rich_summary") or "",
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
                "model": models[MODEL_METADATA],
                "models": {
                    MODEL_METADATA: models[MODEL_METADATA],
                    MODEL_SUMMARY: models[MODEL_SUMMARY],
                    MODEL_APA_CITATION: models[MODEL_APA_CITATION],
                    MODEL_KEYWORDS_TOPICS: models[MODEL_KEYWORDS_TOPICS],
                },
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
    ) -> tuple[list[dict[str, Any]], bool, int, int]:
        sample = text[:28_000]
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
    ) -> dict[str, Any]:
        response = None
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
