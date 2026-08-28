"""Typed MCP compatibility for historical reference-validation jobs."""

from __future__ import annotations

import json

import httpx
import pytest

from rka.mcp import operation_args, server as mcp_server
from rka.mcp.operations_schema import OPERATIONS_SCHEMA
from rka.mcp.verb_dispatch import EXECUTE_OPERATIONS


def test_reference_validation_write_surface_is_removed() -> None:
    assert "validate_reference" not in EXECUTE_OPERATIONS
    assert "validate_reference" not in OPERATIONS_SCHEMA
    assert not hasattr(operation_args, "ValidateReferenceArgs")
    assert not hasattr(mcp_server, "rka_validate_reference")
    assert "reference_validation_status" in OPERATIONS_SCHEMA


@pytest.mark.asyncio
async def test_historical_status_proxy_remains_available(monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "job_id": "job_old",
                "status": "completed",
                "result": {
                    "outcome": "skipped",
                    "reason": "writer_runtime_moved",
                },
            },
        )

    transport = httpx.MockTransport(handler)

    def client(project_id=None):
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    monkeypatch.setattr(mcp_server, "_client", client)
    result = json.loads(
        await mcp_server.rka_get_reference_validation_status(
            manuscript_id="man_old",
            job_id="job_old",
            project_id="prj_test",
        )
    )
    assert result["result"]["reason"] == "writer_runtime_moved"
    assert calls[0] == "/api/manuscripts/man_old/reference-validations/job_old"
