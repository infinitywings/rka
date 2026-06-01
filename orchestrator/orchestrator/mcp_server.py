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
# Default 600s (10min) — defense-in-depth headroom over the empirical 4-min
# segment ceiling that previously tripped the 120s client timeout. The
# accept/reject/correct endpoints background the graph segment so this
# timeout only covers the synchronous answer-commit (~ms), but read-side
# endpoints (/inbox, /runs) and any explicit wait_segment=true caller can
# legitimately need minutes.
API_TIMEOUT = float(os.environ.get("ORCHESTRATOR_API_TIMEOUT", "600"))

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
    """Build an AsyncClient with HTTP keep-alive disabled.

    See `rka/mcp/server.py:_client` for the full rationale. Same bug, same
    fix: macOS Docker Desktop bridge connections to the daemon (here, the
    orchestrator daemon on 9713) can wedge in CLOSE_WAIT after the server
    closes its side, and the default httpx pool tries to reuse the stale
    entry on the next call, blocking until the OS times it out. Disabling
    keep-alive (`max_keepalive_connections=0`) forces a fresh TCP connection
    per call. Empirically observed on `orchestrator_correct` after several
    successful calls in the same session.
    """
    return httpx.AsyncClient(
        base_url=API_URL,
        timeout=API_TIMEOUT,
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=10),
    )


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
    run_instructions: Optional[str] = None,
) -> dict:
    """Start a new orchestrator workflow.

    Kicks off the Brain ⇄ Executor ⇄ PI LangGraph topology against the
    given RKA mission. Returns IMMEDIATELY after the run row is created
    + the mission spec is loaded — the first graph segment (Brain
    strategy_node + confirmation_brief, typically 2 LLM calls = minutes)
    runs as a background task. Poll `orchestrator_get_run` and
    `orchestrator_inbox` to discover the first parked interrupt or
    terminal state.

    Args:
        mission_id: RKA mission id (mis_…) the orchestrator should execute.
        project_id: RKA project id (prj_…) scoping the mission.
        budget_usd: USD cap on LLM spend. Default 5.0.
        workflow_thread_id: Optional explicit thread id. Auto-generated
            if omitted (`thr_<unix-ms-hex><uuid-hex>`).
        run_instructions: Phase-X (Cross-Run Correction Channel) — optional
            per-run PI override text that supersedes contradicting framing
            in the mission body for THIS run only. Use this to declare
            run-level scope, budget intent, or other corrections without
            polluting the mission body. Brain renders it under a delimited
            "PI OVERRIDES (highest priority)" block at the top of the
            strategy prompt, alongside any auto-rehydrated prior
            pi_greenlight redirects for this mission. Redacted from the
            response (returned as "<set>" not the raw text) to avoid
            leaking to logs.

    Returns:
        {workflow_thread_id, mission_id, project_id, status: "starting",
         wait_segment: false, run_instructions: "<set>" | null}
    """
    async with _client() as c:
        r = await c.post(
            "/runs",
            params={"wait_segment": "false"},
            json={
                "mission_id": mission_id,
                "project_id": project_id,
                "budget_usd": budget_usd,
                "workflow_thread_id": workflow_thread_id,
                "run_instructions": run_instructions,
            },
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_cancel_overrides(mission_id: str) -> dict:
    """Phase-X PI escape valve — clear auto-rehydrated prior redirects
    for this mission.

    The orchestrator auto-rehydrates the most-recent pi_greenlight
    redirect responses for a mission into each new run's strategy prompt
    so the PI doesn't have to re-type corrections across run boundaries.
    Once the PI has confirmed those corrections are fully absorbed (e.g.,
    Brain's last brief reflected them correctly), call this tool to stamp
    `mission_metadata.overrides_cleared_at` so future runs start with a
    fresh slate (no prior_redirects in the override block).

    Manual `run_instructions` passed to a subsequent `orchestrator_run_start`
    still apply — this only clears the AUTO-rehydration, not the manual
    per-run channel.

    Args:
        mission_id: RKA mission id (mis_…) to clear overrides for.

    Returns:
        {mission_id, overrides_cleared_at: <ISO-8601 UTC timestamp>}
    """
    async with _client() as c:
        r = await c.post(f"/missions/{mission_id}/overrides/cancel")
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
    """Get detail for one workflow run.

    Returns the cached `workflow_runs` row (status, current_node,
    usd_spent, last_error, terminal_state, final_report_id, started_at,
    updated_at, run_overrides) PLUS a `live_state` overlay read from the
    LangGraph SqliteSaver checkpoint.

    **Why `live_state` matters (Phase-X² polish, 2026-06-01).** The
    `workflow_runs` row is a cache updated only at park/terminal
    boundaries; during a long-running segment (Brain backbrief /
    gate1_validation / mission_execute / Executor running Bash/Python)
    its `current_node`, `usd_spent`, and `run_overrides` fields are
    stale by minutes. The PI cockpit was misdiagnosing healthy
    long-running execution as "stalled" because the cached row stayed
    frozen between segment boundaries. `live_state` exposes the live
    LangGraph checkpoint so the PI can observe mid-segment progress:

      live_state.current_node          — what node the graph is at NOW
      live_state.current_phase         — workflow_phase enum
      live_state.usd_spent             — running spend (often higher
                                          than cached usd_spent)
      live_state.greenlight_redrafts   — Phase-X² in-run redraft counter
      live_state.run_overrides         — full mid-run override dict
                                          (cache only has start-of-run)
      live_state.proposed_actions      — Brain's pending PA list
                                          (before pi_decision_select)
      live_state.ratified_actions      — post-accept dispatch list
      live_state.interrupts_count      — for freshness comparison
      live_state.latest_interrupt_node — most recent pi_* node visited
      live_state.artifacts_count       — RKA writes journaled this run

    `live_state` is `None` when the saver isn't configured, the
    thread has no checkpoint yet (just-committed run pre-first-node),
    or the checkpoint file is missing. Returns `{"_error": "..."}`
    on a corrupted-checkpoint edge case — graceful degradation, the
    cached row is still returned alongside.
    """
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
    accept token. Returns immediately after the answer is committed
    (`status: "resuming"`); the graph segment runs on a background
    task. Poll `orchestrator_get_run` / `orchestrator_inbox` to
    discover the next state.

    For `pi_greenlight`: emits "approve" → routes to backbrief_draft.
    For `pi_decision_select`: emits "accept" → routes to
        execute_ratified_actions (which dispatches the PI-ratified
        proposed_actions to RKA via WRITE_TOOLS). *Always confirm with
        the user explicitly before calling this on pi_decision_select.*
    For `pi_acceptance`: emits "accept" → terminal_state=complete.

    Returns `{workflow_thread_id, answered_interrupt_id,
    answered_interrupt_type, status: "resuming", wait_segment: false}`.
    409 if the interrupt was already answered.
    """
    async with _client() as c:
        r = await c.post(
            f"/inbox/{interrupt_id}/accept",
            params={"wait_segment": "false"},
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_reject(
    interrupt_id: str,
    reason: Optional[str] = None,
) -> dict:
    """PI rejects the interrupt — graph routes to escalation_router.

    Returns immediately with `status: "resuming"`; the graph segment
    runs on a background task. Poll `orchestrator_get_run` /
    `orchestrator_inbox` to discover the next state.

    Args:
        interrupt_id: The interrupt to reject.
        reason: Optional human note recorded with the response. Does not
            change routing; the graph sees only the literal token
            "reject".
    """
    async with _client() as c:
        r = await c.post(
            f"/inbox/{interrupt_id}/reject",
            json={"reason": reason},
            params={"wait_segment": "false"},
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_correct(
    interrupt_id: str,
    response_text: str,
) -> dict:
    """PI redirects the interrupt — graph resumes with the freeform
    text as the response. Returns immediately after the answer is
    committed (`status: "resuming"`); the graph segment runs on a
    background task. Poll `orchestrator_get_run` /
    `orchestrator_inbox` to discover the next state.

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
            params={"wait_segment": "false"},
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

    Returns IMMEDIATELY after the run row is created — the first graph
    segment (Brain topic-elicitation prompt) runs as a background task.
    Poll `orchestrator_get_run` and `orchestrator_inbox` to discover the
    first parked interrupt (`pi_onboarding_topic`).

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
            params={"wait_segment": "false"},
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
    merged with any per-mission extensions written via a future mid-
    stream extension flow (Phase D6). Useful for the PI session to
    answer "what tools is this project configured to use?"

    Raises 404 if the project hasn't been onboarded yet.
    """
    async with _client() as c:
        r = await c.get(f"/projects/{project_id}/manifest")
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
async def orchestrator_extend_manifest(
    project_id: str, tool_name: str
) -> dict:
    """v2.6.0+agentic.4 — append a registry-known tool to an
    already-onboarded project's manifest in-place.

    Use case: a project was onboarded before a tool was added to the
    curated registry, OR the PI realizes mid-stream that a tool is
    needed (e.g., the empirical
    `prj_01KSMW9RBFXRY6HRRADH3SX7ZP` case where Zotero MCP was added
    to the registry in v2.6.0+agentic.3 but the project was onboarded
    a week earlier). Without this tool, the only fix was to re-run
    `orchestrator_onboard_start` — which goes through the full Phase D
    wizard and risks clobbering existing manifest customizations.

    Behavior:
      - Idempotent: returns `added: false` if the tool is already in
        the manifest (no mutation, no hash change).
      - Validates `tool_name` against the registry (400 if unknown).
      - Validates project has a baseline manifest (404 if onboarding
        never completed).
      - Recomputes manifest hash on successful append.

    Audit hygiene: this tool does NOT auto-write a journal entry.
    The PI session should call
    `rka_add_note(type='log', source='pi', verbatim_input='...')`
    after extending if a project-scoped audit record is desired.
    Keeps the daemon's role narrow (no per-project RKA project_id
    binding required from the orchestrator).

    Returns:
        {project_id, tool_name, added: bool, manifest_hash,
         total_tools, reason?: str}
    """
    async with _client() as c:
        r = await c.post(
            f"/projects/{project_id}/manifest/tools",
            json={"tool_name": tool_name},
        )
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

    Returns IMMEDIATELY after the run row is created — the first graph
    segment runs as a background task. Poll `orchestrator_get_run` and
    `orchestrator_inbox` to discover the first parked interrupt
    (`pi_bootstrap_intent`).

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
            params={"wait_segment": "false"},
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
