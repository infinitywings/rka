"""Test for Affordance C (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
GET /api/capabilities returns embedding + LLM availability.

Verified states:
  - embeddings disabled (test conftest default) → available=false, reason cites disabled flag
  - LLM disabled (test conftest default) → available=false with reason
  - response shape locked: {embedding: {available, reason_unavailable}, llm: {...}}
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
    """API client with embeddings + LLM disabled (default test config)."""
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
async def test_capabilities_endpoint_shape(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"embedding", "llm"}
    for block_name in ("embedding", "llm"):
        block = body[block_name]
        assert set(block.keys()) >= {"available", "reason_unavailable"}
        assert isinstance(block["available"], bool)
        # reason_unavailable is None iff available=true
        if block["available"]:
            assert block["reason_unavailable"] is None
        else:
            assert isinstance(block["reason_unavailable"], str)
            assert len(block["reason_unavailable"]) > 0


@pytest.mark.asyncio
async def test_capabilities_disabled_state(api_client: httpx.AsyncClient):
    """In the test conftest, both LLM and embeddings are disabled. Both
    blocks should report unavailable with disabled-flag wording so the
    consumer side (rka_search degraded one-liner, rka_get_status
    capability lines) can rely on the message shape."""
    r = await api_client.get("/api/capabilities")
    body = r.json()

    emb = body["embedding"]
    assert emb["available"] is False
    assert "disabled" in emb["reason_unavailable"].lower()

    llm = body["llm"]
    assert llm["available"] is False
    assert ("disabled" in llm["reason_unavailable"].lower()
            or "not reachable" in llm["reason_unavailable"].lower())
