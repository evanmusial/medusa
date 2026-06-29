from __future__ import annotations

import html
import re
from dataclasses import dataclass
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


APA_SENTENCE_CASE_PRESERVED_WORDS = {
    "api": "API",
    "bayesian": "Bayesian",
    "covid": "COVID",
    "crossref": "Crossref",
    "doi": "DOI",
    "gcs": "GCS",
    "html": "HTML",
    "ieee": "IEEE",
    "iot": "IoT",
    "json": "JSON",
    "alexa": "Alexa",
    "markov": "Markov",
    "medusa": "Medusa",
    "openai": "OpenAI",
    "pdf": "PDF",
    "google": "Google",
    "snowden": "Snowden",
    "postgresql": "PostgreSQL",
    "sql": "SQL",
    "url": "URL",
    "xml": "XML",
}

APA_SENTENCE_CASE_PRESERVED_PHRASES = {
    "edward snowden": "Edward Snowden",
    "google home": "Google Home",
}


def _sentence_case_core_word(word: str, *, capitalize: bool) -> str:
    if not word:
        return word
    preserved = APA_SENTENCE_CASE_PRESERVED_WORDS.get(word.casefold())
    if preserved:
        cased = preserved
    elif re.search(r"://|@", word):
        cased = word
    elif re.fullmatch(r"[A-Z0-9][A-Z0-9&.+/-]{1,}", word) and (len(re.sub(r"[^A-Z0-9]", "", word)) <= 6 or any(ch.isdigit() for ch in word)):
        cased = word
    elif re.search(r"[a-z][A-Z]", word):
        cased = word
    else:
        cased = word.lower()
    if not capitalize:
        return cased
    first_letter = re.search(r"[A-Za-z]", cased)
    if not first_letter:
        return cased
    index = first_letter.start()
    return cased[:index] + cased[index].upper() + cased[index + 1 :]


def _sentence_case_token(token: str, *, capitalize: bool) -> str:
    leading = re.match(r"^[^A-Za-z0-9]+", token)
    trailing = re.search(r"[^A-Za-z0-9]+$", token)
    leading_text = leading.group(0) if leading else ""
    trailing_text = trailing.group(0) if trailing and trailing.start() >= len(leading_text) else ""
    core_end = len(token) - len(trailing_text) if trailing_text else len(token)
    core = token[len(leading_text) : core_end]
    if not core:
        return token
    if "-" in core and not re.search(r"://", core):
        parts = core.split("-")
        cased_parts = [
            _sentence_case_core_word(part, capitalize=capitalize and index == 0)
            for index, part in enumerate(parts)
        ]
        cased_core = "-".join(cased_parts)
    else:
        cased_core = _sentence_case_core_word(core, capitalize=capitalize)
    return f"{leading_text}{cased_core}{trailing_text}"


def sentence_case_title(title: str) -> str:
    title = re.sub(r"\s+", " ", decode_html_entities(title)).strip()
    if not title:
        return title
    parts = re.split(r"(\s+)", title)
    cased_parts: list[str] = []
    capitalize_next = True
    for part in parts:
        if not part or part.isspace():
            cased_parts.append(part)
            continue
        cased_parts.append(_sentence_case_token(part, capitalize=capitalize_next))
        if re.search(r"[:!?]\s*$", part):
            capitalize_next = True
        elif re.search(r"[A-Za-z0-9]", part):
            capitalize_next = False
    cased = "".join(cased_parts)
    for phrase, replacement in APA_SENTENCE_CASE_PRESERVED_PHRASES.items():
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"\b"
        cased = re.sub(pattern, replacement, cased, flags=re.IGNORECASE)
    return cased


_APA_REFERENCE_YEAR_PREFIX_RE = re.compile(r"\(\s*(?:n\.d\.|(?:18|19|20)\d{2}[a-z]?)\s*\)\.\s+", re.IGNORECASE)
_APA_REFERENCE_TITLE_BOUNDARY_HINT_RE = re.compile(
    r"^(?:\*|In\s+|Retrieved\s+|https?://|doi:|Journal\b|Proceedings\b|Press\b|Publisher\b|University\b|Institute\b|"
    r"Association\b|Conference\b|Review\b|Magazine\b|Report\b|Department\b|Springer\b|ACM\b|IEEE\b|"
    r"[A-Z][A-Za-z& ]{0,40}\b(?:Journal|Proceedings|Press|Publisher|University|Institute|Association|Conference|"
    r"Review|Magazine|Report|Department|Springer|ACM|IEEE)\b)",
    re.IGNORECASE,
)


