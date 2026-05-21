"""T4 unit tests for the Eval-v2 metrics module.

Mission spec calls for 5 unit tests with synthetic scenarios + returned
bundles to lock the metric math. This file lands those 5 + a small set
of additional locks for edge cases (empty inputs, vacuous expected
sets) so future drift surfaces immediately.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

_V2_DIR = Path(__file__).resolve().parent.parent
if str(_V2_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V2_DIR.parent))

from v2.metrics import (
    aggregate,
    breadth,
    compute_corpus_metrics,
    efficiency,
    expanded_recall,
    ordering_score,
    recall,
    score_scenario,
)


# ---------------------------------------------------------------------------
# Required test #1 — recall over critical-tagged entities only
# ---------------------------------------------------------------------------


def test_recall_over_critical_only():
    # 3 critical-tagged entities expected; 2 of them returned → recall 2/3.
    expected_critical = {
        "dec_01A0000000000000000000",
        "mis_01B0000000000000000000",
        "chk_01C0000000000000000000",
    }
    returned = [
        "dec_01A0000000000000000000",  # ✓
        "mis_01B0000000000000000000",  # ✓
        "jrn_01D0000000000000000000",  # not in critical
    ]
    assert recall(returned, expected_critical) == pytest.approx(2 / 3)


def test_recall_empty_critical_returns_zero():
    """Vacuous case — caller should never invoke for scenarios with no
    critical anchors (schema enforces >=3), but lock the behavior."""
    assert recall(["jrn_01X0000000000000000000"], set()) == 0.0


# ---------------------------------------------------------------------------
# Required test #2 — expanded_recall over the full expected set
# ---------------------------------------------------------------------------


def test_expanded_recall_over_full_expected_set():
    expected_all = {
        "dec_01A0000000000000000000",
        "mis_01B0000000000000000000",
        "chk_01C0000000000000000000",
        "jrn_01D0000000000000000000",
        "ecl_01E0000000000000000000",
    }
    returned = [
        "dec_01A0000000000000000000",
        "mis_01B0000000000000000000",
        "jrn_01D0000000000000000000",
        "lit_01ZZZ000000000000000000",  # noise
    ]
    # 3 of 5 expected returned → 0.6
    assert expanded_recall(returned, expected_all) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Required test #3 — ordering_score is NDCG-style with importance gains
# ---------------------------------------------------------------------------


def test_ordering_score_perfect_ordering_returns_one():
    """When returned order matches the ideal (high-gain items first),
    NDCG == 1.0."""
    expected = [
        {"entity_id": "a", "entity_type": "decision", "importance": "critical"},
        {"entity_id": "b", "entity_type": "mission", "importance": "useful"},
        {"entity_id": "c", "entity_type": "journal", "importance": "nice-to-have"},
    ]
    returned = ["a", "b", "c"]  # critical first, useful second, nice-to-have third
    assert ordering_score(returned, expected) == pytest.approx(1.0)


def test_ordering_score_inverted_ordering_is_lower():
    """Same items in worst order: nice-to-have first, critical last —
    NDCG should drop noticeably."""
    expected = [
        {"entity_id": "a", "entity_type": "decision", "importance": "critical"},
        {"entity_id": "b", "entity_type": "mission", "importance": "useful"},
        {"entity_id": "c", "entity_type": "journal", "importance": "nice-to-have"},
    ]
    returned_perfect = ["a", "b", "c"]
    returned_inverted = ["c", "b", "a"]
    perfect_ndcg = ordering_score(returned_perfect, expected)
    inverted_ndcg = ordering_score(returned_inverted, expected)
    assert inverted_ndcg < perfect_ndcg
    # Hand-computed: DCG_inverted = 1/log2(2) + 2/log2(3) + 3/log2(4)
    #                = 1 + 2/1.585 + 3/2 = 1 + 1.262 + 1.5 = 3.762
    # IDCG = 3/log2(2) + 2/log2(3) + 1/log2(4)
    #      = 3 + 1.262 + 0.5 = 4.762
    # NDCG_inverted = 3.762 / 4.762 ≈ 0.790
    expected_dcg = 1 / math.log2(2) + 2 / math.log2(3) + 3 / math.log2(4)
    expected_idcg = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert inverted_ndcg == pytest.approx(expected_dcg / expected_idcg, abs=1e-6)


def test_ordering_score_unrelated_entries_contribute_zero():
    """Entities not in the expected set contribute 0 gain; only their
    positional displacement of expected items shows in the score."""
    expected = [
        {"entity_id": "a", "entity_type": "decision", "importance": "critical"},
    ]
    # 'a' at position 2 instead of 0 — gain pushed back
    returned = ["x", "y", "a"]
    score = ordering_score(returned, expected)
    # DCG = 3/log2(4) = 1.5; IDCG = 3/log2(2) = 3 → NDCG = 0.5
    assert score == pytest.approx(1.5 / 3.0)


# ---------------------------------------------------------------------------
# Required test #4 — breadth counts entity_type categories matched
# ---------------------------------------------------------------------------


def test_breadth_counts_distinct_entity_types_in_intersection():
    expected = [
        {"entity_id": "a", "entity_type": "decision", "importance": "critical"},
        {"entity_id": "b", "entity_type": "mission", "importance": "critical"},
        {"entity_id": "c", "entity_type": "checkpoint", "importance": "critical"},
        {"entity_id": "d", "entity_type": "journal", "importance": "useful"},
    ]
    # Returned hits 3 of the 4 → breadth=3 (decision + mission + journal)
    returned = ["a", "b", "d", "noise"]
    assert breadth(returned, expected) == 3


def test_breadth_zero_when_nothing_matches():
    expected = [
        {"entity_id": "a", "entity_type": "decision", "importance": "critical"},
    ]
    assert breadth(["noise1", "noise2"], expected) == 0


# ---------------------------------------------------------------------------
# Required test #5 — efficiency (signal-to-noise)
# ---------------------------------------------------------------------------


def test_efficiency_dense_bundle_score_one():
    expected_all = {"a", "b", "c"}
    assert efficiency(["a", "b", "c"], expected_all) == pytest.approx(1.0)


def test_efficiency_diluted_bundle_drops_proportionally():
    expected_all = {"a", "b", "c"}
    # 3 expected of 6 returned → 0.5
    assert efficiency(
        ["a", "b", "c", "noise1", "noise2", "noise3"], expected_all
    ) == pytest.approx(0.5)


def test_efficiency_empty_returned_is_zero():
    assert efficiency([], {"a", "b"}) == 0.0


# ---------------------------------------------------------------------------
# score_scenario — wraps the 5 primitives + per-tool contribution
# ---------------------------------------------------------------------------


def test_score_scenario_integrates_all_metrics():
    scenario = {
        "scenario_id": "test-scenario",
        "actor": "brain",
        "expected_entities": [
            {"entity_id": "dec_01A0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01B0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "chk_01C0000000000000000000", "entity_type": "checkpoint", "importance": "critical"},
            {"entity_id": "jrn_01D0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01E0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    bundle = {
        "scenario_id": "test-scenario",
        "actor": "brain",
        "combined_ranking": [
            "dec_01A0000000000000000000",
            "mis_01B0000000000000000000",
            "jrn_01D0000000000000000000",
            "noise_01000000000000000000",
        ],
        "invocations": [
            {
                "tool": "rka_get_context",
                "entity_ids": [
                    "dec_01A0000000000000000000",
                    "mis_01B0000000000000000000",
                ],
            },
            {
                "tool": "rka_get_journal",
                "entity_ids": ["jrn_01D0000000000000000000"],
            },
        ],
    }
    m = score_scenario(scenario, bundle)
    # 2 of 3 critical present → recall 2/3
    assert m.recall == pytest.approx(2 / 3)
    # 3 of 5 expected present → expanded_recall 0.6
    assert m.expanded_recall == pytest.approx(0.6)
    # 3 expected types hit (decision + mission + journal); cluster + checkpoint missed
    assert m.breadth == 3
    # 3 expected of 4 returned → efficiency 0.75
    assert m.efficiency == pytest.approx(0.75)
    # Per-tool: rka_get_context contributed 2 critical → 2/3 coverage;
    # rka_get_journal contributed 0 critical → 0.0
    assert m.per_tool_critical_coverage["rka_get_context"] == pytest.approx(2 / 3)
    assert m.per_tool_critical_coverage["rka_get_journal"] == 0.0
    # Bookkeeping
    assert m.n_expected_critical == 3
    assert m.n_expected_total == 5
    assert m.n_returned == 4


# ---------------------------------------------------------------------------
# aggregate — per-actor + per-tool breakdown + floor check
# ---------------------------------------------------------------------------


def test_aggregate_computes_per_actor_breakdown():
    from v2.metrics import ScenarioMetrics

    metrics = [
        ScenarioMetrics(
            scenario_id="s1",
            actor="brain",
            recall=0.9, expanded_recall=0.8, ordering_score=0.85,
            breadth=4, efficiency=0.7,
        ),
        ScenarioMetrics(
            scenario_id="s2",
            actor="brain",
            recall=0.6, expanded_recall=0.5, ordering_score=0.65,
            breadth=2, efficiency=0.4,
        ),
        ScenarioMetrics(
            scenario_id="s3",
            actor="executor",
            recall=1.0, expanded_recall=1.0, ordering_score=1.0,
            breadth=3, efficiency=1.0,
        ),
    ]
    agg = aggregate(metrics)
    # Overall mean recall = (0.9 + 0.6 + 1.0) / 3 = 0.833
    assert agg.mean_recall == pytest.approx((0.9 + 0.6 + 1.0) / 3)
    # Per-actor recall: brain = 0.75, executor = 1.0
    assert agg.per_actor["brain"]["mean_recall"] == pytest.approx(0.75)
    assert agg.per_actor["executor"]["mean_recall"] == pytest.approx(1.0)
    # Floor at 0.85: 0.833 < 0.85 → floor_passed False
    assert agg.floor_passed is False


def test_aggregate_per_tool_critical_coverage():
    from v2.metrics import ScenarioMetrics

    metrics = [
        ScenarioMetrics(
            scenario_id="s1", actor="brain", recall=1.0,
            expanded_recall=1.0, ordering_score=1.0, breadth=3, efficiency=1.0,
            per_tool_critical_coverage={"rka_get_context": 0.8, "rka_get_status": 0.5},
        ),
        ScenarioMetrics(
            scenario_id="s2", actor="brain", recall=1.0,
            expanded_recall=1.0, ordering_score=1.0, breadth=3, efficiency=1.0,
            per_tool_critical_coverage={"rka_get_context": 0.6},
        ),
    ]
    agg = aggregate(metrics)
    # rka_get_context invoked in both scenarios → mean of [0.8, 0.6] = 0.7
    assert agg.per_tool_mean_critical_coverage["rka_get_context"] == pytest.approx(0.7)
    # rka_get_status invoked in s1 only → mean of [0.5] = 0.5 (NOT
    # averaged over all scenarios)
    assert agg.per_tool_mean_critical_coverage["rka_get_status"] == pytest.approx(0.5)


def test_aggregate_floor_passes_when_mean_recall_at_threshold():
    from v2.metrics import ScenarioMetrics

    # All three exactly at 0.85
    metrics = [
        ScenarioMetrics(
            scenario_id=f"s{i}", actor="brain", recall=0.85,
            expanded_recall=0.85, ordering_score=0.85, breadth=3, efficiency=0.85,
        )
        for i in range(3)
    ]
    agg = aggregate(metrics)
    assert agg.mean_recall == pytest.approx(0.85)
    assert agg.floor_passed is True


# ---------------------------------------------------------------------------
# End-to-end compute_corpus_metrics — reads corpus + bundles, writes metrics.json
# ---------------------------------------------------------------------------


def test_compute_corpus_metrics_round_trip(tmp_path: Path):
    # Minimal corpus (1 scenario)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    corpus = corpus_dir / "scenarios.jsonl"
    scenario = {
        "scenario_id": "round-trip-test",
        "actor": "brain",
        "trigger": "Round-trip test scenario",
        "tools_invoked": ["rka_get_context"],
        "expected_entities": [
            {"entity_id": "dec_01A0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01B0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "chk_01C0000000000000000000", "entity_type": "checkpoint", "importance": "critical"},
            {"entity_id": "jrn_01D0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01E0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    corpus.write_text(json.dumps(scenario) + "\n")

    # Matching raw bundle: hits every critical + the useful, misses the
    # nice-to-have, plus one noise entity.
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    bundle = {
        "scenario_id": "round-trip-test",
        "actor": "brain",
        "invocations": [
            {
                "tool": "rka_get_context",
                "path": "/api/context",
                "status_code": 200,
                "entity_ids": [
                    "dec_01A0000000000000000000",
                    "mis_01B0000000000000000000",
                    "chk_01C0000000000000000000",
                    "jrn_01D0000000000000000000",
                    "noise_01000000000000000000",
                ],
                "divergence": None,
                "notes": "",
            }
        ],
        "combined_ranking": [
            "dec_01A0000000000000000000",
            "mis_01B0000000000000000000",
            "chk_01C0000000000000000000",
            "jrn_01D0000000000000000000",
            "noise_01000000000000000000",
        ],
    }
    (raw_dir / "round-trip-test.jsonl").write_text(json.dumps(bundle))

    out = tmp_path / "metrics.json"
    result = compute_corpus_metrics(
        corpus_path=corpus, raw_dir=raw_dir, output_path=out
    )

    # Round-trip the JSON write
    persisted = json.loads(out.read_text())
    assert persisted["n_scenarios_corpus"] == 1
    assert persisted["n_scenarios_scored"] == 1
    assert persisted["missing_bundles"] == []
    assert persisted["aggregate"]["mean_recall"] == pytest.approx(1.0)
    # 4 of 5 expected returned → expanded_recall 0.8
    assert persisted["aggregate"]["mean_expanded_recall"] == pytest.approx(0.8)
    # Floor at 0.85: critical-recall 1.0 → passes
    assert persisted["aggregate"]["floor_passed"] is True
    # Reproducibility section is present + non-empty
    assert persisted["provenance"]["corpus_hash"].startswith("sha256:")
    assert persisted["provenance"]["rka_head"]
    assert persisted["provenance"]["timestamp"].endswith("Z")


# ---------------------------------------------------------------------------
# v2.5.4 D4 — per-tool attribution annotation
# (mis_01KS0C8BKTHCA8GB38BGDR1PTQ T2; per dec_01KS0C4PG88F29YBR91VQ3RRXY)
# ---------------------------------------------------------------------------


def test_annotation_records_first_discoverer():
    """The metrics layer derives first-discovery from invocation order: each
    entity is credited to the tool that introduced it first in the bundle,
    NOT to any subsequent tool that also returns it. Verify the per-tool
    split distinguishes first_discovery from total coverage."""
    scenario = {
        "scenario_id": "annotation-test",
        "actor": "brain",
        "expected_entities": [
            {"entity_id": "dec_01CRIT0000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "jrn_01CRIT0000000000000000", "entity_type": "journal", "importance": "critical"},
        ],
    }
    # Two tools both return dec_01CRIT...; ego_graph (first invocation) gets
    # first_discovery credit; rka_get_context also returns it and gets total
    # credit too. jrn_01CRIT... only appears in get_context — credited there
    # both ways.
    bundle = {
        "scenario_id": "annotation-test",
        "actor": "brain",
        "invocations": [
            {
                "tool": "rka_get_ego_graph",
                "path": "/api/graph/ego/dec_01CRIT0000000000000000",
                "status_code": 200,
                "entity_ids": ["dec_01CRIT0000000000000000"],
                "divergence": None,
                "notes": "",
            },
            {
                "tool": "rka_get_context",
                "path": "/api/context",
                "status_code": 200,
                "entity_ids": [
                    "dec_01CRIT0000000000000000",  # already seen by ego_graph
                    "jrn_01CRIT0000000000000000",  # first time
                ],
                "divergence": None,
                "notes": "",
            },
        ],
        "combined_ranking": [
            "dec_01CRIT0000000000000000",
            "jrn_01CRIT0000000000000000",
        ],
    }
    metrics = score_scenario(scenario, bundle)

    # first_discovery: ego_graph first-discovered dec (1/2 critical);
    # get_context first-discovered jrn (1/2 critical).
    assert metrics.per_tool_first_discovery_coverage == {
        "rka_get_ego_graph": pytest.approx(0.5),
        "rka_get_context": pytest.approx(0.5),
    }
    # total: ego_graph returned dec (1/2 critical); get_context returned BOTH (2/2).
    assert metrics.per_tool_total_coverage == {
        "rka_get_ego_graph": pytest.approx(0.5),
        "rka_get_context": pytest.approx(1.0),
    }
    # Pre-v2.5.4 alias preserved and equals total (NOT first_discovery).
    assert metrics.per_tool_critical_coverage == metrics.per_tool_total_coverage


def test_per_tool_attribution_metric_distinguishes_first_vs_total():
    """The canonical D4 use case: rka_get_journal's v2.5.5 drop from 1.000 to
    0.000 was 'attribution shift, not coverage loss' — the entities moved
    from being first-discovered by get_journal to being first-discovered
    by anchor-aware tools. The dual metric makes this distinguishable:
    first_discovery_coverage drops while total_coverage stays the same."""

    expected = [
        {"entity_id": "jrn_01CRIT_A0000000000000", "entity_type": "journal", "importance": "critical"},
        {"entity_id": "jrn_01CRIT_B0000000000000", "entity_type": "journal", "importance": "critical"},
    ]

    # SCENARIO 1 (pre-v2.5.5): get_journal fires first → it first-discovers
    # both critical journals. Anchor-aware tools either don't fire or return
    # empty (the v2.5.5 reorder hadn't lifted them yet).
    pre_bundle = {
        "scenario_id": "pre",
        "actor": "brain",
        "invocations": [
            {
                "tool": "rka_get_journal",
                "path": "/api/notes",
                "status_code": 200,
                "entity_ids": ["jrn_01CRIT_A0000000000000", "jrn_01CRIT_B0000000000000"],
                "divergence": None,
                "notes": "",
            },
            {
                "tool": "rka_get_ego_graph",
                "path": "/api/graph/ego/jrn_01CRIT_A0000000000000",
                "status_code": 200,
                "entity_ids": [],
                "divergence": None,
                "notes": "",
            },
        ],
        "combined_ranking": ["jrn_01CRIT_A0000000000000", "jrn_01CRIT_B0000000000000"],
    }
    pre = score_scenario(
        {"scenario_id": "x", "actor": "brain", "expected_entities": expected},
        pre_bundle,
    )
    assert pre.per_tool_first_discovery_coverage["rka_get_journal"] == pytest.approx(1.0)
    assert pre.per_tool_total_coverage["rka_get_journal"] == pytest.approx(1.0)

    # SCENARIO 2 (post-v2.5.5 runner reorder): anchor-aware ego_graph fires
    # FIRST and first-discovers both critical journals. get_journal still
    # returns them (total unchanged) but no longer first-discovers any
    # (first_discovery drops to 0.000 — PURE attribution shift).
    post_bundle = {
        "scenario_id": "post",
        "actor": "brain",
        "invocations": [
            {
                "tool": "rka_get_ego_graph",
                "path": "/api/graph/ego/jrn_01CRIT_A0000000000000",
                "status_code": 200,
                "entity_ids": ["jrn_01CRIT_A0000000000000", "jrn_01CRIT_B0000000000000"],
                "divergence": None,
                "notes": "",
            },
            {
                "tool": "rka_get_journal",
                "path": "/api/notes",
                "status_code": 200,
                "entity_ids": ["jrn_01CRIT_A0000000000000", "jrn_01CRIT_B0000000000000"],
                "divergence": None,
                "notes": "",
            },
        ],
        "combined_ranking": ["jrn_01CRIT_A0000000000000", "jrn_01CRIT_B0000000000000"],
    }
    post = score_scenario(
        {"scenario_id": "x", "actor": "brain", "expected_entities": expected},
        post_bundle,
    )
    # First-discovery shifted to ego_graph (1.000); get_journal dropped to 0.000.
    assert post.per_tool_first_discovery_coverage["rka_get_ego_graph"] == pytest.approx(1.0)
    assert post.per_tool_first_discovery_coverage["rka_get_journal"] == pytest.approx(0.0)
    # CRITICAL: get_journal's TOTAL coverage stayed at 1.000 — the entities
    # are still in the bundle, just credited to a different tool.
    # The D4 metric makes this distinguishable so a per-tool drop can be
    # flagged as "attribution shift, not coverage loss" WITHOUT triggering
    # false-alarm investigation.
    assert post.per_tool_total_coverage["rka_get_journal"] == pytest.approx(1.0)


def test_compute_corpus_metrics_reports_missing_bundles(tmp_path: Path):
    """If a scenario's bundle file is absent, it's reported in missing_bundles
    and not scored."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    corpus = corpus_dir / "scenarios.jsonl"
    scenario = {
        "scenario_id": "missing-test",
        "actor": "executor",
        "trigger": "Bundle missing-test scenario",
        "tools_invoked": ["rka_get_context"],
        "expected_entities": [
            {"entity_id": "dec_01A0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01B0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "chk_01C0000000000000000000", "entity_type": "checkpoint", "importance": "critical"},
            {"entity_id": "jrn_01D0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01E0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
    }
    corpus.write_text(json.dumps(scenario) + "\n")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    # No bundle file created
    out = tmp_path / "metrics.json"
    result = compute_corpus_metrics(
        corpus_path=corpus, raw_dir=raw_dir, output_path=out
    )
    assert result["missing_bundles"] == ["missing-test"]
    assert result["n_scenarios_scored"] == 0
