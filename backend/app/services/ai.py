from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.extraction import normalize_extracted_text


METADATA_SCHEMA: dict[str, Any] = {
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
                },
                "required": ["given", "family", "affiliation"],
            },
        },
        "universities": {"type": "array", "items": {"type": "string"}},
        "publication_year": {"type": ["integer", "null"]},
        "journal": {"type": ["string", "null"]},
        "publisher": {"type": ["string", "null"]},
        "doi": {"type": ["string", "null"]},
        "abstract": {"type": ["string", "null"]},
        "rich_summary": {"type": "string"},
        "apa_citation": {"type": ["string", "null"]},
        "citation_warnings": {"type": "array", "items": {"type": "string"}},
        "topics": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
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
        "rich_summary",
        "apa_citation",
        "citation_warnings",
        "topics",
        "keywords",
        "confidence",
        "needs_review_reasons",
    ],
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


class AiService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        if self.settings.openai_api_key:
            from openai import OpenAI

            self.client = OpenAI(api_key=self.settings.openai_api_key)

    def extract_metadata(self, filename: str, text: str, pdf_bytes: bytes | None = None) -> dict[str, Any]:
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

        prompt = (
            "Extract scholarly metadata from this PDF text. The beginning may contain unrelated cover "
            "or front matter before the true article/chapter begins. Prefer DOI and publisher metadata "
            "when present. Generate rich_summary as concise Markdown, not one dense paragraph: use a "
            "short overview plus 3-5 labeled bullets for methods, findings, usefulness, and caveats when "
            "the evidence supports them. Generate topic tags, keywords, and an APA 7 citation candidate "
            "as Markdown-compatible text with italicized publication titles where APA requires italics, "
            "using only evidence visible in the supplied document context. Return cautious confidence and "
            "review reasons. If exact citation fields are uncertain, leave fields null and explain the "
            "ambiguity in citation_warnings."
        )
        sample = text[:28_000]
        input_content: list[dict[str, Any]] = []
        used_pdf_file = self._should_send_pdf_file(pdf_bytes)
        if used_pdf_file and pdf_bytes:
            input_content.append(
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('ascii')}",
                }
            )
        input_content.append({"type": "input_text", "text": f"Filename: {filename}\n\nExtracted PDF text:\n{sample}"})
        response = self.client.responses.create(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": input_content},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "medusa_document_metadata",
                    "schema": METADATA_SCHEMA,
                    "strict": True,
                }
            },
        )
        metadata = json.loads(response.output_text)
        metadata["_openai"] = {
            "model": self.settings.openai_model,
            "used_pdf_file": used_pdf_file,
            "pdf_file_bytes": len(pdf_bytes or b"") if used_pdf_file else 0,
        }
        return metadata

    def _should_send_pdf_file(self, pdf_bytes: bytes | None) -> bool:
        if not pdf_bytes or not self.settings.openai_send_pdf_file:
            return False
        return len(pdf_bytes) <= self.settings.openai_pdf_file_max_mb * 1024 * 1024

    def normalize_page_text(self, filename: str, page_number: int, text: str | None) -> dict[str, Any]:
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

        prompt = (
            "You normalize PDF-extracted scholarly text for a research reading pane. Preserve the original "
            "wording, order, citations, equations, section headings, and tables. Do not summarize, paraphrase, "
            "omit substantive content, or add facts. Fix extraction artifacts only: strange spaces inside words, "
            "hyphenated line breaks, line-wrapped paragraphs, inconsistent whitespace, and obvious reading-flow "
            "breaks. Keep paragraph breaks where they reflect the document's logical flow. Preserve tables as "
            "plain-text or Markdown-style tables when a table is evident."
        )
        sample = fallback[: self.settings.openai_text_normalization_page_max_chars]
        try:
            response = self.client.responses.create(
                model=self.settings.openai_model,
                input=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Filename: {filename}\nPage: {page_number}\n\n"
                            f"PDF-extracted page text to normalize:\n{sample}"
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "medusa_page_text_normalization",
                        "schema": PAGE_TEXT_NORMALIZATION_SCHEMA,
                        "strict": True,
                    }
                },
            )
            result = json.loads(response.output_text)
            normalized = normalize_extracted_text(result.get("normalized_text") or fallback) or fallback
            return {
                "normalized_text": normalized,
                "source": "openai",
                "confidence": result.get("confidence"),
                "notes": result.get("notes") or [],
                "_openai": {
                    "model": self.settings.openai_model,
                    "input_characters": len(sample),
                },
            }
        except Exception as exc:
            return {
                "normalized_text": fallback,
                "source": "local_fallback",
                "confidence": 0.45,
                "notes": [f"OpenAI page text normalization failed: {exc}"],
            }

    def embed(self, text: str) -> list[float] | None:
        if not self.client or not text.strip():
            return None
        response = self.client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text[:24_000],
            encoding_format="float",
        )
        return response.data[0].embedding


def get_ai_service() -> AiService:
    return AiService()
