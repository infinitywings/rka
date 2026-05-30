"""MCP server contract — verifies the tool functions correctly proxy
to the orchestrator HTTP surface.

The tests mock httpx so the MCP tool bodies hit a fake server. The
test surface is the *tool function* (the wrapped async coroutine), not
the FastMCP runtime — the latter is library code.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orchestrator import mcp_server


# ---------------------------------------------------------------------------
# httpx transport patching — every tool opens its own AsyncClient via
# `_client()`. We monkeypatch `_client` to return one bound to a
# MockTransport, so the test owns the request/response surface.
# ---------------------------------------------------------------------------


class _Recorder:
    """Captures the requests the MCP tool issues against the fake server."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []

    def script(self, response: httpx.Response) -> None:
        self.responses.append(response)

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            return httpx.Response(500, json={"detail": "no scripted response"})
        return self.responses.pop(0)


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    transport = httpx.MockTransport(rec.handler)

    def fake_client():
        return httpx.AsyncClient(transport=transport, base_url="http://test", timeout=5.0)

    monkeypatch.setattr(mcp_server, "_client", fake_client)
    return rec


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_run_start_posts_to_runs(recorder):
    recorder.script(
        _json({"workflow_thread_id": "thr_x", "status": "starting"})
    )
    out = await mcp_server.orchestrator_run_start(
        mission_id="mis_test",
        project_id="prj_test",
        budget_usd=3.0,
    )
    assert out["workflow_thread_id"] == "thr_x"
    req = recorder.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/runs"
    # Phase D2.1: orchestrator_run_start MUST send wait_segment=false so
    # the HTTP call returns immediately after the run row is committed.
    # Otherwise the first segment (Brain strategy + confirmation_brief,
    # typically 2 LLM calls = ~4 min) blows past the MCP client timeout
    # exactly the way orchestrator_correct used to before the fix.
    assert req.url.params["wait_segment"] == "false"
    body = json.loads(req.content)
    assert body == {
        "mission_id": "mis_test",
        "project_id": "prj_test",
        "budget_usd": 3.0,
        "workflow_thread_id": None,
    }


@pytest.mark.asyncio
async def test_orchestrator_run_start_propagates_404(recorder):
    recorder.script(_json({"detail": "mission not found"}, status=404))
    with pytest.raises(Exception, match="404"):
        await mcp_server.orchestrator_run_start(
            mission_id="mis_missing", project_id="prj_test"
        )


@pytest.mark.asyncio
async def test_orchestrator_list_runs_passes_status_filter(recorder):
    recorder.script(_json([{"workflow_thread_id": "thr_a"}]))
    out = await mcp_server.orchestrator_list_runs(status="awaiting_pi", limit=10)
    assert out == [{"workflow_thread_id": "thr_a"}]
    req = recorder.requests[0]
    assert req.method == "GET"
    assert req.url.path == "/runs"
    assert req.url.params["status"] == "awaiting_pi"
    assert req.url.params["limit"] == "10"


@pytest.mark.asyncio
async def test_orchestrator_get_run(recorder):
    recorder.script(_json({"workflow_thread_id": "thr_x", "status": "running"}))
    out = await mcp_server.orchestrator_get_run("thr_x")
    assert out["status"] == "running"
    assert recorder.requests[0].url.path == "/runs/thr_x"


@pytest.mark.asyncio
async def test_orchestrator_cancel(recorder):
    recorder.script(_json({"cancelled_interrupts": 2}))
    out = await mcp_server.orchestrator_cancel("thr_x")
    assert out == {"cancelled_interrupts": 2}
    req = recorder.requests[0]
    assert req.method == "DELETE"
    assert req.url.path == "/runs/thr_x"


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_inbox_no_filter(recorder):
    recorder.script(_json([{"interrupt_id": "int_a"}]))
    out = await mcp_server.orchestrator_inbox()
    assert out == [{"interrupt_id": "int_a"}]
    req = recorder.requests[0]
    assert req.url.path == "/inbox"
    # No workflow_thread_id param.
    assert "workflow_thread_id" not in req.url.params


