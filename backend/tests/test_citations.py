from app.services.citations import (
    apa_author_list,
    format_apa_citation,
    format_bibtex,
    format_ris,
    to_csl_json,
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
