"""Phase-0 dry-run for the end-to-end research-lifecycle eval harness.

Proves the eval scaffolding (`orchestrator/eval/`) drives the REAL mission
graph with in-process fakes — no live SDK, no REST, no network — so the
harness itself is testable in CI before any of the live Phases 1-5 run on
the PI's machine.

Three things are asserted:
  1. ``happy_path_oracle()`` (accept-every-gate) takes the real 19-node
     graph to ``terminal_state == "complete"`` and records a decision per
     PI gate visited — i.e. the oracle is a drop-in for the pilot's
     hardcoded ``interrupt_fn`` but with an auditable log.
  2. A rubric whose ``correct`` rule fires on the first ``pi_greenlight``
     drives the Phase-X² in-run redraft loop exactly once
     (``greenlight_redrafts == 1``) and still reaches ``complete`` — the
     redirect path the live pivot stage exercises.
  3. ``RunRecord.from_final_state`` lifts the terminal state + oracle log
     into the gradeable per-run record (telemetry axes + JSON round-trip).

These use the same ``FakeSDK(canned_reply="APPROVED…")`` + ``FakeMCP``
doubles as ``tests/test_graph.py::test_happy_path_runs_to_completion`` so
the graph routes deterministically to terminal.
"""

from __future__ import annotations

import json

import pytest

from orchestrator import graph
from orchestrator.eval import graders
from orchestrator.eval.pi_oracle import PIOracle, Rubric, Rule, happy_path_oracle
from orchestrator.eval.run_record import RunRecord
from orchestrator.runner import REDIRECT_SENTINEL
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


@pytest.fixture
def sdk():
    # "APPROVED" first line → gate1 routes to mission_execute (same as the
    # canonical happy-path smoke in test_graph.py).
    return FakeSDK(canned_reply="APPROVED\nLooks fine.")


@pytest.fixture
def mcp():
    return FakeMCP()


def _run(sdk, mcp, oracle, thread="thr_eval_dryrun"):
    ckpt = graph.open_checkpointer(None)
    g = graph.build_graph(sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=oracle)
    initial = make_initial_state(
        workflow_thread_id=thread,
        mission_id="mis_eval",
        motivated_by_decision_id="dec_eval",
        project_id="prj_eval",
    )
    return g.invoke(initial, config={"configurable": {"thread_id": thread}})


# ---------------------------------------------------------------------------
# 1. happy-path oracle == pilot interrupt_fn, but logged
# ---------------------------------------------------------------------------


def test_happy_path_oracle_drives_graph_to_complete(sdk, mcp):
    oracle = happy_path_oracle()
    final = _run(sdk, mcp, oracle)

    assert final["terminal_state"] == "complete"
    # Every PI gate visit recorded a Decision.
    types = {d.interrupt_type for d in oracle.log}
    assert "pi_greenlight" in types
    assert "pi_acceptance" in types
    # No redirect on the happy path.
    assert oracle.corrections() == []
    # Accept tokens are the bare type-specific tokens (no sentinel).
    for d in oracle.log:
        assert not d.token.startswith(REDIRECT_SENTINEL)
    assert {d.token for d in oracle.decisions_of_type("pi_greenlight")} == {"approve"}
    assert {d.token for d in oracle.decisions_of_type("pi_acceptance")} == {"accept"}


# ---------------------------------------------------------------------------
# 2. correct rule drives the Phase-X² in-run greenlight redraft loop once
# ---------------------------------------------------------------------------


def test_correct_rule_triggers_single_greenlight_redraft(sdk, mcp):
    # Stateful matcher: correct the FIRST pi_greenlight, approve the rest.
    # (Rules are stateless by design; the predicate closes over a counter so
    # the loop redrafts exactly once instead of cycling to the cap.)
    seen = {"n": 0}

    def first_greenlight_only(payload: dict) -> bool:
        if payload.get("type") != "pi_greenlight":
            return False
        seen["n"] += 1
        return seen["n"] == 1

    rubric = Rubric(
        rules=[
            Rule(
                type="pi_greenlight",
                action="correct",
                label="redirect-framing-once",
                predicate=first_greenlight_only,
                correct_text="Reframe around the falsified hypothesis, not the original.",
            )
        ],
        default_action="accept",
    )
    oracle = PIOracle(rubric)
    final = _run(sdk, mcp, oracle, thread="thr_eval_redraft")

    assert final["terminal_state"] == "complete"
    assert final["greenlight_redrafts"] == 1
    corr = oracle.corrections()
    assert len(corr) == 1
    # The correction token carries the sentinel + verbatim PI text.
    assert corr[0].token.startswith(REDIRECT_SENTINEL)
    assert corr[0].token[len(REDIRECT_SENTINEL):].startswith("Reframe around")
    # The loop re-parked at pi_greenlight: at least two greenlight visits.
    assert len(oracle.decisions_of_type("pi_greenlight")) >= 2


# ---------------------------------------------------------------------------
# 3. RunRecord lifts terminal state + oracle log into the gradeable record
# ---------------------------------------------------------------------------


def test_run_record_from_final_state_round_trips(sdk, mcp):
    oracle = happy_path_oracle()
    final = _run(sdk, mcp, oracle)

    rec = RunRecord.from_final_state(
        arc="mission",
        run_label="phase0-dryrun",
        final_state=final,
        oracle_decisions=oracle.as_dicts(),
        seed=7,
        subject_id="cot-gsm8k",
        arm="A",
    )

    assert rec.terminal_state == "complete"
    assert rec.workflow_thread_id == "thr_eval_dryrun"
    assert rec.project_id == "prj_eval"
    assert rec.arm == "A"
    assert rec.seed == 7
    # happy path: no interventions, no redrafts.
    assert rec.pi_intervention_count == 0
    assert rec.greenlight_redrafts == 0
    assert rec.pi_decisions  # non-empty decision log carried through
    # JSON round-trips (default=str covers any non-primitive).
    parsed = json.loads(rec.to_json())
    assert parsed["terminal_state"] == "complete"
    assert parsed["arc"] == "mission"


