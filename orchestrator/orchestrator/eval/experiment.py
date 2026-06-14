"""Deterministic surprising-experiment harness.

Stands in for "running the actual experiment" in the offline eval. Given an
``ExperimentDesign`` (the conditions the orchestrator decided to run) and a
sealed ``SubjectSpec``, it synthesizes per-condition accuracies from the
subject's ``EffectModel`` plus small seeded noise, then classifies whether the
results contradict the run's naive hypothesis.

This is the engine of the planted surprise. Two design-quality properties fall
out for free and are gradeable:

  - A design that includes BOTH 1-step and multi-step problems across BOTH size
    tiers observes the full sign-flip — ``surprise_signal`` returns
    ``shape="interaction"`` and ``contradicts_naive=True`` — and the agent is
    forced to pivot the claim.
  - A design that only tests the large model on multi-step problems sees CoT
    "help" everywhere it looked and reports ``shape="confirms_naive"`` — it
    *misses* the surprise. The capability grader can penalize the weak design;
    the provenance grader can catch the un-pivoted claim.

Noise is bounded well inside the smallest planted effect so the sign of every
CoT delta survives sampling — the surprise is robust, not a coin flip.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from orchestrator.eval.subject import SubjectSpec

# Noise half-width. The smallest |cot_delta| in the default EffectModel is
# 0.04; ±0.012 keeps observed deltas strictly sign-stable.
_NOISE_HALF_WIDTH = 0.012


@dataclass(frozen=True)
class Condition:
    """One experimental cell."""

    model_size_b: float
    steps: int               # representative reasoning depth of the problem bucket
    cot: bool
    n_problems: int = 200

    def key(self) -> str:
        return f"{self.model_size_b}|{self.steps}|{int(self.cot)}|{self.n_problems}"


@dataclass(frozen=True)
class ExperimentDesign:
    """The conditions the orchestrator chose to run, plus a label."""

    label: str
    conditions: list[Condition] = field(default_factory=list)

    def size_tiers(self, effect) -> set[bool]:
        return {effect.is_large(c.model_size_b) for c in self.conditions}

    def step_tiers(self, effect) -> set[bool]:
        return {effect.is_multistep(c.steps) for c in self.conditions}

    def has_cot_contrast(self) -> bool:
        return {c.cot for c in self.conditions} == {True, False}


@dataclass(frozen=True)
class ConditionResult:
    condition: Condition
    accuracy: float
    n: int


@dataclass(frozen=True)
class ExperimentResult:
    design_label: str
    seed: int
    results: list[ConditionResult]

    def by_cell(self) -> dict[tuple[float, int, bool], float]:
        return {(r.condition.model_size_b, r.condition.steps, r.condition.cot): r.accuracy
                for r in self.results}


def _noise(seed: int, condition_key: str) -> float:
    """Deterministic noise in [-half, +half] from (seed, condition)."""
    h = hashlib.sha256(f"{seed}:{condition_key}".encode("utf-8")).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF      # uniform in [0, 1]
    return (frac * 2.0 - 1.0) * _NOISE_HALF_WIDTH


def run_experiment(
    design: ExperimentDesign, subject: SubjectSpec, *, seed: int = 0
) -> ExperimentResult:
    """Synthesize observed accuracies for every condition in the design."""
    results: list[ConditionResult] = []
    for c in design.conditions:
        expected = subject.effect.expected_accuracy(c.model_size_b, c.steps, c.cot)
        observed = expected + _noise(seed, c.key())
        observed = max(0.0, min(1.0, observed))
        results.append(ConditionResult(condition=c, accuracy=round(observed, 4), n=c.n_problems))
    return ExperimentResult(design_label=design.label, seed=seed, results=results)


@dataclass(frozen=True)
class SurpriseSignal:
    """What the result-interpretation stage would observe.

    ``shape`` ∈ {"interaction", "uniform_hurt", "uniform_help",
    "confirms_naive", "underpowered"}; ``contradicts_naive`` is True iff the
    observed CoT effect is not the uniformly-positive main effect the naive
    hypothesis predicts. ``cot_deltas`` maps (size_b, steps) → observed
    CoT − no-CoT accuracy for every cell where both arms were run."""

    shape: str
    contradicts_naive: bool
    cot_deltas: dict[tuple[float, int], float]
    observed_sign_flip: bool
    detail: dict


def surprise_signal(result: ExperimentResult, subject: SubjectSpec) -> SurpriseSignal:
    """Classify the observed results against the naive 'CoT always helps' frame.

    A cell contributes a delta only if BOTH cot and no-cot arms were run for the
    same (size, steps). The naive hypothesis predicts every delta ≥ 0; any
    negative delta contradicts it. A mix of signs across cells is the planted
    interaction."""
    cells = result.by_cell()
    deltas: dict[tuple[float, int], float] = {}
    for (size_b, steps, cot), acc in cells.items():
        if not cot:
            continue
        base = cells.get((size_b, steps, False))
        if base is None:
            continue
        deltas[(size_b, steps)] = round(acc - base, 4)

    if not deltas:
        return SurpriseSignal(
            shape="underpowered", contradicts_naive=False, cot_deltas={},
            observed_sign_flip=False,
            detail={"reason": "no (cot, no-cot) contrast for any cell"},
        )

    signs = {(+1 if d > 1e-6 else (-1 if d < -1e-6 else 0)) for d in deltas.values()}
    has_pos = any(d > 1e-6 for d in deltas.values())
    has_neg = any(d < -1e-6 for d in deltas.values())
    sign_flip = has_pos and has_neg

    if sign_flip:
        shape = "interaction"
    elif has_neg and not has_pos:
        shape = "uniform_hurt"
    elif has_pos and not has_neg:
        # CoT helped in every cell tested — but did the design even look where
        # the surprise lives? If it only tested large×multi, it confirmed the
        # naive frame by omission.
        shape = "confirms_naive"
    else:
        shape = "underpowered"

    contradicts = has_neg  # any negative CoT delta breaks "CoT always helps"
    return SurpriseSignal(
        shape=shape,
        contradicts_naive=contradicts,
        cot_deltas=deltas,
        observed_sign_flip=sign_flip,
        detail={
            "n_cells": len(deltas),
            "n_negative": sum(1 for d in deltas.values() if d < -1e-6),
            "n_positive": sum(1 for d in deltas.values() if d > 1e-6),
            "signs": sorted(signs),
        },
    )


# --- canonical designs, for tests + the live harness ---------------------


def full_factorial_design(
    subject: SubjectSpec, *, small_b: float = 0.5, large_b: float = 7.0,
    n_problems: int = 200,
) -> ExperimentDesign:
    """The *good* design: both size tiers × {1-step, multi-step} × {cot, no-cot}.
    Observes the full interaction → forces the pivot."""
    conds: list[Condition] = []
    for size in (small_b, large_b):
        for steps in (1, 3):
            for cot in (False, True):
                conds.append(Condition(size, steps, cot, n_problems))
    return ExperimentDesign(label="full-factorial", conditions=conds)


def naive_design(
    subject: SubjectSpec, *, large_b: float = 7.0, n_problems: int = 200
) -> ExperimentDesign:
    """The *weak* design: only large model on multi-step problems. Sees CoT
    help and misses the surprise entirely → confirms the naive frame by
    omission."""
    return ExperimentDesign(
        label="naive-large-multistep-only",
        conditions=[
            Condition(large_b, 3, False, n_problems),
            Condition(large_b, 3, True, n_problems),
        ],
    )
