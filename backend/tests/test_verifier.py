from app.services.verifier import crossref_to_citation_metadata, normalized_title_similarity


def test_title_similarity_rejects_loose_crossref_match():
    assert normalized_title_similarity("medusa layout smoke", "MEDUSA") < 0.82


def test_title_similarity_accepts_minor_case_and_spacing_differences():
    assert normalized_title_similarity("Situated Knowledges", "situated   knowledges") > 0.82


def test_crossref_to_citation_metadata_extracts_authors_year_and_doi():
    metadata = crossref_to_citation_metadata(
        {
            "DOI": "10.1109/spw.2013.35",
            "URL": "https://doi.org/10.1109/spw.2013.35",
            "title": ["A Bayesian Network Model for Predicting Insider Threats"],
            "author": [
                {"given": "Elise T.", "family": "Axelrad"},
                {"given": "Paul J.", "family": "Sticha"},
                {"given": "Oliver", "family": "Brdiczka"},
                {"family": "Jianqiang Shen"},
            ],
            "published": {"date-parts": [[2013, 5]]},
            "container-title": ["2013 IEEE Security and Privacy Workshops"],
            "publisher": "IEEE",
        }
    )

    assert metadata["publication_year"] == 2013
    assert metadata["doi"] == "10.1109/spw.2013.35"
    assert metadata["journal"] == "2013 IEEE Security and Privacy Workshops"
    assert metadata["authors"][-1] == {"given": "Jianqiang", "family": "Shen", "affiliation": None}
