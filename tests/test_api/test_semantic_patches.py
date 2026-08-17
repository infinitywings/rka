"""REST contract for semantic patch preview, apply, and conflict."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


HEADERS = {"X-RKA-Project": "proj_default"}


@pytest_asyncio.fixture
async def patch_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("semantic-patches-api.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_rest_create_preview_apply_and_schema(patch_client: httpx.AsyncClient) -> None:
    manuscript = await patch_client.post(
        "/api/manuscripts/native",
        headers=HEADERS,
        json={"title": "Before"},
    )
    assert manuscript.status_code == 201
    manuscript_id = manuscript.json()["id"]
    created = await patch_client.post(
        "/api/semantic-patches/proposals",
        headers=HEADERS,
        json={
            "origin": "human",
            "intent": "Rename manuscript.",
            "reason": "Clearer framing.",
            "created_by": "web_ui",
            "operations": [{
                "operation": "manuscript_metadata_update",
                "manuscript_id": manuscript_id,
                "expected_revision": 1,
                "title": "After",
            }],
        },
    )
    assert created.status_code == 201
    proposal = created.json()
    unchanged = await patch_client.get(f"/api/manuscripts/{manuscript_id}", headers=HEADERS)
    assert unchanged.json()["title"] == "Before"

    applied = await patch_client.post(
        f"/api/semantic-patches/proposals/{proposal['id']}/apply",
        headers=HEADERS,
        json={"expected_revision": 1, "actor": "web_ui", "reason": "Approved in preview."},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    changed = await patch_client.get(f"/api/manuscripts/{manuscript_id}", headers=HEADERS)
    assert changed.json()["title"] == "After"

    schema = await patch_client.get("/api/semantic-patches/schema", headers=HEADERS)
    assert schema.status_code == 200
    assert schema.json()["title"] == "GeneratedProposalDraft"


@pytest.mark.asyncio
async def test_rest_rejects_ai_proposal_without_prepared_manifest(
    patch_client: httpx.AsyncClient,
) -> None:
    response = await patch_client.post(
        "/api/semantic-patches/proposals",
        headers=HEADERS,
        json={
            "origin": "host_agent",
            "intent": "Candidate.",
            "reason": "Generated in host.",
            "created_by": "web_ui",
            "provider": "chatgpt",
            "model": "host-model",
            "boundary": "host_conversation",
            "operations": [{
                "operation": "manuscript_metadata_update",
                "manuscript_id": "man_missing",
                "expected_revision": 1,
                "title": "Candidate",
            }],
        },
    )
    assert response.status_code == 422
    assert "context_manifest_id" in response.text


@pytest.mark.asyncio
async def test_mcp_transport_cannot_apply_or_reject_proposals(
    patch_client: httpx.AsyncClient,
) -> None:
    manuscript = await patch_client.post(
        "/api/manuscripts/native",
        headers=HEADERS,
        json={"title": "Before review"},
    )
    manuscript_id = manuscript.json()["id"]
    created = await patch_client.post(
        "/api/semantic-patches/proposals",
        headers=HEADERS,
        json={
            "origin": "human",
            "intent": "Rename manuscript.",
            "reason": "Prepared for a human reviewer.",
            "created_by": "web_ui",
            "operations": [{
                "operation": "manuscript_metadata_update",
                "manuscript_id": manuscript_id,
                "expected_revision": 1,
                "title": "After review",
            }],
        },
    )
    assert created.status_code == 201
    proposal_id = created.json()["id"]
    misattributed = await patch_client.post(
        "/api/semantic-patches/proposals",
        headers={**HEADERS, "X-RKA-Actor": "executor"},
        json={
            "origin": "human",
            "intent": "Falsely claim human authorship.",
            "reason": "Exercise the provenance guard.",
            "created_by": "executor",
            "operations": [{
                "operation": "manuscript_metadata_update",
                "manuscript_id": manuscript_id,
                "expected_revision": 1,
                "title": "Misattributed",
            }],
        },
    )
    assert misattributed.status_code == 403
    transition = {
        "expected_revision": 1,
        "actor": "pi",
        "reason": "An MCP agent cannot claim the PI review transition.",
    }

    for action in ("apply", "reject"):
        response = await patch_client.post(
            f"/api/semantic-patches/proposals/{proposal_id}/{action}",
            headers={**HEADERS, "X-RKA-Actor": "executor"},
            json=transition,
        )
        assert response.status_code == 403
    mismatched_reviewer = await patch_client.post(
        f"/api/semantic-patches/proposals/{proposal_id}/apply",
        headers=HEADERS,
        json=transition,
    )
    assert mismatched_reviewer.status_code == 403
    current = await patch_client.get(
        f"/api/manuscripts/{manuscript_id}", headers=HEADERS
    )
    assert current.json()["title"] == "Before review"
