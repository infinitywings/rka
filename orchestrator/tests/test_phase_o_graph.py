"""Phase O — subgraph composer tests.

Covers:
  - build_phase_o_graph compiles and registers all 12 nodes
  - START edges to capture_idea (the workflow's first node)
  - Routing fns: scope_ratify, deepresearch, claims_review, plan_ratify
    each gate on the right state flag
  - Phase H interrupt always terminates (the queue iteration is
    runner-driven, not graph-internal)
  - runner.start_phase_o creates a workflow_runs row + parks at the
    first interrupt with the right interrupt_type (pi_idea_capture)
  - runner.respond() with a Phase O interrupt routes to the Phase O
    compile factory (not Phase D's tool-setup factory)
"""

from __future__ import annotations

import pytest

from orchestrator import phase_o_graph
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


pytest.importorskip("langgraph")


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _stub_interrupt(payload):
    """Stub interrupt that just returns a hardcoded accept for graph-
    compile smoke tests. The actual interrupt mechanics are tested
    per-node in the test_o*.py files."""
    return "accept"


def test_phase_o_graph_compiles_and_registers_all_nodes():
    g = phase_o_graph.build_phase_o_graph(
        sdk=FakeSDK(), mcp=FakeMCP(), interrupt_fn=_stub_interrupt
    )
    registered = set(g.get_graph().nodes.keys())
    # All 12 Phase O nodes should be present.
    expected = {
        "capture_idea",
        "pi_idea_capture",
        "idea_polish",
        "pi_scope_ratify",
        "workspace_setup",
        "pi_deepresearch_prompt",
        "hygiene_pass",
        "claim_extraction",
        "pi_claims_review",
        "plan_synthesis",
        "pi_plan_ratify",
        "pi_phase_entry_ack",
    }
    missing = expected - registered
    assert not missing, f"Phase O graph missing nodes: {missing}"


# ---------------------------------------------------------------------------
# Routing fns
# ---------------------------------------------------------------------------


def test_route_after_scope_ratify_accept_goes_to_workspace():
    out = phase_o_graph._route_after_scope_ratify({"scope_ratified": True})
    assert out == "workspace_setup"


def test_route_after_scope_ratify_reject_goes_to_end():
    from langgraph.graph import END

    assert phase_o_graph._route_after_scope_ratify({"scope_ratified": False}) == END
    assert phase_o_graph._route_after_scope_ratify({}) == END


def test_route_after_deepresearch_accept_goes_to_hygiene():
    assert (
        phase_o_graph._route_after_deepresearch({"deepresearch_complete": True})
        == "hygiene_pass"
    )


def test_route_after_deepresearch_reject_goes_to_end():
    from langgraph.graph import END

    assert (
        phase_o_graph._route_after_deepresearch({"deepresearch_complete": False})
        == END
    )


def test_route_after_claims_review_keeps_claim_ids_set_advances():
    assert (
        phase_o_graph._route_after_claims_review({"claim_ids": ["clm_a", "clm_b"]})
        == "plan_synthesis"
    )


def test_route_after_claims_review_cleared_claim_ids_terminates():
    from langgraph.graph import END

    assert phase_o_graph._route_after_claims_review({"claim_ids": []}) == END


def test_route_after_plan_ratify_decision_set_advances_to_phase_h():
    assert (
        phase_o_graph._route_after_plan_ratify({"ratified_plan_decision_id": "dec_aa"})
        == "pi_phase_entry_ack"
    )


def test_route_after_plan_ratify_empty_decision_terminates():
    from langgraph.graph import END

    assert (
        phase_o_graph._route_after_plan_ratify({"ratified_plan_decision_id": ""})
        == END
    )


def test_route_after_phase_entry_ack_always_terminates():
    """Phase H per-milestone iteration happens at the runner level,
    not within a single graph invocation."""
    from langgraph.graph import END

    assert (
        phase_o_graph._route_after_phase_entry_ack({"current_milestone_index": 1})
        == END
    )


# ---------------------------------------------------------------------------
# runner.start_phase_o
# ---------------------------------------------------------------------------


