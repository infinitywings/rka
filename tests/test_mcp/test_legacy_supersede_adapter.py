"""Unit tests for the rka_supersede_decision MCP adapter (v2.7.0.5).

Regression guard for the v2.7.0.4 wire-shape bug: the adapter previously
constructed ``{old_decision_id, new_decision: {...}}`` and POSTed it to
the FastAPI route, which binds the whole JSON body to
``DecisionCreate(extra='forbid')`` — so every supersede returned 422.

These tests intercept the outbound HTTP request at the httpx layer (no
server required) and assert:

1. The request body is a flat ``DecisionCreate``-shaped dict with
   top-level ``question`` / ``chosen`` / ``rationale`` / ``decided_by`` /
   ``phase`` / ``kind``.
2. The body does NOT contain ``old_decision_id`` (lives in URL path) or
   a nested ``new_decision`` (the bug).
3. Optional forwarded fields (``related_journal``,
   ``related_literature``, ``related_missions``, ``parent_id``,
   ``options``, ``assumptions``, ``tags``, ``status``) flow through when
   the caller provides them, and are absent when the caller doesn't
   (so DecisionCreate's defaults apply).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

# The adapter is registered as a FastMCP tool but is plain async function
# underneath. Import via the rka.mcp.server module so we exercise the same
# code path the MCP harness would.
from rka.mcp import server as mcp_server


@pytest.fixture
def captured_requests(monkeypatch) -> list[dict[str, Any]]:
    """Replace `mcp_server._client` with a factory that yields a stub
    httpx.AsyncClient. The stub uses httpx.MockTransport so the
    adapter's `await c.post(...)` returns a real `httpx.Response`
    (201 Created) — and the request body is captured into the
    fixture-returned list for assertion.
    """
    captured: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = {}
        try:
            body = json.loads(request.content) if request.content else {}
        except json.JSONDecodeError:
            body = {"__raw__": request.content.decode("utf-8", errors="replace")}
        captured.append(
            {
                "method": request.method,
                "url": str(request.url),
                "path": request.url.path,
                "body": body,
            }
        )
        return httpx.Response(
            201,
            json={
                "id": "dec_new_test_xyz",
                "status": "active",
                "question": body.get("question", ""),
            },
        )

    transport = httpx.MockTransport(_handler)

    def _stub_client(project_id: str | None = None) -> httpx.AsyncClient:
        headers = {"X-RKA-Project": project_id} if project_id else {}
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=headers,
        )

    monkeypatch.setattr(mcp_server, "_client", _stub_client)
    return captured


@pytest.mark.asyncio
async def test_supersede_body_is_flat_decision_create_shape(captured_requests):
    """The wire body is a flat DecisionCreate dict — NO wrapping envelope."""
    raw = await mcp_server.rka_supersede_decision(
        old_decision_id="dec_old_abc",
        question="Reframed Q",
        chosen="Option B",
        rationale="why B is better",
        decided_by="brain",
        phase="design",
        kind="design_choice",
        related_journal=["jrn_evidence_1"],
        project_id="proj_default",
    )
    assert json.loads(raw)["id"] == "dec_new_test_xyz"

    # The @tool decorator also fires a session_start hook (POST /api/hooks/fire)
    # after the tool body; filter to just the supersede call we care about.
    supersede_reqs = [r for r in captured_requests if "/supersede" in r["path"]]
    assert len(supersede_reqs) == 1
    req = supersede_reqs[0]
    assert req["method"] == "POST"
    assert req["path"] == "/api/decisions/dec_old_abc/supersede"

    body = req["body"]
    # FLAT shape: top-level required DecisionCreate fields.
    assert body["question"] == "Reframed Q"
    assert body["chosen"] == "Option B"
    assert body["rationale"] == "why B is better"
    assert body["decided_by"] == "brain"
    assert body["phase"] == "design"
    assert body["kind"] == "design_choice"
    assert body["related_journal"] == ["jrn_evidence_1"]

    # NO bug-shape keys at the top level.
    assert "old_decision_id" not in body, (
        f"old_decision_id leaked into body — should live ONLY in URL path. Got: {body}"
    )
    assert "new_decision" not in body, (
        f"v2.7.0.4 regression: body wrapped in 'new_decision' envelope. Got: {body}"
    )


@pytest.mark.asyncio
async def test_supersede_omits_optional_fields_when_caller_passes_none(
    captured_requests,
):
    """When the caller passes None for optional fields, they MUST be
    stripped from the body — DecisionCreate(extra='forbid') would reject
    unexpected fields, but a None tagged-but-allowed field would skip
    the default. Stripping keeps the payload tidy and aligned with how
    DecisionCreate validates input."""
    await mcp_server.rka_supersede_decision(
        old_decision_id="dec_old",
        question="Q",
        chosen="C",
        rationale="R",
        project_id="proj_default",
    )
    supersede_reqs = [r for r in captured_requests if "/supersede" in r["path"]]
    body = supersede_reqs[0]["body"]

    for absent in (
        "related_journal",
        "related_literature",
        "related_missions",
        "parent_id",
        "options",
        "assumptions",
        "tags",
        "status",
    ):
        assert absent not in body, (
            f"optional field {absent!r} should be omitted when caller passes None, "
            f"got: {body}"
        )


@pytest.mark.asyncio
async def test_supersede_forwards_provenance_fields_when_provided(
    captured_requests,
):
    """All optional fields round-trip into the body when supplied."""
    await mcp_server.rka_supersede_decision(
        old_decision_id="dec_old",
        question="Q",
        chosen="C",
        rationale="R",
        decided_by="pi",
        phase="design",
        kind="design_choice",
        related_journal=["jrn_a", "jrn_b"],
        related_literature=["lit_x"],
        related_missions=["mis_q"],
        parent_id="dec_parent",
        options=[{"id": "opt1", "label": "A"}, {"id": "opt2", "label": "B"}],
        assumptions=["A1", "A2"],
        tags=["t1", "t2"],
        status="active",
        project_id="proj_default",
    )
    supersede_reqs = [r for r in captured_requests if "/supersede" in r["path"]]
    body = supersede_reqs[0]["body"]
    assert body["related_journal"] == ["jrn_a", "jrn_b"]
    assert body["related_literature"] == ["lit_x"]
    assert body["related_missions"] == ["mis_q"]
    assert body["parent_id"] == "dec_parent"
    assert body["options"] == [
        {"id": "opt1", "label": "A"},
        {"id": "opt2", "label": "B"},
    ]
    assert body["assumptions"] == ["A1", "A2"]
    assert body["tags"] == ["t1", "t2"]
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_supersede_url_contains_old_id_not_body(captured_requests):
    """old_decision_id lives ONLY in URL path, NEVER in body. Locks the
    REST contract — a future regression that 'just adds back' the
    duplicate in body would fail here."""
    await mcp_server.rka_supersede_decision(
        old_decision_id="dec_OLD_01KSAMPLE",
        question="Q",
        chosen="C",
        rationale="R",
        project_id="proj_default",
    )
    supersede_reqs = [r for r in captured_requests if "/supersede" in r["path"]]
    req = supersede_reqs[0]
    assert "dec_OLD_01KSAMPLE" in req["path"]
    assert "dec_OLD_01KSAMPLE" not in json.dumps(req["body"]), (
        f"old_decision_id leaked into body: {req['body']}"
    )
