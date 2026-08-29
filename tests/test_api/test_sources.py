"""REST contract for safe registered sources and explicit admission."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


@pytest_asyncio.fixture
async def source_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("sources.db"),
        data_dir=tmp_path / "data",
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-RKA-Project": "proj_default"},
        ) as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_source_registration_query_and_explicit_admission(source_client) -> None:
    registered = await source_client.post(
        "/api/sources",
        json={
            "source_kind": "pasted_text",
            "pasted_text": "Exact source text.",
            "title": "Source note",
            "ownership_kind": "researcher",
            "provenance": {"session": "api-test"},
            "registered_by": "web_ui",
        },
    )
    assert registered.status_code == 201, registered.text
    result = registered.json()
    source = result["source"]
    assert result["duplicate"] is False

    duplicate = await source_client.post("/api/sources", json={
        "source_kind": "pasted_text",
        "pasted_text": "Exact source text.",
        "title": "Source note",
        "ownership_kind": "researcher",
        "provenance": {"session": "api-test"},
        "registered_by": "web_ui",
    })
    assert duplicate.status_code == 201
    assert duplicate.json()["source"]["id"] == source["id"]
    assert duplicate.json()["duplicate"] is True

    listed = await source_client.get("/api/sources", params={"source_kind": "pasted_text"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [source["id"]]

    candidate = await source_client.post(
        "/api/interpretations",
        json={
            "source_type": "artifact",
            "source_id": source["artifact_id"],
            "locator_kind": "record",
            "locator_value": "full_record",
            "statement": "Exact source text.",
            "epistemic_kind": "reported_fact",
            "created_by": "executor",
            "extraction_tool": "api-test",
        },
    )
    assert candidate.status_code == 201, candidate.text
    target = await source_client.post(
        "/api/notes",
        json={"content": "Reviewed canonical summary.", "source": "pi", "verbatim_input": "Reviewed canonical summary."},
    )
    assert target.status_code == 201, target.text

    admitted = await source_client.post(
        f"/api/sources/{source['id']}/admissions",
        json={
            "candidate_id": candidate.json()["id"],
            "expected_revision": 1,
            "target_type": "journal",
            "target_id": target.json()["id"],
            "actor": "web_ui",
            "reason": "Checked the exact registered text.",
            "grounding_verified": True,
        },
    )
    assert admitted.status_code == 201, admitted.text
    detail = await source_client.get(f"/api/sources/{source['id']}")
    assert detail.status_code == 200
    assert detail.json()["interpretation_candidate_count"] == 1
    assert detail.json()["admissions"][0]["id"] == admitted.json()["id"]


@pytest.mark.asyncio
async def test_source_rest_rejects_missing_scope_and_locator(source_client) -> None:
    invalid = await source_client.post(
        "/api/sources",
        json={"source_kind": "url", "registered_by": "web_ui"},
    )
    assert invalid.status_code == 422

    unscoped = await source_client.get(
        "/api/sources",
        headers={"X-RKA-Project": ""},
    )
    assert unscoped.status_code == 422


@pytest.mark.asyncio
async def test_source_rest_accepts_transferred_binary_bytes(source_client) -> None:
    payload = b"mcp-transfer\x00\xff"
    registered = await source_client.post(
        "/api/sources",
        json={
            "source_kind": "file",
            "content_base64": base64.b64encode(payload).decode("ascii"),
            "filename": "capture.bin",
            "registered_by": "executor",
        },
    )
    assert registered.status_code == 201, registered.text
    source = registered.json()["source"]
    detail = await source_client.get(f"/api/sources/{source['id']}")
    assert detail.status_code == 200
    artifact = detail.json()["artifact"]
    assert Path(artifact["filepath"]).read_bytes() == payload
