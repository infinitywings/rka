"""Phase B — orchestrator-level bootstrap subgraph composer.

Wires the 6 Phase B nodes (3 PI interrupts + 3 background) into a
LangGraph subgraph distinct from:

  - graph.py             — Phase A mission graph
  - onboarding_graph.py  — Phase D per-project tool-setup
  - phase_o_graph.py     — Phase O project-onboarding

Phase B handles the *prerequisite* problem: a fresh install can't run
Phase D (or anything else) until the orchestrator daemon itself can
call Claude. So Phase B writes the orchestrator's own .env.

Topology:

    START
      → pi_bootstrap_intent       [interrupt — free-form intent]
      → bootstrap_propose         [match catalog vs intent]
      → pi_bootstrap_ratify       [TWO-TAP — accept the shortlist]
         ┌─ accept → bootstrap_emit_template
         │            → pi_bootstrap_fill_ack [replayable interrupt]
         │                ┌─ accept → bootstrap_verify
         │                │             → END (terminal_state set by verify)
         │                └─ else  → END (template stays on disk)
         └─ else   → END (re-enter via /orchestrator-bootstrap)

Set-identity for ratification gates:
  - state["bootstrap_ratified_ids"] non-empty iff PI accepted ratify
  - terminal_state set by verify ("complete" iff all required pass)

Reject/correct loops back to entry by ending the graph; the runner
or skill re-enters from scratch with the brain_position carrying any
redirect text. Keeps the graph acyclic + SqliteSaver-durable per-segment.
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
from orchestrator.nodes import bootstrap as bootstrap_nodes
from orchestrator.nodes import pi
from orchestrator.state import ResearchWorkflowState


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _route_after_bootstrap_ratify(state: dict) -> str:
    """Accept → emit; else → END.
    Set-identity: bootstrap_ratified_ids non-empty iff accepted."""
    return "bootstrap_emit_template" if state.get("bootstrap_ratified_ids") else END


def _route_after_fill_ack(state: dict) -> str:
    """Accept → verify; else → END.

    The latest interrupt's response carries the accept/reject signal.
    On reject the .env.example is left on disk so the PI can resume later.
    """
    interrupts = state.get("interrupts") or []
    if not interrupts:
        return END
    last = interrupts[-1]
    if last.get("node_name") != "pi_bootstrap_fill_ack":
        return END
    response = str(last.get("response", "")).lower()
    return "bootstrap_verify" if ("accept" in response or "approve" in response) else END


def _bind(fn: Callable, sdk: SDKClient, mcp: MCPClient, **extras: Any) -> Callable:
    return functools.partial(fn, sdk=sdk, mcp=mcp, **extras)


def build_phase_b_graph(
    *,
    sdk: SDKClient,
    mcp: MCPClient,
    checkpointer: Any | None = None,
    interrupt_fn: Callable[[dict], Any] = lg_interrupt,
):
    """Compile the Phase B subgraph.

    Signature mirrors build_graph / build_onboarding_graph /
    build_phase_o_graph. PI interrupts park via the SqliteSaver and
    resume via Command(resume=...).
    """
    sg: StateGraph = StateGraph(ResearchWorkflowState)

    # Background nodes (no interrupt_fn).
    sg.add_node("bootstrap_propose", _bind(bootstrap_nodes.bootstrap_propose_node, sdk, mcp))
    sg.add_node(
        "bootstrap_emit_template",
        _bind(bootstrap_nodes.bootstrap_emit_template_node, sdk, mcp),
    )
    sg.add_node("bootstrap_verify", _bind(bootstrap_nodes.bootstrap_verify_node, sdk, mcp))

    # PI interrupt nodes.
    sg.add_node(
        "pi_bootstrap_intent",
        _bind(pi.pi_bootstrap_intent, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_bootstrap_ratify",
        _bind(pi.pi_bootstrap_ratify, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_bootstrap_fill_ack",
        _bind(pi.pi_bootstrap_fill_ack, sdk, mcp, interrupt_fn=interrupt_fn),
    )

    # Edges.
    sg.add_edge(START, "pi_bootstrap_intent")
    sg.add_edge("pi_bootstrap_intent", "bootstrap_propose")
    sg.add_edge("bootstrap_propose", "pi_bootstrap_ratify")
    sg.add_conditional_edges(
        "pi_bootstrap_ratify",
        _route_after_bootstrap_ratify,
        {"bootstrap_emit_template": "bootstrap_emit_template", END: END},
    )
    sg.add_edge("bootstrap_emit_template", "pi_bootstrap_fill_ack")
    sg.add_conditional_edges(
        "pi_bootstrap_fill_ack",
        _route_after_fill_ack,
        {"bootstrap_verify": "bootstrap_verify", END: END},
    )
    sg.add_edge("bootstrap_verify", END)

    return sg.compile(checkpointer=checkpointer)


def open_checkpointer(db_path: str | None = None) -> SqliteSaver:
    """SqliteSaver convenience — mirrors graph.open_checkpointer."""
    conn = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
    return SqliteSaver(conn)
