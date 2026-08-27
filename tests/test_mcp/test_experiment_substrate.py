"""Typed MCP routes for the experiment evidence substrate."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from rka.mcp import server
from rka.mcp.operation_args import (
    ExecuteArgsUnion,
    QueryArgsUnion,
    RecordExperimentObservationArgs,
)
from rka.mcp.verb_dispatch import dispatch_execute_typed, dispatch_query_typed


@pytest.fixture
def captured_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        captured.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
                "body": body,
            }
        )
        return httpx.Response(200, json={"ok": True})

    def client(_project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
        )

    monkeypatch.setattr(server, "_client", client)
    return captured


@pytest.mark.asyncio
async def test_typed_reads_route_to_detail_and_filtered_list(
    captured_requests: list[dict[str, Any]],
) -> None:
    detail = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "experiment_runs",
            "project_id": "prj_test",
            "id": "run_01XYZ",
        }
    )
    await dispatch_query_typed(detail)

    listed = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "experiment_observations",
            "project_id": "prj_test",
            "filters": {
                "run_id": "run_01XYZ",
                "direction": "negative",
                "claim_id": "clm_01XYZ",
            },
            "limit": 12,
        }
    )
    await dispatch_query_typed(listed)

    experiment_requests = [
        request for request in captured_requests
        if request["path"].startswith("/api/experiment-")
    ]
    assert experiment_requests == [
        {
            "method": "GET",
            "path": "/api/experiment-runs/run_01XYZ",
            "query": {},
            "body": None,
        },
        {
            "method": "GET",
            "path": "/api/experiment-observations",
            "query": {
                "run_id": "run_01XYZ",
                "direction": "negative",
                "claim_id": "clm_01XYZ",
                "limit": "12",
            },
            "body": None,
        },
    ]


@pytest.mark.asyncio
async def test_typed_writes_preserve_ids_in_paths_and_payloads(
    captured_requests: list[dict[str, Any]],
) -> None:
    create = TypeAdapter(ExecuteArgsUnion).validate_python(
        {
            "operation": "create_experiment",
            "project_id": "prj_test",
            "title": "MCP experiment",
            "objective": "Measure a bounded effect.",
            "protocol": "Run the frozen benchmark.",
            "created_by": "brain",
            "reason": "Exercise the typed MCP path.",
        }
    )
    await dispatch_execute_typed(create)

    transition = TypeAdapter(ExecuteArgsUnion).validate_python(
        {
            "operation": "transition_experiment_run",
            "project_id": "prj_test",
            "id": "run_01XYZ",
            "expected_revision": 2,
            "action": "succeed",
            "actor": "executor",
            "reason": "Command exited normally.",
            "exit_code": 0,
        }
    )
    await dispatch_execute_typed(transition)

    assert captured_requests[0]["path"] == "/api/experiments"
    assert captured_requests[0]["body"]["objective"] == "Measure a bounded effect."
    assert "project_id" not in captured_requests[0]["body"]
    assert captured_requests[1] == {
        "method": "POST",
        "path": "/api/experiment-runs/run_01XYZ/transition",
        "query": {},
        "body": {
            "expected_revision": 2,
            "action": "succeed",
            "actor": "executor",
            "reason": "Command exited normally.",
            "exit_code": 0,
        },
    }


def test_typed_evidence_review_requires_explicit_role() -> None:
    with pytest.raises(ValidationError, match="evidence_role"):
        TypeAdapter(ExecuteArgsUnion).validate_python(
            {
                "operation": "triage_interpretation_candidate",
                "project_id": "prj_test",
                "id": "icd_01XYZ",
                "action": "classify_evidence",
                "expected_revision": 1,
                "actor": "pi",
                "reason": "Reviewed exact locator.",
                "target_entity_id": "clm_01XYZ",
            }
        )


@pytest.mark.asyncio
async def test_observation_value_contract_is_visible_before_execution() -> None:
    """Both typed JSON Schema and rka_describe must disclose value rules."""
    typed_schema = RecordExperimentObservationArgs.model_json_schema()
    properties = typed_schema["properties"]

    assert "metric/comparison/test require one value" in properties["kind"][
        "description"
    ]
    assert "Mutually exclusive with value_text" in properties["value_real"][
        "description"
    ]
    assert "required for qualitative/failure" in properties["value_text"][
        "description"
    ]

    described = json.loads(
        await server.rka_describe(operation="record_experiment_observation")
    )
    assert "at most one of value_real and value_text" in described["notes"]
    assert "metric, comparison, and test require one" in described["notes"]
    assert "qualitative and failure require value_text" in described["notes"]
    assert "REST/domain validator is authoritative" in described["notes"]
