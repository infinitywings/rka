"""Tests for POST /api/graph/multi-hop request validation.

Mission v2.5.1-D1 (mis_01KRRM8CJP34KTN8KJMZQH2PFP /
dec_01KRRM5WKSSX7C3ZXZME0BMVQ9): the v2.4-era schema required
``query: str`` with no default, which rejected the seeds-only
invocation Eval-v2's runner emitted. v2.5.1 makes ``query`` optional
when ``seeds`` is provided; neither-set returns 422 with the
Affordance-G structured body.

Locked states:
  - seeds-only body → 200 (NEW v2.5.1 capability)
  - query-only body → 200 (existing behavior; regression-lock)
  - neither-provided body → 422 with {error, detail, hint} shape
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    """API client backed by a fresh tmp DB.

    embeddings + LLM disabled — multi-hop doesn't need them; the search
    step is bypassed entirely on seeds-only invocations, so SearchService
    isn't exercised here. For query-only invocations the empty seed set
    falls through cleanly without crashing.
    """
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("graph_route.db"),
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


# ---------------------------------------------------------------------------
# T1 regression tests — schema fix for v2.5.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_hop_seeds_only_returns_200(api_client: httpx.AsyncClient):
    """The NEW v2.5.1 capability: seeds-only body must succeed (pre-fix
    this was the body Eval-v2's runner sent and got 422 on)."""
    r = await api_client.post(
        "/api/graph/multi-hop",
        json={"seeds": ["dec_01KRPF09AP1FE1CRR6YQBY2R5F"], "max_depth": 2},
    )
    # 200 — service may legitimately return an empty subgraph if the seed
    # entity doesn't exist in the test DB (the DB is fresh). We only
    # require the request shape to be ACCEPTED.
    assert r.status_code == 200, (
        f"seeds-only body should now be accepted; got {r.status_code} body={r.text[:200]}"
    )
    body = r.json()
    # Returned shape has at least the documented keys.
    assert "nodes" in body
    assert "edges" in body


@pytest.mark.asyncio
async def test_multi_hop_query_only_returns_200(api_client: httpx.AsyncClient):
    """Pre-v2.5.1 behavior preserved: query-only body still works.

    Regression-lock so a future schema change doesn't accidentally drop
    the search-based seeding path.
    """
    r = await api_client.post(
        "/api/graph/multi-hop",
        json={"query": "decisions about agentic workflow", "max_depth": 2},
    )
    assert r.status_code == 200, (
        f"query-only body must still work post-v2.5.1; got {r.status_code} body={r.text[:200]}"
    )
    body = r.json()
    assert "nodes" in body
    assert "edges" in body


@pytest.mark.asyncio
async def test_multi_hop_neither_field_returns_422_affordance_g_shape(
    api_client: httpx.AsyncClient,
):
    """Request with neither ``query`` nor ``seeds`` is rejected with the
    Affordance-G structured body — not FastAPI's default per-field-error
    array. The route handler does the check explicitly so the message is
    actionable: tells the caller what to send next."""
    r = await api_client.post(
        "/api/graph/multi-hop",
        json={"max_depth": 2},
    )
    assert r.status_code == 422, (
        f"neither-provided body should be rejected; got {r.status_code}"
    )
    body = r.json()
    # Affordance-G shape: {error, detail, hint}
    assert set(body.keys()) == {"error", "detail", "hint"}, (
        f"expected Affordance-G shape (error/detail/hint); got keys {sorted(body.keys())}"
    )
    assert body["error"] == "multi_hop_invalid_request"
    assert "query" in body["detail"].lower() and "seeds" in body["detail"].lower()
    # Hint should be a fully-rendered example.
    assert "seeds" in body["hint"]
    assert "query" in body["hint"]


# ---------------------------------------------------------------------------
# Bonus: both fields provided is still accepted (regression-lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_hop_both_query_and_seeds_returns_200(api_client: httpx.AsyncClient):
    """When both are provided, the service uses the explicit seeds and
    skips the search step. The request must still be accepted at the
    schema layer."""
    r = await api_client.post(
        "/api/graph/multi-hop",
        json={
            "query": "decisions about agentic workflow",
            "seeds": ["dec_01KRPF09AP1FE1CRR6YQBY2R5F"],
            "max_depth": 2,
        },
    )
    assert r.status_code == 200, (
        f"query+seeds combined must be accepted; got {r.status_code} body={r.text[:200]}"
    )
