"""MCP stdio server — thin HTTP proxy to the orchestrator REST API.

This is the binary registered in Claude Desktop / Claude Code as a second
MCP server, alongside `rka`. It exposes the orchestrator surface (run a
mission, list parked PI interrupts, accept/reject/correct) to the PI's
Claude session — so the PI never leaves Claude Code to drive the
LangGraph workflow.

Tools (all prefixed `orchestrator_` for namespace isolation):

  orchestrator_run_start(mission_id, project_id, budget_usd?)
  orchestrator_list_runs(status?, limit?)
  orchestrator_get_run(workflow_thread_id)
  orchestrator_cancel(workflow_thread_id)
  orchestrator_inbox(workflow_thread_id?)
  orchestrator_get_interrupt(interrupt_id)
  orchestrator_accept(interrupt_id)
  orchestrator_reject(interrupt_id, reason?)
  orchestrator_correct(interrupt_id, response_text)

The server reads `ORCHESTRATOR_API_URL` (default
`http://localhost:9713`) — same pattern as `rka/mcp/server.py` proxies
to `http://localhost:9712`.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

API_URL = os.environ.get("ORCHESTRATOR_API_URL", "http://localhost:9713")
API_TIMEOUT = float(os.environ.get("ORCHESTRATOR_API_TIMEOUT", "120"))

ORCHESTRATOR_INSTRUCTIONS = """\
RKA orchestrator MCP — start and supervise LangGraph workflows.

Workflow: orchestrator_run_start(mission_id) kicks off a run; the
orchestrator parks PI interrupts in an inbox. The PI session (this
session, when in PI mode) calls orchestrator_inbox() to see waiting
items, renders them, and uses orchestrator_accept / orchestrator_reject
/ orchestrator_correct to respond.

CRITICAL — Ratification: orchestrator_accept on a `pi_decision_select`
interrupt authorizes the orchestrator to dispatch the proposed RKA
writes (rka_add_*, rka_update_*, etc.). Always perform a two-tap
confirmation before calling orchestrator_accept on pi_decision_select:
render the proposed actions, ask the user explicitly, and only then
call accept.

Response routing: the server emits the type-correct resume token for
each interrupt type — callers do NOT supply raw strings, so the
Phase-2.4 v1 driver bug ('accept' for greenlight routes to escalation)
is impossible at this surface.
"""

mcp = FastMCP("rka-orchestrator", instructions=ORCHESTRATOR_INSTRUCTIONS)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API_URL, timeout=API_TIMEOUT)


def _raise_with_detail(r: httpx.Response) -> None:
    if r.is_success:
        return
    try:
        detail = r.json().get("detail", r.text)
    except Exception:  # noqa: BLE001
        detail = r.text
    raise Exception(f"Orchestrator API error {r.status_code}: {detail}")


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


@mcp.tool()
async def orchestrator_run_start(
    mission_id: str,
    project_id: str,
    budget_usd: float = 5.0,
    workflow_thread_id: Optional[str] = None,
) -> dict:
    """Start a new orchestrator workflow.

    Kicks off the Brain ⇄ Executor ⇄ PI LangGraph topology against the
    given RKA mission. Returns immediately when the graph parks at its
    first PI interrupt (or completes if there are none).

    Args:
        mission_id: RKA mission id (mis_…) the orchestrator should execute.
        project_id: RKA project id (prj_…) scoping the mission.
        budget_usd: USD cap on LLM spend. Default 5.0.
        workflow_thread_id: Optional explicit thread id. Auto-generated
            if omitted (`thr_<unix-ms-hex><uuid-hex>`).

    Returns:
        {workflow_thread_id, parked_interrupt_id?, parked_interrupt_type?,
         terminal_state?, current_node, usd_spent, final_report_id?}
    """
    async with _client() as c:
        r = await c.post(
            "/runs",
            json={
                "mission_id": mission_id,
                "project_id": project_id,
                "budget_usd": budget_usd,
                "workflow_thread_id": workflow_thread_id,
            },
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_list_runs(
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List orchestrator workflow runs.

    Args:
        status: Filter by run status — running | awaiting_pi | complete |
            escalated | failed | cancelled. Omit for all.
        limit: Max rows to return. Default 50.
    """
    params: dict = {"limit": limit}
    if status:
        params["status"] = status
    async with _client() as c:
        r = await c.get("/runs", params=params)
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_get_run(workflow_thread_id: str) -> dict:
    """Get detail for one workflow run."""
    async with _client() as c:
        r = await c.get(f"/runs/{workflow_thread_id}")
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_cancel(workflow_thread_id: str) -> dict:
    """Cancel a workflow run. Marks all pending interrupts as cancelled
    and the run as cancelled. Returns the count of cancelled interrupts."""
    async with _client() as c:
        r = await c.delete(f"/runs/{workflow_thread_id}")
        _raise_with_detail(r)
        return r.json()


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


