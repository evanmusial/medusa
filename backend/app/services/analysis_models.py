from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.config import get_settings


DEFAULT_GPT_MODEL = "gpt-5.5"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_RAW_TEXT_EXTRACTOR = "marker"

MODEL_RAW_TEXT_EXTRACTION = "raw_text_extraction"
MODEL_METADATA = "metadata"
MODEL_SUMMARY = "summary"
MODEL_APA_CITATION = "apa_citation"
MODEL_KEYWORDS_TOPICS = "keywords_topics"
MODEL_PAGE_TEXT_NORMALIZATION = "page_text_normalization"
MODEL_TEXT_CHUNK_ENCODING = "text_chunk_encoding"
MODEL_ACCESSORY_SUMMARIES = "accessory_summaries"

GPT_MODEL_OPTIONS = (
    "gpt-4o",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-nano-2025-08-07",
    "gpt-5-pro",
    "gpt-5.1",
    "gpt-5.1-2025-11-13",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-5.4-pro-2026-03-05",
    "gpt-5.5",
    "gpt-5.5-2026-04-23",
    "gpt-5.5-pro",
    "gpt-5.5-pro-2026-04-23",
)
EMBEDDING_MODEL_OPTIONS = (
    "text-embedding-3-small",
    "text-embedding-3-large",
)
LOCAL_RAW_TEXT_EXTRACTOR_OPTIONS = (
    "docling",
    "marker",
    "pymupdf",
)

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


@dataclass(frozen=True)
class AnalysisModelTask:
    key: str
    label: str
    model_kind: Literal["gpt", "embedding", "raw_text_extraction"]
    description: str


ANALYSIS_MODEL_TASKS: tuple[AnalysisModelTask, ...] = (
    AnalysisModelTask(
        key=MODEL_RAW_TEXT_EXTRACTION,
        label="Raw Text Extraction",
        model_kind="raw_text_extraction",
        description="Extracts and linearizes the PDF text/layout before page normalization, indexing, and document intelligence. Local extractors avoid cloud model spend; OpenAI options are reserved for cloud-backed extraction fallbacks.",
    ),
    AnalysisModelTask(
        key=MODEL_METADATA,
        label="Metadata",
        model_kind="gpt",
        description="Extracts scholarly identity fields from the original PDF context: title, authors, affiliations, normalized author emails, venue, publisher, DOI, abstract, and review reasons.",
    ),
    AnalysisModelTask(
        key=MODEL_SUMMARY,
        label="Summary",
        model_kind="gpt",
        description="Generates the concise Markdown research summary used in document rows, detail panes, and later review surfaces.",
    ),
    AnalysisModelTask(
        key=MODEL_APA_CITATION,
        label="APA Citation Matching",
        model_kind="gpt",
        description="Generates an evidence-bounded APA 7 citation candidate and warnings; verified status still depends on Crossref, DOI evidence, or user acceptance.",
    ),
    AnalysisModelTask(
        key=MODEL_KEYWORDS_TOPICS,
        label="Keywords & Topics",
        model_kind="gpt",
        description="Suggests topic and keyword tags from the document context so imports and Concordance refreshes can enrich organization surfaces.",
    ),
    AnalysisModelTask(
        key=MODEL_PAGE_TEXT_NORMALIZATION,
        label="Text on Pages (Normalization)",
        model_kind="gpt",
        description="Conforms extracted page text into standard readable flow across columns and graphics while preserving wording, order, citations, equations, headings, labels, captions, and tables.",
    ),
    AnalysisModelTask(
        key=MODEL_TEXT_CHUNK_ENCODING,
        label="Text Chunk Encoding",
        model_kind="embedding",
        description="Encodes text chunks for vector search during indexing. This uses the OpenAI embeddings endpoint, not the Responses API.",
    ),
    AnalysisModelTask(
        key=MODEL_ACCESSORY_SUMMARIES,
        label="Accessory Summaries",
        model_kind="gpt",
        description="Reserved for future user-prompted custom summaries; those runs should use the original PDF plus the user's prompt.",
    ),
)

TASK_BY_KEY = {task.key: task for task in ANALYSIS_MODEL_TASKS}


def normalize_model_id(value: object, default: str) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate and MODEL_ID_RE.match(candidate):
            return candidate
    return default


def default_model_for_task(task_key: str) -> str:
    settings = get_settings()
    task = TASK_BY_KEY.get(task_key)
    if task and task.model_kind == "raw_text_extraction":
        return DEFAULT_RAW_TEXT_EXTRACTOR
    if task and task.model_kind == "embedding":
        return normalize_model_id(settings.openai_embedding_model, DEFAULT_EMBEDDING_MODEL)
    return normalize_model_id(settings.openai_model, DEFAULT_GPT_MODEL)


def default_analysis_models() -> dict[str, str]:
    return {task.key: default_model_for_task(task.key) for task in ANALYSIS_MODEL_TASKS}


def model_options(saved_models: dict[str, str] | None = None) -> dict[str, list[str]]:
    saved_values = set(saved_models.values()) if saved_models else set()
    gpt = [*GPT_MODEL_OPTIONS]
    embedding = [*EMBEDDING_MODEL_OPTIONS]
    raw_text_extraction = [*LOCAL_RAW_TEXT_EXTRACTOR_OPTIONS]
    for model in sorted(saved_values):
        if model.startswith("text-embedding-"):
            if model not in embedding:
                embedding.append(model)
        elif model in LOCAL_RAW_TEXT_EXTRACTOR_OPTIONS:
            continue
        elif model not in gpt:
            gpt.append(model)
    for model in (get_settings().openai_model, DEFAULT_GPT_MODEL):
        normalized = normalize_model_id(model, DEFAULT_GPT_MODEL)
        if normalized not in gpt:
            gpt.insert(0, normalized)
    embedding_default = normalize_model_id(get_settings().openai_embedding_model, DEFAULT_EMBEDDING_MODEL)
    if embedding_default not in embedding:
        embedding.insert(0, embedding_default)
    for model in gpt:
        if model not in raw_text_extraction:
            raw_text_extraction.append(model)
    for model in sorted(saved_values):
        if model.startswith("text-embedding-") or model in raw_text_extraction:
            continue
        raw_text_extraction.append(model)
    return {"gpt": gpt, "embedding": embedding, "raw_text_extraction": raw_text_extraction}


def option_groups_for_task(task: AnalysisModelTask, models: dict[str, str] | None = None) -> list[dict[str, list[str] | str]]:
    if task.model_kind != "raw_text_extraction":
        return []
    options = model_options(models)
    return [
        {"label": "Local", "options": [*LOCAL_RAW_TEXT_EXTRACTOR_OPTIONS]},
        {"label": "OpenAI", "options": options["gpt"]},
    ]


def task_payloads(models: dict[str, str] | None = None) -> list[dict[str, str | list[dict[str, list[str] | str]]]]:
    model_map = models or default_analysis_models()
    return [
        {
            "key": task.key,
            "label": task.label,
            "model_kind": task.model_kind,
            "default_model": default_model_for_task(task.key),
            "selected_model": model_map.get(task.key, default_model_for_task(task.key)),
            "description": task.description,
            "option_groups": option_groups_for_task(task, model_map),
        }
        for task in ANALYSIS_MODEL_TASKS
    ]
