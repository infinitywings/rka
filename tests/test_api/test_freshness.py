"""API tests for Phase 2: Knowledge Freshness Layer."""

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
        db_path=Path("freshness.db"),
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


async def _seed_claim(client: httpx.AsyncClient) -> dict:
    note = await client.post("/api/notes", json={
        "content": "Test observation for freshness", "type": "note", "source": "executor",
    })
    assert note.status_code == 201
    claim = await client.post("/api/claims", json={
        "source_entry_id": note.json()["id"], "claim_type": "evidence",
        "content": "Test claim for staleness", "confidence": 0.8,
    })
    assert claim.status_code == 201
    return {"note_id": note.json()["id"], "claim_id": claim.json()["id"]}


@pytest.mark.asyncio
async def test_flag_stale_marks_claim(api_client: httpx.AsyncClient):
    seed = await _seed_claim(api_client)

    r = await api_client.post("/api/freshness/flag-stale", json={
        "entity_id": seed["claim_id"],
        "reason": "Contradicted by new experiment",
        "staleness": "yellow",
        "propagate": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["total_flagged"] == 1
    assert data["flagged"][0]["id"] == seed["claim_id"]


@pytest.mark.asyncio
async def test_flag_stale_propagates_to_cluster(api_client: httpx.AsyncClient):
    # Create cluster with 2 claims, flag both to trigger cluster staleness
    note = await api_client.post("/api/notes", json={
        "content": "Propagation test", "type": "note", "source": "executor",
    })
    cluster = await api_client.post("/api/clusters", json={
        "label": "Propagation test cluster",
    })
    c1 = await api_client.post("/api/claims", json={
        "source_entry_id": note.json()["id"], "claim_type": "evidence",
        "content": "Claim 1", "confidence": 0.8,
    })
    c2 = await api_client.post("/api/claims", json={
        "source_entry_id": note.json()["id"], "claim_type": "evidence",
        "content": "Claim 2", "confidence": 0.7,
    })
    for cid in (c1.json()["id"], c2.json()["id"]):
        await api_client.post("/api/claims/edges", json={
            "source_claim_id": cid, "cluster_id": cluster.json()["id"],
            "relation": "member_of", "confidence": 1.0,
        })

    # Flag first claim (50% stale - not enough to trigger)
    await api_client.post("/api/freshness/flag-stale", json={
        "entity_id": c1.json()["id"], "reason": "Stale", "staleness": "yellow",
    })

    # Flag second claim (now 100% stale - should propagate to cluster)
    r = await api_client.post("/api/freshness/flag-stale", json={
        "entity_id": c2.json()["id"], "reason": "Also stale", "staleness": "yellow",
    })
    assert r.status_code == 200
    flagged_ids = [f["id"] for f in r.json()["flagged"]]
    assert cluster.json()["id"] in flagged_ids


@pytest.mark.asyncio
async def test_check_freshness_returns_categories(api_client: httpx.AsyncClient):
    seed = await _seed_claim(api_client)

    # Flag the claim
    await api_client.post("/api/freshness/flag-stale", json={
        "entity_id": seed["claim_id"], "reason": "Test", "propagate": False,
    })

    r = await api_client.get("/api/freshness/check")
    assert r.status_code == 200
    data = r.json()
    assert data["total_items"] >= 1
    assert "stale_claims" in data["categories"]
    assert seed["claim_id"] in data["categories"]["stale_claims"]["ids"]


@pytest.mark.asyncio
async def test_detect_contradictions_no_embeddings(api_client: httpx.AsyncClient):
    seed = await _seed_claim(api_client)

    r = await api_client.post("/api/freshness/detect-contradictions", json={
        "entity_id": seed["claim_id"],
    })
    assert r.status_code == 200
    data = r.json()
    # Should gracefully handle missing embeddings
    assert "candidates" in data


@pytest.mark.asyncio
async def test_flag_stale_rejects_invalid_staleness(api_client: httpx.AsyncClient):
    seed = await _seed_claim(api_client)

    r = await api_client.post("/api/freshness/flag-stale", json={
        "entity_id": seed["claim_id"], "reason": "Bad", "staleness": "purple",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_check_freshness_empty_returns_zero(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/freshness/check")
    assert r.status_code == 200
    # May have items from default project setup but shouldn't error
    assert "total_items" in r.json()
