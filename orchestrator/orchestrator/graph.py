"""LangGraph topology + SqliteSaver checkpointer.

Wires all 15 nodes into a flat `StateGraph` keyed on `ResearchWorkflowState`.
Phase 1 keeps the topology single-thread + linear-with-escalation-shortcuts;
no Send-API parallelism, no subgraphs. T7 deliverable.

Each node-callable is bound to its (sdk, mcp[, interrupt_fn]) dependencies
via `functools.partial`, so the function LangGraph receives accepts only
`(state,)` — keeping the engine-facing surface uniform.

Topology (16 nodes; 5 conditional branches):

  START
    → strategy_node
    → confirmation_brief
    → pi_greenlight     ── approve → backbrief_draft
                       └─ else    → escalation_router
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
    → pi_decision_select ── accept → execute_ratified_actions → final_synthesis
                         └─ else  → escalation_router
    → execute_ratified_actions    # Phase 2.7 T3e — parent-side WRITE_TOOLS calls
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
    response = _latest_interrupt_response(state)
    return "backbrief_draft" if "approve" in response else "escalation_router"


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
    # before final_synthesis closes the run. On reject/escape, escalate
    # directly (no writes to commit).
    response = _latest_interrupt_response(state)
    return "execute_ratified_actions" if "accept" in response else "escalation_router"


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

    # ---- 6 Brain nodes ----
    sg.add_node("strategy_node", _bind(brain.strategy_node, sdk, mcp))
    sg.add_node("confirmation_brief", _bind(brain.confirmation_brief, sdk, mcp))
    sg.add_node("decision_present", _bind(brain.decision_present, sdk, mcp))
    sg.add_node("cluster_review", _bind(brain.cluster_review, sdk, mcp))
    sg.add_node("gate1_validation", _bind(brain.gate1_validation, sdk, mcp))
    sg.add_node("final_synthesis", _bind(brain.final_synthesis, sdk, mcp))

    # ---- 4 Executor nodes (Phase 2.7 T3e added execute_ratified_actions) ----
    sg.add_node("backbrief_draft", _bind(executor.backbrief_draft, sdk, mcp))
    sg.add_node("mission_execute", _bind(executor.mission_execute, sdk, mcp))
    sg.add_node("submit_report", _bind(executor.submit_report, sdk, mcp))
    sg.add_node(
        "execute_ratified_actions",
        _bind(executor.execute_ratified_actions, sdk, mcp),
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
            "escalation_router": "escalation_router",
        },
    )

    # Phase 2.7 T3f: execute_ratified_actions sits between pi_decision_select
    # (accept path) and final_synthesis. The node is a no-op when
    # state["ratified_actions"] is empty, so no extra routing logic needed.
    sg.add_edge("execute_ratified_actions", "final_synthesis")
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

# The 16 canonical node names in topology order. T11 audit-symmetry
# cross-checks this against the set of nodes registered in the graph
# and the set of node names referenced from any state["current_node"]
# assignment in the codebase.
NODE_NAMES: tuple[str, ...] = (
    # Brain (6)
    "strategy_node",
    "confirmation_brief",
    "decision_present",
    "cluster_review",
    "gate1_validation",
    "final_synthesis",
    # Executor (4) — Phase 2.7 T3e added execute_ratified_actions
    "backbrief_draft",
    "mission_execute",
    "submit_report",
    "execute_ratified_actions",
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
    # Phase D5b additions land here as draft_manifest, finalize, etc.
)
