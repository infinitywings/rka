"""Tests for the sorting-crossover subject — a REAL, CPU-only experiment.

These assert the planted surprise is a genuine, reproducible empirical
phenomenon (not a synthetic effect): the comparison-count advantage of quicksort
over insertion sort really flips sign across input size × ordering.
"""

from __future__ import annotations

from orchestrator.eval.graders import grade_provenance, grade_run
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.sort_crossover import (
    LARGE_N,
    SMALL_N,
    full_quadrant_design,
    insertion_sort_comparisons,
    make_array,
    naive_design,
    quicksort_first_pivot_comparisons,
    run_sort_experiment,
    sort_crossover_subject,
    sort_surprise_signal,
)

PIVOTED_CLAIM = (
    "Quicksort vs insertion sort is an interaction between size and ordering: "
    "naive first-pivot quicksort hits its worst case on nearly-sorted input and "
    "the comparison-count advantage crosses over."
)
NAIVE_CLAIM = "Quicksort is always faster than insertion sort regardless of input."


# --- the instrumented sorts are correct + count as expected ---------------


def test_both_sorts_produce_correct_order():
    for ordering in ("random", "nearly_sorted", "sorted", "reversed"):
        arr = make_array(40, ordering, seed=1)
        ins_sorted, _ = insertion_sort_comparisons(arr)
        qs_sorted, _ = quicksort_first_pivot_comparisons(arr)
        assert ins_sorted == sorted(arr)
        assert qs_sorted == sorted(arr)


def test_insertion_sort_is_linear_on_sorted_input():
    arr = make_array(100, "sorted", seed=0)
    _, comparisons = insertion_sort_comparisons(arr)
    assert comparisons == 99            # exactly n-1: O(n) best case


def test_quicksort_first_pivot_is_quadratic_on_sorted_input():
    n = 100
    arr = make_array(n, "sorted", seed=0)
    _, qs = quicksort_first_pivot_comparisons(arr)
    _, ins = insertion_sort_comparisons(arr)
    # First-pivot quicksort degrades to ~n(n-1)/2 on sorted input...
    assert qs == n * (n - 1) // 2
    # ...far worse than insertion sort's O(n) there.
    assert qs > 40 * ins


# --- the planted surprise is REAL + reproducible --------------------------


def test_full_quadrant_observes_real_sign_flip():
    sig = sort_surprise_signal(run_sort_experiment(full_quadrant_design(), seed=7))
    assert sig.shape == "interaction"
    assert sig.contradicts_naive is True
    assert sig.observed_sign_flip is True
    adv = sig.quicksort_advantage
    # Quicksort wins on random input (the headline) at BOTH sizes...
    assert adv[(LARGE_N, "random")] > 0
    assert adv[(SMALL_N, "random")] > 0
    # ...and the surprise: nearly-sorted breaks quicksort at BOTH sizes.
    assert adv[(LARGE_N, "nearly_sorted")] < 0
    assert adv[(SMALL_N, "nearly_sorted")] < 0
    # Ordering-driven sign flip: 2 wins, 2 losses.
    assert sig.detail["n_quicksort_better"] == 2
    assert sig.detail["n_quicksort_worse"] == 2


def test_experiment_is_deterministic():
    r1 = run_sort_experiment(full_quadrant_design(), seed=3)
    r2 = run_sort_experiment(full_quadrant_design(), seed=3)
    assert r1.by_cell() == r2.by_cell()


def test_sign_flip_is_robust_across_seeds():
    for seed in range(8):
        sig = sort_surprise_signal(run_sort_experiment(full_quadrant_design(), seed=seed))
        assert sig.shape == "interaction"
        assert sig.quicksort_advantage[(LARGE_N, "random")] > 0
        assert sig.quicksort_advantage[(LARGE_N, "nearly_sorted")] < 0


def test_naive_design_misses_the_surprise():
    sig = sort_surprise_signal(run_sort_experiment(naive_design(), seed=7))
    assert sig.shape == "confirms_naive"
    assert sig.contradicts_naive is False
    assert sig.observed_sign_flip is False


# --- subject framing + sealing -------------------------------------------


def test_public_framing_hides_the_sealed_quadrant():
    s = sort_crossover_subject()
    pub = s.public_framing()
    flat = str(pub).lower()
    # The sealed quadrant + the distinctive sealed-claim phrasing must not leak.
    # (The word "crossover" appears in the public subject_id, which is fine — it
    # names the subject; it does not reveal the answer.)
    assert "quadrant_quicksort_advantage_sign" not in flat
    assert "flips sign" not in flat
    assert "interaction between" not in flat
    assert "quicksort" in flat                # but the question IS visible
    assert len(pub["literature_anchors"]) == 4


def test_ground_truth_hash_stable_and_seals_quadrant():
    s1 = sort_crossover_subject()
    s2 = sort_crossover_subject()
    assert s1.ground_truth_hash() == s2.ground_truth_hash()
    assert len(s1.ground_truth_hash()) == 64
    # The sealed quadrant participates in the hash.
    import dataclasses

    tampered = dataclasses.replace(
        s1, sealed_extra={**s1.sealed_extra, "headline_win_cell": "small/random"}
    )
    assert tampered.ground_truth_hash() != s1.ground_truth_hash()


def test_subject_has_no_synthetic_effect_model():
    # This subject's experiment is a real computation; it must not carry the
    # CoT synthetic EffectModel.
    assert sort_crossover_subject().effect is None


# --- end-to-end: real experiment → surprise → graders --------------------


def _record(**kw) -> RunRecord:
    base = dict(
        arc="mission", run_label="sort", workflow_thread_id="thr_sort",
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


def test_graders_score_a_pivoted_sorting_run_full_marks():
    s = sort_crossover_subject()
    sig = sort_surprise_signal(run_sort_experiment(full_quadrant_design(), seed=1))
    g = grade_provenance(_record(), claim_text=PIVOTED_CLAIM, subject=s, surprise=sig)
    assert g.score == 1.0
    assert all(g.detail["components"].values())


def test_graders_punish_ignoring_the_real_surprise():
    s = sort_crossover_subject()
    sig = sort_surprise_signal(run_sort_experiment(full_quadrant_design(), seed=1))
    report = grade_run(_record(), subject=s, claim_text=NAIVE_CLAIM, surprise=sig)
    assert report.provenance.score <= 0.5      # naive claim tanks provenance
    assert report.capability.score == 1.0      # but artifacts still produced