@mcp.tool()
async def orchestrator_inbox(
    workflow_thread_id: Optional[str] = None,
) -> list[dict]:
    """List pending PI interrupts.

    Each item carries the structured payload the graph produced — `type`,
    `title`, `items`, `total_items`, and (for batched payloads >10 items)
    `batched: true, page_size: 10`.

    Args:
        workflow_thread_id: If set, only interrupts for this run.

    Returns:
        List of {interrupt_id, workflow_thread_id, mission_id,
        interrupt_type, status, payload, parked_at}.
    """
    params: dict = {}
    if workflow_thread_id:
        params["workflow_thread_id"] = workflow_thread_id
    async with _client() as c:
        r = await c.get("/inbox", params=params)
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_get_interrupt(interrupt_id: str) -> dict:
    """Fetch one parked interrupt (including answered/cancelled ones).

    Useful for replay/audit. Returns 404 if not found.
    """
    # The server doesn't have a direct /interrupts/{id} route — use the
    # inbox listing and filter, falling back to a not-found.
    async with _client() as c:
        r = await c.get("/inbox")
        _raise_with_detail(r)
        for item in r.json():
            if item["interrupt_id"] == interrupt_id:
                return item
    raise Exception(f"interrupt {interrupt_id!r} not found in pending inbox")


# ---------------------------------------------------------------------------
# PI response endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def orchestrator_accept(interrupt_id: str) -> dict:
    """PI accepts the interrupt — graph resumes with the type-correct
    accept token.

    For `pi_greenlight`: emits "approve" → routes to backbrief_draft.
    For `pi_decision_select`: emits "accept" → routes to
        execute_ratified_actions (which dispatches the PI-ratified
        proposed_actions to RKA via WRITE_TOOLS). *Always confirm with
        the user explicitly before calling this on pi_decision_select.*
    For `pi_acceptance`: emits "accept" → terminal_state=complete.

    Returns the next segment's outcome (next interrupt parked OR
    terminal_state). 409 if the interrupt was already answered.
    """
    async with _client() as c:
        r = await c.post(f"/inbox/{interrupt_id}/accept")
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_reject(
    interrupt_id: str,
    reason: Optional[str] = None,
) -> dict:
    """PI rejects the interrupt — graph routes to escalation_router.

    Args:
        interrupt_id: The interrupt to reject.
        reason: Optional human note recorded with the response. Does not
            change routing; the graph sees only the literal token
            "reject".
    """
    async with _client() as c:
        r = await c.post(f"/inbox/{interrupt_id}/reject", json={"reason": reason})
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_correct(
    interrupt_id: str,
    response_text: str,
) -> dict:
    """PI redirects the interrupt — graph resumes with the freeform
    text as the response.

    The graph's routing functions substring-match on "approve" / "accept";
    a correction that doesn't include those tokens routes to
    escalation_router (which is the correct semantic — the PI is
    redirecting, not approving). If the PI wants to approve WITH
    notes, they should call orchestrator_accept instead.

    Args:
        interrupt_id: The interrupt to redirect.
        response_text: PI's freeform direction. Must be non-empty.
    """
    if not response_text or not response_text.strip():
        raise ValueError("response_text must be non-empty")
    async with _client() as c:
        r = await c.post(
            f"/inbox/{interrupt_id}/correct",
            json={"response_text": response_text},
        )
        _raise_with_detail(r)
        return r.json()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@mcp.tool()
async def orchestrator_health() -> dict:
    """Check that the orchestrator daemon is reachable.

    Returns the server's /health response. Useful as a smoke-test at PI
    session start before calling any other orchestrator_ tool.
    """
    async with _client() as c:
        r = await c.get("/health")
        _raise_with_detail(r)
        return r.json()


# ---------------------------------------------------------------------------
# Phase D5c — Onboarding subgraph entry points
# ---------------------------------------------------------------------------


