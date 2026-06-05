"""Unit tests for the rka_record_decision MCP adapter (v2.7.0.6).

Sibling to test_legacy_supersede_adapter.py. Targets follow-up A from the
v2.7.0.5 investigation: the legacy `rka_record_decision` adapter accepted
a `confidence` kwarg and put it into the POST body for BOTH the
supersede branch AND the plain-create branch. `DecisionCreate` has no
`confidence` field and `ConfigDict(extra='forbid')`, so every call from
old transcripts using `rka_record_decision(..., confidence='verified', ...)`
returned 422.

v2.7.0.6 contract:
    - `confidence` kwarg is ACCEPTED on the signature (back-compat — old
      transcripts continue to call without TypeError).
    - `confidence` value is DROPPED before constructing the POST body.
    - The other strip-None semantics from v2.7.0.5 are preserved: optional
      fields absent from body when caller passes None.

These tests intercept the outbound HTTP request at the httpx MockTransport
layer (no server required).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from rka.mcp import server as mcp_server
from rka.models.decision import DecisionCreate


@pytest.fixture
def captured_requests(monkeypatch) -> list[dict[str, Any]]:
    """Capture every outbound POST the adapter makes. The MockTransport
    returns 201 + a minimal decision payload so the adapter's parse path
    runs to completion (no TypeError on missing JSON keys)."""
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


def _post_to_decisions(captured: list[dict[str, Any]]) -> dict[str, Any]:
    """Filter captured requests to the single /api/decisions POST.
    The @tool decorator fires a /api/hooks/fire post-call; ignore it."""
    decisions_posts = [r for r in captured if r["path"].startswith("/api/decisions")]
    assert len(decisions_posts) == 1, (
        f"expected exactly one /api/decisions POST, got {len(decisions_posts)}: "
        f"{[r['path'] for r in captured]}"
    )
    return decisions_posts[0]


# ---------------------------------------------------------------------------
# Plain-create branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_decision_plain_create_omits_confidence(captured_requests):
    """Default-kwarg path (no caller-supplied confidence). Adapter
    accepts `confidence: ConfidenceLiteral = 'tested'` on its signature
    but MUST NOT forward it to the body. Explicit phase='design' passed
    so the wire body would survive a real DecisionCreate validator."""
    await mcp_server.rka_record_decision(
        question="Q1?",
        chosen="A",
        rationale="because",
        project_id="prj_test",
        decided_by="brain",
        kind="decision",
        related_journal=["jrn_1"],
        phase="design",
    )
    req = _post_to_decisions(captured_requests)
    assert req["path"] == "/api/decisions"
    assert req["method"] == "POST"
    assert "confidence" not in req["body"], (
        f"v2.7.0.6 contract: rka_record_decision must NOT forward confidence "
        f"to DecisionCreate body (extra='forbid'). Body: {req['body']}"
    )


@pytest.mark.asyncio
async def test_record_decision_supersede_branch_omits_confidence(
    captured_requests,
):
    """The empirical v2.7.0.4 cockpit 422: supersede branch sent
    confidence in the body. v2.7.0.6 strips it. Verifies the body lands
    on the /supersede route AND has no confidence key."""
    await mcp_server.rka_record_decision(
        question="Reframed Q?",
        chosen="B",
        rationale="new evidence",
        project_id="prj_test",
        decided_by="brain",
        kind="decision",
        related_journal=["jrn_evidence"],
        supersedes_decision_id="dec_old_abc",
        phase="design",
    )
    req = _post_to_decisions(captured_requests)
    assert req["path"] == "/api/decisions/dec_old_abc/supersede", (
        f"expected supersede route; got {req['path']}"
    )
    assert "confidence" not in req["body"], (
        f"v2.7.0.6 contract: rka_record_decision supersede branch must NOT "
        f"forward confidence (was the v2.7.0.4 sibling 422 surface). "
        f"Body: {req['body']}"
    )


@pytest.mark.asyncio
async def test_record_decision_explicit_confidence_kwarg_dropped(
    captured_requests,
):
    """Caller explicitly passes confidence='verified'. Adapter accepts
    the kwarg (back-compat) but the value MUST NOT appear in the body.
    Pins the accept-and-drop contract."""
    await mcp_server.rka_record_decision(
        question="Q?",
        chosen="A",
        rationale="r",
        project_id="prj_test",
        decided_by="brain",
        kind="decision",
        related_journal=["jrn_1"],
        confidence="verified",  # legacy kwarg
        phase="design",
    )
    req = _post_to_decisions(captured_requests)
    assert "confidence" not in req["body"], (
        f"explicit confidence='verified' leaked into body: {req['body']}"
    )
    # Other fields should still flow.
    assert req["body"]["question"] == "Q?"
    assert req["body"]["chosen"] == "A"


@pytest.mark.asyncio
async def test_record_decision_plain_create_body_validates_against_decision_create(
    captured_requests,
):
    """Defense-in-depth: feed the constructed body straight into the
    real `DecisionCreate.model_validate`. With `extra='forbid'`, any
    stray field (like a re-introduced 'confidence') would raise here.
    Catches future regressions where someone re-adds a vestigial key
    without re-running the parity tests."""
    await mcp_server.rka_record_decision(
        question="Q?",
        chosen="A",
        rationale="r",
        project_id="prj_test",
        decided_by="brain",
        kind="decision",
        related_journal=["jrn_1"],
        phase="design",
    )
    req = _post_to_decisions(captured_requests)
    DecisionCreate.model_validate(req["body"])


@pytest.mark.asyncio
async def test_record_decision_supersede_branch_body_validates_against_decision_create(
    captured_requests,
):
    """Same defense-in-depth on the supersede branch. The body lands
    on /supersede which binds to DecisionCreate (until item C lands
    its DecisionSupersedeBody; until then DecisionCreate is canonical)."""
    await mcp_server.rka_record_decision(
        question="Reframed",
        chosen="B",
        rationale="reasons",
        project_id="prj_test",
        decided_by="brain",
        kind="decision",
        related_journal=["jrn_e"],
        supersedes_decision_id="dec_old",
        phase="design",
    )
    req = _post_to_decisions(captured_requests)
    DecisionCreate.model_validate(req["body"])