def _sentence_case_markdown_title(title: str) -> str:
    stripped = title.strip()
    if len(stripped) >= 2 and stripped.startswith("*") and stripped.endswith("*"):
        return title.replace(stripped, f"*{sentence_case_title(stripped[1:-1])}*", 1)
    return sentence_case_title(title)


def _split_reference_title(rest: str) -> tuple[str, str, str] | None:
    if not rest.strip():
        return None
    if rest.startswith("*"):
        closing = rest.find("*", 1)
        if closing > 1 and closing + 1 < len(rest) and rest[closing + 1] in ".!?":
            return rest[: closing + 1], rest[closing + 1], rest[closing + 2 :]
    delimiter_matches = list(re.finditer(r"([.!?])(\s+|$)", rest))
    if not delimiter_matches:
        return rest, "", ""
    for match in delimiter_matches:
        tail = rest[match.end() :]
        if not tail or _APA_REFERENCE_TITLE_BOUNDARY_HINT_RE.search(tail):
            return rest[: match.start()], match.group(1), rest[match.end() - len(match.group(2)) :]
    match = delimiter_matches[-1]
    return rest[: match.start()], match.group(1), rest[match.end() - len(match.group(2)) :]


def sentence_case_apa_reference_title(reference: str) -> str:
    reference = decode_html_entities(reference).strip()
    match = _APA_REFERENCE_YEAR_PREFIX_RE.search(reference)
    if not match:
        return reference
    prefix = reference[: match.end()]
    rest = reference[match.end() :]
    split = _split_reference_title(rest)
    if not split:
        return reference
    title, ending, tail = split
    cased_title = _sentence_case_markdown_title(title)
    return f"{prefix}{cased_title}{ending}{tail}".strip()


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


def normalize_apa_page_range(value: Any) -> str:
    text = _strip_terminal_period(str(value or ""))
    if not text:
        return ""
    text = re.sub(r"\s*[-–—]\s*", "–", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _metadata_page_range(metadata: dict[str, Any]) -> str:
    return normalize_apa_page_range(metadata.get("page") or metadata.get("pages") or "")


def _normalize_apa_page_ranges_in_reference(reference: str) -> str:
    def replace_after_comma(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}–{match.group(3)}"

    def replace_after_page_label(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}–{match.group(3)}"

    normalized = re.sub(r"(,\s*)(\d+)\s*[-–—]\s*(\d+)(?=[,.)])", replace_after_comma, reference)
    normalized = re.sub(r"(?i)\b(pp?\.?\s*)(\d+)\s*[-–—]\s*(\d+)\b", replace_after_page_label, normalized)
    return normalized


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
    pages = normalize_apa_page_range(metadata.get("page") or metadata.get("pages") or metadata.get("article_number") or "")
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


def format_apa_in_text_citation(metadata: dict[str, Any]) -> str:
    authors = [
        normalize_author_name(author)["family"]
        for author in metadata.get("authors") or []
        if normalize_author_name(author)["family"]
    ]
    year = metadata.get("publication_year") or metadata.get("year") or "n.d."
    if not authors:
        title = _strip_terminal_period(sentence_case_title(str(metadata.get("title") or "Untitled work")))
        title_words = title.split()
        short_title = " ".join(title_words[:4]) if len(title_words) > 4 else title
        return f'("{short_title}", {year})'
    if len(authors) == 1:
        author_text = authors[0]
    elif len(authors) == 2:
        author_text = f"{authors[0]} & {authors[1]}"
    else:
        author_text = f"{authors[0]} et al."
    return f"({author_text}, {year})"


@dataclass(frozen=True)
class ApaCitationPair:
    reference_list: str
    in_text: str
    validation_warnings: list[str]


_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:apa\s*)?(?:reference\s*list|reference|citation|apa\s*in[-\s]?text\s*citation|in[-\s]?text\s*citation)\s*:\s*",
    re.IGNORECASE,
)
_LABEL_HEADING_RE = re.compile(
    r"^\s*(?:apa\s*)?(?:reference\s*list|reference|citation|apa\s*in[-\s]?text\s*citation|in[-\s]?text\s*citation)\s*$",
    re.IGNORECASE,
)


