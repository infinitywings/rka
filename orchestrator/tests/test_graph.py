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


def test_build_graph_registers_all_canonical_nodes(sdk, mcp, fake_interrupt):
    g = graph.build_graph(sdk=sdk, mcp=mcp, interrupt_fn=fake_interrupt)
    # `get_graph()` returns a drawable representation; the node set on it
    # should include all canonical names plus LangGraph's __start__/__end__.
    nodes = set(g.get_graph().nodes.keys())
    for expected in graph.NODE_NAMES:
        assert expected in nodes, f"node {expected} not registered"


def test_node_names_tuple_has_exactly_eighteen():
    # Phase 2.7 T3e added `execute_ratified_actions` (16th node).
    # Gap 2 added `execute_ratified_fs_actions` (17th, parallel FS
    # dispatcher for PI-ratified Bash/Write/Edit).
    # Phase-X² added `confirmation_brief_redraft` (18th, in-run
    # pi_greenlight redirect state-mutator that owns the redraft
    # policy + bounded loop counter).
    assert len(graph.NODE_NAMES) == 18
    assert len(set(graph.NODE_NAMES)) == 18  # no dupes


def test_execute_ratified_actions_is_in_node_names():
    """Phase 2.7 T3f: the new node is registered in the canonical tuple
    and lives in the executor section between submit_report and the PI nodes."""
    assert "execute_ratified_actions" in graph.NODE_NAMES
    # Position check — keeps the executor group contiguous for T11 audit.
    names = list(graph.NODE_NAMES)
    submit_idx = names.index("submit_report")
    exec_ratified_idx = names.index("execute_ratified_actions")
    pi_greenlight_idx = names.index("pi_greenlight")
    assert submit_idx < exec_ratified_idx < pi_greenlight_idx


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def test_route_after_pi_greenlight_approve_continues_to_backbrief():
    state = {"interrupts": [{"response": "approve"}]}
    assert graph._route_after_pi_greenlight(state) == "backbrief_draft"


def test_route_after_pi_greenlight_bare_redirect_text_still_escalates():
    """Bare 'redirect' (no REDIRECT_SENTINEL prefix) is treated as a hard
    reject — no sentinel → no loopback. Sentinel detection is the load-
    bearing distinction between 'PI wants a redraft' (correct action,
    server prepends sentinel) and 'PI hard-rejects' (reject action, no
    sentinel)."""
    state = {"interrupts": [{"response": "redirect"}]}
    assert graph._route_after_pi_greenlight(state) == "escalation_router"


def test_route_after_pi_greenlight_redirect_sentinel_loops_to_redraft():
    """Phase-X² — REDIRECT_SENTINEL-prefixed response routes to
    confirmation_brief_redraft for the in-run Brain redraft loop,
    NOT to escalation_router (the pre-Phase-X² dead-end). The
    sentinel short-circuit fires FIRST, BEFORE any substring match
    — so a smuggled 'approve' inside the corrected body still
    routes to the redraft path, not to backbrief_draft."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    state = {
        "interrupts": [
            {"response": REDIRECT_SENTINEL + "rework §4 budget framing"}
        ]
    }
    assert (
        graph._route_after_pi_greenlight(state) == "confirmation_brief_redraft"
    )


def test_route_after_pi_greenlight_sentinel_with_approve_substring_still_redrafts():
    """Substring-smuggling guard (Phase D2.1) preserved: 'I cannot
    approve this — redo §4' as the BODY of a correct action gets
    REDIRECT_SENTINEL-prefixed at the runner layer; routing must
    honor the sentinel and loop to redraft, NOT match 'approve' and
    route to backbrief_draft."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    state = {
        "interrupts": [
            {
                "response": (
                    REDIRECT_SENTINEL
                    + "I cannot approve this brief — redo §4 budget framing"
                )
            }
        ]
    }
    assert (
        graph._route_after_pi_greenlight(state) == "confirmation_brief_redraft"
    )


def test_route_after_pi_greenlight_empty_interrupts_escalates():
    # Defensive: no PI response yet → conservative route to escalation
    # (NOT to redraft — a missing signal is not a redirect-to-redraft
    # request).
    assert graph._route_after_pi_greenlight({}) == "escalation_router"


def test_route_after_confirmation_brief_redraft_default_loops_to_brief():
    """Phase-X² happy path: with no next_node_override (cleared by the
    redraft node on success), routes back to confirmation_brief for the
    actual Brain redraft LLM call."""
    state = {"next_node_override": ""}
    assert (
        graph._route_after_confirmation_brief_redraft(state)
        == "confirmation_brief"
    )
    assert (
        graph._route_after_confirmation_brief_redraft({})
        == "confirmation_brief"
    )


