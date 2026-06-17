from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


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
        "topics",
        "keywords",
        "confidence",
        "needs_review_reasons",
    ],
}


class AiService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        if self.settings.openai_api_key:
            from openai import OpenAI

            self.client = OpenAI(api_key=self.settings.openai_api_key)

    def extract_metadata(self, filename: str, text: str) -> dict[str, Any]:
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
                "topics": [],
                "keywords": [],
                "confidence": 0.2,
                "needs_review_reasons": ["OpenAI metadata extraction is not configured."],
            }

        prompt = (
            "Extract scholarly metadata from this PDF text. The beginning may contain unrelated cover "
            "or front matter before the true article/chapter begins. Prefer DOI and publisher metadata "
            "when present. Return cautious confidence and review reasons."
        )
        sample = text[:28_000]
        response = self.client.responses.create(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Filename: {filename}\n\nPDF text:\n{sample}"},
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
        return json.loads(response.output_text)

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
