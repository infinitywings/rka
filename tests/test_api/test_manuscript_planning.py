"""REST contracts for recoverable manuscript-planning branches."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


DEFAULT_HEADERS = {"X-RKA-Project": "proj_default"}
OTHER_HEADERS = {"X-RKA-Project": "proj_planning_api_other"}


@pytest_asyncio.fixture
async def planning_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("planning-api.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/projects",
                json={"id": "proj_planning_api_other", "name": "Planning Other"},
            )
            assert created.status_code == 200
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_planning_routes_resume_compare_and_conflict(
    planning_client: httpx.AsyncClient,
) -> None:
    created = await planning_client.post(
        "/api/planning/branches",
        headers=DEFAULT_HEADERS,
        json={
            "name": "primary",
            "purpose": "Develop a recoverable framing.",
            "created_by": "pi",
            "reason": "Start the workbench.",
        },
    )
    assert created.status_code == 201
    primary = created.json()
    primary_id = primary["branch"]["id"]

    appended = await planning_client.post(
        f"/api/planning/branches/{primary_id}/artifacts",
        headers=DEFAULT_HEADERS,
        json={
            "expected_branch_revision": 1,
            "expected_previous_version": 0,
            "local_key": "core-insight",
            "stage_type": "seed",
            "summary": "Treat timing as a composable security primitive.",
            "payload": {"insight": "Treat timing as a composable security primitive."},
            "origin": "user",
            "created_by": "pi",
            "reason": "Preserve the one-sentence insight.",
        },
    )
    assert appended.status_code == 200
    artifact_id = appended.json()["effective_artifacts"][0]["id"]

    stale = await planning_client.post(
        f"/api/planning/branches/{primary_id}/artifacts",
        headers=DEFAULT_HEADERS,
        json={
            "expected_branch_revision": 1,
            "expected_previous_version": 1,
            "local_key": "core-insight",
            "stage_type": "seed",
            "summary": "Stale edit.",
            "payload": {"insight": "Stale edit."},
            "origin": "user_revised",
            "created_by": "pi",
            "reason": "Exercise concurrency.",
        },
    )
    assert stale.status_code == 409

    forked = await planning_client.post(
        "/api/planning/branches",
        headers=DEFAULT_HEADERS,
        json={
            "name": "alternative",
            "purpose": "Try an alternative paper spine.",
            "parent_branch_id": primary_id,
            "created_by": "pi",
            "reason": "Compare without overwriting primary.",
        },
    )
    assert forked.status_code == 201
    fork_id = forked.json()["branch"]["id"]
    compared = await planning_client.get(
        "/api/planning/branches/compare",
        headers=DEFAULT_HEADERS,
        params={"base_branch_id": primary_id, "other_branch_id": fork_id},
    )
    assert compared.status_code == 200
    assert compared.json()["summary"]["unchanged"] == 1

    resumed = await planning_client.get("/api/planning/resume", headers=DEFAULT_HEADERS)
    assert resumed.status_code == 200
    assert resumed.json()["branch"]["id"] == primary_id
    versions = await planning_client.get(
        f"/api/planning/artifacts/{artifact_id}/versions",
        headers=DEFAULT_HEADERS,
    )
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [1]

    foreign = await planning_client.get(
        f"/api/planning/branches/{primary_id}",
        headers=OTHER_HEADERS,
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_planning_api_rejects_untyped_stage_payload(
    planning_client: httpx.AsyncClient,
) -> None:
    created = await planning_client.post(
        "/api/planning/branches",
        headers=DEFAULT_HEADERS,
        json={
            "name": "schema",
            "purpose": "Exercise stage schemas.",
            "created_by": "pi",
            "reason": "Start schema test.",
        },
    )
    branch_id = created.json()["branch"]["id"]
    invalid = await planning_client.post(
        f"/api/planning/branches/{branch_id}/artifacts",
        headers=DEFAULT_HEADERS,
        json={
            "expected_branch_revision": 1,
            "local_key": "gap",
            "stage_type": "landscape_gap",
            "summary": "Payload lacks its required gap.",
            "payload": {"state_of_the_art": ["Prior work."]},
            "origin": "user",
            "created_by": "pi",
            "reason": "Reject unconstrained JSON.",
        },
    )
    assert invalid.status_code == 422
    assert "gap" in invalid.text


@pytest.mark.asyncio
async def test_planning_argument_workflow_route_is_project_scoped(
    planning_client: httpx.AsyncClient,
) -> None:
    created = await planning_client.post(
        "/api/planning/branches",
        headers=DEFAULT_HEADERS,
        json={
            "name": "workflow",
            "purpose": "Exercise the guided projection.",
            "created_by": "pi",
            "reason": "Start workflow projection.",
        },
    )
    branch_id = created.json()["branch"]["id"]
    appended = await planning_client.post(
        f"/api/planning/branches/{branch_id}/artifacts",
        headers=DEFAULT_HEADERS,
        json={
            "expected_branch_revision": 1,
            "local_key": "seed",
            "stage_type": "seed",
            "lifecycle": "selected",
            "summary": "A selected seed.",
            "payload": {"insight": "Treat timing as composable."},
            "origin": "user",
            "readiness_state": "ready",
            "created_by": "pi",
            "reason": "Select the seed.",
        },
    )
    assert appended.status_code == 200

    response = await planning_client.get(
        f"/api/planning/branches/{branch_id}/argument-workflow",
        headers=DEFAULT_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["stages"][0]["verdict"] == "Ready"
    assert response.json()["next_recommended_stage"] == "paragraph_spine"

    foreign = await planning_client.get(
        f"/api/planning/branches/{branch_id}/argument-workflow",
        headers=OTHER_HEADERS,
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_planning_rq_promotion_route_is_guarded_and_auditable(
    planning_client: httpx.AsyncClient,
) -> None:
    note = await planning_client.post(
        "/api/notes",
        headers=DEFAULT_HEADERS,
        json={
            "content": "Composition held under bounded jitter.",
            "type": "log",
            "source": "executor",
            "confidence": "tested",
        },
    )
    assert note.status_code == 201
    claim = await planning_client.post(
        "/api/claims",
        headers=DEFAULT_HEADERS,
        json={
            "source_entry_id": note.json()["id"],
            "claim_type": "result",
            "content": "Composition held under bounded jitter.",
            "confidence": 0.9,
            "verified": True,
            "evidence_status": "supported",
        },
    )
    assert claim.status_code == 201
    claim_id = claim.json()["id"]
    created = await planning_client.post(
        "/api/planning/branches",
        headers=DEFAULT_HEADERS,
        json={
            "name": "promotion",
            "purpose": "Exercise the explicit RQ promotion route.",
            "created_by": "pi",
            "reason": "Start a promotion-ready branch.",
        },
    )
    branch_id = created.json()["branch"]["id"]
    appended = await planning_client.post(
        f"/api/planning/branches/{branch_id}/artifacts",
        headers=DEFAULT_HEADERS,
        json={
            "expected_branch_revision": 1,
            "local_key": "portfolio",
            "stage_type": "rq_contribution",
            "lifecycle": "selected",
            "summary": "A promotion-ready portfolio.",
            "payload": {
                "research_questions": [{
                    "local_key": "rq-main",
                    "question": "When do bounded timing primitives compose?",
                    "scope": "Two-stage workflows under bounded jitter.",
                    "rationale": "Composition is the central uncertainty.",
                    "evidence_entity_ids": [claim_id],
                    "disposition": "selected",
                }],
                "contributions": [{
                    "local_key": "contribution-main",
                    "exact_wording": "We characterize bounded timing composition.",
                    "contribution_type": "theoretical",
                    "research_question_refs": ["rq-main"],
                    "allowed_wording": "Characterizes the tested boundary.",
                    "prohibited_wording": ["Guarantees universal composition."],
                    "support_ids": [claim_id],
                    "disposition": "selected",
                }],
            },
            "origin": "user",
            "readiness_state": "ready",
            "created_by": "pi",
            "reason": "Select exact candidates.",
            "evidence_bindings": [
                {"entity_type": "claim", "entity_id": claim_id, "role": "support"}
            ],
        },
    )
    assert appended.status_code == 200
    artifact = appended.json()["effective_artifacts"][0]
    promoted = await planning_client.post(
        f"/api/planning/branches/{branch_id}/promote-rq",
        headers=DEFAULT_HEADERS,
        json={
            "expected_branch_revision": 2,
            "artifact_id": artifact["id"],
            "expected_artifact_version": 1,
            "candidate_key": "rq-main",
            "phase": "paper_framing",
            "reason": "PI selected the bounded research question.",
        },
    )
    assert promoted.status_code == 201
    assert promoted.json()["decision"]["kind"] == "research_question"
    events = await planning_client.get(
        f"/api/planning/branches/{branch_id}/promotions",
        headers=DEFAULT_HEADERS,
    )
    assert events.status_code == 200
    assert [item["action"] for item in events.json()] == ["rq_promoted"]
    foreign = await planning_client.get(
        f"/api/planning/branches/{branch_id}/promotions",
        headers=OTHER_HEADERS,
    )
    assert foreign.status_code == 404
