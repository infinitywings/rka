"""API regressions for research-map detail and large journal payloads."""

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
        db_path=Path("api.db"),
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


@pytest.mark.asyncio
async def test_large_note_round_trips_exact_content(api_client: httpx.AsyncClient):
    large_content = " ".join(f"note_token_{i}" for i in range(2200))

    create_response = await api_client.post(
        "/api/notes",
        json={
            "content": large_content,
            "type": "note",
            "source": "executor",
        },
    )

    assert create_response.status_code == 201
    note_id = create_response.json()["id"]

    get_response = await api_client.get(f"/api/notes/{note_id}")
    assert get_response.status_code == 200
    assert get_response.json()["content"] == large_content


@pytest.mark.asyncio
async def test_ingest_document_without_heading_split_preserves_large_body(api_client: httpx.AsyncClient):
    document = "\n\n".join(
        " ".join(f"doc_{section}_{word}" for word in range(300))
        for section in range(10)
    )

    ingest_response = await api_client.post(
        "/api/ingest/document",
        json={
            "content": document,
            "source": "brain",
            "default_type": "note",
            "split_by_headings": False,
        },
    )

    assert ingest_response.status_code == 200
    body = ingest_response.json()
    assert body["errors"] == []
    assert body["total_sections"] == 1
    assert len(body["created"]) == 1

    entry_id = body["created"][0]["id"]
    get_response = await api_client.get(f"/api/notes/{entry_id}")
    assert get_response.status_code == 200
    assert get_response.json()["content"] == document


@pytest.mark.asyncio
async def test_cluster_detail_includes_claims_contradictions_and_review_items(
    api_client: httpx.AsyncClient,
):
    note_response = await api_client.post(
        "/api/notes",
        json={
            "content": "Metric A improves while manual evaluation regresses.",
            "type": "note",
            "source": "executor",
        },
    )
    assert note_response.status_code == 201
    note_id = note_response.json()["id"]

    rq_response = await api_client.post(
        "/api/decisions",
        json={
            "question": "Should we trust the proxy metric?",
            "phase": "design",
            "decided_by": "brain",
            "kind": "research_question",
            "status": "active",
        },
    )
    assert rq_response.status_code == 201
    rq_id = rq_response.json()["id"]

    cluster_response = await api_client.post(
        "/api/clusters",
        json={
            "label": "Proxy metric reliability",
            "research_question_id": rq_id,
            "confidence": "emerging",
        },
    )
    assert cluster_response.status_code == 201
    cluster_id = cluster_response.json()["id"]

    claim_one = await api_client.post(
        "/api/claims",
        json={
            "source_entry_id": note_id,
            "claim_type": "evidence",
            "content": "Metric A increased by 8 points.",
            "confidence": 0.9,
            "verified": True,
        },
    )
    claim_two = await api_client.post(
        "/api/claims",
        json={
            "source_entry_id": note_id,
            "claim_type": "result",
            "content": "Manual evaluation dropped by 5 points.",
            "confidence": 0.85,
            "verified": True,
        },
    )
    assert claim_one.status_code == 201
    assert claim_two.status_code == 201
    claim_one_id = claim_one.json()["id"]
    claim_two_id = claim_two.json()["id"]

    for source_claim_id in (claim_one_id, claim_two_id):
        edge_response = await api_client.post(
            "/api/claims/edges",
            json={
                "source_claim_id": source_claim_id,
                "cluster_id": cluster_id,
                "relation": "member_of",
                "confidence": 1.0,
            },
        )
        assert edge_response.status_code == 201

    contradiction_response = await api_client.post(
        "/api/claims/edges",
        json={
            "source_claim_id": claim_one_id,
            "target_claim_id": claim_two_id,
            "cluster_id": cluster_id,
            "relation": "contradicts",
            "confidence": 0.92,
        },
    )
    assert contradiction_response.status_code == 201

    review_response = await api_client.post(
        "/api/review-queue",
        json={
            "item_type": "cluster",
            "item_id": cluster_id,
            "flag": "potential_contradiction",
            "context": {
                "claim_count": 2,
                "contradictions": ["metric trend conflicts with manual evaluation"],
            },
            "priority": 70,
            "raised_by": "system",
        },
    )
    assert review_response.status_code == 201

    detail_response = await api_client.get(f"/api/research-map/cluster/{cluster_id}")
    assert detail_response.status_code == 200

    detail = detail_response.json()
    assert detail["id"] == cluster_id
    assert detail["research_question"] == {
        "id": rq_id,
        "question": "Should we trust the proxy metric?",
    }
    assert {claim["id"] for claim in detail["claims"]} == {claim_one_id, claim_two_id}
    assert len(detail["contradictions"]) == 1
    assert detail["contradictions"][0]["source_claim_id"] == claim_one_id
    assert detail["contradictions"][0]["target_claim_id"] == claim_two_id
    assert detail["review_items"][0]["flag"] == "potential_contradiction"
