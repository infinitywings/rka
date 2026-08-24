"""Locks for the back-tracing metric math (pure functions, no HTTP)."""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.tracing.metrics import (  # noqa: E402
    aggregate,
    anchor_reciprocal_rank,
    pivot_score,
    score_scenario,
    trace_scores,
)

TRACE = [
    {"entity_id": "jrn_dir", "entity_type": "journal", "relation": "directive", "importance": "critical"},
    {"entity_id": "clm_ev", "entity_type": "claim", "relation": "evidence", "importance": "critical"},
    {"entity_id": "lit_a", "entity_type": "literature", "relation": "literature", "importance": "useful"},
]


def test_anchor_reciprocal_rank() -> None:
    assert anchor_reciprocal_rank(["dec_x", "dec_a"], "dec_a") == 0.5
    assert anchor_reciprocal_rank(["dec_a"], "dec_a") == 1.0
    assert anchor_reciprocal_rank(["dec_x"], "dec_a") == 0.0
    assert anchor_reciprocal_rank([], "dec_a") == 0.0


def test_trace_scores_partial_recall() -> None:
    scores = trace_scores(TRACE, {"jrn_dir", "lit_a", "noise_1", "noise_2"})
    assert scores["trace_recall"] == 0.5  # 1 of 2 critical
    assert scores["expanded_recall"] == 2 / 3
    assert scores["per_relation"]["directive"] == {"expected": 1, "found": 1}
    assert scores["per_relation"]["evidence"] == {"expected": 1, "found": 0}
    assert scores["precision"] == 0.5  # 2 relevant of 4 returned


def test_trace_scores_empty_returns() -> None:
    scores = trace_scores(TRACE, set())
    assert scores["trace_recall"] == 0.0
    assert scores["precision"] == 0.0


def test_pivot_score_stale_surfacing() -> None:
    pivot = {"superseded_decision_id": "dec_old", "superseding_decision_id": "dec_new"}
    assert pivot_score(None, {"dec_old"}) == {"applicable": False}
    ok = pivot_score(pivot, {"dec_new", "dec_old"})
    assert ok["superseding_found"] and not ok["stale_surfacing"]
    stale = pivot_score(pivot, {"dec_old"})
    assert stale["stale_surfacing"] is True


def test_score_scenario_union_beats_single_surface() -> None:
    scenario = {
        "scenario_id": "s1",
        "anchor_decision": "dec_a",
        "expected_trace": TRACE,
        "pivot": {"superseded_decision_id": "dec_old", "superseding_decision_id": "dec_a"},
    }
    result = score_scenario(
        scenario,
        {"ego": ["jrn_dir"], "multi_hop": ["clm_ev", "lit_a", "dec_a"]},
        ["dec_x", "dec_a"],
        [],
    )
    assert result["union"]["trace_recall"] == 1.0
    assert result["per_surface"]["ego"]["trace_recall"] == 0.5
    assert result["anchor_reciprocal_rank"] == 0.5
    assert result["pivot"]["superseding_found"] is True


def test_aggregate_rolls_up_relations_and_pivots() -> None:
    scenario = {
        "scenario_id": "s1",
        "anchor_decision": "dec_a",
        "expected_trace": TRACE,
        "pivot": {"superseded_decision_id": "dec_old", "superseding_decision_id": "dec_a"},
    }
    r1 = score_scenario(
        scenario, {"ego": ["jrn_dir", "clm_ev", "lit_a", "dec_a"]}, ["dec_a"], []
    )
    r2 = score_scenario(
        {**scenario, "scenario_id": "s2", "pivot": None},
        {"ego": []},
        None,
        ["multi_hop: HTTP 422"],
    )
    rollup = aggregate([r1, r2])
    assert rollup["n_scenarios"] == 2
    assert rollup["trace_recall_mean"] == 0.5
    assert rollup["anchor_mrr"] == 1.0  # only s1 had an NL query
    assert rollup["per_relation"]["directive"]["recall"] == 0.5
    assert rollup["pivot_scenarios"] == 1 and rollup["pivot_correct"] == 1
    assert rollup["scenarios_with_divergences"] == ["s2"]
