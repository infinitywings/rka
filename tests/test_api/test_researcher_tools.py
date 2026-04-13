"""API tests for researcher experience tools — changelog, evidence assembly, split/merge, process paper, advance RQ."""

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
        db_path=Path("researcher_tools.db"),
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


# ------------------------------------------------------------------
# Helper: seed basic data
# ------------------------------------------------------------------

async def _seed_rq_with_cluster_and_claims(client: httpx.AsyncClient):
    """Seed a research question, cluster, and two claims for testing."""
    # Note
    note = await client.post("/api/notes", json={
        "content": "Experiment showed 12% improvement with new approach.",
        "type": "note", "source": "executor",
    })
    assert note.status_code == 201
    note_id = note.json()["id"]

    # RQ
    rq = await client.post("/api/decisions", json={
        "question": "Does the new approach improve accuracy?",
        "phase": "design", "decided_by": "brain",
        "kind": "research_question", "status": "active",
    })
    assert rq.status_code == 201
    rq_id = rq.json()["id"]

    # Cluster
    cluster = await client.post("/api/clusters", json={
        "label": "Accuracy improvements",
        "research_question_id": rq_id, "confidence": "moderate",
    })
    assert cluster.status_code == 201
    cluster_id = cluster.json()["id"]

    # Claims
    claim1 = await client.post("/api/claims", json={
        "source_entry_id": note_id, "claim_type": "evidence",
        "content": "12% improvement in accuracy", "confidence": 0.85,
    })
    claim2 = await client.post("/api/claims", json={
        "source_entry_id": note_id, "claim_type": "method",
        "content": "Used cross-validation with 5 folds", "confidence": 0.9,
    })
    assert claim1.status_code == 201
    assert claim2.status_code == 201
    c1_id = claim1.json()["id"]
    c2_id = claim2.json()["id"]

    # Assign claims to cluster
    for cid in (c1_id, c2_id):
        edge = await client.post("/api/claims/edges", json={
            "source_claim_id": cid, "cluster_id": cluster_id,
            "relation": "member_of", "confidence": 1.0,
        })
        assert edge.status_code == 201

    return {
        "note_id": note_id, "rq_id": rq_id, "cluster_id": cluster_id,
        "claim_ids": [c1_id, c2_id],
    }


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_changelog_returns_created_and_modified(api_client: httpx.AsyncClient):
    await api_client.post("/api/notes", json={
        "content": "Test note", "type": "note", "source": "executor",
    })

    r = await api_client.get("/api/changelog", params={"since": "2020-01-01"})
    assert r.status_code == 200
    data = r.json()
    assert data["statistics"]["total_created"] > 0
    assert any(e["entity_type"] == "journal" for e in data["created"])