def test_cap_usd_propagates_through_graph(sdk, mcp):
    """Regression (2026-06-15): a per-run cap_usd seeded into the initial state
    must SURVIVE the graph as a declared channel. LangGraph drops UNDECLARED
    keys at entry, so before cap_usd was added to ResearchWorkflowState an
    expensive run that seeded cap_usd=40 still capped at budget_check's 5.0
    default mid-graph (never reaching the pivot). The budget_check UNIT test
    passed because it called the node directly; only a full-graph invoke catches
    the dropped-channel bug."""
    ckpt = graph.open_checkpointer(None)
    g = graph.build_graph(sdk=sdk, mcp=mcp, checkpointer=ckpt,
                          interrupt_fn=happy_path_oracle())
    initial = make_initial_state(
        workflow_thread_id="thr_cap", mission_id="mis_cap",
        motivated_by_decision_id="dec_cap", project_id="prj_cap")
    initial["cap_usd"] = 42.0  # caller override (e.g. the eval driver for Opus)
    final = g.invoke(initial, config={"configurable": {"thread_id": "thr_cap"}})
    assert final["terminal_state"] == "complete"
    assert final.get("cap_usd") == 42.0, (
        "cap_usd must propagate as a declared state channel; got "
        f"{final.get('cap_usd')!r} (undeclared keys are dropped by LangGraph)"
    )


def test_capability_grades_real_graph_artifacts(sdk, mcp):
    """Regression: a RunRecord built from a REAL graph final_state must let
    grade_capability see the produced artifact kinds.

    The graph emits artifacts shaped {rka_id, entity_type, node_name} but the
    grader reads `kind`; from_final_state must normalize entity_type->kind (and
    rka_id->id, node_name->node) so the documented `from_final_state -> grade_run`
    flow actually scores capability. Before the fix, capability was 0.0 on every
    real run (artifacts present, present_kinds empty)."""
    oracle = happy_path_oracle()
    final = _run(sdk, mcp, oracle, thread="thr_eval_capability")
    assert final["terminal_state"] == "complete"
    assert final["artifacts"], "fake graph should still produce artifacts"

    rec = RunRecord.from_final_state(
        arc="mission", run_label="capability-regression", final_state=final,
    )
    # Normalized artifacts carry a `kind` (alias of entity_type) and `id`.
    assert all("kind" in a for a in rec.artifacts)
    assert all("id" in a for a in rec.artifacts)
    cap = graders.grade_capability(rec)
    assert cap.score > 0.0, f"capability should be > 0, got {cap.detail}"
    assert "journal" in cap.detail["present_kinds"]


def test_run_record_counts_interventions_from_oracle_log(sdk, mcp):
    # A record built off a correcting oracle counts the correction as an
    # intervention (corrections + rejects, not bare accepts).
    seen = {"n": 0}

    def first_greenlight_only(payload: dict) -> bool:
        if payload.get("type") != "pi_greenlight":
            return False
        seen["n"] += 1
        return seen["n"] == 1

    rubric = Rubric(
        rules=[
            Rule(
                type="pi_greenlight",
                action="correct",
                label="redirect-once",
                predicate=first_greenlight_only,
                correct_text="Tighten the scope to the 2-step subset.",
            )
        ],
        default_action="accept",
    )
    oracle = PIOracle(rubric)
    final = _run(sdk, mcp, oracle, thread="thr_eval_intervene")

    rec = RunRecord.from_final_state(
        arc="mission",
        run_label="phase0-intervene",
        final_state=final,
        oracle_decisions=oracle.as_dicts(),
    )
    assert rec.pi_intervention_count == 1
    assert rec.greenlight_redrafts == 1


# ---------------------------------------------------------------------------
# 4. oracle token-contract unit checks (no graph)
# ---------------------------------------------------------------------------


def test_oracle_emits_contract_correct_tokens():
    rubric = Rubric(
        rules=[
            Rule(type="pi_acceptance", action="reject", label="reject-it"),
            Rule(
                type="pi_decision_select",
                action="correct",
                label="redirect-decision",
                correct_text="Pick the pivoted-claim option, not the original.",
            ),
        ],
        default_action="accept",
    )
    oracle = PIOracle(rubric)

    assert oracle({"type": "pi_greenlight"}) == "approve"        # default accept
    assert oracle({"type": "pi_acceptance"}) == "reject"          # explicit reject
    tok = oracle({"type": "pi_decision_select", "decision": "..."})
    assert tok.startswith(REDIRECT_SENTINEL)                      # correct → sentinel
    # log captured all three with right actions
    assert [d.action for d in oracle.log] == ["accept", "reject", "correct"]


def test_correct_rule_without_text_raises():
    rubric = Rubric(
        rules=[Rule(type="pi_greenlight", action="correct", label="no-text")]
    )
    oracle = PIOracle(rubric)
    with pytest.raises(ValueError, match="no correct_text"):
        oracle({"type": "pi_greenlight"})


def test_unknown_interrupt_type_raises():
    oracle = happy_path_oracle()
    with pytest.raises(ValueError, match="unknown interrupt_type"):
        oracle({"type": "pi_not_a_real_gate"})
