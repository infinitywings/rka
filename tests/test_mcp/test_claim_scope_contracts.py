"""Typed MCP coverage for canonical claim-scope contracts."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from rka.mcp import server
from rka.mcp.operation_args import ExecuteArgsUnion, QueryArgsUnion
from rka.mcp.verb_dispatch import dispatch_execute_typed, dispatch_query_typed


@pytest.fixture
def captured_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        captured.append(
            {
                "method": request.method,
                "path": request.url.path,
                "body": body,
            }
        )
        return httpx.Response(
            200,
            json={
                "claim_id": "clm_scope",
                "project_id": "prj_scope",
                "current_revision": 1 if request.method == "POST" else 0,
                "scope_readiness": "ready" if request.method == "POST" else "missing",
                "findings": [],
                "current": None,
                "versions": [],
            },
        )

    def client(_project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
        )

    monkeypatch.setattr(server, "_client", client)
    return captured


@pytest.mark.asyncio
async def test_query_claim_scope_routes_to_history_endpoint(
    captured_requests: list[dict[str, Any]],
) -> None:
    args = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "claim_scope",
            "project_id": "prj_scope",
            "id": "clm_scope",
        }
    )
    result = json.loads(await dispatch_query_typed(args))

    assert result["scope_readiness"] == "missing"
    claim_requests = [
        request for request in captured_requests if request["path"] == "/api/claims/clm_scope/scope"
    ]
    assert claim_requests == [
        {
            "method": "GET",
            "path": "/api/claims/clm_scope/scope",
            "body": None,
        }
    ]


@pytest.mark.asyncio
async def test_set_claim_scope_forwards_full_reviewed_contract(
    captured_requests: list[dict[str, Any]],
) -> None:
    args = TypeAdapter(ExecuteArgsUnion).validate_python(
        {
            "operation": "set_claim_scope",
            "project_id": "prj_scope",
            "claim_id": "clm_scope",
            "expected_revision": 0,
            "actor": "brain",
            "reason": "Checked source and evaluation boundaries.",
            "conditions": [
                {
                    "kind": "dataset",
                    "key": "evaluation_dataset",
                    "operator": "equals",
                    "value": "Dataset A",
                }
            ],
            "uncertainty": "low",
            "extension_policy": "exact_only",
            "prohibited_extensions": ["other datasets without evidence"],
            "falsifier_status": "applicable",
            "falsifier": "Independent replication fails on Dataset A.",
            "review_status": "reviewed",
        }
    )
    result = json.loads(await dispatch_execute_typed(args))

    assert result["scope_readiness"] == "ready"
    assert captured_requests[0]["method"] == "POST"
    assert captured_requests[0]["path"] == "/api/claims/clm_scope/scope"
    assert captured_requests[0]["body"]["conditions"][0]["kind"] == "dataset"
    assert captured_requests[0]["body"]["review_status"] == "reviewed"
    assert "project_id" not in captured_requests[0]["body"]


def test_reviewed_scope_rejects_ambiguous_contract_before_dispatch() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ExecuteArgsUnion).validate_python(
            {
                "operation": "set_claim_scope",
                "project_id": "prj_scope",
                "claim_id": "clm_scope",
                "expected_revision": 0,
                "actor": "brain",
                "reason": "Too vague.",
                "review_status": "reviewed",
            }
        )
