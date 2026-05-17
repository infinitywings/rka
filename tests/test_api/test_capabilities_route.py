"""Tests for the /api/capabilities response shape.

Affordance C (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF) introduced
the endpoint. Mission D (v2.4.0 / mis_01KRNYPVB8N3HDMZ9HK9HM3TB0) is a
BREAKING-IN-MINOR change: the `llm` field is removed entirely per PI
directive jrn_01KRNZBS50K250HHHHEC58E4GC.

Verified states (post-Mission-D):
  - Response is exactly {"embedding": {available, reason_unavailable}}
  - `llm` field is ABSENT (not null, not {available: false} — gone)
  - embedding block shape preserved per Mission B Affordance C
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
    """API client with embeddings disabled (default test config).

    Mission D removed RKA_LLM_* config knobs; we still pass llm_enabled=False
    to the RKAConfig constructor for back-compat — the field is preserved
    server-side but no longer surfaces via capabilities.
    """
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("capabilities_route.db"),
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
async def test_capabilities_endpoint_returns_only_embedding(api_client: httpx.AsyncClient):
    """Mission D BREAKING-IN-MINOR regression lock: `llm` is gone."""
    r = await api_client.get("/api/capabilities")
    assert r.status_code == 200
    body = r.json()
    # Only `embedding` is allowed at the top level.
    assert set(body.keys()) == {"embedding"}, (
        f"capabilities response should contain only 'embedding' after Mission D; "
        f"got keys: {sorted(body.keys())}"
    )


@pytest.mark.asyncio
async def test_capabilities_llm_field_is_absent(api_client: httpx.AsyncClient):
    """Direct assertion for the breaking-change verification — kept as a
    standalone test so a future re-introduction surfaces clearly here."""
    r = await api_client.get("/api/capabilities")
    body = r.json()
    assert "llm" not in body, (
        "the `llm` field was REMOVED in v2.4.0 (Mission D); a re-introduction "
        "would be a backwards-incompatible change deserving its own decision"
    )


@pytest.mark.asyncio
async def test_capabilities_embedding_block_shape_preserved(api_client: httpx.AsyncClient):
    """The embedding block's shape is unchanged from Mission B Affordance C."""
    r = await api_client.get("/api/capabilities")
    body = r.json()
    emb = body["embedding"]
    assert set(emb.keys()) >= {"available", "reason_unavailable"}
    assert isinstance(emb["available"], bool)
    if emb["available"]:
        assert emb["reason_unavailable"] is None
    else:
        assert isinstance(emb["reason_unavailable"], str)
        assert len(emb["reason_unavailable"]) > 0


@pytest.mark.asyncio
async def test_capabilities_embedding_disabled_carries_reason(api_client: httpx.AsyncClient):
    """In the test conftest, embeddings are disabled; the reason mentions
    the disabled flag so the consumer side (rka_search degraded one-liner,
    Settings page first-run banner) can rely on the wording."""
    r = await api_client.get("/api/capabilities")
    body = r.json()
    emb = body["embedding"]
    assert emb["available"] is False
    assert "disabled" in emb["reason_unavailable"].lower()
