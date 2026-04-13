"""API tests for Phase 3: Validation Gates."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("gates.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)

    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


async def _seed_mission(client: httpx.AsyncClient) -> dict:
    dec = await client.post("/api/decisions", json={
        "question": "Test decision for gates", "phase": "design",
        "decided_by": "brain", "kind": "research_question", "status": "active",
    })
    assert dec.status_code == 201
    mission = await client.post("/api/missions", json={
        "phase": "design", "objective": "Test gate mission",
        "motivated_by_decision": dec.json()["id"],
    })
    assert mission.status_code == 201
    return {"decision_id": dec.json()["id"], "mission_id": mission.json()["id"]}


@pytest.mark.asyncio
async def test_create_gate_checkpoint(api_client: httpx.AsyncClient):
    seed = await _seed_mission(api_client)

    gate_desc = json.dumps({
        "gate_type": "plan_validation",
        "deliverables": ["Executor Backbrief"],
        "pass_criteria": ["Plan addresses all tasks", "Risks are acceptable"],
        "assumptions_to_verify": ["Schema doesn't need changes"],
        "status": "pending",
    })

    r = await api_client.post("/api/checkpoints", json={
        "mission_id": seed["mission_id"],
        "type": "gate",
        "description": gate_desc,
        "blocking": True,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["type"] == "gate"
    assert data["status"] == "open"


@pytest.mark.asyncio
async def test_evaluate_gate_with_go_verdict(api_client: httpx.AsyncClient):
    seed = await _seed_mission(api_client)

    # Create gate
    gate_desc = json.dumps({
        "gate_type": "evidence_review",
        "deliverables": ["Mission report"],
        "pass_criteria": ["Results consistent"],
        "assumptions_to_verify": [],
        "status": "pending",
    })
    gate = await api_client.post("/api/checkpoints", json={
        "mission_id": seed["mission_id"],
        "type": "gate",
        "description": gate_desc,
        "blocking": True,
    })
    assert gate.status_code == 201
    gate_id = gate.json()["id"]

    # Evaluate
    resolution = json.dumps({
        "verdict": "go",
        "notes": "Evidence is solid",
        "assumption_status": {},
        "evaluated_at": "2026-04-13T20:00:00Z",
    })
    r = await api_client.put(f"/api/checkpoints/{gate_id}/resolve", json={
        "resolution": resolution,
        "resolved_by": "brain",
        "rationale": "Gate verdict: go",
    })
    assert r.status_code == 200

    # Verify resolved
    chk = await api_client.get(f"/api/checkpoints/{gate_id}")
    assert chk.status_code == 200
    assert chk.json()["status"] == "resolved"


@pytest.mark.asyncio
async def test_gate_appears_in_checkpoints_list(api_client: httpx.AsyncClient):
    seed = await _seed_mission(api_client)

    gate_desc = json.dumps({
        "gate_type": "problem_framing",
        "deliverables": ["Protocol"],
        "pass_criteria": ["Question is testable"],
        "assumptions_to_verify": [],
        "status": "pending",
    })
    await api_client.post("/api/checkpoints", json={
        "mission_id": seed["mission_id"],
        "type": "gate",
        "description": gate_desc,
        "blocking": True,
    })

    r = await api_client.get("/api/checkpoints", params={"status": "open"})
    assert r.status_code == 200
    chks = r.json()
    gate_chks = [c for c in chks if c["type"] == "gate"]
    assert len(gate_chks) >= 1


@pytest.mark.asyncio
async def test_gate_metadata_roundtrips(api_client: httpx.AsyncClient):
    seed = await _seed_mission(api_client)

    meta = {
        "gate_type": "synthesis_validation",
        "deliverables": ["Draft synthesis", "Evidence map"],
        "pass_criteria": ["Each conclusion maps to evidence", "PI approves"],
        "assumptions_to_verify": ["Data is complete", "No stale evidence"],
        "status": "pending",
    }
    gate_desc = json.dumps(meta)

    gate = await api_client.post("/api/checkpoints", json={
        "mission_id": seed["mission_id"],
        "type": "gate",
        "description": gate_desc,
        "blocking": True,
    })
    assert gate.status_code == 201

    # Retrieve and verify metadata roundtrips
    chk = await api_client.get(f"/api/checkpoints/{gate.json()['id']}")
    assert chk.status_code == 200
    parsed = json.loads(chk.json()["description"])
    assert parsed["gate_type"] == "synthesis_validation"
    assert len(parsed["deliverables"]) == 2
    assert len(parsed["pass_criteria"]) == 2
    assert len(parsed["assumptions_to_verify"]) == 2