@pytest.mark.asyncio
async def test_assemble_evidence_progress_report(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    r = await api_client.get("/api/assemble-evidence", params={
        "research_question_id": seed["rq_id"], "format": "progress_report",
    })
    assert r.status_code == 200
    data = r.json()
    assert "Progress Report" in data["content"]
    assert "12% improvement" in data["content"]


@pytest.mark.asyncio
async def test_assemble_evidence_lit_review(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    r = await api_client.get("/api/assemble-evidence", params={
        "research_question_id": seed["rq_id"], "format": "lit_review",
    })
    assert r.status_code == 200
    assert "Literature Review" in r.json()["content"]


@pytest.mark.asyncio
async def test_assemble_evidence_proposal_section(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    r = await api_client.get("/api/assemble-evidence", params={
        "research_question_id": seed["rq_id"], "format": "proposal_section",
    })
    assert r.status_code == 200
    assert seed["rq_id"] is not None  # sanity check


@pytest.mark.asyncio
async def test_split_cluster_reassigns_claims(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    r = await api_client.post("/api/clusters/split", json={
        "source_id": seed["cluster_id"],
        "new_clusters": [
            {"label": "Accuracy evidence", "claim_ids": [seed["claim_ids"][0]]},
            {"label": "Methodology", "claim_ids": [seed["claim_ids"][1]]},
        ],
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["new_clusters"]) == 2
    assert data["source_remaining_claims"] == 0
    assert data["total_reassigned"] == 2


@pytest.mark.asyncio
async def test_merge_clusters_combines_claims(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    # Create a second cluster with its own claim
    note2 = await api_client.post("/api/notes", json={
        "content": "Second experiment", "type": "note", "source": "executor",
    })
    cluster2 = await api_client.post("/api/clusters", json={
        "label": "Second cluster", "research_question_id": seed["rq_id"],
    })
    claim3 = await api_client.post("/api/claims", json={
        "source_entry_id": note2.json()["id"], "claim_type": "result",
        "content": "Consistent with first experiment", "confidence": 0.7,
    })
    await api_client.post("/api/claims/edges", json={
        "source_claim_id": claim3.json()["id"],
        "cluster_id": cluster2.json()["id"],
        "relation": "member_of", "confidence": 1.0,
    })

    r = await api_client.post("/api/clusters/merge", json={
        "source_ids": [seed["cluster_id"], cluster2.json()["id"]],
        "target_label": "Combined accuracy evidence",
        "target_synthesis": "Both experiments support the new approach.",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["total_claims_moved"] == 3
    assert data["target_label"] == "Combined accuracy evidence"


@pytest.mark.asyncio
async def test_process_paper_creates_journal_and_claims(api_client: httpx.AsyncClient):
    # Create a literature entry
    lit = await api_client.post("/api/literature", json={
        "title": "Test Paper on Accuracy",
        "added_by": "brain", "status": "to_read",
    })
    assert lit.status_code == 201
    lit_id = lit.json()["id"]

    r = await api_client.post("/api/literature/process-paper", json={
        "lit_id": lit_id,
        "summary": "This paper presents accuracy improvements in NLP models.",
        "annotations": [
            {"passage": "Table 2 shows 15% improvement", "note": "Strong result",
             "claim_type": "evidence", "confidence": 0.85},
            {"passage": "Authors use BERT-large as baseline",
             "claim_type": "method", "confidence": 0.95},
            {"passage": "Hypothesis: larger models generalize better",
             "claim_type": "hypothesis", "confidence": 0.4},
        ],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["claims_created"] == 3
    assert data["journal_entry_id"].startswith("jrn_")
    assert data["literature_status"] == "reading"

    # Verify journal entry was created
    journal = await api_client.get(f"/api/notes/{data['journal_entry_id']}")
    assert journal.status_code == 200
    assert "Table 2 shows 15% improvement" in journal.json()["content"]


@pytest.mark.asyncio
async def test_advance_rq_updates_status(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    r = await api_client.post("/api/research-questions/advance", json={
        "rq_id": seed["rq_id"],
        "status": "partially_answered",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["previous_status"] == "open"
    assert data["new_status"] == "partially_answered"


@pytest.mark.asyncio
async def test_advance_rq_with_conclusion_and_evidence(api_client: httpx.AsyncClient):
    seed = await _seed_rq_with_cluster_and_claims(api_client)

    r = await api_client.post("/api/research-questions/advance", json={
        "rq_id": seed["rq_id"],
        "status": "answered",
        "conclusion": "Yes, the new approach improves accuracy by 12% on average.",
        "evidence_cluster_ids": [seed["cluster_id"]],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["new_status"] == "answered"
    assert data["conclusion_entry_id"] is not None
    assert data["evidence_clusters_linked"] == 1


@pytest.mark.asyncio
async def test_advance_rq_rejects_non_rq_decision(api_client: httpx.AsyncClient):
    dec = await api_client.post("/api/decisions", json={
        "question": "Use PostgreSQL?", "phase": "design",
        "decided_by": "brain", "kind": "design_choice", "status": "active",
    })
    assert dec.status_code == 201

    r = await api_client.post("/api/research-questions/advance", json={
        "rq_id": dec.json()["id"], "status": "answered",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_changelog_empty_range_returns_empty(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/changelog", params={"since": "2099-01-01"})
    assert r.status_code == 200
    data = r.json()
    assert data["statistics"]["total_created"] == 0
    assert data["statistics"]["total_modified"] == 0
