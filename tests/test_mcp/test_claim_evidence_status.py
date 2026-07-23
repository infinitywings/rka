"""MCP contracts for claim grounding and evidence assessment."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from rka.mcp import server as mcp_server
from rka.mcp import verb_dispatch
from rka.mcp.operation_args import ReviewClaimsArgs


def test_review_args_use_numeric_confidence_and_closed_evidence_status() -> None:
    args = ReviewClaimsArgs(
        project_id="prj_test",
        claim_ids=["clm_1"],
        action="adjust",
        confidence_override=0.75,
        evidence_status="partially_supported",
    )
    assert args.confidence_override == 0.75
    assert args.evidence_status == "partially_supported"

    schema = ReviewClaimsArgs.model_json_schema()["properties"]
    assert schema["confidence_override"]["anyOf"][0]["type"] == "number"

    with pytest.raises(ValidationError):
        ReviewClaimsArgs(
            project_id="prj_test",
            claim_ids=["clm_1"],
            action="adjust",
            confidence_override=1.1,
        )
    with pytest.raises(ValidationError):
        ReviewClaimsArgs(
            project_id="prj_test",
            claim_ids=["clm_1"],
            action="adjust",
        )
    with pytest.raises(ValidationError):
        ReviewClaimsArgs(
            project_id="prj_test",
            claim_ids=["clm_1"],
            evidence_status="verified",  # type: ignore[arg-type]
        )


@pytest.fixture
def captured_requests(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[-1]})

    transport = httpx.MockTransport(handler)

    def client(project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    monkeypatch.setattr(mcp_server, "_client", client)
    return calls


@pytest.mark.asyncio
async def test_legacy_approve_does_not_infer_evidence_support(captured_requests) -> None:
    result = await mcp_server.rka_review_claims(
        claim_ids=["clm_1"],
        action="approve",
        project_id="prj_test",
    )
    assert "clm_1: approved" in result
    assert captured_requests[0]["body"] == {"verified": True}


@pytest.mark.asyncio
async def test_review_can_explicitly_set_evidence_status(captured_requests) -> None:
    await mcp_server.rka_review_claims(
        claim_ids=["clm_1"],
        action="approve",
        evidence_status="supported",
        project_id="prj_test",
    )
    assert captured_requests[0]["body"] == {
        "verified": True,
        "evidence_status": "supported",
    }


@pytest.mark.asyncio
async def test_review_dispatch_forwards_evidence_status(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_review_claims(**kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setattr(verb_dispatch, "_legacy", lambda name: fake_review_claims)
    result = await verb_dispatch.dispatch_review(
        "claims",
        project_id="prj_test",
        payload={
            "claim_ids": ["clm_1"],
            "action": "adjust",
            "confidence_override": 0.6,
            "evidence_status": "inconclusive",
        },
    )
    assert result == "ok"
    assert calls == [
        {
            "claim_ids": ["clm_1"],
            "action": "adjust",
            "confidence_override": 0.6,
            "evidence_status": "inconclusive",
            "project_id": "prj_test",
        }
    ]
