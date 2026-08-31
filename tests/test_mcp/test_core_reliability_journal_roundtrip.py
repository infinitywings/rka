"""Typed MCP -> REST -> service journal reliability contracts."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.mcp.operation_args import BulkUpdateArgs, RecordNoteArgs, UpdateNoteArgs
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
async def test_mcp_journal_lifecycle_and_pinning_update_round_trip(
    mcp_env: httpx.AsyncClient,
) -> None:
    created = await mcp_env.post(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
        json={
            "content": "Lifecycle probe.",
            "source": "brain",
            "confidence": "verified",
            "status": "active",
            "pinned": False,
        },
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]

    result = await dispatch_execute_typed(
        UpdateNoteArgs(
            operation="update_note",
            project_id="proj_default",
            id=note_id,
            status="superseded",
            pinned=True,
        )
    )
    assert "fields=status,pinned" in result

    read_back = await mcp_env.get(
        f"/api/notes/{note_id}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["status"] == "superseded"
    assert read_back.json()["pinned"] is True
    assert read_back.json()["source"] == "brain"
    assert read_back.json()["confidence"] == "verified"


@pytest.mark.asyncio
async def test_flat_and_legacy_nested_bulk_update_round_trip(
    mcp_env: httpx.AsyncClient,
) -> None:
    created = await mcp_env.post(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
        json={
            "content": "Bulk lifecycle probe.",
            "importance": "critical",
            "status": "active",
            "pinned": False,
        },
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]

    flat_result = await dispatch_execute_typed(
        BulkUpdateArgs(
            operation="bulk_update",
            project_id="proj_default",
            updates=[
                {
                    "entity_type": "journal",
                    "id": note_id,
                    "importance": "low",
                    "status": "superseded",
                    "tags": ["bulk-verified"],
                }
            ],
        )
    )
    assert flat_result.startswith("Updated 1/1")
    assert "fields=importance,status,tags" in flat_result

    read_back = await mcp_env.get(
        f"/api/notes/{note_id}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["importance"] == "low"
    assert read_back.json()["status"] == "superseded"
    assert read_back.json()["tags"] == ["bulk-verified"]

    nested_result = await dispatch_execute_typed(
        BulkUpdateArgs(
            operation="bulk_update",
            project_id="proj_default",
            updates=[
                {
                    "entity_type": "note",
                    "id": note_id,
                    "data": {"status": "active", "pinned": True},
                }
            ],
        )
    )
    assert nested_result.startswith("Updated 1/1")

    final_read_back = await mcp_env.get(
        f"/api/notes/{note_id}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert final_read_back.status_code == 200
    assert final_read_back.json()["status"] == "active"
    assert final_read_back.json()["pinned"] is True


@pytest.mark.asyncio
async def test_bulk_update_validates_and_updates_every_supported_entity_type(
    mcp_env: httpx.AsyncClient,
) -> None:
    decision = await mcp_env.post(
        "/api/decisions",
        headers={"X-RKA-Project": "proj_default"},
        json={
            "question": "Original decision question?",
            "phase": "design",
            "decided_by": "brain",
        },
    )
    assert decision.status_code == 201, decision.text
    literature = await mcp_env.post(
        "/api/literature",
        headers={"X-RKA-Project": "proj_default"},
        json={"title": "Bulk update paper", "status": "to_read"},
    )
    assert literature.status_code == 201, literature.text

    result = await dispatch_execute_typed(
        BulkUpdateArgs(
            operation="bulk_update",
            project_id="proj_default",
            updates=[
                {
                    "entity_type": "decision",
                    "id": decision.json()["id"],
                    "rationale": "Updated through validated bulk dispatch.",
                    "tags": ["bulk-decision"],
                },
                {
                    "entity_type": "literature",
                    "id": literature.json()["id"],
                    "status": "read",
                    "tags": ["bulk-literature"],
                },
            ],
        )
    )
    assert result.startswith("Updated 2/2")

    decision_readback = await mcp_env.get(
        f"/api/decisions/{decision.json()['id']}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert decision_readback.status_code == 200
    assert decision_readback.json()["rationale"] == (
        "Updated through validated bulk dispatch."
    )
    assert decision_readback.json()["tags"] == ["bulk-decision"]

    literature_readback = await mcp_env.get(
        f"/api/literature/{literature.json()['id']}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert literature_readback.status_code == 200
    assert literature_readback.json()["status"] == "read"
    assert literature_readback.json()["tags"] == ["bulk-literature"]


@pytest.mark.asyncio
async def test_legacy_bulk_preflight_prevents_partial_write(
    mcp_env: httpx.AsyncClient,
) -> None:
    import rka.mcp.server as mcp_server

    created = await mcp_env.post(
        "/api/notes",
        headers={"X-RKA-Project": "proj_default"},
        json={"content": "Must remain active.", "status": "active"},
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]

    result = await mcp_server.rka_bulk_update(
        updates=[
            {
                "entity_type": "journal",
                "id": note_id,
                "status": "superseded",
            },
            {
                "entity_type": "journal",
                "id": "jrn_invalid",
                "unknown": "field",
            },
        ],
        project_id="proj_default",
    )
    assert result.startswith("Updated 0/2 (1 errors)")

    read_back = await mcp_env.get(
        f"/api/notes/{note_id}",
        headers={"X-RKA-Project": "proj_default"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["status"] == "active"


@pytest.mark.parametrize(
    "item",
    [
        {"id": "jrn_probe", "status": "superseded"},
        {"entity_type": "journal", "id": "jrn_probe"},
        {
            "entity_type": "journal",
            "id": "jrn_probe",
            "data": {"status": "superseded"},
            "pinned": True,
        },
        {"entity_type": "journal", "id": "jrn_probe", "unknown": "value"},
    ],
)
def test_bulk_update_rejects_ambiguous_or_empty_items(item: dict) -> None:
    with pytest.raises(ValidationError):
        BulkUpdateArgs(
            operation="bulk_update",
            project_id="proj_default",
            updates=[item],
        )


@pytest.mark.asyncio
async def test_bulk_update_does_not_report_success_on_readback_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rka.mcp.server as mcp_server

    class MismatchResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict:
            return {"id": "jrn_probe", "status": "active"}

    class MismatchClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def put(self, _endpoint: str, *, json: dict):
            assert json == {"status": "superseded"}
            return MismatchResponse()

    async def no_session_hook(_project_id):
        return None

    monkeypatch.setattr(mcp_server, "_client", lambda _project_id: MismatchClient())
    monkeypatch.setattr(mcp_server, "_maybe_fire_session_start", no_session_hook)

    result = await mcp_server.rka_bulk_update(
        updates=[
            {
                "entity_type": "journal",
                "id": "jrn_probe",
                "status": "superseded",
            }
        ],
        project_id="proj_default",
    )

    assert result.startswith("Updated 0/1 (1 errors)")
    assert "write response mismatch for fields=status" in result


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
