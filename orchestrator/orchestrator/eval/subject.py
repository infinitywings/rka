"""Sealed research-subject spec + ground-truth effect model for the eval.

The eval measures whether the agentic orchestrator runs a *correct* research
lifecycle — and, critically, whether it **pivots its claim** when the
experiment contradicts the starting hypothesis. To grade that deterministically
we need a subject whose ground truth is known and sealed:

  - the orchestrator under test sees only ``research_question`` +
    ``naive_hypothesis`` (its starting frame) + ``literature_anchors``;
  - the ``EffectModel`` (the true data-generating process) and
    ``ground_truth_claim`` are the *sealed* answer — used by the experiment
    harness to synthesize results and by the graders to score the final claim,
    never shown to the agent;
  - ``ground_truth_hash()`` publishes a sha256 over the sealed fields so a run
    can be proven not to have leaked the answer (a result is only credible if
    the sealed hash matches what the graders scored against).

Subject: *"Does chain-of-thought prompting improve a small open LLM's accuracy
on grade-school math word problems?"*

The planted surprise is an **interaction with a sign flip**, not the main
effect the naive hypothesis predicts:

  - CoT *helps* large models on multi-step (≥2-step) problems  (the headline,
    the thing everyone expects);
  - CoT *hurts* on 1-step problems (the overhead/derailment cost);
  - the benefit *inverts* below a model-size threshold — small models are hurt
    by CoT even on multi-step problems.

A thorough literature review surfaces a hint of the interaction (one anchor
reports a 1-step regression); a good experiment design that includes BOTH
1-step and multi-step problems across BOTH size tiers will observe the flip
and be forced to pivot the claim from "CoT improves accuracy" to the
interaction statement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EffectModel:
    """The sealed data-generating process: expected accuracy by condition.

    ``cot_delta`` encodes the planted surprise (sign depends on size × steps).
    Deltas are kept well clear of the experiment harness's noise band so the
    sign of every effect survives sampling.
    """

    size_threshold_b: float = 2.0          # "large" iff params ≥ this (billions)
    step_threshold: int = 2                # "multi-step" iff steps ≥ this

    # base accuracy (CoT off) decomposed into size/step contributions
    base_floor: float = 0.35
    large_bonus: float = 0.25
    multistep_penalty: float = 0.10

    # CoT deltas per (large?, multi?) quadrant — the interaction surface
    delta_large_multi: float = 0.12        # the expected headline win
    delta_large_single: float = -0.06      # surprise A: hurts on 1-step
    delta_small_multi: float = -0.04       # surprise B: inverts below threshold
    delta_small_single: float = -0.08      # hurt most: small model, 1-step

    acc_floor: float = 0.02
    acc_ceil: float = 0.98

    def is_large(self, size_b: float) -> bool:
        return size_b >= self.size_threshold_b

    def is_multistep(self, steps: int) -> bool:
        return steps >= self.step_threshold

    def base_accuracy(self, size_b: float, steps: int) -> float:
        acc = self.base_floor
        if self.is_large(size_b):
            acc += self.large_bonus
        if self.is_multistep(steps):
            acc -= self.multistep_penalty
        return acc

    def cot_delta(self, size_b: float, steps: int) -> float:
        large, multi = self.is_large(size_b), self.is_multistep(steps)
        if large and multi:
            return self.delta_large_multi
        if large and not multi:
            return self.delta_large_single
        if not large and multi:
            return self.delta_small_multi
        return self.delta_small_single

    def expected_accuracy(self, size_b: float, steps: int, cot: bool) -> float:
        acc = self.base_accuracy(size_b, steps)
        if cot:
            acc += self.cot_delta(size_b, steps)
        return max(self.acc_floor, min(self.acc_ceil, acc))


@dataclass(frozen=True)
class LiteratureAnchor:
    """A synthetic prior-work claim the literature stage should surface.

    ``hints_interaction`` marks the anchor that seeds the surprise — a thorough
    review finds it; a shallow one misses it and the pivot lands later (a
    gradeable difference)."""

    cite_key: str
    claim: str
    supports_cot: bool
    hints_interaction: bool = False


@dataclass(frozen=True)
class SubjectSpec:
    subject_id: str
    title: str
    research_question: str
    naive_hypothesis: str          # the frame the agent starts from
    ground_truth_claim: str        # SEALED — the correct pivoted claim
    # ``effect`` is the CoT subject's synthetic data-generating process. Subjects
    # whose experiment is a REAL computation (e.g. the sorting-crossover subject,
    # which actually counts comparisons) leave it None and instead describe their
    # sealed answer in ``sealed_extra``.
    effect: Optional[EffectModel] = None
    literature_anchors: list[LiteratureAnchor] = field(default_factory=list)

    # grading vocabulary (sealed answer key for the claim graders)
    required_claim_keywords: list[str] = field(default_factory=list)
    forbidden_claim_keywords: list[str] = field(default_factory=list)

    # subject-specific sealed ground truth for subjects that don't use ``effect``
    # (e.g. the sorting crossover quadrant thresholds). Folded into the hash.
    sealed_extra: dict = field(default_factory=dict)

    # --- the open (agent-visible) framing vs. the sealed answer ---
    def public_framing(self) -> dict:
        """Exactly what the orchestrator-under-test is allowed to see."""
        return {
            "subject_id": self.subject_id,
            "title": self.title,
            "research_question": self.research_question,
            "naive_hypothesis": self.naive_hypothesis,
            "literature_anchors": [
                {"cite_key": a.cite_key, "claim": a.claim} for a in self.literature_anchors
            ],
        }

    def _sealed_fields(self) -> dict:
        """The fields the agent must NOT see — hashed for integrity."""
        sealed: dict = {
            "ground_truth_claim": self.ground_truth_claim,
            "required_claim_keywords": sorted(self.required_claim_keywords),
            "forbidden_claim_keywords": sorted(self.forbidden_claim_keywords),
        }
        if self.effect is not None:
            e = self.effect
            sealed["effect"] = {
                "size_threshold_b": e.size_threshold_b,
                "step_threshold": e.step_threshold,
                "base_floor": e.base_floor,
                "large_bonus": e.large_bonus,
                "multistep_penalty": e.multistep_penalty,
                "delta_large_multi": e.delta_large_multi,
                "delta_large_single": e.delta_large_single,
                "delta_small_multi": e.delta_small_multi,
                "delta_small_single": e.delta_small_single,
            }
        if self.sealed_extra:
            sealed["sealed_extra"] = self.sealed_extra
        return sealed

    def ground_truth_hash(self) -> str:
        blob = json.dumps(self._sealed_fields(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def cot_gsm8k_subject() -> SubjectSpec:
    """The recommended Phase-0 subject — CoT × GSM8K with a planted
    size×steps interaction (sign-flip) surprise."""
    effect = EffectModel()
    return SubjectSpec(
        subject_id="cot-gsm8k",
        title="Chain-of-thought prompting and small-LLM accuracy on grade-school math",
        research_question=(
            "Does chain-of-thought prompting improve a small open LLM's accuracy "
            "on grade-school math word problems?"
        ),
        naive_hypothesis=(
            "Chain-of-thought prompting improves accuracy on grade-school math "
            "word problems across model sizes and problem types."
        ),
        ground_truth_claim=(
            "Chain-of-thought prompting helps only large models on multi-step "
            "(>=2-step) problems; it degrades accuracy on 1-step problems, and "
            "the benefit inverts below a model-size threshold (small models are "
            "hurt by CoT even on multi-step problems). The effect is an "
            "interaction between model size and reasoning depth, not a main effect."
        ),
        effect=effect,
        literature_anchors=[
            LiteratureAnchor(
                "wei2022cot",
                "Chain-of-thought prompting elicits reasoning in large language models.",
                supports_cot=True,
            ),
            LiteratureAnchor(
                "kojima2022zeroshot",
                "Large language models are zero-shot reasoners when prompted to think step by step.",
                supports_cot=True,
            ),
            LiteratureAnchor(
                "liu2023overhead",
                "On simple single-step questions, step-by-step prompting can introduce "
                "errors and reduce accuracy relative to direct answering.",
                supports_cot=False,
                hints_interaction=True,
            ),
            LiteratureAnchor(
                "scaling2023emergent",
                "Reasoning-prompt gains appear only above a model-scale threshold; "
                "below it the same prompts can hurt.",
                supports_cot=False,
                hints_interaction=True,
            ),
        ],
        required_claim_keywords=["interaction", "1-step", "multi-step", "threshold"],
        forbidden_claim_keywords=[
            "uniformly improves", "always helps", "across all", "main effect of cot is positive",
        ],
    )