@pytest.mark.asyncio
async def test_orchestrator_inbox_with_thread_filter(recorder):
    recorder.script(_json([]))
    await mcp_server.orchestrator_inbox(workflow_thread_id="thr_x")
    req = recorder.requests[0]
    assert req.url.params["workflow_thread_id"] == "thr_x"


@pytest.mark.asyncio
async def test_orchestrator_get_interrupt_filters_inbox(recorder):
    recorder.script(
        _json(
            [
                {"interrupt_id": "int_a", "status": "pending"},
                {"interrupt_id": "int_b", "status": "pending"},
            ]
        )
    )
    out = await mcp_server.orchestrator_get_interrupt("int_b")
    assert out["interrupt_id"] == "int_b"


@pytest.mark.asyncio
async def test_orchestrator_get_interrupt_raises_when_missing(recorder):
    recorder.script(_json([{"interrupt_id": "int_a"}]))
    with pytest.raises(Exception, match="not found"):
        await mcp_server.orchestrator_get_interrupt("int_b")


# ---------------------------------------------------------------------------
# PI response endpoints — these are the contract that locks the Phase-2.4
# v1 regression. Each tool MUST hit the type-correct endpoint; the server
# emits the resume token.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_accept_posts_to_accept_endpoint(recorder):
    recorder.script(_json({"status": "resuming"}))
    await mcp_server.orchestrator_accept("int_x")
    req = recorder.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/inbox/int_x/accept"
    # Phase D2: MCP binary MUST send wait_segment=false so the HTTP call
    # returns immediately after the answer commit (background-tasks the
    # graph segment). Otherwise the 600s API_TIMEOUT can still trip on a
    # particularly slow LLM segment.
    assert req.url.params["wait_segment"] == "false"


@pytest.mark.asyncio
async def test_orchestrator_reject_posts_with_reason(recorder):
    recorder.script(_json({"status": "resuming"}))
    await mcp_server.orchestrator_reject("int_x", reason="wrong scope")
    req = recorder.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/inbox/int_x/reject"
    assert req.url.params["wait_segment"] == "false"
    assert json.loads(req.content) == {"reason": "wrong scope"}


@pytest.mark.asyncio
async def test_orchestrator_reject_with_no_reason(recorder):
    recorder.script(_json({}))
    await mcp_server.orchestrator_reject("int_x")
    body = json.loads(recorder.requests[0].content)
    assert body == {"reason": None}


@pytest.mark.asyncio
async def test_orchestrator_correct_posts_text(recorder):
    recorder.script(_json({"status": "resuming"}))
    await mcp_server.orchestrator_correct(
        "int_x", response_text="redirect to plan C"
    )
    req = recorder.requests[0]
    assert req.url.path == "/inbox/int_x/correct"
    assert req.url.params["wait_segment"] == "false"
    assert json.loads(req.content) == {"response_text": "redirect to plan C"}


@pytest.mark.asyncio
async def test_orchestrator_correct_rejects_empty(recorder):
    with pytest.raises(ValueError, match="non-empty"):
        await mcp_server.orchestrator_correct("int_x", response_text="")
    with pytest.raises(ValueError, match="non-empty"):
        await mcp_server.orchestrator_correct("int_x", response_text="   ")
    # No HTTP call was made.
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_orchestrator_health(recorder):
    recorder.script(_json({"status": "ok"}))
    out = await mcp_server.orchestrator_health()
    assert out == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tool registry — every public surface lives under orchestrator_ prefix
# and is registered with FastMCP.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_tools_use_orchestrator_prefix():
    """Catch accidental cross-namespace tool naming."""
    tools = await mcp_server.mcp.list_tools()
    names = [t.name for t in tools]
    assert names, "expected at least one tool"
    bad = [n for n in names if not n.startswith("orchestrator_")]
    assert not bad, f"tools missing prefix: {bad}"


@pytest.mark.asyncio
async def test_expected_tool_surface_is_present():
    expected = {
        "orchestrator_run_start",
        "orchestrator_list_runs",
        "orchestrator_get_run",
        "orchestrator_cancel",
        "orchestrator_inbox",
        "orchestrator_get_interrupt",
        "orchestrator_accept",
        "orchestrator_reject",
        "orchestrator_correct",
        "orchestrator_health",
    }
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}
    missing = expected - names
    assert not missing, f"missing tools: {missing}"
