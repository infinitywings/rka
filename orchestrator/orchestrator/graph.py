"""LangGraph topology + SqliteSaver checkpointer.

Wires all 18 mission-graph nodes into a flat `StateGraph` keyed on
`ResearchWorkflowState`. Phase 1 kept the topology single-thread +
linear-with-escalation-shortcuts; Phase-X² (`confirmation_brief_redraft`)
introduced the first cycle — a bounded back-edge for in-run pi_greenlight
redirects. No Send-API parallelism, no subgraphs. T7 deliverable.

Each node-callable is bound to its (sdk, mcp[, interrupt_fn]) dependencies
via `functools.partial`, so the function LangGraph receives accepts only
`(state,)` — keeping the engine-facing surface uniform.

Topology (18 mission-graph nodes; 7 conditional branches):

  START
    → strategy_node
    → confirmation_brief  ◄────────────────────────┐
    → pi_greenlight     ── approve → backbrief_draft
                       ├─ correct (sentinel) → confirmation_brief_redraft ┤
                       │                                                  │
                       │   (Phase-X²: redraft node mutates state, then    │
                       │    loops back to confirmation_brief — bounded   │
                       │    at MAX_GREENLIGHT_REDRAFTS; on cap-exceed    │
                       │    emits real ErrorRecord and falls to          │
                       │    escalation_router)                           │
                       └─ reject/other → escalation_router
    → backbrief_draft
    → gate1_validation  ── approved   → mission_execute
                       └─ redirected → escalation_router
    → mission_execute
    → budget_check      ── override → escalation_router
                       └─ default  → consensus_check
    → consensus_check   ── override → escalation_router
                       └─ default  → submit_report
    → submit_report
    → cluster_review
    → decision_present
    → pi_decision_select ── accept → execute_ratified_actions
                                       ── clean → execute_ratified_fs_actions
                                       └─ partial-dispatch → escalation_router
                         └─ else  → escalation_router
    → execute_ratified_fs_actions    # Gap 2 — parent-side FS dispatch
    → final_synthesis
    → pi_acceptance     → END
    escalation_router   → pi_acceptance
"""

from __future__ import annotations

import functools
import sqlite3
from typing import Any, Callable, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt as lg_interrupt

from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.nodes import brain, executor, pi, utility
from orchestrator.response_tokens import is_redirect_token
from orchestrator.state import ResearchWorkflowState


# ---------------------------------------------------------------------------
# Routing helpers (pure functions of state)
# ---------------------------------------------------------------------------


def _latest_interrupt_response(state: dict) -> str:
    interrupts = state.get("interrupts", [])
    if not interrupts:
        return ""
    return str(interrupts[-1].get("response", "")).lower()


def _route_after_pi_greenlight(state: dict) -> str:
    """Three-way routing at the first-look brief-ratification gate:

      approve (substring on a non-sentinel response)
          → backbrief_draft       (happy path, proceed to Backbrief)
      correct (REDIRECT_SENTINEL-prefixed response)
          → confirmation_brief_redraft  (Phase-X² in-run loop-back; Brain
            redrafts the brief with the PI's correction prepended to the
            prompt, then re-parks pi_greenlight for ratification.
            Bounded by MAX_GREENLIGHT_REDRAFTS — see
            brain.confirmation_brief_redraft.)
      reject / other (no sentinel, no "approve" substring)
          → escalation_router      (hard reject of the framing; PI is
            saying "this brief is fundamentally wrong, escalate")

    The sentinel short-circuit MUST stay at the TOP, before any
    substring match — closes the substring-smuggling class bug
    (Phase D2.1) where "I cannot approve this" would otherwise route
    to backbrief_draft. The fix is purely destination routing; the
    sentinel detection itself is unchanged.
    """
    response = _latest_interrupt_response(state)
    if is_redirect_token(response):
        return "confirmation_brief_redraft"
    return "backbrief_draft" if "approve" in response else "escalation_router"


def _route_after_confirmation_brief_redraft(state: dict) -> str:
    """Phase-X²: the redraft node sets next_node_override='escalation_router'
    when the redraft budget is exceeded (or on a defensive empty-redirect
    / missing-record case), emitting a real ErrorRecord first so
    escalation_router has a genuine error to classify. Happy path
    (budget OK + sanitized text present) loops back to
    confirmation_brief for the LLM redraft.
    """
    if state.get("next_node_override") == "escalation_router":
        return "escalation_router"
    return "confirmation_brief"


