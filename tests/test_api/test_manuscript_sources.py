"""REST authorization and explicit source-proposal workflow tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


HEADERS = {"X-RKA-Project": "proj_default"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest_asyncio.fixture
async def source_client(tmp_path: Path):
    workspace = tmp_path / "paper"
    workspace.mkdir()
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("source-api.db"),
        data_dir=tmp_path / "data",
        llm_enabled=False,
        embeddings_enabled=False,
        manuscript_workspace_roots=str(tmp_path),
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            created = await client.post(
                "/api/manuscripts/native",
                headers=HEADERS,
                json={"title": "Source API", "workspace_ref": str(workspace)},
            )
            assert created.status_code == 201
            manuscript_id = created.json()["id"]
            spine = await client.put(
                f"/api/manuscripts/{manuscript_id}/argument-spine",
                headers=HEADERS,
                json={
                    "expected_revision": 1,
                    "spine": {
                        "claims": [],
                        "units": [
                            {
                                "unit_id": "U1",
                                "kind": "introduction",
                                "location": "main.md#u1",
                                "status": "planned",
                                "outline_level": 3,
                                "unit_role": "argument_block",
                                "rhetorical_move": "frame_problem",
                                "communicative_job": "Frame the problem.",
                                "intended_takeaway": "The bounded problem matters.",
                                "evidence_plan": ["One bounded source."],
                            }
                        ],
                    },
                },
            )
            assert spine.status_code == 200
            unit_id = spine.json()["units"][0]["id"]
            yield client, workspace, manuscript_id, unit_id
    finally:
        await lifespan.__aexit__(None, None, None)


def _content(unit_id: str, sentence: str) -> str:
    return (
        f"<!-- rka:unit {unit_id} begin -->\n"
        f"{sentence}\n"
        f"<!-- rka:unit {unit_id} end -->\n"
    )


@pytest.mark.asyncio
async def test_rest_prepare_read_apply_and_overview(source_client) -> None:
    client, workspace, manuscript_id, unit_id = source_client
    before = _content(unit_id, "Before.")
    after = _content(unit_id, "After.")
    (workspace / "main.md").write_text(before)

    read = await client.post(
        f"/api/manuscripts/{manuscript_id}/source/read",
        headers=HEADERS,
        json={"relative_path": "main.md"},
    )
    assert read.status_code == 200
    assert read.json()["content_hash"] == _hash(before)

    prepared = await client.post(
        f"/api/manuscripts/{manuscript_id}/source/proposals",
        headers=HEADERS,
        json={
            "origin": "human",
            "relative_path": "main.md",
            "expected_content_hash": _hash(before),
            "content": after,
            "created_by": "web_ui",
            "reason": "Prepare the reviewed source change.",
        },
    )
    assert prepared.status_code == 201
    assert (workspace / "main.md").read_text() == before

    applied = await client.post(
        f"/api/manuscript-source-proposals/{prepared.json()['id']}/apply",
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "actor": "web_ui",
            "reason": "Apply after reviewing the source diff.",
        },
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert (workspace / "main.md").read_text() == after

    overview = await client.get(
        f"/api/manuscripts/{manuscript_id}/source",
        headers=HEADERS,
    )
    assert overview.status_code == 200
    assert overview.json()["quick_reader"][0]["anchor_state"] == "linked"


@pytest.mark.asyncio
async def test_rest_conflict_and_mcp_transport_denial(source_client) -> None:
    client, workspace, manuscript_id, unit_id = source_client
    before = _content(unit_id, "Before.")
    after = _content(unit_id, "After.")
    external = _content(unit_id, "External.")
    (workspace / "main.md").write_text(before)

    denied = await client.post(
        f"/api/manuscripts/{manuscript_id}/source/read",
        headers={**HEADERS, "X-RKA-Actor": "executor"},
        json={"relative_path": "main.md"},
    )
    assert denied.status_code == 403

    prepared = await client.post(
        f"/api/manuscripts/{manuscript_id}/source/proposals",
        headers=HEADERS,
        json={
            "origin": "human",
            "relative_path": "main.md",
            "expected_content_hash": _hash(before),
            "content": after,
            "created_by": "web_ui",
            "reason": "Prepare a source change.",
        },
    )
    assert prepared.status_code == 201
    (workspace / "main.md").write_text(external)
    conflict = await client.post(
        f"/api/manuscript-source-proposals/{prepared.json()['id']}/apply",
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "actor": "web_ui",
            "reason": "Attempt stale apply.",
        },
    )
    assert conflict.status_code == 409
    assert (workspace / "main.md").read_text() == external
