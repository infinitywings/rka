"""Tests for the sealed subject spec + ground-truth effect model."""

from __future__ import annotations

from orchestrator.eval.subject import EffectModel, cot_gsm8k_subject


def test_effect_model_encodes_the_planted_interaction():
    e = EffectModel()
    # The headline win: large model, multi-step → CoT helps.
    assert e.cot_delta(7.0, 3) > 0
    # Surprise A: large model, 1-step → CoT hurts.
    assert e.cot_delta(7.0, 1) < 0
    # Surprise B: small model, multi-step → benefit inverts (hurts).
    assert e.cot_delta(0.5, 3) < 0
    # Small model, 1-step → hurt as well.
    assert e.cot_delta(0.5, 1) < 0


def test_only_large_multistep_is_a_cot_win():
    e = EffectModel()
    wins = [
        (size, steps)
        for size in (0.5, 7.0)
        for steps in (1, 3)
        if e.cot_delta(size, steps) > 0
    ]
    assert wins == [(7.0, 3)]


def test_expected_accuracy_reflects_delta_and_clamps():
    e = EffectModel()
    base = e.expected_accuracy(7.0, 3, cot=False)
    with_cot = e.expected_accuracy(7.0, 3, cot=True)
    assert with_cot > base                      # large+multi: CoT lifts accuracy
    # 1-step large: CoT lowers it.
    assert e.expected_accuracy(7.0, 1, cot=True) < e.expected_accuracy(7.0, 1, cot=False)
    # Clamped into [floor, ceil].
    assert 0.0 <= e.expected_accuracy(0.5, 9, cot=True) <= 1.0


def test_size_and_step_thresholds():
    e = EffectModel(size_threshold_b=2.0, step_threshold=2)
    assert e.is_large(7.0) and not e.is_large(0.5)
    assert e.is_multistep(2) and not e.is_multistep(1)


def test_public_framing_excludes_sealed_answer():
    s = cot_gsm8k_subject()
    pub = s.public_framing()
    flat = str(pub).lower()
    # The sealed pivoted claim and the effect deltas must not leak.
    assert "interaction between model size" not in flat
    assert "delta_large_multi" not in flat
    assert "required_claim_keywords" not in pub
    # But the agent-visible framing IS present.
    assert "chain-of-thought" in flat
    assert pub["naive_hypothesis"]
    assert len(pub["literature_anchors"]) == 4


def test_ground_truth_hash_is_stable_and_seals_the_answer():
    s1 = cot_gsm8k_subject()
    s2 = cot_gsm8k_subject()
    assert s1.ground_truth_hash() == s2.ground_truth_hash()
    assert len(s1.ground_truth_hash()) == 64        # sha256 hex


def test_ground_truth_hash_changes_when_sealed_effect_changes():
    import dataclasses

    s = cot_gsm8k_subject()
    tampered = dataclasses.replace(
        s, effect=dataclasses.replace(s.effect, delta_large_multi=0.99)
    )
    assert tampered.ground_truth_hash() != s.ground_truth_hash()


def test_literature_anchors_seed_the_surprise():
    s = cot_gsm8k_subject()
    hinters = [a for a in s.literature_anchors if a.hints_interaction]
    # At least one anchor hints at the interaction so a thorough lit review
    # can surface the seed of the surprise.
    assert len(hinters) >= 2
    assert any(not a.supports_cot for a in s.literature_anchors)