def _route_after_gate1(state: dict) -> str:
    verdict = state.get("gate1_verdict")
    return "mission_execute" if verdict == "approved" else "escalation_router"


def _route_after_budget_or_consensus(state: dict) -> str:
    """Both budget_check and consensus_check use `next_node_override`."""
    override = state.get("next_node_override")
    if override == "escalation_router":
        return "escalation_router"
    # Return the canonical "continue" target — the caller adds this to the mapping.
    return "__continue__"


def _route_after_pi_decision(state: dict) -> str:
    # Phase 2.7 T3f: on accept, route through execute_ratified_actions first
    # so any PI-ratified WRITE_TOOLS proposed by mission_execute land in RKA
    # before final_synthesis closes the run.
    #
    # v0.6.11: three-way distinction (mirrors _route_after_pi_greenlight):
    #   correct (REDIRECT_SENTINEL token) → mission_redraft (NEW in-run loop:
    #       Executor revises proposed_actions with the PI's correction, then
    #       re-renders decision_present + re-parks for ratification). Was:
    #       dead-ended at escalation_router, dropping the correction in-run.
    #   accept → execute_ratified_actions (dispatch the ratified writes)
    #   reject / other → escalation_router (hard reject)
    #
    # The sentinel short-circuit MUST stay at the TOP — prevents a PI
    # correction containing "accept" (e.g. "do not accept this — redo") from
    # bypassing the TWO-TAP gate via substring match.
    response = _latest_interrupt_response(state)
    if is_redirect_token(response):
        return "mission_redraft"
    return "execute_ratified_actions" if "accept" in response else "escalation_router"


def _route_after_mission_redraft(state: dict) -> str:
    """v0.6.11: the mission_redraft node sets next_node_override=
    'escalation_router' on cap-exceed / defensive escape (emitting a real
    classified ErrorRecord first). Happy path re-renders the decision via
    decision_present, which re-parks pi_decision_select for re-ratification.
    """
    if state.get("next_node_override") == "escalation_router":
        return "escalation_router"
    return "decision_present"


def _route_after_execute_ratified_actions(state: dict) -> str:
    """EC8 set-identity guard (Phase D2.4 empirical follow-up).

    Before this guard, execute_ratified_actions appended ErrorRecords for
    each failed WRITE_TOOLS dispatch BUT the graph then unconditionally
    advanced to final_synthesis → pi_acceptance, surfacing the failures
    only as an `error_count` in the pi_acceptance payload. Concrete
    impact observed on thr_19e790f90b4f9301179: PI ratified 4 actions,
    PA-3 (rka_submit_checkpoint) and PA-4 (rka_submit_report) failed
    with TypeError on an adapter signature mismatch — and the graph
    treated the run as "complete-class" instead of escalating. EC8 says
    ratified MUST equal proposed; partial dispatch violates the
    invariant and should escalate loud, not silently advance.

    Routing rule: if execute_ratified_actions accumulated ANY
    ErrorRecord with node_name='execute_ratified_actions', route to
    escalation_router so the PI sees the partial-dispatch failure as
    an escalation context (not buried in error_count on a pi_acceptance
    payload that looks complete). On clean dispatch (zero errors), or
    on no-op (state['ratified_actions'] was empty), proceed to
    final_synthesis as before.
    """
    errors = state.get("errors", []) or []
    erroring_actions = [
        e for e in errors
        if isinstance(e, dict)
        and e.get("node_name") == "execute_ratified_actions"
    ]
    if erroring_actions:
        return "escalation_router"
    return "final_synthesis"


# ---------------------------------------------------------------------------
# Node binding
# ---------------------------------------------------------------------------


