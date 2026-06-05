"""API tests for POST /api/decisions/{dec_id}/supersede (v2.7.0.5).

Regression coverage for the v2.7.0.4 bug where the MCP layer's
`rka_supersede_decision` adapter wrapped its body in
``{old_decision_id, new_decision: {...}}`` and the FastAPI route bound the
whole body to ``DecisionCreate`` (``extra='forbid'``), so every call
returned HTTP 422 before reaching the service layer.

Two coverage angles:

1. **Happy-path contract** — POST a flat ``DecisionCreate`` body and
   assert 201 + the OLD decision's status flipped to 'superseded' +
   the new decision is created with the documented fields.

2. **Reject-the-wrapped-envelope regression** — POST the OLD broken
   wrapped envelope and assert 422 with ``extra_forbidden`` /
   ``missing`` error classes. This locks the contract — re-introducing
   the wrap regresses this test before the symptom reaches users.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


PROJECT_ID = "proj_default"
HEADERS = {"X-RKA-Project": PROJECT_ID}


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("decisions_supersede_routes.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest_asyncio.fixture
async def old_decision_id(api_client: httpx.AsyncClient) -> str:
    """Seed a journal + decision to supersede later."""
    # Provenance-bearing journal entry (decisions require non-empty
    # related_journal at the typed-args boundary; the REST route doesn't
    # enforce non-empty, but supplying one mirrors realistic use).
    jrn = await api_client.post(
        "/api/notes",
        json={
            "content": "Initial framing of the question.",
            "type": "note",
            "source": "brain",
        },
        headers=HEADERS,
    )
    assert jrn.status_code in (200, 201), jrn.text
    jrn_id = jrn.json()["id"]

    r = await api_client.post(
        "/api/decisions",
        json={
            "question": "Should we use Option A?",
            "phase": "design",
            "decided_by": "brain",
            "chosen": "yes",
            "rationale": "initial choice",
            "related_journal": [jrn_id],
        },
        headers=HEADERS,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ---------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_supersede_with_flat_decision_create_body_returns_201(
    api_client: httpx.AsyncClient, old_decision_id: str
):
    """v2.7.0.5 contract — POST a flat DecisionCreate body, expect 201."""
    new_jrn = await api_client.post(
        "/api/notes",
        json={
            "content": "New evidence reverses the framing.",
            "type": "finding",
            "source": "brain",
        },
        headers=HEADERS,
    )
    new_jrn_id = new_jrn.json()["id"]

    r = await api_client.post(
        f"/api/decisions/{old_decision_id}/supersede",
        json={
            "question": "Reframed: should we use Option B?",
            "phase": "design",
            "decided_by": "brain",
            "chosen": "Option B",
            "rationale": "New evidence dec_old was wrong; switching.",
            "related_journal": [new_jrn_id],
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    assert new_id.startswith("dec_")
    assert new_id != old_decision_id


@pytest.mark.asyncio
async def test_supersede_flips_old_status_and_sets_superseded_by(
    api_client: httpx.AsyncClient, old_decision_id: str
):
    """The atomic supersede flips old.status='superseded' AND sets
    old.superseded_by=<new_id>. The cockpit workaround (record new +
    update old status only) leaks the FK; this test guards the FK."""
    new_jrn = await api_client.post(
        "/api/notes",
        json={"content": "newer evidence", "type": "note", "source": "brain"},
        headers=HEADERS,
    )
    new_jrn_id = new_jrn.json()["id"]

    r = await api_client.post(
        f"/api/decisions/{old_decision_id}/supersede",
        json={
            "question": "Reframed",
            "phase": "design",
            "decided_by": "brain",
            "chosen": "Option B",
            "rationale": "switching",
            "related_journal": [new_jrn_id],
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    old = await api_client.get(f"/api/decisions/{old_decision_id}", headers=HEADERS)
    assert old.status_code == 200
    body = old.json()
    assert body["status"] == "superseded"
    assert body.get("superseded_by") == new_id, (
        f"old.superseded_by should be {new_id}, got {body.get('superseded_by')}. "
        "The cockpit-workaround (status flip only, no FK) leaks this signal."
    )


# ---------------------------------------------------------------- regression


@pytest.mark.asyncio
async def test_supersede_rejects_wrapped_envelope_with_422(
    api_client: httpx.AsyncClient, old_decision_id: str
):
    """REGRESSION LOCK for the v2.7.0.4 bug.

    The MCP adapter previously wrapped its body in
    ``{old_decision_id, new_decision: {...}}``. The REST route binds the
    whole body to DecisionCreate(extra='forbid'), so this shape MUST
    return 422. If a future change makes the route lenient about wrapped
    envelopes, this test fails — and the test should be re-evaluated
    rather than silently dropped, because the MCP adapter is the
    canonical client and lenience here would mask future drift.
    """
    new_jrn = await api_client.post(
        "/api/notes",
        json={"content": "x", "type": "note", "source": "brain"},
        headers=HEADERS,
    )
    new_jrn_id = new_jrn.json()["id"]

    wrapped = {
        "old_decision_id": old_decision_id,
        "new_decision": {
            "question": "Q",
            "phase": "design",
            "decided_by": "brain",
            "chosen": "X",
            "rationale": "R",
            "related_journal": [new_jrn_id],
        },
    }
    r = await api_client.post(
        f"/api/decisions/{old_decision_id}/supersede",
        json=wrapped,
        headers=HEADERS,
    )
    assert r.status_code == 422, r.text
    # The 422 detail should mention both classes of failure: the
    # unexpected top-level keys AND the missing required fields.
    detail_text = r.text.lower()
    assert "extra_forbidden" in detail_text or "extra forbidden" in detail_text, (
        f"expected extra_forbidden in 422 detail, got: {detail_text[:600]}"
    )
    # Required top-level fields that the wrapper hid behind 'new_decision':
    # at least one of question / decided_by / phase should be flagged.
    assert any(
        f in detail_text for f in ("question", "decided_by", "phase")
    ), f"expected missing-required-field message; got: {detail_text[:600]}"


@pytest.mark.asyncio
async def test_supersede_accepts_empty_phase_and_inherits(
    api_client: httpx.AsyncClient, old_decision_id: str
):
    """v2.7.0.6 — POST without `phase` returns 201 (not 422). The new
    decision inherits the OLD decision's phase ('design')."""
    new_jrn = await api_client.post(
        "/api/notes",
        json={"content": "evidence", "type": "note", "source": "brain"},
        headers=HEADERS,
    )
    new_jrn_id = new_jrn.json()["id"]

    r = await api_client.post(
        f"/api/decisions/{old_decision_id}/supersede",
        json={
            "question": "Reframed (phase omitted)",
            "decided_by": "brain",
            "chosen": "B",
            "rationale": "new evidence",
            "related_journal": [new_jrn_id],
            # phase intentionally omitted — DecisionSupersedeBody allows.
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["phase"] == "design", (
        f"new decision should inherit phase='design' from old; got {body['phase']!r}"
    )


@pytest.mark.asyncio
async def test_plain_decision_create_still_requires_phase(
    api_client: httpx.AsyncClient
):
    """Regression guard: POST /api/decisions (plain create, NOT supersede)
    still requires phase. DecisionCreate(extra='forbid') with required
    phase: str — should remain 422 on missing phase. Pins the
    supersede-vs-plain boundary so the v2.7.0.6 DecisionSupersedeBody
    relaxation doesn't leak into the plain-create path."""
    jrn = await api_client.post(
        "/api/notes",
        json={"content": "x", "type": "note", "source": "brain"},
        headers=HEADERS,
    )
    jrn_id = jrn.json()["id"]

    r = await api_client.post(
        "/api/decisions",
        json={
            "question": "Q?",
            "decided_by": "brain",
            "chosen": "A",
            "rationale": "r",
            "related_journal": [jrn_id],
            # phase intentionally omitted — DecisionCreate must reject.
        },
        headers=HEADERS,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_supersede_forwards_provenance_fields(
    api_client: httpx.AsyncClient, old_decision_id: str
):
    """Optional provenance fields (related_literature, parent_id, tags,
    options, assumptions) must round-trip through the supersede route.
    Prior versions silently dropped these on the supersede path, leaving
    the replacement decision provenance-orphaned even after the wire
    fix landed."""
    new_jrn = await api_client.post(
        "/api/notes",
        json={"content": "y", "type": "note", "source": "brain"},
        headers=HEADERS,
    )
    new_jrn_id = new_jrn.json()["id"]

    r = await api_client.post(
        f"/api/decisions/{old_decision_id}/supersede",
        json={
            "question": "Reframed with full provenance",
            "phase": "design",
            "decided_by": "brain",
            "chosen": "Option B",
            "rationale": "switching",
            "related_journal": [new_jrn_id],
            "tags": ["v2-supersede-test", "provenance-roundtrip"],
            "assumptions": ["A1", "A2"],
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "v2-supersede-test" in (body.get("tags") or []), body
