"""MCP claim listings preserve the server-derived contradiction signal."""

from __future__ import annotations

import httpx
import pytest

from rka.mcp import server as mcp_server


@pytest.mark.asyncio
async def test_get_claims_prints_explicit_contradiction_state(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/claims"
        assert request.url.params["cluster_id"] == "ecl_test"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "clm_clear",
                    "source_entry_id": "jrn_clear",
                    "claim_type": "result",
                    "content": "Uncontested result.",
                    "confidence": 0.9,
                    "verified": True,
                    "evidence_status": "supported",
                    "contradicted": False,
                    "stale": False,
                },
                {
                    "id": "clm_conflict",
                    "source_entry_id": "jrn_conflict",
                    "claim_type": "result",
                    "content": "Conflicted result.",
                    "confidence": 0.8,
                    "verified": True,
                    "evidence_status": "partially_supported",
                    "contradicted": True,
                    "stale": False,
                },
            ],
        )

    transport = httpx.MockTransport(handler)

    def client(project_id: str | None = None) -> httpx.AsyncClient:
        assert project_id == "prj_test"
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    monkeypatch.setattr(mcp_server, "_client", client)
    result = await mcp_server.rka_get_claims(
        cluster_id="ecl_test", project_id="prj_test"
    )

    assert "clm_clear" in result and "contradicted=no" in result
    assert "clm_conflict" in result and "contradicted=yes" in result


@pytest.mark.asyncio
async def test_get_claims_does_not_treat_missing_projection_as_clear(monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json=[
                {
                    "id": "clm_unattested",
                    "source_entry_id": "jrn_unattested",
                    "claim_type": "result",
                    "content": "Legacy response without graph projection.",
                    "confidence": 0.7,
                    "verified": True,
                    "evidence_status": "supported",
                    "stale": False,
                }
            ],
        )
    )
    monkeypatch.setattr(
        mcp_server,
        "_client",
        lambda _project_id=None: httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ),
    )

    result = await mcp_server.rka_get_claims(project_id="prj_test")
    assert "contradicted=unknown" in result
