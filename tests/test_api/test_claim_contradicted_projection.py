"""REST claim responses expose server-derived contradiction state."""

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
        db_path=Path("claim-contradiction.db"),
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
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


async def _create_claim(client: httpx.AsyncClient, content: str) -> dict:
    note = await client.post(
        "/api/notes",
        json={"content": content, "type": "note", "source": "executor"},
    )
    assert note.status_code == 201
    claim = await client.post(
        "/api/claims",
        json={
            "source_entry_id": note.json()["id"],
            "claim_type": "result",
            "content": content,
        },
    )
    assert claim.status_code == 201
    return claim.json()


@pytest.mark.asyncio
async def test_api_get_and_cluster_list_expose_contradicted_boolean(api_client) -> None:
    source = await _create_claim(api_client, "Primary result.")
    target = await _create_claim(api_client, "Conflicting result.")
    assert source["contradicted"] is False
    assert target["contradicted"] is False

    cluster_response = await api_client.post(
        "/api/clusters", json={"label": "Conflicting evidence"}
    )
    assert cluster_response.status_code == 201
    cluster_id = cluster_response.json()["id"]
    membership = await api_client.post(
        "/api/claims/edges",
        json={
            "source_claim_id": target["id"],
            "cluster_id": cluster_id,
            "relation": "member_of",
        },
    )
    assert membership.status_code == 201
    contradiction = await api_client.post(
        "/api/claims/edges",
        json={
            "source_claim_id": source["id"],
            "target_claim_id": target["id"],
            "relation": "contradicts",
        },
    )
    assert contradiction.status_code == 201

    for claim_id in (source["id"], target["id"]):
        response = await api_client.get(f"/api/claims/{claim_id}")
        assert response.status_code == 200
        assert response.json()["contradicted"] is True

    listed = await api_client.get("/api/claims", params={"cluster_id": cluster_id})
    assert listed.status_code == 200
    assert [(claim["id"], claim["contradicted"]) for claim in listed.json()] == [
        (target["id"], True)
    ]
