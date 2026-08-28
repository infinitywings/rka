"""Typed MCP -> REST -> service journal reliability contracts."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.mcp.operation_args import RecordNoteArgs, UpdateNoteArgs
from rka.mcp.verb_dispatch import dispatch_execute_typed


@pytest_asyncio.fixture
async def mcp_env(tmp_path: Path, monkeypatch):
    import rka.mcp.server as mcp_server

    app = create_app(
        RKAConfig(
            project_dir=tmp_path,
            db_path=Path("core-reliability-mcp.db"),
            llm_enabled=False,
            embeddings_enabled=False,
        )
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)

        def client(project_id: str | None = None) -> httpx.AsyncClient:
            headers = {"X-RKA-Project": project_id} if project_id else {}
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                headers=headers,
            )

        monkeypatch.setattr(mcp_server, "_client", client)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as rest:
            yield rest


@pytest.mark.asyncio
async def test_mcp_summary_only_note_update_round_trip(
    mcp_env: httpx.AsyncClient,
) -> None:
    created = await mcp_env.post(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
        json={"content": "Body stays unchanged.", "summary": "Old summary."},
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]

    result = await dispatch_execute_typed(
        UpdateNoteArgs(
            operation="update_note",
            project_id="proj_default",
            id=note_id,
            summary="New summary.",
        )
    )
    assert "Updated" in result

    read_back = await mcp_env.get(
        f"/api/notes/{note_id}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["summary"] == "New summary."
    assert read_back.json()["content"] == "Body stays unchanged."


@pytest.mark.asyncio
async def test_mcp_rejects_foreign_provenance_without_partial_write(
    mcp_env: httpx.AsyncClient,
) -> None:
    project = await mcp_env.post(
        "/api/projects",
        json={"id": "prj_foreign", "name": "Foreign"},
    )
    assert project.status_code == 200, project.text
    decision = await mcp_env.post(
        "/api/decisions",
        headers={"X-RKA-Project": "prj_foreign"},
        json={
            "question": "Foreign decision?",
            "phase": "design",
            "decided_by": "brain",
        },
    )
    assert decision.status_code == 201, decision.text

    with pytest.raises(Exception, match="API error 422.*proj_default"):
        await dispatch_execute_typed(
            RecordNoteArgs(
                operation="record_note",
                project_id="proj_default",
                content="MCP write that must roll back.",
                provenance={"related_decisions": [decision.json()["id"]]},
            )
        )

    listed = await mcp_env.get(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert listed.status_code == 200
    assert all(
        note["content"] != "MCP write that must roll back."
        for note in listed.json()
    )