def _bind(fn: Callable, sdk: SDKClient, mcp: MCPClient, **extras: Any) -> Callable:
    """Return a 1-arg LangGraph-facing callable.

    LangGraph nodes receive only `(state,)`; sdk + mcp (+ interrupt_fn for
    PI nodes) are bound at graph-construction time.
    """
    return functools.partial(fn, sdk=sdk, mcp=mcp, **extras)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph(
    *,
    sdk: SDKClient,
    mcp: MCPClient,
    checkpointer: Any | None = None,
    interrupt_fn: Callable[[dict], Any] = lg_interrupt,
):
    """Construct the compiled Phase 1 orchestrator graph.

    Args:
      sdk: a `SDKClient` implementation (production = Claude Agent SDK).
      mcp: a `MCPClient` implementation (production = stdio RKA MCP).
      checkpointer: LangGraph checkpointer instance. If `None`, the graph
        compiles uncheckpointed (useful for tests that don't need
        durability). Production callers pass a `SqliteSaver`.
      interrupt_fn: defaults to `langgraph.types.interrupt`; tests pass a
        fake to capture payloads without needing a running graph.

    Returns the compiled graph, ready to be `invoke()`d or `stream()`ed.
    """
    sg: StateGraph = StateGraph(ResearchWorkflowState)

    # ---- 7 Brain nodes (Phase-X² added confirmation_brief_redraft) ----
    sg.add_node("strategy_node", _bind(brain.strategy_node, sdk, mcp))
    sg.add_node("confirmation_brief", _bind(brain.confirmation_brief, sdk, mcp))
    # Phase-X² (In-Run Redraft Channel): owns the redraft policy
    # (extract latest pi_greenlight redirect → sanitize → cap →
    # increment counter). No LLM call here; downstream
    # confirmation_brief picks up the sanitized redirect text from
    # state['run_overrides']['in_run_redirects'].
    sg.add_node(
        "confirmation_brief_redraft",
        _bind(brain.confirmation_brief_redraft, sdk, mcp),
    )
    sg.add_node("decision_present", _bind(brain.decision_present, sdk, mcp))
    sg.add_node("cluster_review", _bind(brain.cluster_review, sdk, mcp))
    sg.add_node("gate1_validation", _bind(brain.gate1_validation, sdk, mcp))
    sg.add_node("final_synthesis", _bind(brain.final_synthesis, sdk, mcp))

    # ---- 4 Executor nodes (Phase 2.7 T3e added execute_ratified_actions) ----
    sg.add_node("backbrief_draft", _bind(executor.backbrief_draft, sdk, mcp))
    sg.add_node("mission_execute", _bind(executor.mission_execute, sdk, mcp))
    # v0.6.11 — in-run pi_decision_select redraft. On a `correct` at the
    # decision gate, this node revises proposed_actions with the PI's
    # correction (one LLM call; does NOT re-run mission_execute's work),
    # then routes back to decision_present for re-ratification. Bounded by
    # MAX_DECISION_REDRAFTS.
    sg.add_node("mission_redraft", _bind(executor.mission_redraft, sdk, mcp))
    sg.add_node("submit_report", _bind(executor.submit_report, sdk, mcp))
    sg.add_node(
        "execute_ratified_actions",
        _bind(executor.execute_ratified_actions, sdk, mcp),
    )
    # Gap 2 — sibling dispatcher for PI-ratified FS actions
    # (Bash/Write/Edit). Wired into the graph alongside
    # execute_ratified_actions: pi_decision_select on accept populates
    # BOTH ratified lists; both nodes fire sequentially before
    # final_synthesis. Both are no-ops on empty lists.
    sg.add_node(
        "execute_ratified_fs_actions",
        _bind(executor.execute_ratified_fs_actions, sdk, mcp),
    )

    # ---- 3 PI interrupt nodes ----
    sg.add_node(
        "pi_greenlight",
        _bind(pi.pi_greenlight, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_decision_select",
        _bind(pi.pi_decision_select, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_acceptance",
        _bind(pi.pi_acceptance, sdk, mcp, interrupt_fn=interrupt_fn),
    )

    # ---- 3 Utility nodes ----
    sg.add_node("budget_check", _bind(utility.budget_check, sdk, mcp))
    sg.add_node("consensus_check", _bind(utility.consensus_check, sdk, mcp))
    sg.add_node("escalation_router", _bind(utility.escalation_router, sdk, mcp))

    # ---- Edges ----
    sg.add_edge(START, "strategy_node")
    sg.add_edge("strategy_node", "confirmation_brief")
    sg.add_edge("confirmation_brief", "pi_greenlight")

    sg.add_conditional_edges(
        "pi_greenlight",
        _route_after_pi_greenlight,
        {
            "backbrief_draft": "backbrief_draft",
            # Phase-X² in-run redraft loop-back. The sentinel
            # (REDIRECT_SENTINEL-prefixed correct action) routes here;
            # confirmation_brief_redraft mutates run_overrides +
            # increments greenlight_redrafts, then routes back to
            # confirmation_brief for the actual Brain redraft LLM
            # call. Bounded by MAX_GREENLIGHT_REDRAFTS.
            "confirmation_brief_redraft": "confirmation_brief_redraft",
            "escalation_router": "escalation_router",
        },
    )
    sg.add_conditional_edges(
        "confirmation_brief_redraft",
        _route_after_confirmation_brief_redraft,
        {
            # Happy redraft: back into confirmation_brief which
            # re-builds the prompt with the just-appended
            # in_run_redirects block at the top.
            "confirmation_brief": "confirmation_brief",
            # Cap exceeded / defensive escapes (missing record /
            # empty text after sanitize): the node has already
            # appended a real ErrorRecord.
            "escalation_router": "escalation_router",
        },
    )

    sg.add_edge("backbrief_draft", "gate1_validation")
    sg.add_conditional_edges(
        "gate1_validation",
        _route_after_gate1,
        {
            "mission_execute": "mission_execute",
            "escalation_router": "escalation_router",
        },
    )

    sg.add_edge("mission_execute", "budget_check")
    sg.add_conditional_edges(
        "budget_check",
        _route_after_budget_or_consensus,
        {
            "escalation_router": "escalation_router",
            "__continue__": "consensus_check",
        },
    )

    sg.add_conditional_edges(
        "consensus_check",
        _route_after_budget_or_consensus,
        {
            "escalation_router": "escalation_router",
            "__continue__": "submit_report",
        },
    )

    sg.add_edge("submit_report", "cluster_review")
    sg.add_edge("cluster_review", "decision_present")
    sg.add_edge("decision_present", "pi_decision_select")

    sg.add_conditional_edges(
        "pi_decision_select",
        _route_after_pi_decision,
        {
            "execute_ratified_actions": "execute_ratified_actions",
            # v0.6.11 in-run decision redraft loop-back (correct action).
            "mission_redraft": "mission_redraft",
            "escalation_router": "escalation_router",
        },
    )
    # v0.6.11 — mission_redraft revises proposed_actions then re-renders via
    # decision_present (happy path) or escalates on cap-exceed / defensive
    # escape (next_node_override set + real ErrorRecord emitted).
    sg.add_conditional_edges(
        "mission_redraft",
        _route_after_mission_redraft,
        {
            "decision_present": "decision_present",
            "escalation_router": "escalation_router",
        },
    )

    # Phase 2.7 T3f / Phase D2.4: execute_ratified_actions sits between
    # pi_decision_select (accept path) and final_synthesis. EC8 set-
    # identity guard: if ANY ratified action's dispatch raised an error,
    # route to escalation_router so the partial-dispatch failure escalates
    # explicitly instead of being buried as an error_count on a
    # pi_acceptance payload that otherwise looks "complete-class". On
    # zero errors (including the no-op state['ratified_actions'] == []
    # case), proceed to final_synthesis as before.
    sg.add_conditional_edges(
        "execute_ratified_actions",
        _route_after_execute_ratified_actions,
        {
            # Gap 2: success path now flows through execute_ratified_fs_actions
            # FIRST so PI-ratified FS work runs before final_synthesis.
            "final_synthesis": "execute_ratified_fs_actions",
            "escalation_router": "escalation_router",
        },
    )
    # Gap 2: FS dispatcher → final_synthesis (no error-route distinction at
    # this layer; the dispatcher embeds its own ErrorRecords which
    # final_synthesis and downstream pi_acceptance handle uniformly).
    sg.add_edge("execute_ratified_fs_actions", "final_synthesis")
    sg.add_edge("final_synthesis", "pi_acceptance")
    sg.add_edge("escalation_router", "pi_acceptance")
    sg.add_edge("pi_acceptance", END)

    return sg.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# SqliteSaver convenience
# ---------------------------------------------------------------------------


def open_checkpointer(db_path: str | None = None) -> SqliteSaver:
    """Construct a SqliteSaver bound to a database file (or `:memory:`).

    Pass `db_path=None` to use in-memory storage (handy for short-lived
    runs + tests). For durable workflows, pass an absolute path; the
    parent directory must exist.
    """
    conn = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
    return SqliteSaver(conn)


# ---------------------------------------------------------------------------
# Names exported (for T11 audit-symmetry)
# ---------------------------------------------------------------------------

# The 18 canonical node names in topology order. T11 audit-symmetry
# cross-checks this against the set of nodes registered in the graph
# and the set of node names referenced from any state["current_node"]
# assignment in the codebase.
NODE_NAMES: tuple[str, ...] = (
    # Brain (7) — Phase-X² added confirmation_brief_redraft (no-LLM
    # state mutator that owns the in-run pi_greenlight redraft policy).
    "strategy_node",
    "confirmation_brief",
    "confirmation_brief_redraft",
    "decision_present",
    "cluster_review",
    "gate1_validation",
    "final_synthesis",
    # Executor (6) — Phase 2.7 T3e added execute_ratified_actions;
    # Gap 2 added execute_ratified_fs_actions (parallel FS dispatcher);
    # v0.6.11 added mission_redraft (in-run pi_decision_select redraft).
    "backbrief_draft",
    "mission_execute",
    "mission_redraft",
    "submit_report",
    "execute_ratified_actions",
    "execute_ratified_fs_actions",
    # PI (3)
    "pi_greenlight",
    "pi_decision_select",
    "pi_acceptance",
    # Utility (3)
    "budget_check",
    "consensus_check",
    "escalation_router",
)

# Phase D — onboarding subgraph nodes. Distinct from NODE_NAMES (the
# mission graph) so the mission-graph audit-symmetry tests stay
# locked at 16 entries. The audit-symmetry sweep over all
# `current_node="..."` string literals checks the union of both
# tuples. Eventually D5 wires these into a separate onboarding subgraph
# (onboarding_graph.build_onboarding_graph(...)).
ONBOARDING_NODE_NAMES: tuple[str, ...] = (
    "research_toolkit",
    # PI interrupt nodes (Phase D5a — colocated in nodes/pi.py with
    # the mission-level interrupts; they share the pi_* naming
    # convention so the orchestrator-pi skill rendering rules apply
    # uniformly).
    "pi_onboarding_topic",
    "pi_toolkit_ratify",
    "pi_credentials_ready",
    # Phase D5b — manifest IO + credential validation + audit entry.
    "draft_manifest",
    "finalize",
    # Phase O — project-onboarding workflow. Names are added
    # incrementally as the corresponding nodes land — audit-symmetry
    # enforces bidirectional alignment (every declared name needs a
    # node assigning current_node=<name>; every current_node write
    # needs the name declared here).
    #
    # O1.1 (idea capture):
    "capture_idea",
    "pi_idea_capture",
    # O1.2 (Brain polish of the captured idea):
    "idea_polish",
    # O1.3 (TWO-TAP ratification of the polished idea):
    "pi_scope_ratify",
    # O2.1 (mkdir + .rka scaffold on disk):
    "workspace_setup",
    # O2.2 (async-pause for Deep Research literature scan):
    "pi_deepresearch_prompt",
    # O3.1 (hygiene sweep over RKA state):
    "hygiene_pass",
    # O3.2 (Brain extracts atomic claims + TWO-TAP review):
    "claim_extraction",
    "pi_claims_review",
    # O4.1 (Brain composes ResearchPlan):
    "plan_synthesis",
    # O4.2 (TWO-TAP — auto-create missions):
    "pi_plan_ratify",
    # Phase H (per-milestone go/no-go before each mission dispatch):
    "pi_phase_entry_ack",
    # Phase B — orchestrator-level credential bootstrap. Distinct from
    # Phase D (per-project credentials); Phase B wires orchestrator/.env
    # so the daemon itself can call Claude before any project exists.
    "pi_bootstrap_intent",
    "bootstrap_propose",
    "pi_bootstrap_ratify",
    "bootstrap_emit_template",
    "pi_bootstrap_fill_ack",
    "bootstrap_verify",
)