def test_route_after_confirmation_brief_redraft_escalates_on_override():
    """Phase-X² budget-cap / defensive path: the redraft node sets
    next_node_override='escalation_router' after emitting a real
    ErrorRecord; the router routes there so escalation_router has a
    genuine error to classify (not the synthetic 'unclassified' that
    used to fire pre-Phase-X²)."""
    state = {"next_node_override": "escalation_router"}
    assert (
        graph._route_after_confirmation_brief_redraft(state)
        == "escalation_router"
    )


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


def test_route_after_pi_decision_accept_routes_through_execute_ratified():
    """Phase 2.7 T3f: on accept, pi_decision_select routes to
    execute_ratified_actions FIRST (parent-side WRITE_TOOLS dispatch from
    state["ratified_actions"]), then unconditionally to final_synthesis.
    Phase 2.6 routed straight to final_synthesis, which was a bug — there
    was nowhere to commit ratified writes."""
    state = {"interrupts": [{"response": "accept"}]}
    assert graph._route_after_pi_decision(state) == "execute_ratified_actions"


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


# ---------------------------------------------------------------------------
# Phase D2.4 — EC8 set-identity guard on execute_ratified_actions routing
#
# Empirical follow-up from thr_19e790f90b4f9301179: PI ratified 4 actions,
# PA-3 + PA-4 dispatched as TypeError on adapter signature mismatch, and
# the graph silently advanced to final_synthesis (pi_acceptance reported
# error_count=2 in payload but the run looked "complete-class"). The new
# conditional edge routes to escalation_router on ANY dispatch error so
# partial-dispatch failures escalate loud, not silent.
# ---------------------------------------------------------------------------


def test_route_after_execute_ratified_actions_clean_dispatch_to_final_synthesis():
    """Clean dispatch (zero ErrorRecords from execute_ratified_actions)
    routes to final_synthesis as before."""
    state = {"errors": []}
    assert (
        graph._route_after_execute_ratified_actions(state)
        == "final_synthesis"
    )


def test_route_after_execute_ratified_actions_no_op_state_to_final_synthesis():
    """No errors key at all (or empty state) routes to final_synthesis —
    the node is a documented no-op when ratified_actions is empty."""
    assert (
        graph._route_after_execute_ratified_actions({})
        == "final_synthesis"
    )


def test_route_after_execute_ratified_actions_partial_dispatch_to_escalation():
    """EC8 guard: ANY ErrorRecord scoped to execute_ratified_actions
    routes to escalation_router. Reproduces the thr_19e790f90b4f9301179
    failure shape: 2 of 4 PAs raised TypeError on adapter mismatch."""
    state = {
        "errors": [
            {
                "node_name": "execute_ratified_actions",
                "error_type": "ratified_action_call_failed",
                "detail": "PA-3: tool='rka_submit_checkpoint' exc=TypeError(...)",
                "timestamp": "2026-05-30T15:09:55Z",
            },
            {
                "node_name": "execute_ratified_actions",
                "error_type": "ratified_action_call_failed",
                "detail": "PA-4: tool='rka_submit_report' exc=TypeError(...)",
                "timestamp": "2026-05-30T15:09:55Z",
            },
        ]
    }
    assert (
        graph._route_after_execute_ratified_actions(state)
        == "escalation_router"
    )


def test_route_after_execute_ratified_actions_ignores_other_nodes_errors():
    """An ErrorRecord from a DIFFERENT node (e.g., mission_execute's
    proposed_actions parser) must NOT trigger the EC8 escalation here —
    only errors scoped to execute_ratified_actions count."""
    state = {
        "errors": [
            {
                "node_name": "mission_execute",
                "error_type": "proposed_actions_parse_failure",
                "detail": "empty LLM reply",
                "timestamp": "2026-05-30T15:00:00Z",
            },
        ]
    }
    assert (
        graph._route_after_execute_ratified_actions(state)
        == "final_synthesis"
    )


def test_route_after_execute_ratified_actions_partial_success_still_escalates():
    """Even if MOST PAs succeeded, a single failed dispatch is enough to
    violate EC8 set-identity (ratified == proposed) — route to escalation."""
    state = {
        "errors": [
            {
                "node_name": "execute_ratified_actions",
                "error_type": "ratified_action_call_failed",
                "detail": "PA-1: tool='rka_add_note' exc=...",
                "timestamp": "2026-05-30T15:00:00Z",
            }
        ]
    }
    assert (
        graph._route_after_execute_ratified_actions(state)
        == "escalation_router"
    )
