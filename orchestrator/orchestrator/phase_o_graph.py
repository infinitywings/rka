"""Phase O — full project-onboarding subgraph composer.

Wires the 12 Phase O nodes (6 system/Brain + 6 PI interrupts) into a
LangGraph subgraph distinct from:

  - graph.py             — Phase A mission graph (16 nodes)
  - onboarding_graph.py  — Phase D tool-setup subgraph (6 nodes;
                           becomes Phase O5 conceptually but kept
                           callable standalone for projects that
                           already have a plan and just want tooling)

Topology (matches phase-o-project-onboarding-design.md §"Sub-phase decomposition"):

    START
      → capture_idea            [O1.1 system]
      → pi_idea_capture         [O1.1 interrupt — free-form]
      → idea_polish             [O1.2 Brain]
      → pi_scope_ratify         [O1.3 TWO-TAP]
         ┌─ accept  → workspace_setup
         │              → pi_deepresearch_prompt [O2.2 async pause]
         │                 ┌─ accept → hygiene_pass
         │                 │            → claim_extraction
         │                 │              → pi_claims_review [O3.2 TWO-TAP]
         │                 │                  ┌─ accept → plan_synthesis
         │                 │                  │            → pi_plan_ratify [O4.2 TWO-TAP]
         │                 │                  │                ┌─ accept → pi_phase_entry_ack [Phase H]
         │                 │                  │                │             → END (runner picks up mission queue)
         │                 │                  │                └─ else  → END (escalated)
         │                 │                  └─ else   → END (re-enter via /orchestrator-onboard-continue)
         │                 └─ else  → END (escalated; abandoned)
         └─ else    → END (re-enter via /orchestrator-onboard-continue)

The reject/correct loops back to entry by ending the graph and letting
the orchestrator-pi skill / runner.start_phase_o re-enter from O1 with
the brain_position carrying the redirection. This keeps the graph
acyclic + the SqliteSaver state durable per-segment.

Phase O5 (tool setup) is NOT wired into this graph. The orchestrator
runs Phase O end-to-end through Phase H entry, then runner-side logic
launches the tool-setup subgraph (existing onboarding_graph) before
the first mission. That keeps Phase O5 testable in isolation against
its existing test corpus (test_d3, test_d5b, test_d5c).
"""

from __future__ import annotations

import functools
import sqlite3
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt as lg_interrupt

from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.nodes import onboarding, pi
from orchestrator.state import ResearchWorkflowState


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def _latest_interrupt_response(state: dict) -> str:
    interrupts = state.get("interrupts") or []
    if not interrupts:
        return ""
    return str(interrupts[-1].get("response", "")).lower()


def _route_after_scope_ratify(state: dict) -> str:
    """pi_scope_ratify on accept → workspace_setup; else → END."""
    return "workspace_setup" if state.get("scope_ratified") else END


def _route_after_deepresearch(state: dict) -> str:
    """pi_deepresearch_prompt on accept → hygiene_pass; else → END."""
    return "hygiene_pass" if state.get("deepresearch_complete") else END


def _route_after_claims_review(state: dict) -> str:
    """pi_claims_review on accept → plan_synthesis; else → END.

    Set-identity: state["claim_ids"] is non-empty iff PI accepted
    (pi_claims_review clears it on reject/correct).
    """
    return "plan_synthesis" if state.get("claim_ids") else END


def _route_after_plan_ratify(state: dict) -> str:
    """pi_plan_ratify on accept → pi_phase_entry_ack; else → END.

    Set-identity: state["ratified_plan_decision_id"] is populated iff
    the accept-path mission-materialization succeeded.
    """
    return "pi_phase_entry_ack" if state.get("ratified_plan_decision_id") else END


def _route_after_phase_entry_ack(state: dict) -> str:
    """pi_phase_entry_ack ALWAYS terminates the Phase-O graph segment.

    Mission dispatch happens at the runner level: when the interrupt
    resumes with accept, the runner reads current_milestone_index,
    launches the mission via the Phase A mission graph, and re-enters
    Phase O at pi_phase_entry_ack on mission completion (with the
    bumped index). The graph itself only sees one ack per segment.
    """
    return END