def _make_runner(store, sdk_factory=None, mcp_factory=None, phase_o_factory=None):
    return OrchestratorRunner(
        store=store,
        sdk_factory=sdk_factory or (lambda _p, _ws="": FakeSDK()),
        mcp_factory=mcp_factory or (lambda _t, _p: FakeMCP()),
        saver_factory=lambda _t: None,  # no checkpointer in tests
        phase_o_compile_factory=phase_o_factory,
    )


def test_start_phase_o_creates_run_and_parks_at_first_interrupt():
    """Compile a real Phase O graph (with no checkpointer) and verify
    runner.start_phase_o parks at pi_idea_capture (the first PI
    interrupt after capture_idea)."""
    store = ParkedStore(":memory:")
    runner = _make_runner(store)
    outcome = runner.start_phase_o(project_id="prj_test_01")

    # Run row created.
    run = store.get_run(outcome.workflow_thread_id)
    assert run is not None
    assert run["project_id"] == "prj_test_01"
    # Parked at the first interrupt (pi_idea_capture).
    assert outcome.parked_interrupt_id is not None
    assert outcome.parked_interrupt_type == "pi_idea_capture"
    assert outcome.terminal_state is None
    assert run["status"] == "awaiting_pi"


def test_respond_to_phase_o_interrupt_routes_via_phase_o_factory():
    """Verify the runner's respond() picks the Phase O compile factory
    (not the Phase D one) when the interrupt belongs to Phase O."""
    store = ParkedStore(":memory:")

    factory_call_count = {"phase_o": 0, "phase_d": 0}

    def phase_o_factory(*, sdk, mcp, checkpointer):
        factory_call_count["phase_o"] += 1
        return phase_o_graph.build_phase_o_graph(
            sdk=sdk, mcp=mcp, checkpointer=checkpointer
        )

    def phase_d_factory(*, sdk, mcp, checkpointer):
        factory_call_count["phase_d"] += 1
        from orchestrator import onboarding_graph as _og

        return _og.build_onboarding_graph(
            sdk=sdk, mcp=mcp, checkpointer=checkpointer
        )

    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda _p, _ws="": FakeSDK(),
        mcp_factory=lambda _t, _p: FakeMCP(),
        saver_factory=lambda _t: None,
        phase_o_compile_factory=phase_o_factory,
        onboarding_compile_factory=phase_d_factory,
    )

    outcome = runner.start_phase_o(project_id="prj_test_02")
    assert outcome.parked_interrupt_type == "pi_idea_capture"
    # start_phase_o called the Phase O factory once.
    assert factory_call_count["phase_o"] == 1
    assert factory_call_count["phase_d"] == 0


def test_respond_to_phase_d_interrupt_still_routes_via_phase_d_factory():
    """Verify the Phase D path is not regressed by the new Phase O routing."""
    store = ParkedStore(":memory:")

    factory_call_count = {"phase_o": 0, "phase_d": 0}

    def phase_o_factory(*, sdk, mcp, checkpointer):
        factory_call_count["phase_o"] += 1
        return phase_o_graph.build_phase_o_graph(
            sdk=sdk, mcp=mcp, checkpointer=checkpointer
        )

    def phase_d_factory(*, sdk, mcp, checkpointer):
        factory_call_count["phase_d"] += 1
        from orchestrator import onboarding_graph as _og

        return _og.build_onboarding_graph(
            sdk=sdk, mcp=mcp, checkpointer=checkpointer
        )

    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda _p, _ws="": FakeSDK(),
        mcp_factory=lambda _t, _p: FakeMCP(),
        saver_factory=lambda _t: None,
        phase_o_compile_factory=phase_o_factory,
        onboarding_compile_factory=phase_d_factory,
    )

    # start_onboarding parks at pi_onboarding_topic (Phase D).
    outcome = runner.start_onboarding(project_id="prj_phase_d")
    assert outcome.parked_interrupt_type == "pi_onboarding_topic"
    assert factory_call_count["phase_d"] == 1
    assert factory_call_count["phase_o"] == 0
