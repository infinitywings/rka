"""Tests for the Pareto dominance helper used by rka_present_decision."""

from __future__ import annotations

from rka.services.pareto import (
    DOMINANCE_DIMS,
    _dominates,
    _score,
    compute_dominance,
)


def _opt(conf: float, time: str, rev: str) -> dict:
    return {
        "confidence_numeric": conf,
        "effort_time": time,
        "effort_reversibility": rev,
    }


class TestScore:
    def test_confidence_higher_better(self):
        assert _score(_opt(0.8, "M", "reversible"), "confidence_numeric") > \
               _score(_opt(0.4, "M", "reversible"), "confidence_numeric")

    def test_effort_time_s_beats_xl(self):
        # Lower effort is better → higher score.
        assert _score(_opt(0.5, "S", "reversible"), "effort_time") > \
               _score(_opt(0.5, "XL", "reversible"), "effort_time")

    def test_reversibility_reversible_beats_irreversible(self):
        assert _score(_opt(0.5, "M", "reversible"), "effort_reversibility") > \
               _score(_opt(0.5, "M", "irreversible"), "effort_reversibility")


class TestDominates:
    def test_a_dominates_b_on_all_three(self):
        a = _opt(0.9, "S", "reversible")
        b = _opt(0.5, "XL", "irreversible")
        assert _dominates(a, b, DOMINANCE_DIMS) is True
        assert _dominates(b, a, DOMINANCE_DIMS) is False

    def test_mutual_non_dominance_trade_off(self):
        # A has higher confidence, but B has better effort → neither dominates.
        a = _opt(0.9, "XL", "irreversible")
        b = _opt(0.5, "S", "reversible")
        assert _dominates(a, b, DOMINANCE_DIMS) is False
        assert _dominates(b, a, DOMINANCE_DIMS) is False

    def test_identical_options_are_not_dominated(self):
        a = _opt(0.7, "M", "costly")
        b = _opt(0.7, "M", "costly")
        assert _dominates(a, b, DOMINANCE_DIMS) is False
        assert _dominates(b, a, DOMINANCE_DIMS) is False

    def test_tie_plus_strict_is_dominance(self):
        # Same confidence and reversibility, A has better effort_time.
        a = _opt(0.7, "S", "reversible")
        b = _opt(0.7, "L", "reversible")
        assert _dominates(a, b, DOMINANCE_DIMS) is True


class TestComputeDominance:
    def test_one_dominated_one_dominator(self):
        options = [
            _opt(0.9, "S", "reversible"),   # 0: dominator
            _opt(0.5, "XL", "irreversible"),  # 1: dominated by 0
        ]
        result = compute_dominance(options)
        assert result == {0: None, 1: 0}

    def test_two_mutually_non_dominated(self):
        options = [
            _opt(0.9, "XL", "irreversible"),
            _opt(0.5, "S", "reversible"),
        ]
        result = compute_dominance(options)
        assert result == {0: None, 1: None}

    def test_five_options_two_non_dominated(self):
        options = [
            _opt(0.9, "S", "reversible"),     # 0: Pareto-optimal
            _opt(0.8, "M", "reversible"),     # 1: dominated by 0
            _opt(0.7, "M", "costly"),         # 2: dominated by 0
            _opt(0.95, "XL", "costly"),       # 3: trade-off vs 0 (higher conf, worse effort + rev)
            _opt(0.5, "S", "irreversible"),   # 4: dominated by 0 (lower conf, equal effort, worse rev)
        ]
        result = compute_dominance(options)
        assert result[0] is None
        assert result[1] == 0
        assert result[2] == 0
        assert result[3] is None  # non-dominated trade-off
        assert result[4] == 0

    def test_all_identical_none_dominated(self):
        options = [_opt(0.7, "M", "costly") for _ in range(4)]
        result = compute_dominance(options)
        assert all(v is None for v in result.values())

    def test_chain_dominance_records_first_dominator(self):
        # 0 dominates 1 and 2; 1 also dominates 2. compute_dominance records
        # the first dominator it encounters; either 0 or 1 is acceptable for 2.
        options = [
            _opt(0.9, "S", "reversible"),
            _opt(0.8, "M", "reversible"),
            _opt(0.6, "L", "costly"),
        ]
        result = compute_dominance(options)
        assert result[0] is None
        assert result[1] == 0
        assert result[2] in {0, 1}
