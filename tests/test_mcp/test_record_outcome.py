"""MCP-tool tests for rka_record_outcome."""

from __future__ import annotations

import json as _json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


HEADERS = {"X-RKA-Project": "proj_default"}


def _option_payload(label: str = "A", conf: float = 0.7, seed: int = 1) -> dict:
    return {
        "label": label,
        "summary": f"{label} sum",
        "justification": f"{label} just",
        "explanation": f"{label} expl",
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
async def env(tmp_path: Path, monkeypatch):
    """ASGI-wired test app + monkeypatched MCP _client."""
    import rka.mcp.server as mcp_mod

    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("record_outcome.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            mcp_mod._session.project_id = "proj_default"

            def fake_client() -> httpx.AsyncClient:
                return httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                    headers=HEADERS,
                    timeout=30.0,
                )

            monkeypatch.setattr(mcp_mod, "_client", fake_client)
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


def _tool_body(tool_obj):
    fn = tool_obj
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


async def _resolved_decision(client: httpx.AsyncClient) -> str:
    r = await client.post(
        "/api/decisions",
        json={"question": "Q?", "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    dec = r.json()["id"]
    opt = await client.post(f"/api/decisions/{dec}/options", json=_option_payload(), headers=HEADERS)
    opt_id = opt.json()["id"]
    await client.put(f"/api/decision_options/{opt_id}/recommend", headers=HEADERS)
    await client.put(
        f"/api/decisions/{dec}/pi_selection",
        json={"selected_option_id": opt_id, "override_rationale": None},
        headers=HEADERS,
    )
    return dec


@pytest.mark.asyncio
async def test_tool_happy_path(env):
    import rka.mcp.server as mcp_mod
    record = _tool_body(mcp_mod.rka_record_outcome)
    dec_id = await _resolved_decision(env)
    out = _json.loads(await record(decision_id=dec_id, outcome="succeeded"))
    assert "error" not in out
    assert out["id"].startswith("cao_")
    assert out["outcome"] == "succeeded"


@pytest.mark.asyncio
async def test_tool_refuses_decision_without_pi_selection(env):
    import rka.mcp.server as mcp_mod
    record = _tool_body(mcp_mod.rka_record_outcome)
    r = await env.post(
        "/api/decisions",
        json={"question": "open", "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    open_dec = r.json()["id"]
    out = _json.loads(await record(decision_id=open_dec, outcome="succeeded"))
    assert out.get("error") == "decision_not_resolved"


@pytest.mark.asyncio
async def test_tool_accepts_override_rationale_as_resolution(env):
    """A decision resolved via escape hatch (override_rationale set) is also
    valid for outcome recording even though no option was selected."""
    import rka.mcp.server as mcp_mod
    record = _tool_body(mcp_mod.rka_record_outcome)

    r = await env.post(
        "/api/decisions",
        json={"question": "deferred", "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    dec_id = r.json()["id"]
    # Resolve via override only (no option).
    await env.put(
        f"/api/decisions/{dec_id}/pi_selection",
        json={"selected_option_id": None, "override_rationale": "defer"},
        headers=HEADERS,
    )
    out = _json.loads(await record(
        decision_id=dec_id,
        outcome="unresolved",
        outcome_details="PI deferred — no concrete outcome yet",
    ))
    assert "error" not in out
    assert out["outcome"] == "unresolved"
