from app.services.verifier import crossref_lookup, crossref_to_citation_metadata, extract_doi_from_text, normalized_title_similarity


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


def test_extract_doi_from_text_normalizes_visible_doi():
    assert extract_doi_from_text("Available at https://doi.org/10.1109/SPW.2013.35.") == "10.1109/spw.2013.35"


def test_crossref_lookup_scores_title_author_and_year(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["A Bayesian Network Model for Predicting Insider Threats"],
                            "author": [{"given": "Elise T.", "family": "Axelrad"}],
                            "published": {"date-parts": [[2013, 5]]},
                            "DOI": "10.1109/spw.2013.35",
                        },
                        {
                            "title": ["A Bayesian Network Model for Predicting External Threats"],
                            "author": [{"given": "Other", "family": "Author"}],
                            "published": {"date-parts": [[2012]]},
                            "DOI": "10.example/wrong",
                        },
                    ]
                }
            }

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.services.verifier.httpx.get", fake_get)

    result = crossref_lookup(
        None,
        "A Bayesian Network Model for Predicting Insider Threats",
        [{"given": "Elise", "family": "Axelrad"}],
        2013,
    )

    assert result is not None
    assert result["DOI"] == "10.1109/spw.2013.35"
    assert calls[0]["params"]["query.author"] == "Axelrad"
    assert calls[0]["params"]["filter"] == "from-pub-date:2013,until-pub-date:2013"
