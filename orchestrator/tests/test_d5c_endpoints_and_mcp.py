"""Phase D, D5c — HTTP endpoints + MCP tools for onboarding.

Covers:
  - POST /onboard returns the SegmentOutcome shape
  - GET /projects/{id}/manifest returns the effective manifest
  - GET /projects/{id}/manifest 404s when no manifest on disk
  - MCP tools: orchestrator_onboard_start, orchestrator_get_manifest
    proxy correctly to the HTTP surface
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from orchestrator import manifest as M
from orchestrator import mcp_server
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import SegmentOutcome
from orchestrator.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    os.environ["RKA_PROJECTS_ROOT"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("RKA_PROJECTS_ROOT", None)


class _FakeRunner:
    """Spec-compatible with OrchestratorRunner — scripts outcomes for
    both start_run and start_onboarding."""

    def __init__(self, store: ParkedStore):
        self.store = store
        self.start_run_calls: list[dict] = []
        self.start_onboard_calls: list[dict] = []
        self._next_outcome: SegmentOutcome | None = None

    def script(self, outcome: SegmentOutcome) -> None:
        self._next_outcome = outcome

    def _consume(self) -> SegmentOutcome:
        assert self._next_outcome is not None, "scripted outcome required"
        out = self._next_outcome
        self._next_outcome = None
        return out

    def start_run(self, **kw):
        self.start_run_calls.append(kw)
        self.store.create_run(
            mission_id=kw["mission_id"],
            project_id=kw["project_id"],
            budget_usd=kw.get("budget_usd", 5.0),
        )
        return self._consume()

    def start_onboarding(self, **kw):
        self.start_onboard_calls.append(kw)
        self.store.create_run(
            mission_id=kw["project_id"],  # placeholder; mirror real runner
            project_id=kw["project_id"],
        )
        return self._consume()

    def respond(self, **kw):
        raise NotImplementedError

    def cancel(self, *args):
        raise NotImplementedError


@pytest.fixture
def setup(tmp_root):
    store = ParkedStore(":memory:")
    runner = _FakeRunner(store)
    app = create_app(store=store, runner=runner)
    client = TestClient(app)
    with client:
        yield client, store, runner
    store.close()


# ---------------------------------------------------------------------------
# POST /onboard
# ---------------------------------------------------------------------------


def test_post_onboard_returns_outcome(setup):
    client, store, runner = setup
    runner.script(
        SegmentOutcome(
            workflow_thread_id="thr_o",
            parked_interrupt_id="int_topic",
            parked_interrupt_type="pi_onboarding_topic",
            current_node="pi_onboarding_topic",
        )
    )
    r = client.post(
        "/onboard", json={"project_id": "prj_x"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parked_interrupt_id"] == "int_topic"
    assert body["parked_interrupt_type"] == "pi_onboarding_topic"
    # Runner.start_onboarding was called with the project_id.
    assert runner.start_onboard_calls == [
        {"project_id": "prj_x", "workflow_thread_id": None}
    ]


def test_post_onboard_honors_explicit_thread_id(setup):
    client, store, runner = setup
    runner.script(
        SegmentOutcome(
            workflow_thread_id="thr_explicit_o",
            parked_interrupt_id="int_p",
            parked_interrupt_type="pi_onboarding_topic",
        )
    )
    r = client.post(
        "/onboard",
        json={"project_id": "prj_x", "workflow_thread_id": "thr_explicit_o"},
    )
    assert r.status_code == 200
    assert runner.start_onboard_calls[0]["workflow_thread_id"] == "thr_explicit_o"


# ---------------------------------------------------------------------------
# GET /projects/{id}/manifest
# ---------------------------------------------------------------------------


def test_get_manifest_returns_loaded_manifest(setup, tmp_root):
    client, _store, _runner = setup
    # Plant a manifest on disk.
    m = M.ToolManifest(
        project_id="prj_with_manifest",
        topic=M.TopicMetadata(summary="test"),
        tools=[M.ToolDecl(name="rka", type="mcp_stdio", always_on=True)],
    )
    M.save_manifest(m)
    r = client.get("/projects/prj_with_manifest/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == "prj_with_manifest"
    assert body["manifest_type"] == "baseline"
    assert any(t["name"] == "rka" for t in body["tools"])


def test_get_manifest_404_when_no_baseline(setup, tmp_root):
    client, _store, _runner = setup
    r = client.get("/projects/prj_never_onboarded/manifest")
    assert r.status_code == 404
    assert "onboarding" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# MCP tools — proxy contract
# ---------------------------------------------------------------------------


class _Recorder:
    """Recreated from test_mcp_server.py — records httpx requests."""

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


@pytest.mark.asyncio
async def test_mcp_orchestrator_onboard_start_posts_to_onboard(recorder):
    recorder.script(
        _json(
            {
                "workflow_thread_id": "thr_o",
                "parked_interrupt_id": "int_topic",
                "parked_interrupt_type": "pi_onboarding_topic",
            }
        )
    )
    out = await mcp_server.orchestrator_onboard_start(project_id="prj_x")
    assert out["workflow_thread_id"] == "thr_o"
    req = recorder.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/onboard"
    body = json.loads(req.content)
    assert body == {"project_id": "prj_x", "workflow_thread_id": None}


@pytest.mark.asyncio
async def test_mcp_orchestrator_onboard_start_passes_thread_id(recorder):
    recorder.script(_json({"workflow_thread_id": "thr_t"}))
    await mcp_server.orchestrator_onboard_start(
        project_id="prj_x", workflow_thread_id="thr_t"
    )
    body = json.loads(recorder.requests[0].content)
    assert body["workflow_thread_id"] == "thr_t"


@pytest.mark.asyncio
async def test_mcp_orchestrator_get_manifest_returns_manifest(recorder):
    recorder.script(
        _json(
            {
                "project_id": "prj_x",
                "manifest_type": "baseline",
                "tools": [{"name": "rka"}],
            }
        )
    )
    out = await mcp_server.orchestrator_get_manifest(project_id="prj_x")
    assert out["project_id"] == "prj_x"
    req = recorder.requests[0]
    assert req.method == "GET"
    assert req.url.path == "/projects/prj_x/manifest"


@pytest.mark.asyncio
async def test_mcp_orchestrator_get_manifest_propagates_404(recorder):
    recorder.script(_json({"detail": "no manifest"}, status=404))
    with pytest.raises(Exception, match="404"):
        await mcp_server.orchestrator_get_manifest(project_id="prj_x")


@pytest.mark.asyncio
async def test_mcp_onboarding_tools_appear_in_registry():
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}
    assert "orchestrator_onboard_start" in names
    assert "orchestrator_get_manifest" in names
