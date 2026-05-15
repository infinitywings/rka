"""Topology integration tests (T7).

Exercises the real `langgraph` 1.x runtime — these are conceptually
integration tests, not unit tests, but they're cheap (no I/O, all fakes
for SDK + MCP + interrupt).
"""

from __future__ import annotations

import pytest

# Skip the whole module if langgraph isn't installed — keeps the suite
# usable in environments that only need unit coverage.
langgraph = pytest.importorskip("langgraph")

from orchestrator import graph
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


@pytest.fixture
def sdk():
    return FakeSDK(canned_reply="APPROVED\nLooks fine.")


@pytest.fixture
def mcp():
    return FakeMCP()


@pytest.fixture
def fake_interrupt():
    """Returns 'approve'/'accept' so the happy path runs end-to-end."""

    def _fn(payload):
        kind = payload.get("type", "")
        # pi_acceptance checks for "accept"; pi_decision_select likewise.
        # pi_greenlight router checks for "approve".
        if kind in ("pi_decision_select", "pi_acceptance"):
            return "accept"
        return "approve"

    return _fn


# ---------------------------------------------------------------------------
# Graph-construction smoke
# ---------------------------------------------------------------------------


def test_build_graph_returns_compiled_runnable(sdk, mcp, fake_interrupt):
    g = graph.build_graph(sdk=sdk, mcp=mcp, interrupt_fn=fake_interrupt)
    # Compiled graph exposes an `invoke` method.
    assert hasattr(g, "invoke")
    assert hasattr(g, "stream")


def test_build_graph_registers_all_fifteen_nodes(sdk, mcp, fake_interrupt):
    g = graph.build_graph(sdk=sdk, mcp=mcp, interrupt_fn=fake_interrupt)
    # `get_graph()` returns a drawable representation; the node set on it
    # should include all 15 canonical names plus LangGraph's __start__/__end__.
    nodes = set(g.get_graph().nodes.keys())
    for expected in graph.NODE_NAMES:
        assert expected in nodes, f"node {expected} not registered"


def test_node_names_tuple_has_exactly_fifteen():
    assert len(graph.NODE_NAMES) == 15
    assert len(set(graph.NODE_NAMES)) == 15  # no dupes


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def test_route_after_pi_greenlight_approve_continues_to_backbrief():
    state = {"interrupts": [{"response": "approve"}]}
    assert graph._route_after_pi_greenlight(state) == "backbrief_draft"


def test_route_after_pi_greenlight_redirect_routes_to_escalation():
    state = {"interrupts": [{"response": "redirect"}]}
    assert graph._route_after_pi_greenlight(state) == "escalation_router"


def test_route_after_pi_greenlight_empty_interrupts_escalates():
    # Defensive: no PI response yet → conservative route to escalation.
    assert graph._route_after_pi_greenlight({}) == "escalation_router"


def test_route_after_gate1_approved_continues():
    assert graph._route_after_gate1({"gate1_verdict": "approved"}) == "mission_execute"


def test_route_after_gate1_redirected_escalates():
    assert graph._route_after_gate1({"gate1_verdict": "redirected"}) == "escalation_router"


def test_route_after_budget_respects_next_node_override():
    state = {"next_node_override": "escalation_router"}
    assert graph._route_after_budget_or_consensus(state) == "escalation_router"


def test_route_after_budget_default_continue():
    state = {}
    assert graph._route_after_budget_or_consensus(state) == "__continue__"


def test_route_after_pi_decision_accept_continues_to_final():
    state = {"interrupts": [{"response": "accept"}]}
    assert graph._route_after_pi_decision(state) == "final_synthesis"


def test_route_after_pi_decision_reject_escalates():
    state = {"interrupts": [{"response": "reject"}]}
    assert graph._route_after_pi_decision(state) == "escalation_router"


# ---------------------------------------------------------------------------
# SqliteSaver
# ---------------------------------------------------------------------------


def test_open_checkpointer_in_memory_constructs():
    ckpt = graph.open_checkpointer(None)
    # SqliteSaver carries a `conn` attribute we can probe.
    assert ckpt.conn is not None


def test_open_checkpointer_with_path(tmp_path):
    db_path = str(tmp_path / "checkpoints.db")
    ckpt = graph.open_checkpointer(db_path)
    assert ckpt.conn is not None


def test_compiled_graph_accepts_sqlite_checkpointer(sdk, mcp, fake_interrupt):
    ckpt = graph.open_checkpointer(None)
    g = graph.build_graph(sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=fake_interrupt)
    assert hasattr(g, "invoke")


# ---------------------------------------------------------------------------
# End-to-end happy-path smoke (with checkpointer + thread_id config)
# ---------------------------------------------------------------------------


def test_happy_path_runs_to_completion(sdk, mcp, fake_interrupt):
    # Construct the graph with a per-test SqliteSaver in :memory:.
    ckpt = graph.open_checkpointer(None)
    g = graph.build_graph(
        sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=fake_interrupt
    )
    initial = make_initial_state(
        workflow_thread_id="thr_smoke",
        mission_id="mis_smoke",
        motivated_by_decision_id="dec_smoke",
    )
    config = {"configurable": {"thread_id": "thr_smoke"}}
    # The SDK's canned reply starts with "APPROVED" so gate1 routes to
    # mission_execute, the budget stays at 0, consensus_check sees
    # gate1_verdict=approved → agreed → continue, and the PI fake
    # responds "accept" so pi_acceptance → END.
    final = g.invoke(initial, config=config)

    assert final["terminal_state"] == "complete"
    # All 15 nodes should have produced state writes (via current_node).
    # At minimum the run touched a representative set.
    assert "final_report_id" in final
    assert len(final["interrupts"]) >= 2  # pi_greenlight + pi_acceptance
