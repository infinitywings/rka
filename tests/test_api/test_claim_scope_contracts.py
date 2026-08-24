"""REST contracts for canonical claim-scope history and review."""

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
        db_path=Path("claim-scopes.db"),
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
            # Scoped endpoints no longer fall back to a default project.
            headers={"X-RKA-Project": "proj_default"},
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


async def _claim(client: httpx.AsyncClient) -> dict:
    note = await client.post(
        "/api/notes",
        json={"content": "Delay was 42 ms.", "source": "executor"},
    )
    assert note.status_code == 201
    response = await client.post(
        "/api/claims",
        json={
            "source_entry_id": note.json()["id"],
            "claim_type": "result",
            "content": "Delay was 42 ms.",
            "verified": True,
            "evidence_status": "supported",
        },
    )
    assert response.status_code == 201
    return response.json()


def _scope(expected_revision: int) -> dict:
    return {
        "expected_revision": expected_revision,
        "actor": "web_ui",
        "reason": "Reviewed exact DelaySteer boundary.",
        "conditions": [
            {
                "kind": "environment",
                "key": "testbed",
                "operator": "equals",
                "value": "isolated local testbed",
            }
        ],
        "uncertainty": "low",
        "extension_policy": "exact_only",
        "prohibited_extensions": ["Do not generalize to remote deployments."],
        "falsifier_status": "applicable",
        "falsifier": "Repeated runs do not reproduce the direction.",
        "review_status": "reviewed",
    }


@pytest.mark.asyncio
async def test_scope_api_is_revision_guarded_and_visible_on_claim(api_client) -> None:
    claim = await _claim(api_client)
    assert claim["scope_readiness"] == "missing"

    initial = await api_client.get(f"/api/claims/{claim['id']}/scope")
    assert initial.status_code == 200
    assert initial.json()["current_revision"] == 0

    appended = await api_client.post(
        f"/api/claims/{claim['id']}/scope",
        json=_scope(0),
    )
    assert appended.status_code == 200, appended.text
    assert appended.json()["scope_readiness"] == "ready"
    assert appended.json()["current"]["id"].startswith("csc_")

    stale = await api_client.post(
        f"/api/claims/{claim['id']}/scope",
        json=_scope(0),
    )
    assert stale.status_code == 409

    refreshed = await api_client.get(f"/api/claims/{claim['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["scope_revision"] == 1
    assert refreshed.json()["scope_readiness"] == "ready"


@pytest.mark.asyncio
async def test_scope_api_rejects_unreviewable_contract(api_client) -> None:
    claim = await _claim(api_client)
    response = await api_client.post(
        f"/api/claims/{claim['id']}/scope",
        json={
            "expected_revision": 0,
            "actor": "web_ui",
            "reason": "Missing semantic boundaries.",
            "review_status": "reviewed",
        },
    )
    assert response.status_code == 422
