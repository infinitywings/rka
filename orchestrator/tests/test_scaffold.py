"""Sanity tests for the T1 scaffold.

These verify the package imports cleanly and the CLI entrypoint resolves
arguments. Real behavioral tests follow in T2 (state schema), T3-T6
(per-node), and T11 (full suite).
"""

from __future__ import annotations

import pytest

import orchestrator
from orchestrator import budgets, main, notifications
from orchestrator.nodes import brain, executor, pi, utility


def test_version_is_phase_1_v0_1_0():
    assert orchestrator.__version__ == "0.1.0"


def test_cli_version_command_returns_zero(capsys):
    rc = main.cli(["version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "rka-orchestrator" in out


def test_cli_run_command_is_scaffold_placeholder(capsys):
    rc = main.cli(["run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "scaffold" in out.lower()


def test_budget_snapshot_loop_bound_is_two():
    b = budgets.BudgetSnapshot(usd_spent=0.0, loop_iterations=2)
    assert b.at_loop_cap()
    assert budgets.MAX_LOOP_DEPTH == 2


def test_budget_snapshot_exceeds_cap():
    b = budgets.BudgetSnapshot(usd_spent=5.0, loop_iterations=0)
    assert b.exceeds(5.0)
    assert not b.exceeds(10.0)


def test_notifications_webhook_blocklist_includes_known_telemetry():
    # Telemetry-zero stance: the blocklist must include the obvious
    # analytics endpoints so they cannot be POSTed to even via env config.
    assert "api.segment.io" in notifications.WEBHOOK_BLOCKLIST
    assert "api.posthog.com" in notifications.WEBHOOK_BLOCKLIST
    assert "api.amplitude.com" in notifications.WEBHOOK_BLOCKLIST


def test_pi_batch_review_threshold_default_is_ten():
    # Per rehearsal observation #15 (labeler-UX-scaling-friction).
    assert pi.PI_BATCH_REVIEW_THRESHOLD == 10


@pytest.mark.parametrize(
    "fn",
    [
        # T3 (Brain ×6) has landed — those nodes get covered by test_brain.py.
        # The remaining 9 are still placeholders until T4-T6 land.
        executor.backbrief_draft,
        executor.mission_execute,
        executor.submit_report,
        pi.pi_greenlight,
        pi.pi_decision_select,
        pi.pi_acceptance,
        utility.budget_check,
        utility.consensus_check,
        utility.escalation_router,
    ],
)
def test_remaining_nine_nodes_are_stub_placeholders(fn):
    # T4-T6 nodes still raise NotImplementedError. As each task lands,
    # remove its functions from this parametrize list and add behavioral
    # tests in a dedicated module (mirror test_brain.py).
    with pytest.raises(NotImplementedError):
        fn({})


def test_brain_nodes_have_three_arg_signature():
    # Sanity guard: the 6 Brain nodes accept (state, sdk, mcp). Catches
    # accidental signature regressions during T4-T6 expansion.
    import inspect

    for fn in (
        brain.strategy_node,
        brain.confirmation_brief,
        brain.decision_present,
        brain.cluster_review,
        brain.gate1_validation,
        brain.final_synthesis,
    ):
        params = list(inspect.signature(fn).parameters.keys())
        assert params == ["state", "sdk", "mcp"], (
            f"{fn.__name__} should accept (state, sdk, mcp); got {params}"
        )
