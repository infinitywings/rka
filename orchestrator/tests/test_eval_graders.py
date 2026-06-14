"""Tests for the three-axis grader suite."""

from __future__ import annotations

from orchestrator.eval.experiment import (
    full_factorial_design,
    naive_design,
    run_experiment,
    surprise_signal,
)
from orchestrator.eval.graders import (
    claim_pivoted,
    grade_capability,
    grade_provenance,
    grade_reliability,
    grade_run,
)
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.subject import cot_gsm8k_subject

PIVOTED_CLAIM = (
    "CoT is an interaction effect: it helps large models on multi-step problems "
    "but hurts 1-step problems and inverts below a size threshold."
)
NAIVE_CLAIM = "Chain-of-thought uniformly improves accuracy across all problem types."


def _record(**kw) -> RunRecord:
    base = dict(
        arc="mission",
        run_label="t",
        workflow_thread_id="thr_x",
        terminal_state="complete",
        artifacts=[
            {"id": "jrn_1", "kind": "journal", "node": "n"},
            {"id": "dec_1", "kind": "decision", "node": "n"},
            {"id": "clm_1", "kind": "claim", "node": "n"},
            {"id": "mis_1", "kind": "report", "node": "n"},
        ],
        usd_spent=1.0,
    )
    base.update(kw)
    return RunRecord(**base)


# --- capability -----------------------------------------------------------


def test_capability_full_lifecycle_scores_one():
    g = grade_capability(_record())
    assert g.score == 1.0
    assert g.detail["missing_kinds"] == []


def test_capability_partial_scores_fraction():
    rec = _record(artifacts=[{"id": "jrn_1", "kind": "journal", "node": "n"}])
    g = grade_capability(rec)
    assert g.score == 0.25                       # 1 of {journal,decision,claim,report}
    assert set(g.detail["missing_kinds"]) == {"decision", "claim", "report"}


def test_capability_writer_arc_expects_manuscript_and_diagram():
    rec = _record(arc="writer", artifacts=[
        {"id": "ms_1", "kind": "manuscript", "node": "n"},
        {"id": "fig_1", "kind": "diagram", "node": "n"},
        {"id": "jrn_1", "kind": "journal", "node": "n"},
        {"id": "dec_1", "kind": "decision", "node": "n"},
        {"id": "clm_1", "kind": "claim", "node": "n"},
        {"id": "rep_1", "kind": "report", "node": "n"},
    ])
    assert grade_capability(rec).score == 1.0


# --- reliability ----------------------------------------------------------


def test_reliability_clean_run_scores_one():
    assert grade_reliability(_record()).score == 1.0


def test_reliability_penalizes_overruns_and_churn():
    rec = _record(
        terminal_state="escalated",
        usd_spent=99.0,
        greenlight_redrafts=5,
        decision_redrafts=5,
        watchdog_escalations=1,
        escalation_router_hits=2,
    )
    g = grade_reliability(rec, budget_usd=5.0, max_redrafts=6)
    assert g.score == 0.0
    assert g.detail["checks"]["terminal_complete"] is False
    assert g.detail["checks"]["within_budget"] is False
    assert g.detail["checks"]["bounded_redrafts"] is False


def test_reliability_partial_credit():
    rec = _record(usd_spent=99.0)               # only the budget check fails
    g = grade_reliability(rec, budget_usd=5.0)
    assert g.score == 0.8                        # 4 of 5 checks pass


# --- pivot detection ------------------------------------------------------


def test_claim_pivoted_accepts_correct_interaction_claim():
    s = cot_gsm8k_subject()
    res = claim_pivoted(PIVOTED_CLAIM, s)
    assert res["pivoted"] is True
    assert not res["forbidden_hit"]


def test_claim_pivoted_rejects_naive_claim():
    s = cot_gsm8k_subject()
    res = claim_pivoted(NAIVE_CLAIM, s)
    assert res["pivoted"] is False
    assert res["forbidden_hit"]                  # "uniformly improves" / "across all"


# --- provenance (centerpiece) --------------------------------------------


def test_provenance_full_credit_for_traced_recorded_pivot():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=1), s)
    g = grade_provenance(_record(), claim_text=PIVOTED_CLAIM, subject=s, surprise=sig)
    assert g.score == 1.0
    assert all(g.detail["components"].values())


def test_provenance_penalizes_untraceable_pivot():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=1), s)
    rec = _record(workflow_thread_id=None)       # no thread → not recoverable
    g = grade_provenance(rec, claim_text=PIVOTED_CLAIM, subject=s, surprise=sig)
    assert g.detail["components"]["traceable"] is False
    assert g.score < 1.0


def test_provenance_penalizes_unrecorded_pivot():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=1), s)
    rec = _record(artifacts=[                     # claim made but no decision recorded
        {"id": "jrn_1", "kind": "journal", "node": "n"},
        {"id": "clm_1", "kind": "claim", "node": "n"},
    ])
    g = grade_provenance(rec, claim_text=PIVOTED_CLAIM, subject=s, surprise=sig)
    assert g.detail["components"]["pivot_recorded"] is False


def test_provenance_punishes_ignoring_a_real_surprise():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=1), s)
    # Surprise contradicted the naive frame, but the agent parroted it anyway.
    g = grade_provenance(_record(), claim_text=NAIVE_CLAIM, subject=s, surprise=sig)
    assert g.detail["components"]["pivot_correct"] is False
    assert g.detail["components"]["responsive_to_surprise"] is False
    assert g.score <= 0.5


def test_provenance_no_overclaim_credit_when_no_contradiction():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(naive_design(s), s, seed=1), s)
    # No contradiction observed; a measured (non-naive) claim is fine even
    # without the full interaction vocabulary.
    measured = "On the large model with multi-step problems, CoT improved accuracy."
    g = grade_provenance(_record(), claim_text=measured, subject=s, surprise=sig)
    assert g.detail["components"]["responsive_to_surprise"] is True


# --- aggregate ------------------------------------------------------------


def test_grade_run_aggregates_three_axes():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=1), s)
    report = grade_run(_record(), subject=s, claim_text=PIVOTED_CLAIM, surprise=sig)
    assert report.overall == 1.0
    d = report.to_dict()
    assert d["capability"]["score"] == 1.0
    assert d["reliability"]["score"] == 1.0
    assert d["provenance"]["score"] == 1.0


def test_grade_run_overall_is_mean_of_axes():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=1), s)
    # Naive claim tanks provenance; capability + reliability stay high.
    report = grade_run(_record(), subject=s, claim_text=NAIVE_CLAIM, surprise=sig)
    expected = round((report.capability.score + report.reliability.score
                      + report.provenance.score) / 3.0, 4)
    assert report.overall == expected
    assert report.provenance.score < report.capability.score