def _bind(fn: Callable, sdk: SDKClient, mcp: MCPClient, **extras: Any) -> Callable:
    return functools.partial(fn, sdk=sdk, mcp=mcp, **extras)


def build_phase_o_graph(
    *,
    sdk: SDKClient,
    mcp: MCPClient,
    checkpointer: Any | None = None,
    interrupt_fn: Callable[[dict], Any] = lg_interrupt,
):
    """Compile the Phase O subgraph.

    Same signature shape as graph.build_graph() / build_onboarding_graph().
    PI interrupts park via the SqliteSaver and resume via
    Command(resume=...).
    """
    sg: StateGraph = StateGraph(ResearchWorkflowState)

    # System / Brain nodes (no interrupt_fn).
    sg.add_node("capture_idea", _bind(onboarding.capture_idea_node, sdk, mcp))
    sg.add_node("idea_polish", _bind(onboarding.idea_polish_node, sdk, mcp))
    sg.add_node("workspace_setup", _bind(onboarding.workspace_setup_node, sdk, mcp))
    sg.add_node("hygiene_pass", _bind(onboarding.hygiene_pass_node, sdk, mcp))
    sg.add_node("claim_extraction", _bind(onboarding.claim_extraction_node, sdk, mcp))
    sg.add_node("plan_synthesis", _bind(onboarding.plan_synthesis_node, sdk, mcp))

    # PI interrupt nodes.
    sg.add_node(
        "pi_idea_capture",
        _bind(pi.pi_idea_capture, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_scope_ratify",
        _bind(pi.pi_scope_ratify, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_deepresearch_prompt",
        _bind(pi.pi_deepresearch_prompt, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_claims_review",
        _bind(pi.pi_claims_review, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_plan_ratify",
        _bind(pi.pi_plan_ratify, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_phase_entry_ack",
        _bind(pi.pi_phase_entry_ack, sdk, mcp, interrupt_fn=interrupt_fn),
    )

    # Edges — O1 (idea capture + polish + scope ratify).
    sg.add_edge(START, "capture_idea")
    sg.add_edge("capture_idea", "pi_idea_capture")
    sg.add_edge("pi_idea_capture", "idea_polish")
    sg.add_edge("idea_polish", "pi_scope_ratify")
    sg.add_conditional_edges(
        "pi_scope_ratify",
        _route_after_scope_ratify,
        {"workspace_setup": "workspace_setup", END: END},
    )

    # O2 (workspace + deep research).
    sg.add_edge("workspace_setup", "pi_deepresearch_prompt")
    sg.add_conditional_edges(
        "pi_deepresearch_prompt",
        _route_after_deepresearch,
        {"hygiene_pass": "hygiene_pass", END: END},
    )

    # O3 (hygiene + claim extraction).
    sg.add_edge("hygiene_pass", "claim_extraction")
    sg.add_edge("claim_extraction", "pi_claims_review")
    sg.add_conditional_edges(
        "pi_claims_review",
        _route_after_claims_review,
        {"plan_synthesis": "plan_synthesis", END: END},
    )

    # O4 (plan synthesis + ratification).
    sg.add_edge("plan_synthesis", "pi_plan_ratify")
    sg.add_conditional_edges(
        "pi_plan_ratify",
        _route_after_plan_ratify,
        {"pi_phase_entry_ack": "pi_phase_entry_ack", END: END},
    )

    # Phase H (mission queue handoff entry point).
    sg.add_conditional_edges(
        "pi_phase_entry_ack",
        _route_after_phase_entry_ack,
        {END: END},
    )

    return sg.compile(checkpointer=checkpointer)


def open_checkpointer(db_path: str | None = None) -> SqliteSaver:
    """SqliteSaver convenience — mirrors graph.open_checkpointer."""
    conn = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
    return SqliteSaver(conn)
