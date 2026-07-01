import pytest

from app.config import get_settings
from app.services.verifier import (
    crossref_lookup,
    crossref_to_citation_metadata,
    discover_doi_from_title,
    extract_doi_from_text,
    local_doi_resolution_evidence,
    normalized_title_similarity,
    stable_source_link_evidence,
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
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF", "false")
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX", "false")
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

    class EmptyJsonResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            if "doiRA" in getattr(self, "url", ""):
                return [{"DOI": "10.5555/1218112.1218218", "RA": "Crossref"}]
            return {"data": [], "resultList": {"result": []}}

    def fake_get(url, params=None, timeout=None, headers=None, follow_redirects=None):
        if "semanticscholar.org" in url:
            assert params["query"] == "Modeling the Emergence of Insider Threat Vulnerabilities"
            return FakeResponse()
        response = EmptyJsonResponse()
        response.url = url
        return response

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
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF", "false")
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX", "false")
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

    class EmptyJsonResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [], "resultList": {"result": []}}

    def fake_get(url, params=None, timeout=None, headers=None, follow_redirects=None):
        if "duckduckgo.com" not in url:
            return EmptyJsonResponse()
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
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF", "false")
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX", "false")
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

    class EmptyJsonResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [], "resultList": {"result": []}}

    def fake_get(url, *args, **kwargs):
        if "duckduckgo.com" in url:
            return FakeResponse()
        return EmptyJsonResponse()

    monkeypatch.setattr("app.services.verifier.httpx.get", fake_get)

    assert discover_doi_from_title("Modeling the Emergence of Insider Threat Vulnerabilities") is None


def test_discover_doi_from_title_searches_open_metadata_before_web(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF", "false")
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR", "false")
    monkeypatch.setenv("MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX", "true")
    monkeypatch.setenv("MEDUSA_CITATION_TITLE_WEB_SEARCH", "false")

    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, params=None, timeout=None, headers=None, follow_redirects=None):
        calls.append(url)
        if "api.openalex.org" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "display_name": "Modeling the Emergence of Insider Threat Vulnerabilities",
                            "publication_year": 2006,
                            "doi": "https://doi.org/10.5555/1218112.1218218",
                            "id": "https://openalex.org/W123",
                            "authorships": [{"author": {"display_name": "Ignacio J. Martinez-Moyano"}}],
                            "primary_location": {"landing_page_url": "https://publisher.test/insider-threat"},
                        }
                    ]
                }
            )
        if "api.datacite.org" in url:
            return FakeResponse({"data": []})
        if "europepmc" in url:
            return FakeResponse({"resultList": {"result": []}})
        if "opencitations" in url:
            return FakeResponse([])
        if "doi.org/doiRA" in url:
            return FakeResponse([{"DOI": "10.5555/1218112.1218218", "RA": "Crossref"}])
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("app.services.verifier.httpx.get", fake_get)

    result = discover_doi_from_title(
        "Modeling the Emergence of Insider Threat Vulnerabilities",
        [{"given": "Ignacio J.", "family": "Martinez-Moyano"}],
        2006,
    )

    assert result is not None
    assert result["doi"] == "10.5555/1218112.1218218"
    assert result["source"] == "openalex_title"
    assert result["registration_agency"]["registration_agency"] == "Crossref"
    assert any("api.openalex.org" in call for call in calls)


def test_local_doi_resolution_rejects_unrelated_reference_doi():
    result = local_doi_resolution_evidence(
        doi=None,
        title="Modeling the Emergence of Insider Threat Vulnerabilities",
        authors=[{"given": "Ignacio J.", "family": "Martinez-Moyano"}],
        year=2006,
        text="References\nDifferent Paper. https://doi.org/10.9999/wrong.",
        bibliography="Different Paper. https://doi.org/10.9999/wrong.",
    )

    assert result["status"] == "not_found"
    assert result["candidates"] == []


def test_stable_source_link_prefers_direct_pdf_with_title_context():
    result = stable_source_link_evidence(
        title="Modeling the Emergence of Insider Threat Vulnerabilities",
        authors=[{"given": "Ignacio J.", "family": "Martinez-Moyano"}],
        year=2006,
        source_url=None,
        text=(
            "Modeling the Emergence of Insider Threat Vulnerabilities by Martinez-Moyano "
            "is available at https://publisher.test/static/insider-threat.pdf"
        ),
        bibliography=None,
    )

    assert result["status"] == "found"
    assert result["selected"]["source_url"] == "https://publisher.test/static/insider-threat.pdf"
    assert result["selected"]["confidence"] >= 0.76
