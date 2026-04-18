"""API tests for the calibration_outcomes endpoints (Mission 1B-iii)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


HEADERS = {"X-RKA-Project": "proj_default"}


def _option_payload(label: str, conf: float, seed: int) -> dict:
    return {
        "label": label,
        "summary": f"{label} summary",
        "justification": f"{label} reason",
        "explanation": f"{label} explanation",
        "pros": ["p1", "p2", "p3"],
        "cons": ["c1", "c2", "steel"],
        "evidence": [],
        "confidence_verbal": "moderate",
        "confidence_numeric": conf,
        "confidence_evidence_strength": "moderate",
        "confidence_known_unknowns": ["u1"],
        "effort_time": "M",
        "effort_reversibility": "reversible",
        "presentation_order_seed": seed,
    }


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("calibration_routes.db"),
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


async def _resolved_decision(client: httpx.AsyncClient, question: str = "Q?") -> str:
    """Create a decision with a recommended option + recorded PI selection."""
    r = await client.post(
        "/api/decisions",
        json={"question": question, "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    dec_id = r.json()["id"]
    opt = await client.post(
        f"/api/decisions/{dec_id}/options",
        json=_option_payload("A", 0.7, 1),
        headers=HEADERS,
    )
    opt_id = opt.json()["id"]
    await client.put(f"/api/decision_options/{opt_id}/recommend", headers=HEADERS)
    await client.put(
        f"/api/decisions/{dec_id}/pi_selection",
        json={"selected_option_id": opt_id, "override_rationale": None},
        headers=HEADERS,
    )
    return dec_id


@pytest.mark.asyncio
async def test_post_outcome_happy_path(api_client: httpx.AsyncClient):
    dec_id = await _resolved_decision(api_client)
    r = await api_client.post(
        f"/api/decisions/{dec_id}/outcomes",
        json={"outcome": "succeeded"},
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"].startswith("cao_")
    assert body["outcome"] == "succeeded"
    assert body["recorded_by"] == "pi"


@pytest.mark.asyncio
async def test_post_outcome_refused_when_no_pi_selection(api_client: httpx.AsyncClient):
    r = await api_client.post(
        "/api/decisions",
        json={"question": "open Q", "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    open_dec = r.json()["id"]
    r = await api_client.post(
        f"/api/decisions/{open_dec}/outcomes",
        json={"outcome": "succeeded"},
        headers=HEADERS,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_outcomes_for_decision(api_client: httpx.AsyncClient):
    dec_id = await _resolved_decision(api_client)
    await api_client.post(
        f"/api/decisions/{dec_id}/outcomes",
        json={"outcome": "succeeded"},
        headers=HEADERS,
    )
    await api_client.post(
        f"/api/decisions/{dec_id}/outcomes",
        json={"outcome": "failed", "outcome_details": "rolled back"},
        headers=HEADERS,
    )
    r = await api_client.get(f"/api/decisions/{dec_id}/outcomes", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {row["outcome"] for row in rows} == {"succeeded", "failed"}


@pytest.mark.asyncio
async def test_get_calibration_outcomes_filter_by_outcome(api_client: httpx.AsyncClient):
    dec_id = await _resolved_decision(api_client, "Q1")
    dec2 = await _resolved_decision(api_client, "Q2")
    await api_client.post(f"/api/decisions/{dec_id}/outcomes", json={"outcome": "succeeded"}, headers=HEADERS)
    await api_client.post(f"/api/decisions/{dec2}/outcomes", json={"outcome": "failed"}, headers=HEADERS)
    r = await api_client.get("/api/calibration/outcomes?outcome=succeeded", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "succeeded"


@pytest.mark.asyncio
async def test_get_calibration_outcomes_filter_by_since(api_client: httpx.AsyncClient):
    dec_id = await _resolved_decision(api_client)
    await api_client.post(f"/api/decisions/{dec_id}/outcomes", json={"outcome": "succeeded"}, headers=HEADERS)
    # Future timestamp filters out everything.
    r = await api_client.get(
        "/api/calibration/outcomes?since=2099-01-01T00:00:00Z",
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_calibration_metrics_warning_when_n_below_threshold(api_client: httpx.AsyncClient):
    dec_id = await _resolved_decision(api_client)
    await api_client.post(f"/api/decisions/{dec_id}/outcomes", json={"outcome": "succeeded"}, headers=HEADERS)
    r = await api_client.get("/api/calibration/metrics", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == 1
    assert body["metrics_available"] is False
    assert "Need" in body["warning"]
    assert body["brier_score"] is None
    assert body["ece"] is None
