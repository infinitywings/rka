"""Unit tests for the 3 utility nodes (T6)."""

from __future__ import annotations

from orchestrator.budgets import MAX_LOOP_DEPTH
from orchestrator.nodes import utility
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


def _state(**overrides) -> dict:
    s = make_initial_state(
        workflow_thread_id="thr_t6",
        mission_id="mis_t6",
        motivated_by_decision_id="dec_t6",
    )
    s.update(overrides)
    return s


# ---------------------------------------------------------------------------
# budget_check
# ---------------------------------------------------------------------------


def test_budget_check_passes_when_under_cap():
    update = utility.budget_check(_state(usd_spent=2.0, loop_iterations=0))
    assert update.get("next_node_override") is None
    assert "errors" not in update
    assert update["current_node"] == "budget_check"


def test_budget_check_flags_overspend():
    update = utility.budget_check(_state(usd_spent=5.0, loop_iterations=0), cap_usd=5.0)
    assert update["next_node_override"] == "escalation_router"
    assert update["errors"][0]["error_type"] == "budget_exceeded"
    assert "usd_spent=5.0" in update["errors"][0]["detail"]


def test_budget_check_respects_custom_cap():
    # Run-specific cap can be tighter than the default.
    update = utility.budget_check(_state(usd_spent=2.5, loop_iterations=0), cap_usd=2.0)
    assert update["next_node_override"] == "escalation_router"


def test_budget_check_flags_loop_overrun():
    update = utility.budget_check(_state(loop_iterations=MAX_LOOP_DEPTH))
    assert update["next_node_override"] == "escalation_router"
    assert update["errors"][0]["error_type"] == "loop_bound_exceeded"


def test_budget_check_records_node_name_on_error():
    update = utility.budget_check(_state(usd_spent=10.0))
    assert update["errors"][0]["node_name"] == "budget_check"


# ---------------------------------------------------------------------------
# consensus_check
# ---------------------------------------------------------------------------


def test_consensus_check_starts_unresolved_with_empty_positions():
    update = utility.consensus_check(_state())
    assert update["consensus_state"] == "unresolved"
    assert "next_node_override" not in update


def test_consensus_check_marks_agreed_when_gate1_approved():
    update = utility.consensus_check(
        _state(
            brain_position="Brain says go.",
            executor_position="Executor agrees.",
            gate1_verdict="approved",
        )
    )
    assert update["consensus_state"] == "agreed"


def test_consensus_check_escalates_after_max_loop_unresolved():
    update = utility.consensus_check(
        _state(
            brain_position="Strategy A is right.",
            executor_position="Strategy B is right.",
            loop_iterations=MAX_LOOP_DEPTH,
        )
    )
    assert update["consensus_state"] == "disagree"
    assert update["next_node_override"] == "escalation_router"
    assert update["errors"][0]["error_type"] == "consensus_loop_exceeded"


def test_consensus_check_keeps_unresolved_below_loop_cap():
    update = utility.consensus_check(
        _state(
            brain_position="brain says X",
            executor_position="executor says Y",
            loop_iterations=1,  # below MAX_LOOP_DEPTH=2
        )
    )
    assert update["consensus_state"] == "unresolved"
    assert "next_node_override" not in update


# ---------------------------------------------------------------------------
# escalation_router
# ---------------------------------------------------------------------------


def test_escalation_router_submits_checkpoint_via_mcp():
    mcp = FakeMCP()
    state = _state(
        errors=[
            {
                "node_name": "budget_check",
                "error_type": "budget_exceeded",
                "detail": "spent too much",
                "timestamp": "2026-05-14T10:00:00Z",
            }
        ]
    )

    update = utility.escalation_router(state, mcp=mcp)

    chk_calls = [c for c in mcp.calls if c["op"] == "rka_submit_checkpoint"]
    assert len(chk_calls) == 1
    assert "budget_exceeded" in chk_calls[0]["reason"]
    assert chk_calls[0]["type"] == "decision"
    assert update["checkpoints"][0]["chk_id"].startswith("chk_")
    assert update["current_phase"] == "escalated"
    assert update["next_node_override"] == "pi_acceptance"


def test_escalation_router_classifies_clarification_for_ambiguity():
    mcp = FakeMCP()
    state = _state(
        errors=[
            {
                "node_name": "executor_backbrief",
                "error_type": "ambiguous_acceptance",
                "detail": "multiple valid interpretations",
            }
        ]
    )
    update = utility.escalation_router(state, mcp=mcp)
    chk_call = next(c for c in mcp.calls if c["op"] == "rka_submit_checkpoint")
    assert chk_call["type"] == "clarification"
    assert update["checkpoints"][0]["type"] == "clarification"


def test_escalation_router_handles_no_prior_error_gracefully():
    mcp = FakeMCP()
    update = utility.escalation_router(_state(), mcp=mcp)
    chk_call = next(c for c in mcp.calls if c["op"] == "rka_submit_checkpoint")
    assert "unclassified" in chk_call["reason"]
    # Default classification = decision (conservative).
    assert chk_call["type"] == "decision"


def test_escalation_router_works_without_mcp_for_dry_runs():
    # Pre-T9 wiring: escalation_router can run with mcp=None and still
    # emit a checkpoint record (with chk_pending placeholder) so the
    # state surface is uniform.
    update = utility.escalation_router(
        _state(
            errors=[
                {
                    "node_name": "budget_check",
                    "error_type": "budget_exceeded",
                    "detail": "x",
                }
            ]
        ),
        mcp=None,
    )
    assert update["checkpoints"][0]["chk_id"] == "chk_pending"
    assert update["current_phase"] == "escalated"


def test_escalation_router_reads_latest_error_only():
    mcp = FakeMCP()
    state = _state(
        errors=[
            {
                "node_name": "old_node",
                "error_type": "unclassified",
                "detail": "old failure",
            },
            {
                "node_name": "consensus_check",
                "error_type": "consensus_loop_exceeded",
                "detail": "loop exceeded",
            },
        ]
    )
    update = utility.escalation_router(state, mcp=mcp)
    # Reason should reference the LATEST error, not the first.
    assert "consensus_loop_exceeded" in update["checkpoints"][0]["reason"]
    assert "consensus_check" in update["checkpoints"][0]["reason"]


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_every_utility_node_sets_current_node():
    state = _state()
    sdk = FakeSDK()
    mcp = FakeMCP()
    for fn, expected in [
        (utility.budget_check, "budget_check"),
        (utility.consensus_check, "consensus_check"),
        (utility.escalation_router, "escalation_router"),
    ]:
        update = fn(state, sdk, mcp)
        assert update["current_node"] == expected
