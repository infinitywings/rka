"""REST contract for independent claim evidence assessment."""

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
        db_path=Path("claim-evidence-status.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            # Scoped endpoints no longer fall back to a default project.
            headers={"X-RKA-Project": "proj_default"},
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


async def _create_claim(client: httpx.AsyncClient) -> dict:
    note = await client.post(
        "/api/notes",
        json={"content": "Measured 42 ms.", "type": "note", "source": "executor"},
    )
    assert note.status_code == 201
    claim = await client.post(
        "/api/claims",
        json={
            "source_entry_id": note.json()["id"],
            "claim_type": "result",
            "content": "Measured 42 ms.",
            "verified": True,
        },
    )
    assert claim.status_code == 201
    return claim.json()


@pytest.mark.asyncio
async def test_claim_response_and_update_expose_evidence_status(api_client) -> None:
    created = await _create_claim(api_client)
    assert created["verified"] is True
    assert created["evidence_status"] == "unassessed"

    response = await api_client.put(
        f"/api/claims/{created['id']}",
        json={"evidence_status": "supported"},
    )
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert response.json()["evidence_status"] == "supported"

    listed = await api_client.get(
        "/api/claims", params={"evidence_status": "supported"}
    )
    assert listed.status_code == 200
    assert [claim["id"] for claim in listed.json()] == [created["id"]]


@pytest.mark.asyncio
async def test_claim_api_rejects_unknown_evidence_status(api_client) -> None:
    created = await _create_claim(api_client)
    update = await api_client.put(
        f"/api/claims/{created['id']}",
        json={"evidence_status": "verified"},
    )
    assert update.status_code == 422

    query = await api_client.get(
        "/api/claims", params={"evidence_status": "verified"}
    )
    assert query.status_code == 422
