"""Tests for the 3 manuscript MCP tools (Phase 3 T3).

The 3 tools (rka_register_manuscript, rka_get_manuscript,
rka_validate_reference) are thin HTTP proxies that call the manuscripts
REST endpoints. Tests mock httpx.AsyncClient at the MCP layer so no
running server is required.

Per mis_01KS2WW6MRN6AXP11EMCSCDFAR T4 acceptance criteria.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _noop_fire_session_start(project_id):
    """Test helper: neutralize the post-tool session_start hook fire so it doesn't pollute fake-client post_calls counters."""
    return None





@pytest.fixture
def mcp_server():
    """Import the rka.mcp.server module (the FastMCP module instance)."""
    from rka.mcp import server
    return server


def _make_response(status_code: int, payload: dict | list) -> MagicMock:
    """Build a fake httpx.Response with the given payload."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json = MagicMock(return_value=payload)
    resp.text = json.dumps(payload)
    return resp


class _AsyncClientContext:
    """Context-manager fake for httpx.AsyncClient with stubbed get/post."""

    def __init__(self, *, get_response=None, post_response=None):
        self._get_response = get_response
        self._post_response = post_response
        self.get_calls: list[tuple[str, dict | None]] = []
        self.post_calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs.get("params")))
        return self._get_response

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs.get("json")))
        return self._post_response


class TestRkaRegisterManuscript:
    """rka_register_manuscript POSTs /api/manuscripts and returns JSON."""

    async def test_register_calls_post_with_payload(self, mcp_server) -> None:
        fake_client = _AsyncClientContext(
            post_response=_make_response(201, {
                "id": "jrn_01_test", "title": "Sample", "venue": "CHI", "phase": "draft",
            }),
        )
        with patch.object(mcp_server, "_client", return_value=fake_client), patch.object(mcp_server, "_maybe_fire_session_start", new=_noop_fire_session_start):
            result_text = await mcp_server.rka_register_manuscript(
                venue="CHI", title="Sample",
                project_id="proj_default",
        )
        result = json.loads(result_text)
        assert result["id"] == "jrn_01_test"
        assert len(fake_client.post_calls) == 1
        url, payload = fake_client.post_calls[0]
        assert url == "/api/manuscripts"
        assert payload == {"venue": "CHI", "title": "Sample"}

    async def test_register_with_abstract_and_sections(self, mcp_server) -> None:
        fake_client = _AsyncClientContext(
            post_response=_make_response(201, {"id": "jrn_X"}),
        )
        with patch.object(mcp_server, "_client", return_value=fake_client), patch.object(mcp_server, "_maybe_fire_session_start", new=_noop_fire_session_start):
            await mcp_server.rka_register_manuscript(
                venue="EMNLP", title="T", abstract="abs", sections=["S1", "S2"],
                project_id="proj_default",
        )
        _, payload = fake_client.post_calls[0]
        assert payload["abstract"] == "abs"
        assert payload["sections"] == ["S1", "S2"]


class TestRkaGetManuscript:
    """rka_get_manuscript GETs /api/manuscripts/{id} and returns JSON."""

    async def test_get_calls_get_endpoint(self, mcp_server) -> None:
        fake_client = _AsyncClientContext(
            get_response=_make_response(200, {
                "id": "jrn_01_test",
                "title": "Sample",
                "venue": "CHI",
                "tags": ["manuscript", "venue:CHI", "phase:draft"],
            }),
        )
        with patch.object(mcp_server, "_client", return_value=fake_client), patch.object(mcp_server, "_maybe_fire_session_start", new=_noop_fire_session_start):
            result_text = await mcp_server.rka_get_manuscript(manuscript_id="jrn_01_test", project_id="proj_default")
        result = json.loads(result_text)
        assert result["id"] == "jrn_01_test"
        assert len(fake_client.get_calls) == 1
        url, _ = fake_client.get_calls[0]
        assert url == "/api/manuscripts/jrn_01_test"


class TestRkaValidateReference:
    """rka_validate_reference POSTs /api/manuscripts/{id}/validate-reference."""

    async def test_validate_reference_returns_verdict(self, mcp_server) -> None:
        fake_client = _AsyncClientContext(
            post_response=_make_response(200, {
                "identifier": "10.1234/test",
                "status": "VERIFIED",
                "sources_confirmed": ["crossref", "openalex"],
            }),
        )
        with patch.object(mcp_server, "_client", return_value=fake_client), patch.object(mcp_server, "_maybe_fire_session_start", new=_noop_fire_session_start):
            result_text = await mcp_server.rka_validate_reference(
                manuscript_id="jrn_01_test",
                doi="10.1234/test",
                project_id="proj_default",
        )
        result = json.loads(result_text)
        assert result["status"] == "VERIFIED"
        _, payload = fake_client.post_calls[0]
        assert payload == {"DOI": "10.1234/test"}

    async def test_validate_reference_requires_doi_or_title(self, mcp_server) -> None:
        result_text = await mcp_server.rka_validate_reference(
            manuscript_id="jrn_01_test",
            project_id="proj_default",
        )
        result = json.loads(result_text)
        assert result["status"] == "error"
        assert "doi or title" in result["message"].lower()

    async def test_validate_reference_with_title_and_authors(self, mcp_server) -> None:
        fake_client = _AsyncClientContext(
            post_response=_make_response(200, {"status": "UNVERIFIED"}),
        )
        with patch.object(mcp_server, "_client", return_value=fake_client), patch.object(mcp_server, "_maybe_fire_session_start", new=_noop_fire_session_start):
            await mcp_server.rka_validate_reference(
                manuscript_id="jrn_01_X",
                title="A Title",
                author=[{"family": "Smith"}],
                project_id="proj_default",
        )
        _, payload = fake_client.post_calls[0]
        assert payload == {"title": "A Title", "author": [{"family": "Smith"}]}
