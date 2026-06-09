"""v2.7.0.7 — MCP typed-dispatch contract fixes.

The third-party review found fields the operation_args models accept but
the adapters silently dropped before the POST, plus a phase field
advertised optional that the REST model required. These tests pin the
fixes:
  - RecordDecisionArgs.phase is REQUIRED (matches DecisionCreate).
  - rka_add_note forwards summary/status/pinned to the body.
  - rka_add_decision forwards tags/status/related_missions to the body.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from rka.mcp import server as mcp_server
from rka.mcp.operation_args import RecordDecisionArgs


# ---------------------------------------------------------------------------
# RecordDecisionArgs.phase required
# ---------------------------------------------------------------------------


def test_record_decision_args_requires_phase():
    """phase promoted optional -> required so a missing phase fails at the
    typed-args boundary, not as an opaque 422 at the API."""
    with pytest.raises(ValidationError) as excinfo:
        RecordDecisionArgs(
            operation="record_decision",
            project_id="prj_t",
            question="Q?",
            chosen="A",
            rationale="r",
            decided_by="brain",
            kind="decision",
            related_journal=["jrn_1"],
            # phase intentionally omitted
        )
    assert "phase" in str(excinfo.value)


def test_record_decision_args_accepts_explicit_phase():
    args = RecordDecisionArgs(
        operation="record_decision",
        project_id="prj_t",
        question="Q?",
        chosen="A",
        rationale="r",
        decided_by="brain",
        kind="decision",
        related_journal=["jrn_1"],
        phase="design",
    )
    assert args.phase == "design"


# ---------------------------------------------------------------------------
# Adapter body-forwarding (httpx MockTransport capture)
# ---------------------------------------------------------------------------


@pytest.fixture
def captured(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append({"path": request.url.path, "body": body})
        return httpx.Response(
            201,
            json={"id": "x_1", "type": body.get("type", "note"),
                  "confidence": body.get("confidence", "hypothesis"),
                  "question": body.get("question", "")},
        )

    transport = httpx.MockTransport(_handler)

    def _client(project_id: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport, base_url="http://test",
            headers={"X-RKA-Project": project_id} if project_id else {},
        )

    monkeypatch.setattr(mcp_server, "_client", _client)
    return calls


def _body_for(captured: list[dict], path_fragment: str) -> dict:
    hits = [c for c in captured if path_fragment in c["path"]]
    assert len(hits) == 1, f"expected 1 POST to {path_fragment}, got {[c['path'] for c in captured]}"
    return hits[0]["body"]


@pytest.mark.asyncio
async def test_add_note_forwards_summary_status_pinned(captured):
    await mcp_server.rka_add_note(
        content="body text",
        type="note",
        source="brain",
        summary="a short summary",
        status="draft",
        pinned=True,
        project_id="prj_t",
    )
    body = _body_for(captured, "/api/notes")
    assert body["summary"] == "a short summary"
    assert body["status"] == "draft"
    assert body["pinned"] is True


@pytest.mark.asyncio
async def test_add_note_omits_unset_optional_fields(captured):
    await mcp_server.rka_add_note(
        content="body text", type="note", source="brain", project_id="prj_t",
    )
    body = _body_for(captured, "/api/notes")
    for absent in ("summary", "status", "pinned"):
        assert absent not in body


@pytest.mark.asyncio
async def test_add_decision_forwards_tags_status_related_missions(captured):
    await mcp_server.rka_add_decision(
        question="Q?",
        phase="design",
        decided_by="brain",
        chosen="A",
        rationale="r",
        related_journal=["jrn_1"],
        kind="decision",
        tags=["t1", "t2"],
        status="active",
        related_missions=["mis_1"],
        project_id="prj_t",
    )
    body = _body_for(captured, "/api/decisions")
    assert body["tags"] == ["t1", "t2"]
    assert body["status"] == "active"
    assert body["related_missions"] == ["mis_1"]
