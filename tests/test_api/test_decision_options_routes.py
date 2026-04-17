"""API tests for the decision_options endpoints (migration 017 substrate)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


PROJECT_ID = "proj_default"
HEADERS = {"X-RKA-Project": PROJECT_ID}


def _option_payload(
    *,
    label: str = "Option A",
    seed: int = 1,
    confidence: float = 0.7,
) -> dict:
    return {
        "label": label,
        "summary": f"{label} short summary",
        "justification": f"{label} is on the slate because …",
        "expert_archetype": "pragmatic incrementalist",
        "explanation": f"{label} full reasoning.",
        "pros": ["p1", "p2", "p3"],
        "cons": ["c1", "c2", "c3 (steelman)"],
        "evidence": [{"claim_id": "clm_x", "strength_tier": "moderate"}],
        "confidence_verbal": "moderate",
        "confidence_numeric": confidence,
        "confidence_evidence_strength": "moderate",
        "confidence_known_unknowns": ["u1"],
        "effort_time": "M",
        "effort_cost": None,
        "effort_reversibility": "reversible",
        "presentation_order_seed": seed,
    }


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("decision_options_routes.db"),
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


@pytest_asyncio.fixture
async def decision_id(api_client: httpx.AsyncClient) -> str:
    r = await api_client.post(
        "/api/decisions",
        json={"question": "Pick one", "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ---------------------------------------------------------------- POST create


@pytest.mark.asyncio
async def test_create_option_happy_path(api_client: httpx.AsyncClient, decision_id: str):
    r = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(),
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["id"].startswith("dop_")
    assert data["decision_id"] == decision_id
    assert data["is_recommended"] is False


@pytest.mark.asyncio
async def test_create_option_unknown_project_404(
    api_client: httpx.AsyncClient, decision_id: str,
):
    """Explicit unknown project_id surfaces as 404 via require_project."""
    r = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(),
        headers={"X-RKA-Project": "prj_definitely_missing"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_option_pydantic_422(
    api_client: httpx.AsyncClient, decision_id: str,
):
    bad = _option_payload()
    bad["pros"] = ["only two", "items"]  # violates length=3 CHECK
    r = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=bad,
        headers=HEADERS,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- POST bulk


@pytest.mark.asyncio
async def test_bulk_create_returns_ordered_list(
    api_client: httpx.AsyncClient, decision_id: str,
):
    payload = [
        _option_payload(label="C", seed=30),
        _option_payload(label="A", seed=10),
        _option_payload(label="B", seed=20),
    ]
    r = await api_client.post(
        f"/api/decisions/{decision_id}/options/bulk",
        json=payload,
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    assert [o["label"] for o in r.json()] == ["C", "A", "B"]  # preserves input order


@pytest.mark.asyncio
async def test_bulk_create_unknown_decision_400(api_client: httpx.AsyncClient):
    r = await api_client.post(
        "/api/decisions/dec_missing/options/bulk",
        json=[_option_payload()],
        headers=HEADERS,
    )
    assert r.status_code == 404


# --------------------------------------------------------------------- GET list


@pytest.mark.asyncio
async def test_list_returns_by_seed(api_client: httpx.AsyncClient, decision_id: str):
    await api_client.post(
        f"/api/decisions/{decision_id}/options/bulk",
        json=[
            _option_payload(label="C", seed=30),
            _option_payload(label="A", seed=10),
            _option_payload(label="B", seed=20),
        ],
        headers=HEADERS,
    )
    r = await api_client.get(f"/api/decisions/{decision_id}/options", headers=HEADERS)
    assert r.status_code == 200
    assert [o["label"] for o in r.json()] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_list_empty_when_no_options(
    api_client: httpx.AsyncClient, decision_id: str,
):
    r = await api_client.get(f"/api/decisions/{decision_id}/options", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


# ----------------------------------------------------------------- GET single


@pytest.mark.asyncio
async def test_get_single_roundtrip(api_client: httpx.AsyncClient, decision_id: str):
    created = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="X"),
        headers=HEADERS,
    )
    opt_id = created.json()["id"]
    r = await api_client.get(f"/api/decision_options/{opt_id}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["label"] == "X"


@pytest.mark.asyncio
async def test_get_single_404(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/decision_options/dop_missing", headers=HEADERS)
    assert r.status_code == 404


# --------------------------------------------------------- PUT dominated_by


@pytest.mark.asyncio
async def test_dominated_by_set_and_clear(
    api_client: httpx.AsyncClient, decision_id: str,
):
    a = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="A", seed=1),
        headers=HEADERS,
    )
    b = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="B", seed=2),
        headers=HEADERS,
    )
    # A dominated by B.
    r = await api_client.put(
        f"/api/decision_options/{a.json()['id']}/dominated_by",
        json={"dominator_id": b.json()["id"]},
        headers=HEADERS,
    )
    assert r.status_code == 200
    refetched = await api_client.get(
        f"/api/decision_options/{a.json()['id']}", headers=HEADERS,
    )
    assert refetched.json()["dominated_by"] == b.json()["id"]


@pytest.mark.asyncio
async def test_dominated_by_self_reference_400(
    api_client: httpx.AsyncClient, decision_id: str,
):
    a = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="A"),
        headers=HEADERS,
    )
    r = await api_client.put(
        f"/api/decision_options/{a.json()['id']}/dominated_by",
        json={"dominator_id": a.json()["id"]},
        headers=HEADERS,
    )
    assert r.status_code == 400


# ----------------------------------------------------------- PUT recommend


@pytest.mark.asyncio
async def test_recommend_marks_and_clears_prior(
    api_client: httpx.AsyncClient, decision_id: str,
):
    a = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="A", seed=1),
        headers=HEADERS,
    )
    b = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="B", seed=2),
        headers=HEADERS,
    )
    r1 = await api_client.put(
        f"/api/decision_options/{a.json()['id']}/recommend", headers=HEADERS,
    )
    assert r1.status_code == 200
    r2 = await api_client.put(
        f"/api/decision_options/{b.json()['id']}/recommend", headers=HEADERS,
    )
    assert r2.status_code == 200
    # A no longer recommended.
    a_refetched = await api_client.get(
        f"/api/decision_options/{a.json()['id']}", headers=HEADERS,
    )
    assert a_refetched.json()["is_recommended"] is False
    b_refetched = await api_client.get(
        f"/api/decision_options/{b.json()['id']}", headers=HEADERS,
    )
    assert b_refetched.json()["is_recommended"] is True


@pytest.mark.asyncio
async def test_recommend_missing_option_404(api_client: httpx.AsyncClient):
    r = await api_client.put(
        "/api/decision_options/dop_missing/recommend", headers=HEADERS,
    )
    assert r.status_code == 404


# ------------------------------------------------------ PUT pi_selection


@pytest.mark.asyncio
async def test_pi_selection_selected_ok(
    api_client: httpx.AsyncClient, decision_id: str,
):
    a = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="A"),
        headers=HEADERS,
    )
    r = await api_client.put(
        f"/api/decisions/{decision_id}/pi_selection",
        json={"selected_option_id": a.json()["id"], "override_rationale": None},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_pi_selection_both_set_400(
    api_client: httpx.AsyncClient, decision_id: str,
):
    a = await api_client.post(
        f"/api/decisions/{decision_id}/options",
        json=_option_payload(label="A"),
        headers=HEADERS,
    )
    r = await api_client.put(
        f"/api/decisions/{decision_id}/pi_selection",
        json={
            "selected_option_id": a.json()["id"],
            "override_rationale": "also override",
        },
        headers=HEADERS,
    )
    assert r.status_code == 400
