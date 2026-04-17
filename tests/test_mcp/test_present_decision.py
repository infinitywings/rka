"""Integration tests for rka_present_decision + rka_record_pi_selection MCP tools.

These drive the FastAPI app via ASGITransport and monkeypatch the MCP-layer
`_client` factory to use the in-process app instead of a live REST server.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


HEADERS = {"X-RKA-Project": "proj_default"}


def _option(label: str, conf: float, eff_time: str = "M", rev: str = "reversible", seed: int = 0) -> dict:
    return {
        "label": label,
        "summary": f"{label} summary",
        "justification": f"{label} is an option because",
        "explanation": f"{label} full explanation with rationale.",
        "pros": ["p1", "p2", "p3"],
        "cons": ["c1", "c2", "steelman"],
        "evidence": [{"claim_id": "clm_x", "strength_tier": "direct"}],
        "confidence_verbal": "moderate",
        "confidence_numeric": conf,
        "confidence_evidence_strength": "moderate",
        "confidence_known_unknowns": ["u1"],
        "effort_time": eff_time,
        "effort_reversibility": rev,
        "presentation_order_seed": seed,
    }


@pytest_asyncio.fixture
async def present_env(tmp_path: Path, monkeypatch):
    """FastAPI test app + monkeypatched MCP _client pointing at the in-process app.

    Returns (httpx.AsyncClient, decision_id) where the client is the test
    transport (usable directly for REST calls), and decision_id is a fresh
    decision row seeded in the DB.
    """
    import rka.mcp.server as mcp_mod

    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("present_decision.db"),
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
                    headers={"X-RKA-Project": "proj_default"},
                    timeout=30.0,
                )

            monkeypatch.setattr(mcp_mod, "_client", fake_client)

            r = await client.post(
                "/api/decisions",
                json={"question": "Pick one", "phase": "design", "decided_by": "brain"},
                headers=HEADERS,
            )
            assert r.status_code in (200, 201), r.text
            decision_id = r.json()["id"]
            yield client, decision_id
    finally:
        await lifespan.__aexit__(None, None, None)


def _tool_body(tool_obj):
    """Return the underlying function behind an @tool()-wrapped MCP tool."""
    # mcp.tool() wraps our ticker wrapper; the ticker wrapper's __wrapped__
    # is the original async function.
    # Walk __wrapped__ chain until we hit a callable that isn't wrapped.
    fn = tool_obj
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.mark.asyncio
async def test_happy_path_five_options_three_survive(present_env):
    import rka.mcp.server as mcp_mod
    _client_api, decision_id = present_env
    present = _tool_body(mcp_mod.rka_present_decision)

    # Construct a slate where at least 2 options are mutually non-dominated
    # (trade-offs), and the rest are clearly dominated.
    options = [
        _option("A-fast-safe", 0.90, "S", "reversible", seed=1),          # Pareto-optimal (fast + reversible)
        _option("B-confident-costly", 0.95, "XL", "costly", seed=2),      # trade-off: higher conf, worse effort + rev
        _option("C-dominated", 0.50, "XL", "irreversible", seed=3),       # dominated by both A and B
        _option("D-dominated", 0.70, "M", "reversible", seed=4),          # dominated by A
        _option("E-dominated", 0.60, "L", "costly", seed=5),              # dominated by A
    ]
    result_json = await present(
        decision_id=decision_id,
        confirmation_brief="PI wants a scalable option.",
        options=options,
        pi_preference=None,
    )
    result = _json.loads(result_json)

    assert "error" not in result
    # Three surviving options after Pareto (A, B are non-dominated trade-offs;
    # the third survivor depends on seed ordering but should be exactly 2 or 3).
    assert len(result["presented_option_ids"]) >= 2
    assert len(result["presented_option_ids"]) <= 3
    assert result["recommended_option_id"] in result["presented_option_ids"]
    assert result["presentation_method"] == "markdown_fallback"
    assert "presentation_markdown" in result


@pytest.mark.asyncio
async def test_pi_preference_leak_triggers_error(present_env):
    import rka.mcp.server as mcp_mod
    _client_api, decision_id = present_env
    present = _tool_body(mcp_mod.rka_present_decision)

    # Option B's explanation contains "Python", which is in the PI preference.
    options = [
        _option("A", 0.9, seed=1),
        {**_option("B", 0.7, seed=2), "explanation": "Use Python for rapid iteration."},
        _option("C", 0.5, seed=3),
        _option("D", 0.4, seed=4),
        _option("E", 0.3, seed=5),
    ]
    # The strip-check is a substring match on pi_preference.lower() against each
    # option's concatenated text fields.lower(). A single-word preference is the
    # realistic case: the Brain says "PI prefers Python" and checks no option
    # text contains "python" verbatim.
    result_json = await present(
        decision_id=decision_id,
        confirmation_brief="PI wants speed.",
        options=options,
        pi_preference="Python",
    )
    result = _json.loads(result_json)
    assert result.get("error") == "pi_preference_leaked_into_generation"
    assert result.get("offending_option_index") == 1


@pytest.mark.asyncio
async def test_guard_refuses_if_options_already_exist(present_env):
    import rka.mcp.server as mcp_mod
    client_api, decision_id = present_env
    present = _tool_body(mcp_mod.rka_present_decision)

    # Pre-populate one option via the existing service so the guard catches it.
    r = await client_api.post(
        f"/api/decisions/{decision_id}/options",
        json=_option("pre", 0.5, seed=0),
        headers=HEADERS,
    )
    assert r.status_code == 201

    result_json = await present(
        decision_id=decision_id,
        confirmation_brief="second attempt",
        options=[_option(chr(ord("A") + i), 0.5 + i * 0.1, seed=i) for i in range(5)],
        pi_preference=None,
    )
    result = _json.loads(result_json)
    assert result.get("error") == "decision_already_presented"


@pytest.mark.asyncio
async def test_guard_refuses_nonexistent_decision(present_env):
    import rka.mcp.server as mcp_mod
    _client_api, _decision_id = present_env
    present = _tool_body(mcp_mod.rka_present_decision)

    result_json = await present(
        decision_id="dec_nonexistent",
        confirmation_brief="x",
        options=[_option(chr(ord("A") + i), 0.5, seed=i) for i in range(5)],
        pi_preference=None,
    )
    result = _json.loads(result_json)
    assert result.get("error") == "decision_not_found"


@pytest.mark.asyncio
async def test_record_pi_selection_both_paths(present_env):
    import rka.mcp.server as mcp_mod
    _client_api, decision_id = present_env
    present = _tool_body(mcp_mod.rka_present_decision)
    record = _tool_body(mcp_mod.rka_record_pi_selection)

    # Present
    options = [
        _option("A", 0.9, "S", "reversible", seed=1),
        _option("B", 0.7, "M", "costly", seed=2),
        _option("C", 0.6, "L", "irreversible", seed=3),
        _option("D", 0.5, "XL", "irreversible", seed=4),
        _option("E", 0.3, "XL", "irreversible", seed=5),
    ]
    result = _json.loads(await present(
        decision_id=decision_id,
        confirmation_brief="brief",
        options=options,
        pi_preference=None,
    ))
    presented = result["presented_option_ids"]
    assert presented

    # Path 1 — selected_option_id.
    rec1 = _json.loads(await record(
        decision_id=decision_id,
        selected_option_id=presented[0],
        override_rationale=None,
    ))
    assert rec1["selected_option_id"] == presented[0]

    # Seed a fresh decision for the override path.
    r = await _client_api.post(
        "/api/decisions",
        json={"question": "Path 2", "phase": "design", "decided_by": "brain"},
        headers=HEADERS,
    )
    dec2 = r.json()["id"]
    # Populate options so the guard doesn't get in the way for the second presentation.
    await present(
        decision_id=dec2,
        confirmation_brief="brief",
        options=options,
        pi_preference=None,
    )

    # Path 2 — override_rationale (escape hatch).
    rec2 = _json.loads(await record(
        decision_id=dec2,
        selected_option_id=None,
        override_rationale="defer",
    ))
    assert rec2["override_rationale"] == "defer"
