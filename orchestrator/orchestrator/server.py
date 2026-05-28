"""FastAPI server — HTTP surface for the orchestrator daemon.

This is the daemon side of the Claude-Code-native PI workflow:

  POST   /runs                       — start a new workflow
  GET    /runs                       — list runs (active + recent)
  GET    /runs/{thread_id}           — run detail
  DELETE /runs/{thread_id}           — cancel
  GET    /inbox                      — list pending PI interrupts
  POST   /inbox/{interrupt_id}/accept   — PI accepts (server emits type-correct token)
  POST   /inbox/{interrupt_id}/reject   — PI rejects → escalation_router
  POST   /inbox/{interrupt_id}/correct  — PI redirects with freeform text
  GET    /health                     — liveness

The runner does the heavy work; this module is thin glue. Graph
invocation happens inside `asyncio.to_thread` so a long-running segment
(seconds-to-minutes for LLM calls) doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import (
    MissionNotFoundError,
    OrchestratorRunner,
    SegmentOutcome,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = os.environ.get(
    "ORCHESTRATOR_DB_PATH", "/data/orchestrator.db"
)
DEFAULT_SAVER_PATH = os.environ.get(
    "ORCHESTRATOR_SAVER_PATH", "/data/orchestrator-saver.db"
)
DEFAULT_RKA_URL = os.environ.get("RKA_API_URL", "http://rka:9712")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StartRunRequest(BaseModel):
    mission_id: str
    project_id: str
    budget_usd: float = 5.0
    workflow_thread_id: Optional[str] = None


class StartOnboardingRequest(BaseModel):
    project_id: str
    workflow_thread_id: Optional[str] = None


class StartBootstrapRequest(BaseModel):
    """Phase B: orchestrator-level credential bootstrap. No project_id;
    Phase B is daemon-level setup."""
    workflow_thread_id: Optional[str] = None


class CorrectRequest(BaseModel):
    response_text: str = Field(min_length=1)


class RejectRequest(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Outcome → dict serializer
# ---------------------------------------------------------------------------


def _outcome_dict(o: SegmentOutcome) -> dict:
    return {
        "workflow_thread_id": o.workflow_thread_id,
        "parked_interrupt_id": o.parked_interrupt_id,
        "parked_interrupt_type": o.parked_interrupt_type,
        "terminal_state": o.terminal_state,
        "current_node": o.current_node,
        "usd_spent": o.usd_spent,
        "final_report_id": o.final_report_id,
    }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _default_sdk_factory(project_id: str):
    """Build the real Claude Agent SDK client. Lazy import so tests that
    inject a fake factory don't trigger the SDK's import-time auth probe."""
    from orchestrator.llm_client import make_sdk

    return make_sdk(project_id=project_id)


def _default_mcp_factory(base_url: str):
    """Return a factory closure that builds a RestMCPClient per thread."""
    from orchestrator.mcp_client import make_client

    def _factory(thread_id: str, project_id: str):
        return make_client(
            workflow_thread_id=thread_id,
            base_url=base_url,
            project_id=project_id,
        )

    return _factory


def _default_saver_factory(saver_path: str):
    """Return a factory closure that opens a fresh SqliteSaver per call.

    Each call opens its own sqlite connection (thread-safe via
    check_same_thread=False inside open_checkpointer). The same file is
    safely reused across all runs — LangGraph's saver namespaces by
    thread_id internally.
    """
    from orchestrator import graph as graph_module

    def _factory(thread_id: str):
        # graph_module.open_checkpointer reads the saver_path even if
        # thread_id changes — the saver itself stores per-thread rows.
        return graph_module.open_checkpointer(saver_path)

    return _factory


def create_app(
    *,
    store: Optional[ParkedStore] = None,
    runner: Optional[OrchestratorRunner] = None,
    db_path: Optional[str] = None,
    saver_path: Optional[str] = None,
    rka_url: Optional[str] = None,
) -> FastAPI:
    """Construct the FastAPI app. All injection points are exposed for
    tests; defaults wire the production daemon."""

    resolved_db_path = db_path or DEFAULT_DB_PATH
    resolved_saver_path = saver_path or DEFAULT_SAVER_PATH
    resolved_rka_url = rka_url or DEFAULT_RKA_URL

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # If the caller injected store/runner, use those; else build them.
        if store is not None:
            app.state.store = store
        else:
            Path(resolved_db_path).parent.mkdir(parents=True, exist_ok=True)
            app.state.store = ParkedStore(resolved_db_path)

        if runner is not None:
            app.state.runner = runner
        else:
            app.state.runner = OrchestratorRunner(
                store=app.state.store,
                sdk_factory=_default_sdk_factory,
                mcp_factory=_default_mcp_factory(resolved_rka_url),
                saver_factory=_default_saver_factory(resolved_saver_path),
            )

        # Wire the workspace path resolver so manifest.workspace_dir()
        # consults project_workspaces (PI-provided paths) before falling
        # back to the hardcoded $HOME/rka-projects convention.
        from orchestrator import manifest as _M
        _M.set_workspace_path_resolver(
            lambda pid: app.state.store.get_project_workspace(pid)
        )
        logger.info(
            "orchestrator-server ready: db=%s saver=%s rka_url=%s",
            resolved_db_path, resolved_saver_path, resolved_rka_url,
        )
        try:
            yield
        finally:
            if store is None:
                app.state.store.close()

    app = FastAPI(title="rka-orchestrator", lifespan=lifespan)

    # -----------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------

    @app.get("/health")
    async def health(request: Request) -> dict:
        return {"status": "ok", "db_path": resolved_db_path}

    @app.post("/runs")
    async def start_run(req: StartRunRequest, request: Request) -> dict:
        runner_: OrchestratorRunner = request.app.state.runner
        try:
            outcome = await asyncio.to_thread(
                runner_.start_run,
                mission_id=req.mission_id,
                project_id=req.project_id,
                budget_usd=req.budget_usd,
                workflow_thread_id=req.workflow_thread_id,
            )
        except MissionNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return _outcome_dict(outcome)

    @app.post("/onboard")
    async def start_onboarding(
        req: StartOnboardingRequest, request: Request
    ) -> dict:
        """Phase D5c: kick off the onboarding subgraph for a project.

        Returns the same SegmentOutcome shape as /runs (workflow_thread_id +
        parked_interrupt_id/type or terminal_state). The PI's Claude
        session then polls /inbox to render the first interrupt
        (pi_onboarding_topic).
        """
        runner_: OrchestratorRunner = request.app.state.runner
        outcome = await asyncio.to_thread(
            runner_.start_onboarding,
            project_id=req.project_id,
            workflow_thread_id=req.workflow_thread_id,
        )
        return _outcome_dict(outcome)

    @app.post("/bootstrap")
    async def start_bootstrap(
        req: StartBootstrapRequest, request: Request
    ) -> dict:
        """Phase B: kick off the orchestrator-level credential bootstrap.

        Returns the SegmentOutcome shape (workflow_thread_id +
        parked_interrupt_id/type) for the first interrupt
        (`pi_bootstrap_intent`). The PI's Claude session polls
        /inbox to render the prompt and respond.
        """
        runner_: OrchestratorRunner = request.app.state.runner
        outcome = await asyncio.to_thread(
            runner_.start_phase_b,
            workflow_thread_id=req.workflow_thread_id,
        )
        return _outcome_dict(outcome)

    @app.get("/projects/{project_id}/zotero_collection")
    async def get_project_zotero_collection(
        project_id: str, request: Request
    ) -> dict:
        """Return the Zotero collection mapping for this project.

        The PI uses the Zotero Connector to save papers into this
        collection. Brain + Executor query zotero-mcp with the
        collection_key to retrieve only this project's papers.

        404 if the project hasn't been onboarded or Zotero wasn't
        configured at onboarding time.
        """
        store_: ParkedStore = request.app.state.store
        row = store_.get_project_manifest(project_id)
        if not row or not row.get("zotero_collection_key"):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"no Zotero collection registered for {project_id}. "
                    "Either onboarding hasn't run or Zotero env vars were "
                    "missing when it did."
                ),
            )
        return {
            "project_id": project_id,
            "zotero_collection_key": row["zotero_collection_key"],
            "zotero_collection_name": row.get("zotero_collection_name"),
            "workspace_path": row.get("workspace_path"),
        }

    @app.get("/projects/{project_id}/manifest")
    async def get_project_manifest(project_id: str, request: Request) -> dict:
        """Return the project's current effective manifest as JSON.

        Resolution order:
          1. project_workspaces.manifest_json in the orchestrator store
             (set by draft_manifest_node; doesn't depend on host FS)
          2. Fallback to compose_effective_manifest which reads from
             {workspace_path}/.rka/tools.json (requires bind mount or
             host-equivalent path access)
        """
        import json
        store_: ParkedStore = request.app.state.store
        row = store_.get_project_manifest(project_id)
        if row and row.get("manifest_json"):
            try:
                return json.loads(row["manifest_json"])
            except json.JSONDecodeError:
                pass  # corrupted; fall through to disk-based load

        from orchestrator import manifest as M
        manifest = M.compose_effective_manifest(project_id)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail=f"no manifest found for project {project_id} — has onboarding completed?",
            )
        return manifest.to_dict()

    @app.get("/runs")
    async def list_runs(
        request: Request, status: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        store_: ParkedStore = request.app.state.store
        return store_.list_runs(status=status, limit=limit)

    @app.get("/runs/{workflow_thread_id}")
    async def get_run(workflow_thread_id: str, request: Request) -> dict:
        store_: ParkedStore = request.app.state.store
        row = store_.get_run(workflow_thread_id)
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")
        return row

    @app.delete("/runs/{workflow_thread_id}")
    async def cancel_run(workflow_thread_id: str, request: Request) -> dict:
        store_: ParkedStore = request.app.state.store
        if store_.get_run(workflow_thread_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        runner_: OrchestratorRunner = request.app.state.runner
        count = runner_.cancel(workflow_thread_id)
        return {"cancelled_interrupts": count}

    @app.get("/inbox")
    async def inbox(
        request: Request, workflow_thread_id: Optional[str] = None
    ) -> list[dict]:
        store_: ParkedStore = request.app.state.store
        return store_.list_pending_interrupts(workflow_thread_id=workflow_thread_id)

    @app.post("/inbox/{interrupt_id}/accept")
    async def accept(interrupt_id: str, request: Request) -> dict:
        return await _respond(request, interrupt_id, "accept", None)

    @app.post("/inbox/{interrupt_id}/reject")
    async def reject(
        interrupt_id: str, body: RejectRequest, request: Request
    ) -> dict:
        return await _respond(request, interrupt_id, "reject", body.reason)

    @app.post("/inbox/{interrupt_id}/correct")
    async def correct(
        interrupt_id: str, body: CorrectRequest, request: Request
    ) -> dict:
        return await _respond(
            request, interrupt_id, "correct", body.response_text
        )

    async def _respond(
        request: Request,
        interrupt_id: str,
        action: str,
        response_text: Optional[str],
    ) -> dict:
        runner_: OrchestratorRunner = request.app.state.runner
        try:
            outcome = await asyncio.to_thread(
                runner_.respond,
                interrupt_id=interrupt_id,
                action=action,
                response_text=response_text,
            )
        except ValueError as e:
            # Distinguish "not found" (404) vs "already answered" (409).
            msg = str(e)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg)
            if "already in status" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=400, detail=msg)
        return _outcome_dict(outcome)

    return app
