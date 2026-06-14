"""Tests for the deterministic surprising-experiment harness."""

from __future__ import annotations

from orchestrator.eval.experiment import (
    Condition,
    ExperimentDesign,
    full_factorial_design,
    naive_design,
    run_experiment,
    surprise_signal,
)
from orchestrator.eval.subject import cot_gsm8k_subject


def test_run_experiment_is_deterministic():
    s = cot_gsm8k_subject()
    design = full_factorial_design(s)
    r1 = run_experiment(design, s, seed=42)
    r2 = run_experiment(design, s, seed=42)
    assert r1.by_cell() == r2.by_cell()


def test_noise_is_bounded_and_sign_stable():
    s = cot_gsm8k_subject()
    design = full_factorial_design(s)
    # Across many seeds, every observed CoT delta keeps the sign of the
    # sealed effect — the surprise is robust, never a coin flip.
    for seed in range(20):
        sig = surprise_signal(run_experiment(design, s, seed=seed), s)
        # large+multi positive, the other three negative → always an interaction
        assert sig.shape == "interaction"
        assert sig.cot_deltas[(7.0, 3)] > 0
        assert sig.cot_deltas[(7.0, 1)] < 0
        assert sig.cot_deltas[(0.5, 3)] < 0
        assert sig.cot_deltas[(0.5, 1)] < 0


def test_full_factorial_observes_the_surprise():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(full_factorial_design(s), s, seed=7), s)
    assert sig.shape == "interaction"
    assert sig.contradicts_naive is True
    assert sig.observed_sign_flip is True
    assert sig.detail["n_negative"] == 3
    assert sig.detail["n_positive"] == 1


def test_naive_design_misses_the_surprise():
    s = cot_gsm8k_subject()
    sig = surprise_signal(run_experiment(naive_design(s), s, seed=7), s)
    # Only large×multi was tested → CoT "helped" everywhere it looked.
    assert sig.shape == "confirms_naive"
    assert sig.contradicts_naive is False
    assert sig.observed_sign_flip is False


def test_underpowered_when_no_cot_contrast():
    s = cot_gsm8k_subject()
    # Only cot-on arms; no baseline to diff against.
    design = ExperimentDesign(
        label="cot-only",
        conditions=[Condition(7.0, 3, True), Condition(0.5, 1, True)],
    )
    sig = surprise_signal(run_experiment(design, s, seed=1), s)
    assert sig.shape == "underpowered"
    assert sig.contradicts_naive is False
    assert sig.cot_deltas == {}


def test_uniform_hurt_shape_when_only_negative_cells_tested():
    s = cot_gsm8k_subject()
    # Test only cells where CoT hurts (small model, both depths).
    design = ExperimentDesign(
        label="small-only",
        conditions=[
            Condition(0.5, 1, False), Condition(0.5, 1, True),
            Condition(0.5, 3, False), Condition(0.5, 3, True),
        ],
    )
    sig = surprise_signal(run_experiment(design, s, seed=3), s)
    assert sig.shape == "uniform_hurt"
    assert sig.contradicts_naive is True       # negative deltas still break the naive frame


def test_design_tier_helpers():
    s = cot_gsm8k_subject()
    full = full_factorial_design(s)
    assert full.size_tiers(s.effect) == {True, False}
    assert full.step_tiers(s.effect) == {True, False}
    assert full.has_cot_contrast() is True
    assert naive_design(s).size_tiers(s.effect) == {True}
