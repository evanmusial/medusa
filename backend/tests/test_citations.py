from app.services.citations import (
    apa_author_list,
    format_apa_citation,
    format_apa_in_text_citation,
    format_bibtex,
    format_ris,
    to_csl_json,
    validate_apa_citation_pair,
)


def test_apa_author_list_uses_initials_and_ampersand():
    authors = [{"given": "Donna J.", "family": "Haraway"}, {"given": "Bruno", "family": "Latour"}]

    assert apa_author_list(authors) == "Haraway, D. J., & Latour, B."


def test_format_apa_prefers_doi_url():
    citation = format_apa_citation(
        {
            "title": "Situated knowledges",
            "authors": [{"given": "Donna", "family": "Haraway"}],
            "publication_year": 1988,
            "journal": "Feminist Studies",
            "doi": "10.2307/3178066",
        }
    )

    assert citation == "Haraway, D. (1988). Situated knowledges. *Feminist Studies*. https://doi.org/10.2307/3178066"


def test_format_apa_includes_journal_volume_issue_and_pages_as_markdown():
    citation = format_apa_citation(
        {
            "title": "A Bayesian network model for predicting insider threats",
            "authors": [
                {"given": "Elise T.", "family": "Axelrad"},
                {"given": "Paul J.", "family": "Sticha"},
                {"given": "Oliver", "family": "Brdiczka"},
            ],
            "publication_year": 2013,
            "journal": "2013 IEEE Security and Privacy Workshops",
            "volume": "1",
            "issue": "2",
            "page": "82-89",
            "doi": "10.1109/spw.2013.35",
        }
    )

    assert citation == (
        "Axelrad, E. T., Sticha, P. J., & Brdiczka, O. (2013). "
        "A Bayesian network model for predicting insider threats. "
        "*2013 IEEE Security and Privacy Workshops, 1*(2), 82-89. "
        "https://doi.org/10.1109/spw.2013.35"
    )


def test_format_apa_in_text_citation_uses_parenthetical_author_year():
    citation = format_apa_in_text_citation(
        {
            "title": "A Bayesian network model for predicting insider threats",
            "authors": [
                {"given": "Elise T.", "family": "Axelrad"},
                {"given": "Paul J.", "family": "Sticha"},
                {"given": "Oliver", "family": "Brdiczka"},
            ],
            "publication_year": 2013,
        }
    )

    assert citation == "(Axelrad et al., 2013)"


def test_format_apa_decodes_html_entities():
    citation = format_apa_citation(
        {
            "title": "A canonical analysis of &quot;intentional&quot; information security breaches by insiders",
            "authors": [{"given": "James", "family": "Shropshire"}],
            "publication_year": 2009,
            "journal": "Information Management &amp; Computer Security",
            "volume": "17",
            "issue": "4",
            "page": "296-310",
            "doi": "10.1108/09685220910993962",
        }
    )

    assert "&amp;" not in citation
    assert "&quot;" not in citation
    assert "Information Management & Computer Security" in citation
    assert '"intentional"' in citation


def test_validate_apa_citation_pair_strips_labels_and_accepts_pair():
    metadata = {
        "title": "Situated knowledges",
        "authors": [{"given": "Donna", "family": "Haraway"}],
        "publication_year": 1988,
        "journal": "Feminist Studies",
    }

    pair = validate_apa_citation_pair(
        metadata,
        reference_list="APA Reference List\nHaraway, D. (1988). Situated knowledges. *Feminist Studies*.",
        in_text="APA In-Text Citation\n(Haraway, 1988)",
    )

    assert pair.reference_list == "Haraway, D. (1988). Situated knowledges. *Feminist Studies*."
    assert pair.in_text == "(Haraway, 1988)"
    assert pair.validation_warnings == []


def test_validate_apa_citation_pair_falls_back_for_wrong_shape():
    metadata = {
        "title": "Situated knowledges",
        "authors": [{"given": "Donna", "family": "Haraway"}],
        "publication_year": 1988,
        "journal": "Feminist Studies",
        "doi": "10.2307/3178066",
    }

    pair = validate_apa_citation_pair(
        metadata,
        reference_list="(Wrong, 2020)",
        in_text="Wrong 2020",
    )

    assert pair.reference_list == format_apa_citation(metadata)
    assert pair.in_text == "(Haraway, 1988)"
    assert pair.validation_warnings == ["reference_list_fallback", "in_text_fallback"]


def test_validate_apa_citation_pair_accepts_supplied_year_when_metadata_lacks_year():
    metadata = {
        "title": "Notes on the analytical engine",
        "authors": [{"given": "Ada", "family": "Lovelace"}],
    }

    pair = validate_apa_citation_pair(
        metadata,
        reference_list="Lovelace, A. (1843). Notes on the analytical engine.",
        in_text="(Lovelace, 1843)",
    )

    assert pair.reference_list == "Lovelace, A. (1843). Notes on the analytical engine."
    assert pair.in_text == "(Lovelace, 1843)"
    assert pair.validation_warnings == []


def test_exports_include_expected_identifiers():
    metadata = {
        "title": "The Cyborg Manifesto",
        "authors": [{"given": "Donna", "family": "Haraway"}],
        "publication_year": 1985,
        "journal": "Socialist Review",
        "doi": "10.example/cyborg",
    }

    assert "@article{Haraway1985thecyborgmanifesto," in format_bibtex(metadata)
    assert "TY  - JOUR" in format_ris(metadata)
    assert to_csl_json(metadata)["DOI"] == "10.example/cyborg"
