"""REST contracts for reviewable Interpretation Staging."""

from __future__ import annotations

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
        db_path=Path("interpretation-staging.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


async def _create_candidate(client: httpx.AsyncClient) -> dict:
    note = await client.post(
        "/api/notes",
        json={"content": "Measured latency was 42 ms.", "source": "executor"},
    )
    assert note.status_code == 201
    response = await client.post(
        "/api/interpretations",
        json={
            "source_type": "journal",
            "source_id": note.json()["id"],
            "locator_kind": "text_offset",
            "locator_start": 0,
            "locator_end": 27,
            "statement": "Latency was 42 ms.",
            "epistemic_kind": "observation",
            "scope_conditions": ["local testbed"],
            "uncertainty": "low",
            "proposed_claim_type": "result",
            "created_by": "executor",
            "extraction_tool": "api_test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_candidate_list_detail_and_promotion_contract(api_client) -> None:
    candidate = await _create_candidate(api_client)
    listed = await api_client.get(
        "/api/interpretations", params={"review_status": "pending"}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [candidate["id"]]

    promoted = await api_client.post(
        f"/api/interpretations/{candidate['id']}/triage",
        json={
            "action": "promote",
            "expected_revision": 1,
            "actor": "web_ui",
            "reason": "Checked exact source span.",
            "grounding_verified": True,
            "claim_confidence": 0.8,
        },
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()
    assert body["active_claim_id"].startswith("clm_")
    assert body["review_events"][-1]["action"] == "promote"

    stale = await api_client.post(
        f"/api/interpretations/{candidate['id']}/triage",
        json={
            "action": "reopen",
            "expected_revision": 1,
            "actor": "web_ui",
            "reason": "stale request",
        },
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_api_rejects_invalid_locator_and_unverified_promotion(api_client) -> None:
    note = await api_client.post(
        "/api/notes",
        json={"content": "A source", "source": "executor"},
    )
    invalid = await api_client.post(
        "/api/interpretations",
        json={
            "source_type": "journal",
            "source_id": note.json()["id"],
            "locator_kind": "page",
            "statement": "Atomic statement.",
            "epistemic_kind": "reported_fact",
            "created_by": "executor",
            "extraction_tool": "api_test",
        },
    )
    assert invalid.status_code == 422

    candidate = await _create_candidate(api_client)
    unverified = await api_client.post(
        f"/api/interpretations/{candidate['id']}/triage",
        json={
            "action": "promote",
            "expected_revision": 1,
            "actor": "web_ui",
            "reason": "not actually checked",
        },
    )
    assert unverified.status_code == 422
