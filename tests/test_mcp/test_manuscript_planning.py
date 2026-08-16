"""Typed MCP routing for manuscript-planning branches."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from rka.mcp import server
from rka.mcp.operation_args import ExecuteArgsUnion, QueryArgsUnion
from rka.mcp.operations_schema import OPERATIONS_SCHEMA
from rka.mcp.verb_dispatch import (
    EXECUTE_OPERATIONS,
    _QUERY_DISPATCH,
    dispatch_execute_typed,
    dispatch_query_typed,
)


@pytest.fixture
def planning_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
                "body": json.loads(request.content) if request.content else None,
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
async def test_planning_reads_route_exact_context_and_compare(planning_requests) -> None:
    listed = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "planning_branches",
            "project_id": "prj_test",
            "manuscript_id": "man_01XYZ",
            "include_archived": False,
        }
    )
    await dispatch_query_typed(listed)
    compared = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "planning_compare",
            "project_id": "prj_test",
            "base_branch_id": "mpb_01BASE",
            "other_branch_id": "mpb_01OTHER",
        }
    )
    await dispatch_query_typed(compared)
    workflow = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "planning_argument_workflow",
            "project_id": "prj_test",
            "id": "mpb_01BASE",
        }
    )
    await dispatch_query_typed(workflow)
    promotions = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "planning_promotions",
            "project_id": "prj_test",
            "id": "mpb_01BASE",
        }
    )
    await dispatch_query_typed(promotions)
    planning_only = [
        request for request in planning_requests if request["path"].startswith("/api/planning/")
    ]
    assert planning_only == [
        {
            "method": "GET",
            "path": "/api/planning/branches",
            "query": {"manuscript_id": "man_01XYZ", "include_archived": "false"},
            "body": None,
        },
        {
            "method": "GET",
            "path": "/api/planning/branches/compare",
            "query": {
                "base_branch_id": "mpb_01BASE",
                "other_branch_id": "mpb_01OTHER",
            },
            "body": None,
        },
        {
            "method": "GET",
            "path": "/api/planning/branches/mpb_01BASE/argument-workflow",
            "query": {},
            "body": None,
        },
        {
            "method": "GET",
            "path": "/api/planning/branches/mpb_01BASE/promotions",
            "query": {},
            "body": None,
        },
    ]


@pytest.mark.asyncio
async def test_evaluation_reads_route_exact_branch(planning_requests) -> None:
    workflow = TypeAdapter(QueryArgsUnion).validate_python({
        "operation": "planning_evaluation_workflow",
        "project_id": "prj_test",
        "id": "mpb_01EVAL",
    })
    events = TypeAdapter(QueryArgsUnion).validate_python({
        "operation": "planning_evaluation_events",
        "project_id": "prj_test",
        "id": "mpb_01EVAL",
    })
    await dispatch_query_typed(workflow)
    await dispatch_query_typed(events)
    assert planning_requests == [
        {
            "method": "GET",
            "path": "/api/planning/branches/mpb_01EVAL/evaluation-workflow",
            "query": {},
            "body": None,
        },
        {
            "method": "GET",
            "path": "/api/planning/branches/mpb_01EVAL/evaluation-events",
            "query": {},
            "body": None,
        },
    ]


@pytest.mark.asyncio
async def test_evaluation_writes_preserve_guarded_payload(planning_requests) -> None:
    mission = TypeAdapter(ExecuteArgsUnion).validate_python({
        "operation": "create_planning_evaluation_mission",
        "project_id": "prj_test",
        "id": "mpb_01EVAL",
        "expected_branch_revision": 4,
        "artifact_id": "pla_01EVAL",
        "expected_artifact_version": 2,
        "commitment_key": "claim-primary",
        "requirement_key": "primary-effect",
        "reason": "Collect missing evidence.",
        "actor": "brain",
    })
    result = TypeAdapter(ExecuteArgsUnion).validate_python({
        "operation": "prepare_planning_evaluation_result",
        "project_id": "prj_test",
        "id": "mpb_01EVAL",
        "expected_branch_revision": 5,
        "artifact_id": "pla_01EVAL",
        "expected_artifact_version": 3,
        "commitment_key": "claim-primary",
        "manuscript_id": "man_01PAPER",
        "expected_manuscript_revision": 7,
        "result_unit_local_key": "result-primary",
        "location": "sections/results.tex#primary",
        "title": "Primary effect",
        "artifact_ref": "art_01RESULT",
        "reason": "Prepare exact result unit.",
        "actor": "brain",
    })
    await dispatch_execute_typed(mission)
    await dispatch_execute_typed(result)
    assert planning_requests[0]["path"].endswith("/evaluation-missions")
    assert planning_requests[0]["body"]["requirement_key"] == "primary-effect"
    assert planning_requests[1]["path"].endswith("/evaluation-result-proposals")
    assert planning_requests[1]["body"]["artifact_ref"] == "art_01RESULT"


@pytest.mark.asyncio
async def test_planning_write_routes_preserve_typed_payload(planning_requests) -> None:
    created = TypeAdapter(ExecuteArgsUnion).validate_python(
        {
            "operation": "create_planning_branch",
            "project_id": "prj_test",
            "name": "primary",
            "purpose": "Develop the argument.",
            "created_by": "pi",
            "reason": "Start planning.",
        }
    )
    await dispatch_execute_typed(created)
    appended = TypeAdapter(ExecuteArgsUnion).validate_python(
        {
            "operation": "append_planning_artifact_version",
            "project_id": "prj_test",
            "id": "mpb_01XYZ",
            "expected_branch_revision": 1,
            "local_key": "core-insight",
            "stage_type": "seed",
            "summary": "Composable timing primitive.",
            "payload": {"insight": "Treat timing as composable."},
            "origin": "user",
            "created_by": "pi",
            "reason": "Preserve insight.",
        }
    )
    await dispatch_execute_typed(appended)
    promoted = TypeAdapter(ExecuteArgsUnion).validate_python(
        {
            "operation": "promote_planning_rq",
            "project_id": "prj_test",
            "id": "mpb_01XYZ",
            "expected_branch_revision": 2,
            "artifact_id": "pla_01PORTFOLIO",
            "expected_artifact_version": 1,
            "candidate_key": "rq-main",
            "phase": "paper_framing",
            "reason": "PI selected the bounded RQ.",
        }
    )
    await dispatch_execute_typed(promoted)
    planning_only = [
        request for request in planning_requests if request["path"].startswith("/api/planning/")
    ]
    assert planning_only[0]["path"] == "/api/planning/branches"
    assert "project_id" not in planning_only[0]["body"]
    assert planning_only[1]["path"] == "/api/planning/branches/mpb_01XYZ/artifacts"
    assert planning_only[1]["body"]["payload"] == {
        "insight": "Treat timing as composable.",
        "audience": [],
    }
    assert planning_only[2]["path"] == "/api/planning/branches/mpb_01XYZ/promote-rq"
    assert planning_only[2]["body"]["candidate_key"] == "rq-main"


def test_planning_operations_are_complete_and_ai_provenance_is_closed() -> None:
    query_ops = {
        "planning_branches",
        "planning_resume",
        "planning_compare",
        "planning_artifact_versions",
        "planning_argument_workflow",
        "planning_promotions",
    }
    execute_ops = {
        "create_planning_branch",
        "transition_planning_branch",
        "append_planning_artifact_version",
        "promote_planning_rq",
        "prepare_planning_contribution",
        "ratify_planning_contribution",
    }
    assert query_ops <= set(_QUERY_DISPATCH)
    assert execute_ops <= set(EXECUTE_OPERATIONS)
    assert query_ops | execute_ops <= set(OPERATIONS_SCHEMA)

    with pytest.raises(ValidationError, match="provider, model, and context_hash"):
        TypeAdapter(ExecuteArgsUnion).validate_python(
            {
                "operation": "append_planning_artifact_version",
                "project_id": "prj_test",
                "id": "mpb_01XYZ",
                "expected_branch_revision": 1,
                "local_key": "core-insight",
                "stage_type": "seed",
                "summary": "AI proposal.",
                "payload": {"insight": "AI proposal."},
                "origin": "ai_suggested",
                "created_by": "llm",
                "reason": "Require complete provenance.",
            }
        )
