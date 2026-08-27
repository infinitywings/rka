"""Typed MCP coverage for native manuscripts and bulk entity resolution."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from rka.mcp import server
from rka.mcp.operation_args import ExecuteArgsUnion, QueryArgsUnion
from rka.mcp.operations_schema import OPERATIONS_SCHEMA
from rka.mcp.verb_dispatch import EXECUTE_OPERATIONS, _QUERY_DISPATCH


QUERY_OPERATIONS = {
    "resolve_entities",
    "manuscript_context",
    "manuscript_reference_manifest",
    "manuscript_readiness",
    "manuscript_spine",
    "manuscript_outline",
    "manuscript_writing_candidates",
    "changes_since",
    "manuscript_impact",
    "reference_validation_status",
}
EXECUTE_OPERATIONS_NATIVE = {
    "create_manuscript",
    "update_manuscript",
    "upsert_argument_spine",
    "replace_manuscript_reference_manifest",
    "ratify_manuscript_claim",
    "transition_manuscript_phase",
    "create_manuscript_checkpoint",
    "resolve_manuscript_checkpoint",
    "record_verification_attestation",
    "prepare_manuscript_outline_proposal",
}


class _Response:
    is_success = True

    @staticmethod
    def json() -> dict[str, bool]:
        return {"ok": True}


class _CaptureClient:
    def __init__(self, requests: list[dict[str, Any]]) -> None:
        self.requests = requests

    async def __aenter__(self) -> "_CaptureClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> _Response:
        self.requests.append({"method": "GET", "path": path, "params": params})
        return _Response()

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> _Response:
        self.requests.append({"method": "POST", "path": path, "json": json})
        return _Response()

    async def patch(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> _Response:
        self.requests.append({"method": "PATCH", "path": path, "json": json})
        return _Response()

    async def put(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> _Response:
        self.requests.append({"method": "PUT", "path": path, "json": json})
        return _Response()


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server,
        "_client",
        lambda _project_id=None: _CaptureClient(captured),
    )
    return captured


def test_create_manuscript_describe_schema_matches_typed_model() -> None:
    schema = OPERATIONS_SCHEMA["create_manuscript"]
    assert {"phase", "state"} <= set(schema["optional_fields"])
    assert schema["enums"]["phase"] == ["planning"]
    assert schema["enums"]["state"] == ["active"]

    parsed = TypeAdapter(ExecuteArgsUnion).validate_python({
        "operation": "create_manuscript",
        "project_id": "prj_test",
        "title": "Native manuscript",
        "phase": "planning",
        "state": "active",
    })
    assert parsed.phase == "planning"
    assert parsed.state == "active"


@pytest.mark.asyncio
async def test_typed_spine_direct_mutation_is_deprecated_without_network(requests) -> None:
    schema = OPERATIONS_SCHEMA["upsert_argument_spine"]
    assert schema["role_tag"] == "ANY"
    assert schema["enums"]["manuscript_unit_role"] == [
        "unspecified",
        "section",
        "argument_block",
        "paragraph_plan",
        "result",
        "caption",
        "appendix",
        "other",
    ]
    payload = {
        "operation": "upsert_argument_spine",
        "project_id": "prj_test",
        "id": "man_test",
        "expected_revision": 4,
        "spine": {
            "claims": [{
                "local_key": "C1",
                "kind": "empirical",
                "state": "active",
                "exact_wording": "Latency was lower in the testbed.",
                "allowed_wording": "Latency was lower in the evaluated testbed.",
                "prohibited_wording": ["Latency is always lower."],
                "conditions": ["Evaluated testbed only."],
                "falsification_criteria": ["The direction does not reproduce."],
                "unit_links": [{"unit_key": "R1", "relationship": "tests"}],
            }],
            "units": [{
                "local_key": "R1",
                "kind": "result",
                "location": "results#latency",
                "artifact_ref": "art_latency",
                "allowed_interpretation": "Lower in the testbed.",
                "prohibited_interpretation": "Lower everywhere.",
                "unit_role": "result",
                "rhetorical_move": "present_result",
                "evidence": {"support": [{
                    "evidence_claim_id": "clm_result",
                    "supported_proposition": "Latency was lower.",
                    "warrant": "The observation measures the stated contrast.",
                }]},
                "citations": [{
                    "citation_key": "author2025",
                    "citation_role": "baseline",
                    "supported_proposition": "This is the established baseline.",
                    "verification_state": "verified",
                    "comparison_axis": "latency",
                }],
            }],
        },
    }
    parsed = TypeAdapter(ExecuteArgsUnion).validate_python(payload)
    result = json.loads(await server._dispatch_execute_typed(parsed))

    assert result["error"] == "deprecated_operation"
    assert result["replacement_operations"] == [
        "prepare_semantic_patch_context",
        "create_semantic_patch_proposal",
        "apply_semantic_patch_proposal",
    ]
    assert result["received"]["spine_keys"] == ["claims", "units"]
    assert not any(
        item["path"] == "/api/manuscripts/man_test/argument-spine"
        for item in requests
    )


def test_typed_spine_rejects_invalid_academic_enums() -> None:
    payload = {
        "operation": "upsert_argument_spine",
        "project_id": "prj_test",
        "id": "man_test",
        "expected_revision": 1,
        "spine": {
            "claims": [],
            "units": [{
                "local_key": "I1",
                "kind": "introduction",
                "location": "intro",
                "unit_role": "paragraph",
                "citations": [{
                    "citation_key": "x",
                    "citation_role": "mentions",
                    "supported_proposition": "Prior work exists.",
                }],
            }],
        },
    }
    with pytest.raises(ValidationError):
        TypeAdapter(ExecuteArgsUnion).validate_python(payload)


def test_semantic_patch_transition_schema_rejects_ai_reviewer() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ExecuteArgsUnion).validate_python({
            "operation": "apply_semantic_patch_proposal",
            "project_id": "prj_test",
            "id": "spp_test",
            "expected_revision": 1,
            "actor": "executor",
            "reason": "AI-authored proposals require a human transition.",
        })


@pytest.mark.parametrize("origin", [None, "human"])
def test_typed_outline_proposal_requires_ai_provenance(origin: str | None) -> None:
    payload = {
        "operation": "prepare_manuscript_outline_proposal",
        "project_id": "prj_test",
        "id": "man_test",
        "expected_revision": 2,
        "action": "edit",
        "reason": "Attempt to omit or falsify MCP authorship.",
        "unit_key": "INTRO",
        "patch": {"blocker": None},
    }
    if origin is not None:
        payload.update({
            "origin": origin,
            "provider": "openai",
            "model": "gpt-test",
            "boundary": "host_conversation",
            "context_manifest_id": "pcm_test",
        })
    with pytest.raises(ValidationError):
        TypeAdapter(ExecuteArgsUnion).validate_python(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "extra", "expected_path"),
    [
        ("changes_since", {}, "/api/changes"),
        (
            "manuscript_impact",
            {"id": "man_1"},
            "/api/manuscripts/man_1/impact",
        ),
    ],
)
async def test_legacy_change_queries_default_to_100(
    requests: list[dict[str, Any]],
    operation: str,
    extra: dict[str, Any],
    expected_path: str,
) -> None:
    await server._rka_query_legacy_impl(
        operation=operation,
        project_id="prj_test",
        **extra,
    )
    assert requests[-1] == {
        "method": "GET",
        "path": expected_path,
        "params": {
            **({"cursor": 0} if operation == "changes_since" else {"since_cursor": 0}),
            "limit": 100,
        },
    }


@pytest.mark.asyncio
async def test_mcp_http_client_attests_executor_transport() -> None:
    client = server._client("prj_test")
    try:
        assert client.headers["X-RKA-Project"] == "prj_test"
        assert client.headers["X-RKA-Actor"] == "executor"
    finally:
        await client.aclose()


def test_operation_registry_and_typed_unions_are_complete() -> None:
    query_mapping = TypeAdapter(QueryArgsUnion).json_schema()["discriminator"][
        "mapping"
    ]
    execute_mapping = TypeAdapter(ExecuteArgsUnion).json_schema()[
        "discriminator"
    ]["mapping"]

    assert QUERY_OPERATIONS <= set(query_mapping)
    assert EXECUTE_OPERATIONS_NATIVE <= set(execute_mapping)
    assert QUERY_OPERATIONS <= set(_QUERY_DISPATCH)
    assert EXECUTE_OPERATIONS_NATIVE <= set(EXECUTE_OPERATIONS)
    assert QUERY_OPERATIONS | EXECUTE_OPERATIONS_NATIVE <= set(OPERATIONS_SCHEMA)
    assert OPERATIONS_SCHEMA["register_manuscript"]["tool"] == "rka_execute"
    assert OPERATIONS_SCHEMA["manuscript"]["tool"] == "rka_query"


@pytest.mark.asyncio
async def test_outline_read_and_proposal_route_through_typed_mcp(requests) -> None:
    query = TypeAdapter(QueryArgsUnion).validate_python({
        "operation": "manuscript_outline",
        "project_id": "prj_test",
        "id": "man_outline",
    })
    await server._dispatch_query_typed(query)
    proposal = TypeAdapter(ExecuteArgsUnion).validate_python({
        "operation": "prepare_manuscript_outline_proposal",
        "project_id": "prj_test",
        "id": "man_outline",
        "expected_revision": 3,
        "action": "reorder",
        "reason": "Lead with the method.",
        "origin": "host_agent",
        "provider": "openai",
        "model": "gpt-test",
        "boundary": "host_conversation",
        "context_manifest_id": "pcm_outline",
        "ordered_unit_keys": ["METHOD", "INTRO"],
    })
    await server._dispatch_execute_typed(proposal)
    outline_requests = [
        request for request in requests
        if request["path"].startswith("/api/manuscripts/man_outline/outline")
    ]
    assert outline_requests == [
        {
            "method": "GET",
            "path": "/api/manuscripts/man_outline/outline",
            "params": None,
        },
        {
            "method": "POST",
            "path": "/api/manuscripts/man_outline/outline/proposals",
            "json": {
                "expected_revision": 3,
                "action": "reorder",
                "reason": "Lead with the method.",
                "origin": "host_agent",
                "provider": "openai",
                "model": "gpt-test",
                "boundary": "host_conversation",
                "context_manifest_id": "pcm_outline",
                "ordered_unit_keys": ["METHOD", "INTRO"],
            },
        },
    ]


@pytest.mark.parametrize(
    "adapter,payload",
    [
        (
            TypeAdapter(QueryArgsUnion),
            {
                "operation": "manuscript_readiness",
                "project_id": "prj_test",
                "id": "man_test",
                "target_phase": "draft",
            },
        ),
        (
            TypeAdapter(ExecuteArgsUnion),
            {
                "operation": "replace_manuscript_reference_manifest",
                "project_id": "prj_test",
                "id": "man_test",
                "expected_revision": 2,
                "members": [
                    {
                        "citation_key": "Smith2026",
                        "literature_id": "lit_1",
                    },
                    {
                        "citation_key": "smith2026",
                        "literature_id": "lit_2",
                    },
                ],
            },
        ),
        (
            TypeAdapter(QueryArgsUnion),
            {
                "operation": "changes_since",
                "project_id": "prj_test",
                "cursor": -1,
            },
        ),
        (
            TypeAdapter(QueryArgsUnion),
            {
                "operation": "manuscript_impact",
                "project_id": "prj_test",
                "id": "man_test",
                "since_cursor": 0,
                "limit": 1001,
            },
        ),
        (
            TypeAdapter(QueryArgsUnion),
            {
                "operation": "reference_validation_status",
                "project_id": "prj_test",
                "manuscript_id": "man_test",
            },
        ),
        (
            TypeAdapter(ExecuteArgsUnion),
            {
                "operation": "create_manuscript",
                "project_id": "prj_test",
                "title": "Lifecycle bypass",
                "phase": "submitted",
            },
        ),
        (
            TypeAdapter(ExecuteArgsUnion),
            {
                "operation": "update_manuscript",
                "project_id": "prj_test",
                "id": "man_test",
                "expected_revision": 1,
                "phase": "submitted",
            },
        ),
        (
            TypeAdapter(ExecuteArgsUnion),
            {
                "operation": "transition_manuscript_phase",
                "project_id": "prj_test",
                "id": "man_test",
                "expected_revision": 1,
                "target_phase": "camera_ready",
            },
        ),
        (
            TypeAdapter(ExecuteArgsUnion),
            {
                "operation": "create_manuscript_checkpoint",
                "project_id": "prj_test",
                "id": "man_test",
                "expected_revision": 1,
                "kind": "approval",
            },
        ),
        (
            TypeAdapter(ExecuteArgsUnion),
            {
                "operation": "upsert_argument_spine",
                "project_id": "prj_test",
                "id": "man_test",
                "expected_revision": 1,
                "spine": {
                    "claims": [
                        {
                            "local_key": "C1",
                            "kind": "unsupported_kind",
                            "exact_wording": "Claim.",
                            "allowed_wording": "Claim.",
                            "prohibited_wording": ["Overclaim."],
                        },
                    ],
                    "units": [],
                },
            },
        ),
    ],
)
def test_invalid_native_enums_fail_at_typed_boundary(
    adapter: TypeAdapter,
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(payload)


@pytest.mark.parametrize(
    "payload,method,path,expected",
    [
        (
            {
                "operation": "resolve_entities",
                "project_id": "prj_test",
                "ids": ["clm_1", "dec_1"],
                "include_sources": True,
                "include_edges": True,
            },
            "POST",
            "/api/entities/resolve",
            {
                "ids": ["clm_1", "dec_1"],
                "include_sources": True,
                "include_edges": True,
            },
        ),
        (
            {
                "operation": "manuscript_context",
                "project_id": "prj_test",
                "id": "man_1",
            },
            "GET",
            "/api/manuscripts/man_1/context",
            None,
        ),
        (
            {
                "operation": "manuscript_reference_manifest",
                "project_id": "prj_test",
                "id": "man_1",
            },
            "GET",
            "/api/manuscripts/man_1/references",
            None,
        ),
        (
            {
                "operation": "manuscript_readiness",
                "project_id": "prj_test",
                "id": "man_1",
                "target_phase": "review",
            },
            "GET",
            "/api/manuscripts/man_1/readiness",
            {"target_phase": "review"},
        ),
        (
            {
                "operation": "manuscript_spine",
                "project_id": "prj_test",
                "id": "man_1",
            },
            "GET",
            "/api/manuscripts/man_1/spine",
            None,
        ),
        (
            {
                "operation": "manuscript_writing_candidates",
                "project_id": "prj_test",
                "id": "man_1",
            },
            "GET",
            "/api/manuscripts/man_1/writing-candidates",
            None,
        ),
        (
            {
                "operation": "changes_since",
                "project_id": "prj_test",
                "cursor": 41,
                "limit": 25,
            },
            "GET",
            "/api/changes",
            {"cursor": 41, "limit": 25},
        ),
        (
            {
                "operation": "manuscript_impact",
                "project_id": "prj_test",
                "id": "man_1",
                "since_cursor": 41,
                "limit": 25,
            },
            "GET",
            "/api/manuscripts/man_1/impact",
            {"since_cursor": 41, "limit": 25},
        ),
        (
            {
                "operation": "reference_validation_status",
                "project_id": "prj_test",
                "manuscript_id": "man_1",
                "job_id": "job_1",
            },
            "GET",
            "/api/manuscripts/man_1/reference-validations/job_1",
            None,
        ),
    ],
)
async def test_typed_query_rest_wiring(
    requests: list[dict[str, Any]],
    payload: dict[str, Any],
    method: str,
    path: str,
    expected: dict[str, Any] | None,
) -> None:
    args = TypeAdapter(QueryArgsUnion).validate_python(payload)
    await server.rka_query(args)

    request = next(item for item in requests if item["path"] == path)
    assert request["method"] == method
    key = "json" if method == "POST" else "params"
    assert request.get(key) == expected


async def test_reference_validation_status_preserves_pending_envelope(
    requests: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _Response,
        "json",
        staticmethod(
            lambda: {
                "job_id": "job_1",
                "status": "pending",
                "canonical_manuscript_id": "man_1",
                "requested_manuscript_id": "man_1",
                "attempts": 0,
                "max_attempts": 3,
            }
        ),
    )
    args = TypeAdapter(QueryArgsUnion).validate_python(
        {
            "operation": "reference_validation_status",
            "project_id": "prj_test",
            "manuscript_id": "man_1",
            "job_id": "job_1",
        }
    )

    result = json.loads(await server.rka_query(args))

    assert result["job_id"] == "job_1"
    assert result["status"] == "pending"
    assert requests == [
        {
            "method": "GET",
            "path": "/api/manuscripts/man_1/reference-validations/job_1",
            "params": None,
        }
    ]


def test_historical_reference_validation_contract_is_described() -> None:
    status_schema = OPERATIONS_SCHEMA["reference_validation_status"]

    assert "validate_reference" not in OPERATIONS_SCHEMA
    assert status_schema["tool"] == "rka_query"
    assert "historical" in status_schema["summary"].lower()
    assert "no longer initiates or executes" in status_schema["notes"]
    assert status_schema["required_fields"] == [
        "project_id",
        "manuscript_id",
        "job_id",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "operation": "changes_since",
            "project_id": "prj_test",
            "cursor": 4,
        },
        {
            "operation": "manuscript_impact",
            "project_id": "prj_test",
            "id": "man_1",
            "since_cursor": 4,
        },
    ],
)
async def test_cursor_queries_expose_page_cursors(
    requests: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        _Response,
        "json",
        staticmethod(
            lambda: {
                "from_cursor": 4,
                "next_cursor": 7,
                "latest_cursor": 11,
                "has_more": True,
            }
        ),
    )
    args = TypeAdapter(QueryArgsUnion).validate_python(payload)
    result = json.loads(await server.rka_query(args))

    assert result["next_cursor"] == 7
    assert result["latest_cursor"] == 11
    assert result["has_more"] is True
    assert requests


_ATTESTATION = {
    "claim_id": "mcl_1",
    "claim_version": 1,
    "overall_verdict": "warn",
    "grounding_verdict": "pass",
    "evidence_verdict": "warn",
    "contradiction_verdict": "pass",
    "currency_verdict": "pass",
    "ratification_verdict": "not_checked",
    "unit_coverage_verdict": "pass",
    "dependency_snapshot": {"claim": "sha256:abc"},
    "full_json_payload": {"findings": []},
    "started_at": "2026-07-22T12:00:00Z",
    "completed_at": "2026-07-22T12:00:01Z",
}


@pytest.mark.parametrize(
    "payload,method,path,expected_json",
    [
        (
            {
                "operation": "create_manuscript",
                "project_id": "prj_test",
                "title": "Native manuscript",
                "venue": "USENIX Security",
            },
            "POST",
            "/api/manuscripts/native",
            {"title": "Native manuscript", "venue": "USENIX Security"},
        ),
        (
            {
                "operation": "update_manuscript",
                "project_id": "prj_test",
                "id": "man_1",
                "expected_revision": 2,
                "venue": None,
            },
            "PATCH",
            "/api/manuscripts/man_1",
            {"expected_revision": 2, "venue": None},
        ),
        (
            {
                "operation": "prepare_manuscript_outline_proposal",
                "project_id": "prj_test",
                "id": "man_1",
                "expected_revision": 3,
                "action": "edit",
                "reason": "Clear the resolved blocker.",
                "origin": "host_agent",
                "provider": "openai",
                "model": "gpt-test",
                "boundary": "host_conversation",
                "context_manifest_id": "pcm_outline",
                "unit_key": "INTRO",
                "patch": {"blocker": None},
            },
            "POST",
            "/api/manuscripts/man_1/outline/proposals",
            {
                "expected_revision": 3,
                "action": "edit",
                "reason": "Clear the resolved blocker.",
                "origin": "host_agent",
                "provider": "openai",
                "model": "gpt-test",
                "boundary": "host_conversation",
                "context_manifest_id": "pcm_outline",
                "unit_key": "INTRO",
                "patch": {"blocker": None},
            },
        ),
        (
            {
                "operation": "replace_manuscript_reference_manifest",
                "project_id": "prj_test",
                "id": "man_1",
                "expected_revision": 4,
                "members": [
                    {
                        "citation_key": "smith2026",
                        "literature_id": "lit_1",
                    }
                ],
            },
            "PUT",
            "/api/manuscripts/man_1/references",
            {
                "expected_revision": 4,
                "members": [
                    {
                        "citation_key": "smith2026",
                        "literature_id": "lit_1",
                    }
                ],
            },
        ),
        (
            {
                "operation": "ratify_manuscript_claim",
                "project_id": "prj_test",
                "id": "man_1",
                "claim_ref": "C1",
                "expected_revision": 4,
                "decision_id": "dec_1",
            },
            "POST",
            "/api/manuscripts/man_1/claims/C1/ratifications",
            {"expected_revision": 4, "decision_id": "dec_1"},
        ),
        (
            {
                "operation": "transition_manuscript_phase",
                "project_id": "prj_test",
                "id": "man_1",
                "expected_revision": 5,
                "target_phase": "review",
            },
            "POST",
            "/api/manuscripts/man_1/transition",
            {"expected_revision": 5, "target_phase": "review"},
        ),
        (
            {
                "operation": "create_manuscript_checkpoint",
                "project_id": "prj_test",
                "id": "man_1",
                "expected_revision": 6,
                "kind": "outline",
            },
            "POST",
            "/api/manuscripts/man_1/checkpoints",
            {"expected_revision": 6, "kind": "outline"},
        ),
        (
            {
                "operation": "resolve_manuscript_checkpoint",
                "project_id": "prj_test",
                "checkpoint_id": "mck_1",
                "expected_revision": 7,
                "decision_id": "dec_2",
                "status": "resolved",
                "resolved_at": "2026-07-22T12:00:00Z",
            },
            "POST",
            "/api/manuscripts/checkpoints/mck_1/resolve",
            {
                "expected_revision": 7,
                "decision_id": "dec_2",
                "status": "resolved",
                "resolved_at": "2026-07-22T12:00:00Z",
            },
        ),
        (
            {
                "operation": "record_verification_attestation",
                "project_id": "prj_test",
                "id": "man_1",
                "expected_revision": 8,
                **_ATTESTATION,
            },
            "POST",
            "/api/manuscripts/man_1/verification-attestations",
            {"expected_revision": 8, "attestation": _ATTESTATION},
        ),
    ],
)
async def test_typed_execute_rest_wiring(
    requests: list[dict[str, Any]],
    payload: dict[str, Any],
    method: str,
    path: str,
    expected_json: dict[str, Any],
) -> None:
    args = TypeAdapter(ExecuteArgsUnion).validate_python(payload)
    await server.rka_execute(args)

    request = next(item for item in requests if item["path"] == path)
    assert request["method"] == method
    assert request["path"] == path
    if payload["operation"] == "create_manuscript":
        # The REST model has explicit nullable fields; only assert the values
        # supplied through the typed operation plus canonical defaults.
        for key, value in expected_json.items():
            assert request["json"][key] == value
        assert request["json"]["phase"] == "planning"
        assert request["json"]["state"] == "active"
    else:
        assert request["json"] == expected_json
