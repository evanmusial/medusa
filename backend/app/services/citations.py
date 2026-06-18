from __future__ import annotations

import html
import re
from typing import Any


def decode_html_entities(value: Any) -> str:
    return html.unescape(str(value or "")).strip()


def normalize_author_name(author: dict[str, Any] | str) -> dict[str, str]:
    if isinstance(author, dict):
        given = decode_html_entities(author.get("given") or author.get("first") or "")
        family = decode_html_entities(author.get("family") or author.get("last") or author.get("name") or "")
        if not family and given:
            parts = given.split()
            given = " ".join(parts[:-1])
            family = parts[-1]
        return {"given": given, "family": family}
    parts = decode_html_entities(author).split()
    if not parts:
        return {"given": "", "family": ""}
    if len(parts) == 1:
        return {"given": "", "family": parts[0]}
    return {"given": " ".join(parts[:-1]), "family": parts[-1]}


def apa_author(author: dict[str, Any] | str) -> str:
    normalized = normalize_author_name(author)
    family = normalized["family"]
    initials = " ".join(f"{part[0]}." for part in normalized["given"].replace("-", " ").split() if part)
    return f"{family}, {initials}".strip().rstrip(",")


def apa_author_list(authors: list[dict[str, Any]] | list[str]) -> str:
    cleaned = [apa_author(author) for author in authors if apa_author(author)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) <= 20:
        return ", ".join(cleaned[:-1]) + f", & {cleaned[-1]}"
    return ", ".join(cleaned[:19]) + f", ... {cleaned[-1]}"


def sentence_case_title(title: str) -> str:
    title = re.sub(r"\s+", " ", decode_html_entities(title)).strip()
    if not title:
        return title
    return title[0].upper() + title[1:]


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def merge_citation_metadata(*metadata_items: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for metadata in metadata_items:
        for key, value in (metadata or {}).items():
            if _has_value(value):
                merged[key] = value
    return merged


def _strip_terminal_period(value: str) -> str:
    return decode_html_entities(value).rstrip(".")


def _with_period(value: str) -> str:
    value = decode_html_entities(value)
    if not value:
        return value
    return value if value.endswith((".", "?", "!")) else f"{value}."


def _doi_url(doi: Any) -> str:
    doi_text = decode_html_entities(doi)
    if not doi_text:
        return ""
    if doi_text.startswith("http"):
        return doi_text
    return "https://doi.org/" + doi_text.removeprefix("doi:").strip()


def _journal_publication_part(metadata: dict[str, Any]) -> str:
    journal = _strip_terminal_period(str(metadata.get("journal") or ""))
    if not journal:
        return ""
    volume = _strip_terminal_period(str(metadata.get("volume") or ""))
    issue = _strip_terminal_period(str(metadata.get("issue") or ""))
    pages = _strip_terminal_period(str(metadata.get("page") or metadata.get("pages") or metadata.get("article_number") or ""))
    journal_volume = f"{journal}, {volume}" if volume else journal
    publication = f"*{journal_volume}*"
    if issue:
        publication += f"({issue})"
    if pages:
        publication += f", {pages}"
    return _with_period(publication)


def format_apa_citation(metadata: dict[str, Any]) -> str:
    authors = apa_author_list(metadata.get("authors") or [])
    year = metadata.get("publication_year") or metadata.get("year") or "n.d."
    title = sentence_case_title(str(metadata.get("title") or "Untitled work"))
    journal = metadata.get("journal")
    publisher = _strip_terminal_period(str(metadata.get("publisher") or ""))
    doi = metadata.get("doi")
    source_url = decode_html_entities(metadata.get("source_url"))

    head = f"{authors} " if authors else ""
    if journal:
        citation = f"{head}({year}). {_with_period(title)} {_journal_publication_part(metadata)}"
    elif publisher:
        citation = f"{head}({year}). *{_with_period(title).rstrip('.')}*. {publisher}."
    else:
        citation = f"{head}({year}). {_with_period(title)}"
    if doi:
        citation += f" {_doi_url(doi)}"
    elif source_url:
        citation += f" {source_url}"
    return re.sub(r"\s+", " ", citation).strip()


def citation_key(metadata: dict[str, Any]) -> str:
    authors = metadata.get("authors") or []
    first = normalize_author_name(authors[0])["family"] if authors else "unknown"
    year = metadata.get("publication_year") or metadata.get("year") or "nd"
    title_words = re.findall(r"[A-Za-z0-9]+", str(metadata.get("title") or "work").lower())
    suffix = "".join(title_words[:3]) or "work"
    return re.sub(r"[^A-Za-z0-9_:-]", "", f"{first}{year}{suffix}")


def format_bibtex(metadata: dict[str, Any]) -> str:
    key = citation_key(metadata)
    authors = metadata.get("authors") or []
    author_text = " and ".join(
        " ".join(filter(None, [normalize_author_name(author)["given"], normalize_author_name(author)["family"]]))
        for author in authors
    )
    fields = {
        "title": decode_html_entities(metadata.get("title")),
        "author": author_text or None,
        "year": decode_html_entities(metadata.get("publication_year") or metadata.get("year")),
        "journal": decode_html_entities(metadata.get("journal")),
        "publisher": decode_html_entities(metadata.get("publisher")),
        "doi": decode_html_entities(metadata.get("doi")),
        "url": decode_html_entities(metadata.get("source_url")),
    }
    lines = [f"@article{{{key},"]
    for field, value in fields.items():
        if value:
            lines.append(f"  {field} = {{{value}}},")
    lines.append("}")
    return "\n".join(lines)


def format_ris(metadata: dict[str, Any]) -> str:
    lines = ["TY  - JOUR"]
    for author in metadata.get("authors") or []:
        normalized = normalize_author_name(author)
        if normalized["family"]:
            lines.append(f"AU  - {normalized['family']}, {normalized['given']}".rstrip())
    field_map = {
        "TI": decode_html_entities(metadata.get("title")),
        "PY": decode_html_entities(metadata.get("publication_year") or metadata.get("year")),
        "JO": decode_html_entities(metadata.get("journal")),
        "PB": decode_html_entities(metadata.get("publisher")),
        "DO": decode_html_entities(metadata.get("doi")),
        "UR": decode_html_entities(metadata.get("source_url")),
    }
    for tag, value in field_map.items():
        if value:
            lines.append(f"{tag}  - {value}")
    lines.append("ER  -")
    return "\n".join(lines)


def to_csl_json(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": citation_key(metadata),
        "type": "article-journal" if metadata.get("journal") else "book",
        "title": decode_html_entities(metadata.get("title")),
        "author": [
            {
                "given": normalize_author_name(author)["given"],
                "family": normalize_author_name(author)["family"],
            }
            for author in metadata.get("authors") or []
        ],
        "issued": {"date-parts": [[metadata.get("publication_year") or metadata.get("year")]]},
        "container-title": decode_html_entities(metadata.get("journal")),
        "publisher": decode_html_entities(metadata.get("publisher")),
        "DOI": decode_html_entities(metadata.get("doi")),
        "URL": decode_html_entities(metadata.get("source_url")),
    }