@mcp.tool()
async def orchestrator_onboard_start(
    project_id: str,
    workflow_thread_id: Optional[str] = None,
) -> dict:
    """Kick off the onboarding subgraph for a project.

    Different from `orchestrator_run_start` which executes a mission:
    this drives the project-scoped onboarding wizard that produces the
    project's `tools.json` baseline manifest.

    Flow once started:
      1. Daemon parks at `pi_onboarding_topic` — claude renders the
         topic-elicitation prompt and asks the PI.
      2. PI responds; daemon resumes, Brain builds proposed_toolkit,
         parks at `pi_toolkit_ratify`.
      3. PI ratifies (set-identity); daemon writes
         `~/rka-projects/{project_id}/tools.json` and a `.env` template,
         parks at `pi_credentials_ready`.
      4. PI edits the .env, signals "ready"; daemon probes each secret
         and either escalates required failures or emits the audit
         journal entry, completing the workflow.

    Args:
        project_id: RKA project id (prj_…) to onboard. The project
            must exist in RKA (orchestrator does NOT create the
            project itself — that's an upstream `rka_create_project`
            call).
        workflow_thread_id: Optional explicit thread id. Auto-
            generated if omitted.

    Returns the same outcome shape as orchestrator_run_start
    (`workflow_thread_id`, `parked_interrupt_id`, `parked_interrupt_type`,
    etc.). The PI session typically calls `orchestrator_inbox` next to
    render the parked interrupt.
    """
    async with _client() as c:
        r = await c.post(
            "/onboard",
            json={
                "project_id": project_id,
                "workflow_thread_id": workflow_thread_id,
            },
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_get_manifest(project_id: str) -> dict:
    """Return the project's current effective tool manifest.

    The effective manifest is the baseline (set by initial onboarding)
    merged with any per-mission extensions written via
    `pi_extend_toolkit` (Phase D6). Useful for the PI session to
    answer "what tools is this project configured to use?"

    Raises 404 if the project hasn't been onboarded yet.
    """
    async with _client() as c:
        r = await c.get(f"/projects/{project_id}/manifest")
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_get_zotero_collection(project_id: str) -> dict:
    """Return the Zotero collection key + name for this project's literature.

    Brain + Executor pass the returned `zotero_collection_key` to
    `zotero_search` / `zotero_get_items_in_collection` (from zotero-mcp)
    to retrieve only this project's papers — not the whole library.

    The PI uses the Zotero Connector browser extension to save papers
    into this collection while authenticated to publisher sites via
    their institutional SSO.

    Raises 404 if the project hasn't been onboarded or Zotero env vars
    weren't configured when it ran.
    """
    async with _client() as c:
        r = await c.get(f"/projects/{project_id}/zotero_collection")
        _raise_with_detail(r)
        return r.json()


# ---------------------------------------------------------------------------
# Phase B — orchestrator-level credential bootstrap
# ---------------------------------------------------------------------------


@mcp.tool()
async def orchestrator_bootstrap_start(
    workflow_thread_id: Optional[str] = None,
) -> dict:
    """Kick off the orchestrator-level credential bootstrap (Phase B).

    Use this on a fresh install BEFORE any project exists. Phase B
    handles the credentials in `orchestrator/.env` that the daemon
    itself needs (Claude OAuth or API key, plus optional Semantic
    Scholar / SerpAPI / OpenAlex polite-pool email).

    Distinct from `orchestrator_onboard_start`, which handles per-
    project credentials under `~/rka-projects/<id>/.env`.

    Flow once started:
      1. Daemon parks at `pi_bootstrap_intent` — claude renders the
         intent-elicitation prompt ("describe your install state").
      2. PI responds; daemon resumes, runs `propose_for_intent`, parks
         at `pi_bootstrap_ratify` with the shortlist.
      3. PI ratifies; daemon writes `orchestrator/.env.example` with
         annotated slots, parks at `pi_bootstrap_fill_ack`.
      4. PI edits `orchestrator/.env` and signals "ready"; daemon
         probes each filled key (without logging values) and reports
         pass/fail, completing the workflow.

    Args:
        workflow_thread_id: Optional explicit thread id.

    Returns the same outcome shape as orchestrator_run_start. The PI
    session typically calls `orchestrator_inbox` next to render the
    parked interrupt.
    """
    async with _client() as c:
        r = await c.post(
            "/bootstrap",
            json={"workflow_thread_id": workflow_thread_id},
        )
        _raise_with_detail(r)
        return r.json()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Stdio entry point — used by Claude Desktop's MCP launcher."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
