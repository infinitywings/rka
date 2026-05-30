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

        # Background-task registry. Async-resume segments (wait_segment=false)
        # are scheduled as fire-and-forget asyncio tasks; without retaining a
        # strong reference they can be garbage-collected mid-run (Python's
        # event loop only keeps weak references to Tasks). We add to the set
        # on creation and discard on completion via add_done_callback.
        app.state.bg_segments: set[asyncio.Task] = set()

        # Startup recovery sweep — runs left in 'running' from a previous
        # process can never make progress (no in-process task is driving
        # them). Mark them 'failed' with last_error so /runs surfaces the
        # state to the PI instead of showing them as live work in flight.
        # Conservative: only sweep on cold-start; don't touch 'awaiting_pi'
        # rows (those are durably parked and resumable when the PI responds).
        try:
            orphan_count = app.state.store.reap_orphaned_running_runs(
                last_error="daemon restarted while segment in flight"
            )
            if orphan_count:
                logger.warning(
                    "startup sweep: reaped %d run(s) left in 'running' from "
                    "previous process", orphan_count,
                )
        except Exception:  # noqa: BLE001 — best-effort; don't block startup
            logger.exception("startup sweep failed (non-fatal); continuing")

        logger.info(
            "orchestrator-server ready: db=%s saver=%s rka_url=%s",
            resolved_db_path, resolved_saver_path, resolved_rka_url,
        )
        try:
            yield
        finally:
            # Graceful drain: wait briefly for in-flight background segments
            # to finish their next interrupt-park or terminal; if they don't
            # complete in time, cancel them. The store's reap-on-startup
            # handles the corresponding workflow_runs rows on next boot.
            pending = list(app.state.bg_segments)
            if pending:
                logger.info(
                    "lifespan shutdown: draining %d background segment(s)",
                    len(pending),
                )
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "lifespan shutdown: background segments did not "
                        "drain in 30s; cancelling and leaving recovery to "
                        "next startup sweep"
                    )
                    for t in pending:
                        t.cancel()
            if store is None:
                app.state.store.close()

    app = FastAPI(title="rka-orchestrator", lifespan=lifespan)

    # -----------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------

    @app.get("/health")
    async def health(request: Request) -> dict:
        return {"status": "ok", "db_path": resolved_db_path}

    def _background_segment(
        request: Request,
        thread_id: str,
        coro_factory,
        *,
        log_tag: str,
    ) -> None:
        """Shared helper for /runs, /onboard, /bootstrap, /inbox/.../*
        async-resume paths. Schedules `coro_factory()` (a callable
        returning an awaitable) as a tracked asyncio task and wires
        last_error + bg_segments lifecycle. Errors land in
        workflow_runs.last_error so the PI can discover them by polling
        /runs/{id}."""
        store_ = request.app.state.store

        async def _drive() -> None:
            try:
                await coro_factory()
            except asyncio.CancelledError:
                logger.info(
                    "background %s cancelled for thread %s", log_tag, thread_id,
                )
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "background %s failed for thread %s", log_tag, thread_id,
                )
                try:
                    store_.update_run(
                        thread_id,
                        status="failed",
                        last_error=f"background {log_tag} crashed: {e!r}"[:500],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "failed to write last_error for thread %s", thread_id,
                    )

        task = asyncio.create_task(_drive())
        request.app.state.bg_segments.add(task)
        task.add_done_callback(request.app.state.bg_segments.discard)

    @app.post("/runs")
    async def start_run(
        req: StartRunRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        """Start a new mission run.

        wait_segment=True (default): synchronous — run create + load
            mission + drive the graph until the first interrupt or
            terminal. Used by tests and any caller that can tolerate
            minutes-long HTTP calls.

        wait_segment=False: commit the run row + load mission
            synchronously, return a `{status: "starting"}` ack
            immediately, and drive the first segment as a background
            task. Used by the MCP-stdio binary so the PI's Claude
            session doesn't time out while the Brain's strategy_node
            + confirmation_brief LLM calls run (typically minutes).
            The PI polls /runs/{id} and /inbox to discover the first
            parked interrupt or terminal state.
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
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

        # async-start path
        try:
            ack = await asyncio.to_thread(
                runner_.start_run_commit,
                mission_id=req.mission_id,
                project_id=req.project_id,
                budget_usd=req.budget_usd,
                workflow_thread_id=req.workflow_thread_id,
            )
        except MissionNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

        _background_segment(
            request,
            ack["workflow_thread_id"],
            lambda: asyncio.to_thread(
                runner_.start_run_drive,
                workflow_thread_id=ack["workflow_thread_id"],
                project_id=ack["project_id"],
                mission_id=ack["mission_id"],
                motivated_by_decision_id=ack["motivated_by_decision_id"],
            ),
            log_tag="start_run",
        )
        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "mission_id": ack["mission_id"],
            "project_id": ack["project_id"],
            "status": "starting",
            "wait_segment": False,
        }

    @app.post("/onboard")
    async def start_onboarding(
        req: StartOnboardingRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        """Phase D5c: kick off the onboarding subgraph for a project.

        Same wait_segment semantics as /runs — default True (sync) for
        tests, False (background-task the first segment) for the MCP-stdio
        binary. PI polls /inbox to render the first interrupt
        (pi_onboarding_topic).
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            outcome = await asyncio.to_thread(
                runner_.start_onboarding,
                project_id=req.project_id,
                workflow_thread_id=req.workflow_thread_id,
            )
            return _outcome_dict(outcome)

        ack = await asyncio.to_thread(
            runner_.start_onboarding_commit,
            project_id=req.project_id,
            workflow_thread_id=req.workflow_thread_id,
        )
        _background_segment(
            request,
            ack["workflow_thread_id"],
            lambda: asyncio.to_thread(
                runner_.start_onboarding_drive,
                workflow_thread_id=ack["workflow_thread_id"],
                project_id=ack["project_id"],
            ),
            log_tag="start_onboarding",
        )
        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "project_id": ack["project_id"],
            "status": "starting",
            "wait_segment": False,
        }

    @app.post("/bootstrap")
    async def start_bootstrap(
        req: StartBootstrapRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        """Phase B: kick off the orchestrator-level credential bootstrap.

        Same wait_segment semantics as /runs. The PI polls /inbox to
        render the first interrupt (pi_bootstrap_intent).
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            outcome = await asyncio.to_thread(
                runner_.start_phase_b,
                workflow_thread_id=req.workflow_thread_id,
            )
            return _outcome_dict(outcome)

        ack = await asyncio.to_thread(
            runner_.start_phase_b_commit,
            workflow_thread_id=req.workflow_thread_id,
        )
        _background_segment(
            request,
            ack["workflow_thread_id"],
            lambda: asyncio.to_thread(
                runner_.start_phase_b_drive,
                workflow_thread_id=ack["workflow_thread_id"],
            ),
            log_tag="start_phase_b",
        )
        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "status": "starting",
            "wait_segment": False,
        }

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
    async def accept(
        interrupt_id: str, request: Request, wait_segment: bool = True
    ) -> dict:
        return await _respond(
            request, interrupt_id, "accept", None, wait_segment=wait_segment
        )

    @app.post("/inbox/{interrupt_id}/reject")
    async def reject(
        interrupt_id: str,
        body: RejectRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        return await _respond(
            request,
            interrupt_id,
            "reject",
            body.reason,
            wait_segment=wait_segment,
        )

    @app.post("/inbox/{interrupt_id}/correct")
    async def correct(
        interrupt_id: str,
        body: CorrectRequest,
        request: Request,
        wait_segment: bool = True,
    ) -> dict:
        return await _respond(
            request,
            interrupt_id,
            "correct",
            body.response_text,
            wait_segment=wait_segment,
        )

    async def _respond(
        request: Request,
        interrupt_id: str,
        action: str,
        response_text: Optional[str],
        *,
        wait_segment: bool,
    ) -> dict:
        """Drive a PI response into the runner.

        wait_segment=True (legacy): commit answer + run the graph
            segment synchronously, return the SegmentOutcome. Used by
            tests + any caller that can tolerate a long-running HTTP
            call (segments are LLM-driven and can run for minutes).

        wait_segment=False: commit the answer synchronously, return an
            ack immediately, and run the graph segment on a background
            task. Used by the MCP-stdio binary so the PI's Claude
            session is never blocked by a 120s httpx timeout while the
            server is happily working. The PI session polls
            `/inbox` and `/runs/{id}` to discover the next state.
        """
        runner_: OrchestratorRunner = request.app.state.runner
        if wait_segment:
            try:
                outcome = await asyncio.to_thread(
                    runner_.respond,
                    interrupt_id=interrupt_id,
                    action=action,
                    response_text=response_text,
                )
            except ValueError as e:
                msg = str(e)
                if "not found" in msg:
                    raise HTTPException(status_code=404, detail=msg)
                if "already in status" in msg:
                    raise HTTPException(status_code=409, detail=msg)
                raise HTTPException(status_code=400, detail=msg)
            return _outcome_dict(outcome)

        # async-resume path: commit synchronously, background the segment.
        try:
            ack = await asyncio.to_thread(
                runner_.commit_response,
                interrupt_id=interrupt_id,
                action=action,
                response_text=response_text,
            )
        except ValueError as e:
            msg = str(e)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg)
            if "already in status" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

        # Background-task the segment. runner._execute_segment catches
        # exceptions raised by compiled.invoke and writes them to
        # workflow_runs.last_error itself; but exceptions raised BEFORE
        # invoke (factory/compile/saver instantiation in resume_segment)
        # would otherwise be swallowed and leave status='running' forever.
        # The except clause below covers that gap by writing last_error
        # explicitly so the PI's `/runs/{id}` shows the failure.
        store_ = request.app.state.store

        async def _drive_segment_bg(ack_: dict) -> None:
            try:
                await asyncio.to_thread(
                    runner_.resume_segment,
                    workflow_thread_id=ack_["workflow_thread_id"],
                    interrupt_type=ack_["interrupt_type"],
                    token=ack_["token"],
                    project_id=ack_["project_id"],
                )
            except asyncio.CancelledError:
                # Lifespan shutdown cancelled us; the startup-sweep on
                # next boot will surface the orphan. Re-raise per asyncio
                # convention.
                logger.info(
                    "background segment cancelled for thread %s",
                    ack_["workflow_thread_id"],
                )
                raise
            except Exception as e:  # noqa: BLE001 — background; surface via last_error
                logger.exception(
                    "background segment failed for thread %s after answering "
                    "interrupt %s",
                    ack_["workflow_thread_id"], ack_["interrupt_id"],
                )
                # Write the failure to workflow_runs.last_error so the PI's
                # poll of /runs/{id} surfaces it instead of seeing a stuck
                # status='running'.
                try:
                    store_.update_run(
                        ack_["workflow_thread_id"],
                        status="failed",
                        last_error=f"background segment crashed: {e!r}"[:500],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "failed to write last_error for thread %s",
                        ack_["workflow_thread_id"],
                    )

        task = asyncio.create_task(_drive_segment_bg(ack))
        # Retain a strong reference so the GC doesn't collect the task
        # mid-run; discard on completion to bound memory.
        request.app.state.bg_segments.add(task)
        task.add_done_callback(request.app.state.bg_segments.discard)

        return {
            "workflow_thread_id": ack["workflow_thread_id"],
            "answered_interrupt_id": ack["interrupt_id"],
            "answered_interrupt_type": ack["interrupt_type"],
            "status": "resuming",
            "wait_segment": False,
        }

    return app
