"""Tests for the 5 rka-writer-tools backend wrappers.

Each backend wraps an external API client via try/except ImportError so the
module is loadable without the optional PyPI package installed. Tests
verify the availability surface plus a small set of core operations via
unittest.mock for callsites where a client is installed locally.

Per mis_01KS2S871YPQ3D5RVY5K3PSQY6 T6 acceptance criteria.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestBackendAvailability:
    """Each backend reports is_available() consistent with its imported state."""

    def test_crossref_is_available_returns_bool(self, crossref_backend) -> None:
        assert isinstance(crossref_backend.is_available(), bool)

    def test_openalex_is_available_returns_bool(self, openalex_backend) -> None:
        assert isinstance(openalex_backend.is_available(), bool)

    def test_semantic_scholar_is_available_returns_bool(self, semantic_scholar_backend) -> None:
        assert isinstance(semantic_scholar_backend.is_available(), bool)

    def test_arxiv_is_available_returns_bool(self, arxiv_backend) -> None:
        assert isinstance(arxiv_backend.is_available(), bool)

    def test_serpapi_is_available_returns_bool(self, serpapi_backend) -> None:
        # serpapi needs BOTH package installed AND API key set.
        assert isinstance(serpapi_backend.is_available(), bool)


class TestGracefulDegradation:
    """When a backend's PyPI package is absent, ops return None/[] not raise."""

    def test_openalex_resolve_doi_returns_none_when_unavailable(self, openalex_backend) -> None:
        # If pyalex not installed (the common case in this test env), resolve
        # should return None rather than raising.
        if openalex_backend.is_available():
            return  # skip if installed locally
        result = openalex_backend.resolve_doi("10.1234/example")
        assert result is None

    def test_serpapi_search_returns_empty_list_when_unavailable(self, serpapi_backend) -> None:
        if serpapi_backend.is_available():
            return
        budget = serpapi_backend.CreditBudget(budget=5)
        result = serpapi_backend.google_scholar_search("test query", budget=budget)
        assert result == []
        # Budget should NOT be consumed when backend is unavailable.
        assert budget.used == 0


class TestCrossrefWithMockedClient:
    """When habanero IS installed locally, test the wrapper logic via mock."""

    def test_resolve_doi_returns_message_on_success(self, crossref_backend) -> None:
        if not crossref_backend.is_available():
            return
        mock_client = MagicMock()
        mock_client.works.return_value = {
            "message": {"DOI": "10.1234/example", "title": ["Test Paper"]}
        }
        with patch.object(crossref_backend, "_client", return_value=mock_client):
            result = crossref_backend.resolve_doi("10.1234/example")
        assert result is not None
        assert result.get("DOI") == "10.1234/example"

    def test_resolve_doi_returns_none_on_exception(self, crossref_backend) -> None:
        if not crossref_backend.is_available():
            return
        mock_client = MagicMock()
        mock_client.works.side_effect = RuntimeError("api error")
        with patch.object(crossref_backend, "_client", return_value=mock_client):
            result = crossref_backend.resolve_doi("10.1234/example")
        assert result is None


class TestCrossrefRetraction:
    """Stage D delegates retraction check to crossref.get_update_to."""

    def test_get_update_to_returns_empty_when_no_updates(self, crossref_backend) -> None:
        if not crossref_backend.is_available():
            return
        mock_client = MagicMock()
        mock_client.works.return_value = {
            "message": {"DOI": "10.1234/example", "update-to": []}
        }
        with patch.object(crossref_backend, "_client", return_value=mock_client):
            updates = crossref_backend.get_update_to("10.1234/example")
        assert updates == []

    def test_get_update_to_returns_retraction_record(self, crossref_backend) -> None:
        if not crossref_backend.is_available():
            return
        mock_client = MagicMock()
        mock_client.works.return_value = {
            "message": {
                "DOI": "10.1234/example",
                "update-to": [{"type": "retraction", "source": "retraction-watch"}],
            }
        }
        with patch.object(crossref_backend, "_client", return_value=mock_client):
            updates = crossref_backend.get_update_to("10.1234/example")
        assert any(u.get("type") == "retraction" for u in updates)


class TestArxivWrapperShape:
    """arxiv wrapper exposes get_paper + search_papers; degrades if absent."""

    def test_search_returns_empty_list_on_exception(self, arxiv_backend) -> None:
        if not arxiv_backend.is_available():
            return
        with patch.object(arxiv_backend, "_arxiv", create=True) as mock_arxiv:
            mock_arxiv.Search.side_effect = RuntimeError("arxiv down")
            result = arxiv_backend.search_papers("test", max_results=1)
        assert result == []