def _strip_citation_wrappers(value: Any) -> str:
    text = decode_html_entities(value)
    text = re.sub(r"^```(?:markdown|text)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if _LABEL_HEADING_RE.fullmatch(line):
            continue
        lines.append(_LABEL_PREFIX_RE.sub("", line).strip())
    lines = [line for line in lines if line]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _metadata_year(metadata: dict[str, Any]) -> str:
    return str(metadata.get("publication_year") or metadata.get("year") or "n.d.").strip() or "n.d."


def _year_pattern(metadata: dict[str, Any]) -> str:
    year = _metadata_year(metadata)
    return r"(?:\d{4}|n\.d\.)" if year == "n.d." else re.escape(year)


def _reference_year(reference_list: str) -> str:
    match = re.search(r"\((\d{4}|n\.d\.)\)", reference_list or "")
    return match.group(1) if match else ""


def _in_text_year(in_text: str) -> str:
    match = re.search(r",\s*(\d{4}|n\.d\.)\)", in_text or "")
    return match.group(1) if match else ""


def _title_anchor_words(metadata: dict[str, Any]) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+", str(metadata.get("title") or "").lower())
    stop_words = {"a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with"}
    return [word for word in words if len(word) > 2 and word not in stop_words][:4]


def _first_author_family(metadata: dict[str, Any]) -> str:
    authors = metadata.get("authors") or []
    if not authors:
        return ""
    return normalize_author_name(authors[0])["family"].strip()


def _reference_list_is_plausible(reference_list: str, metadata: dict[str, Any]) -> bool:
    if not reference_list or len(reference_list) < 20:
        return False
    if reference_list.startswith("(") and reference_list.endswith(")") and len(reference_list) < 80:
        return False
    if not re.search(rf"\({_year_pattern(metadata)}\)", reference_list):
        return False
    lowered = reference_list.lower()
    author_family = _first_author_family(metadata).lower()
    title_words = _title_anchor_words(metadata)
    if author_family and author_family not in lowered:
        return False
    if title_words and not any(word in lowered for word in title_words):
        return False
    pages = _metadata_page_range(metadata)
    if pages and pages not in _normalize_apa_page_ranges_in_reference(reference_list):
        return False
    return True


def _normalize_parenthetical_in_text(value: Any) -> str:
    text = _strip_citation_wrappers(value)
    match = re.search(r"\([^()]+,\s*(?:\d{4}|n\.d\.)\)", text)
    if match:
        return match.group(0).strip()
    if text and not text.startswith("(") and not text.endswith(")"):
        text = f"({text})"
    return text


def _in_text_is_plausible(in_text: str, metadata: dict[str, Any]) -> bool:
    if not re.fullmatch(r"\([^()]+,\s*(?:\d{4}|n\.d\.)\)", in_text or ""):
        return False
    year = _metadata_year(metadata)
    if year != "n.d." and year not in in_text:
        return False
    author_family = _first_author_family(metadata)
    if author_family and author_family not in in_text:
        return False
    if not author_family:
        title_words = _title_anchor_words(metadata)
        if title_words and not any(word in in_text.lower() for word in title_words):
            return False
    return True


def _fallback_in_text_for_reference(metadata: dict[str, Any], reference_list: str) -> str:
    reference_year = _reference_year(reference_list)
    if reference_year and _metadata_year(metadata) == "n.d.":
        metadata = {**metadata, "publication_year": reference_year}
    return format_apa_in_text_citation(metadata)


def _pair_years_conflict(reference_list: str, in_text: str) -> bool:
    reference_year = _reference_year(reference_list)
    parenthetical_year = _in_text_year(in_text)
    return bool(reference_year and parenthetical_year and reference_year != parenthetical_year)


def validate_apa_citation_pair(
    metadata: dict[str, Any],
    *,
    reference_list: str | None = None,
    in_text: str | None = None,
) -> ApaCitationPair:
    """Normalize and validate the paired APA reference-list and in-text values."""
    fallback_reference = format_apa_citation(metadata)
    normalized_reference = _strip_citation_wrappers(reference_list)
    normalized_in_text = _normalize_parenthetical_in_text(in_text)
    supplied_reference = bool(normalized_reference)
    supplied_in_text = bool(normalized_in_text)
    warnings: list[str] = []

    if not _reference_list_is_plausible(normalized_reference, metadata):
        normalized_reference = fallback_reference
        if supplied_reference:
            warnings.append("reference_list_fallback")
    else:
        normalized_reference = _normalize_apa_page_ranges_in_reference(sentence_case_apa_reference_title(normalized_reference))
    fallback_in_text = _fallback_in_text_for_reference(metadata, normalized_reference)
    if not _in_text_is_plausible(normalized_in_text, metadata) or _pair_years_conflict(normalized_reference, normalized_in_text):
        normalized_in_text = fallback_in_text
        if supplied_in_text:
            warnings.append("in_text_fallback")

    return ApaCitationPair(
        reference_list=normalized_reference,
        in_text=normalized_in_text,
        validation_warnings=warnings,
    )


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
