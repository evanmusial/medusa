import pytest

from app.config import get_settings
from app.services.verifier import (
    crossref_lookup,
    crossref_to_citation_metadata,
    discover_doi_from_title,
    extract_doi_from_text,
    normalized_title_similarity,
)


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "originals"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


def test_discover_doi_from_title_uses_semantic_scholar_title_match(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR", "true")

    class FakeResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "title": "Modeling the Emergence of Insider Threat Vulnerabilities",
                        "year": 2006,
                        "authors": [{"name": "Ignacio J. Martinez-Moyano"}],
                        "externalIds": {"DOI": "10.5555/1218112.1218218"},
                        "url": "https://www.semanticscholar.org/paper/example",
                    }
                ]
            }

    def fake_get(url, params=None, timeout=None, headers=None, follow_redirects=None):
        assert "semanticscholar.org" in url
        assert params["query"] == "Modeling the Emergence of Insider Threat Vulnerabilities"
        return FakeResponse()

    monkeypatch.setattr("app.services.verifier.httpx.get", fake_get)

    result = discover_doi_from_title(
        "Modeling the Emergence of Insider Threat Vulnerabilities",
        [{"given": "Ignacio J.", "family": "Martinez-Moyano"}],
        2006,
    )

    assert result is not None
    assert result["doi"] == "10.5555/1218112.1218218"
    assert result["source"] == "semantic_scholar_title"


def test_discover_doi_from_title_uses_quoted_title_web_search(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR", "false")
    monkeypatch.setenv("MEDUSA_CITATION_TITLE_WEB_SEARCH", "true")

    calls = []

    class FakeResponse:
        text = """
        <html><body>
        <div class="result">
          <a>Modeling the Emergence of Insider Threat Vulnerabilities</a>
          <span>The paper is identified by DOI 10.5555/1218112.1218218.</span>
        </div>
        </body></html>
        """

        def raise_for_status(self):
            return None

    def fake_get(url, params=None, timeout=None, headers=None, follow_redirects=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.services.verifier.httpx.get", fake_get)

    result = discover_doi_from_title("Modeling the Emergence of Insider Threat Vulnerabilities")

    assert result is not None
    assert result["doi"] == "10.5555/1218112.1218218"
    assert result["source"] == "title_web_search"
    assert calls[0]["params"]["q"] == '"Modeling the Emergence of Insider Threat Vulnerabilities" DOI'


def test_discover_doi_from_title_rejects_unrelated_web_doi(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR", "false")
    monkeypatch.setenv("MEDUSA_CITATION_TITLE_WEB_SEARCH", "true")

    class FakeResponse:
        text = """
        <html><body>
        <div>Completely Different Paper DOI 10.5555/1218112.1218218.</div>
        </body></html>
        """

        def raise_for_status(self):
            return None

    monkeypatch.setattr("app.services.verifier.httpx.get", lambda *args, **kwargs: FakeResponse())

    assert discover_doi_from_title("Modeling the Emergence of Insider Threat Vulnerabilities") is None
