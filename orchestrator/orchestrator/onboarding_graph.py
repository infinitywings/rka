"""Phase D5c — Onboarding subgraph composer.

Wires the 6 onboarding nodes (3 PI interrupts + 3 Brain/system nodes)
into a LangGraph subgraph distinct from the 16-node mission graph in
graph.py. The subgraph is invoked separately at project-creation time
via the runner's `start_onboarding(project_id, ...)` method.

Topology:

    START
      → pi_onboarding_topic       (PI interrupt: topic elicitation)
      → research_toolkit          (Brain: builds proposed_toolkit)
      → pi_toolkit_ratify         (PI interrupt: ratify the set)
       ┌─ ratified  → draft_manifest → pi_credentials_ready
       │                                ┌─ accept → finalize → END
       │                                └─ reject → END (abandoned)
       └─ rejected → END (abandoned)
       ↓
      END

Compared to the mission graph: no `escalation_router` /
`pi_acceptance` — onboarding either completes cleanly (writes
manifest + audit entry) or is abandoned cleanly (terminal_state set
on state without an extra rendering step). PI's reject/correct on
either interrupt routes straight to END.
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
from orchestrator.nodes import onboarding, pi
from orchestrator.state import ResearchWorkflowState


def _latest_interrupt_response(state: dict) -> str:
    """Read the most recent interrupt's response — same helper shape
    as graph.py's mission routing."""
    interrupts = state.get("interrupts", [])
    if not interrupts:
        return ""
    return str(interrupts[-1].get("response", "")).lower()


def _route_after_toolkit_ratify(state: dict) -> str:
    """pi_toolkit_ratify on accept → draft_manifest; else → END.

    Set-identity ratification: ratified_toolkit is non-empty iff PI
    accepted. The routing fn checks state["ratified_toolkit"] rather
    than re-parsing the response string — this is the canonical
    accept-detection convention (pi_toolkit_ratify itself does the
    response parsing and populates ratified_toolkit accordingly).
    """
    return "draft_manifest" if state.get("ratified_toolkit") else END


def _route_after_credentials_ready(state: dict) -> str:
    """pi_credentials_ready on accept → finalize; else → END.

    Accept emits 'accept' per the runner contract; reject yields
    'reject' which doesn't contain 'accept'. END short-circuits the
    finalize step + audit entry — PI rejected, no manifest commit.
    """
    response = _latest_interrupt_response(state)
    return "finalize" if "accept" in response else END


def _bind(fn: Callable, sdk: SDKClient, mcp: MCPClient, **extras: Any) -> Callable:
    """Same binding pattern as graph.py: LangGraph node-callable
    receives only (state,); sdk + mcp + interrupt_fn bound at graph-
    construction time."""
    return functools.partial(fn, sdk=sdk, mcp=mcp, **extras)


def build_onboarding_graph(
    *,
    sdk: SDKClient,
    mcp: MCPClient,
    checkpointer: Any | None = None,
    interrupt_fn: Callable[[dict], Any] = lg_interrupt,
):
    """Compile the onboarding subgraph.

    Same signature shape as graph.build_graph(): sdk + mcp +
    optional checkpointer + interrupt_fn. The interrupt_fn defaults
    to LangGraph's native `interrupt`, so PI interrupts park via
    the SqliteSaver and resume via Command(resume=...).
    """
    sg: StateGraph = StateGraph(ResearchWorkflowState)

    # PI interrupt nodes (interrupt_fn-bound).
    sg.add_node(
        "pi_onboarding_topic",
        _bind(pi.pi_onboarding_topic, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_toolkit_ratify",
        _bind(pi.pi_toolkit_ratify, sdk, mcp, interrupt_fn=interrupt_fn),
    )
    sg.add_node(
        "pi_credentials_ready",
        _bind(pi.pi_credentials_ready, sdk, mcp, interrupt_fn=interrupt_fn),
    )

    # Brain/system nodes.
    sg.add_node(
        "research_toolkit",
        _bind(onboarding.research_toolkit_node, sdk, mcp),
    )
    sg.add_node(
        "draft_manifest",
        _bind(onboarding.draft_manifest_node, sdk, mcp),
    )
    sg.add_node(
        "finalize",
        _bind(onboarding.finalize_node, sdk, mcp),
    )

    # Edges.
    sg.add_edge(START, "pi_onboarding_topic")
    sg.add_edge("pi_onboarding_topic", "research_toolkit")
    sg.add_edge("research_toolkit", "pi_toolkit_ratify")

    sg.add_conditional_edges(
        "pi_toolkit_ratify",
        _route_after_toolkit_ratify,
        {
            "draft_manifest": "draft_manifest",
            END: END,
        },
    )

    sg.add_edge("draft_manifest", "pi_credentials_ready")

    sg.add_conditional_edges(
        "pi_credentials_ready",
        _route_after_credentials_ready,
        {
            "finalize": "finalize",
            END: END,
        },
    )

    sg.add_edge("finalize", END)

    return sg.compile(checkpointer=checkpointer)


def open_checkpointer(db_path: str | None = None) -> SqliteSaver:
    """SqliteSaver convenience — mirrors graph.open_checkpointer.

    Onboarding uses the same SqliteSaver pattern as missions, but with
    a distinct thread_id so onboarding state doesn't collide with
    mission state for the same project.
    """
    conn = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
    return SqliteSaver(conn)
