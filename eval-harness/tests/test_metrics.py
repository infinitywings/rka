"""Unit tests for the eval-harness metric functions.

Reference-vector validation per mission acceptance criterion. The
graded-NDCG correctness check uses small hand-computed examples so a
regression surfaces immediately.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from eval_harness.metrics import (
    aggregate_for_config,
    build_provenance,
    load_labels,
    load_results_for_config,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    sha256_of_path,
)


# ---------------------------------------------------------------------------
# Precision@k
# ---------------------------------------------------------------------------


def test_precision_at_10_all_relevant():
    ranked = [f"r{i}" for i in range(10)]
    ratings = {rid: 2 for rid in ranked}
    assert precision_at_k(ranked, ratings, k=10) == 1.0


def test_precision_at_10_none_relevant():
    ranked = [f"r{i}" for i in range(10)]
    ratings = {rid: 0 for rid in ranked}
    assert precision_at_k(ranked, ratings, k=10) == 0.0


def test_precision_at_10_three_out_of_ten():
    ranked = [f"r{i}" for i in range(10)]
    ratings = {"r0": 1, "r3": 2, "r7": 1}
    # 3 relevant out of 10 → 0.3
    assert precision_at_k(ranked, ratings, k=10) == pytest.approx(0.3)


def test_precision_missing_id_scores_zero():
    # An ID returned by the ranker but absent from the labels dict is
    # treated as rating 0 (not relevant). This is the production case
    # where the labeler didn't get to a result.
    ranked = ["a", "b", "c"]
    ratings = {"a": 2}  # only `a` is rated; `b` and `c` are unrated
    assert precision_at_k(ranked, ratings, k=3) == pytest.approx(1 / 3)


def test_precision_short_result_list_still_divides_by_k():
    # P@10 with only 3 results returned, all relevant: 3/10, not 3/3.
    ranked = ["a", "b", "c"]
    ratings = {"a": 1, "b": 2, "c": 1}
    assert precision_at_k(ranked, ratings, k=10) == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# MRR / Reciprocal Rank
# ---------------------------------------------------------------------------


def test_rr_first_relevant_at_rank_1():
    ranked = ["a", "b", "c"]
    ratings = {"a": 2}
    assert reciprocal_rank(ranked, ratings, k=10) == 1.0


def test_rr_first_relevant_at_rank_3():
    ranked = ["a", "b", "c"]
    ratings = {"c": 1}
    assert reciprocal_rank(ranked, ratings, k=10) == pytest.approx(1 / 3)


def test_rr_no_relevant_in_top_k_returns_zero():
    ranked = ["a", "b", "c"]
    ratings = {"a": 0, "b": 0, "c": 0}
    assert reciprocal_rank(ranked, ratings, k=10) == 0.0


def test_rr_relevant_beyond_k_returns_zero():
    # Result at rank 11 is irrelevant for MRR@10 — truncation matters.
    ranked = [f"r{i}" for i in range(15)]
    ratings = {"r10": 2}  # rank 11
    assert reciprocal_rank(ranked, ratings, k=10) == 0.0


def test_rr_rating_2_and_rating_1_both_count_as_relevant():
    # Per the RELEVANT_THRESHOLD = 1 in metrics.py, rating 1 is relevant.
    ranked = ["a", "b"]
    ratings = {"a": 1, "b": 2}
    assert reciprocal_rank(ranked, ratings) == 1.0


# ---------------------------------------------------------------------------
# NDCG@k — graded, linear gain (per Q3 lock)
# ---------------------------------------------------------------------------


def test_ndcg_perfect_ranking_returns_1():
    # Returns the best possible order: rating 2 first, then 1.
    ranked = ["a", "b", "c"]
    ratings = {"a": 2, "b": 1, "c": 0}
    assert ndcg_at_k(ranked, ratings, k=3) == pytest.approx(1.0)


def test_ndcg_zero_when_no_relevant():
    ranked = ["a", "b"]
    ratings = {"a": 0, "b": 0}
    assert ndcg_at_k(ranked, ratings, k=10) == 0.0


def test_ndcg_zero_when_empty_results():
    assert ndcg_at_k([], {"a": 2}, k=10) == 0.0


def test_ndcg_known_reference_vector_simple():
    # Hand-computed reference:
    #   ranked = [a, b, c], ratings: a=2, b=0, c=1
    #   DCG  = 2/log2(2) + 0/log2(3) + 1/log2(4) = 2/1 + 0 + 1/2 = 2.5
    #   ideal = [a=2, c=1] (b=0 dropped from ideal pool)
    #   IDCG = 2/log2(2) + 1/log2(3) = 2 + 1/log2(3)
    #        ≈ 2 + 0.6309 = 2.6309
    #   NDCG = 2.5 / 2.6309 ≈ 0.9502
    ranked = ["a", "b", "c"]
    ratings = {"a": 2, "b": 0, "c": 1}
    expected = (2.0 + 1.0 / math.log2(4)) / (2.0 + 1.0 / math.log2(3))
    assert ndcg_at_k(ranked, ratings, k=3) == pytest.approx(expected, abs=1e-6)


def test_ndcg_known_reference_vector_inverted():
    # Same ratings, worst-case ranking — rating-1 first, rating-2 last.
    #   ranked = [c, b, a], ratings: a=2, b=0, c=1
    #   DCG = 1/log2(2) + 0 + 2/log2(4) = 1 + 1 = 2.0
    #   IDCG (same as above) ≈ 2.6309
    #   NDCG ≈ 0.760
    ranked = ["c", "b", "a"]
    ratings = {"a": 2, "b": 0, "c": 1}
    expected_dcg = 1.0 + 2.0 / math.log2(4)
    expected_idcg = 2.0 + 1.0 / math.log2(3)
    expected = expected_dcg / expected_idcg
    assert ndcg_at_k(ranked, ratings, k=3) == pytest.approx(expected, abs=1e-6)


def test_ndcg_truncates_to_k():
    # First k=2 of a 3-result list. Only the first 2 contribute to DCG.
    ranked = ["a", "b", "c"]
    ratings = {"a": 2, "b": 1, "c": 2}
    # k=2 DCG: 2/log2(2) + 1/log2(3) = 2 + 1/log2(3) ≈ 2.6309
    # k=2 IDCG: sorted desc [2, 2, 1] -> top 2 = [2, 2]: 2 + 2/log2(3) ≈ 3.2618
    expected = (2.0 + 1.0 / math.log2(3)) / (2.0 + 2.0 / math.log2(3))
    assert ndcg_at_k(ranked, ratings, k=2) == pytest.approx(expected, abs=1e-6)


def test_ndcg_handles_unrated_ids():
    # Unrated IDs (not in `ratings`) get gain 0 in numerator; ideal pool
    # is built solely from positive ratings in `ratings.values()`.
    ranked = ["a", "b", "c"]
    ratings = {"a": 2}
    # DCG = 2/log2(2) + 0 + 0 = 2.0
    # IDCG = 2/log2(2) = 2.0
    # NDCG = 1.0
    assert ndcg_at_k(ranked, ratings, k=3) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_aggregate_averages_across_queries():
    per_query_results = {
        "q1": ["a", "b"],
        "q2": ["c", "d"],
    }
    per_query_ratings = {
        "q1": {"a": 2, "b": 0},   # perfect ranking → NDCG=1.0
        "q2": {"c": 0, "d": 2},   # worst ranking → NDCG < 1.0
    }
    metrics, rows = aggregate_for_config(
        config_name="test",
        config_fingerprint="sha256:abc",
        per_query_results=per_query_results,
        per_query_ratings=per_query_ratings,
        k=2,
    )
    assert metrics.n_queries == 2
    # q1: RR=1.0, q2: RR=1/2; mean = 0.75
    assert metrics.mrr == pytest.approx(0.75)
    # q1: P@2 = 1/2 (a is relevant of 2), q2: P@2 = 1/2 (d is relevant)
    assert metrics.precision_at_10 == pytest.approx(0.5)
    # Both queries have a relevant result in top-2
    assert metrics.n_queries_with_relevant_in_top_k == 2
    # Per-query rows landed
    assert len(rows) == 2
    assert {r.query for r in rows} == {"q1", "q2"}


def test_aggregate_per_query_n_results_correct():
    per_query_results = {"q1": ["a", "b", "c"]}
    per_query_ratings = {"q1": {"a": 1}}  # only `a` is rated
    _, rows = aggregate_for_config(
        config_name="test",
        config_fingerprint="sha256:fingerprint",
        per_query_results=per_query_results,
        per_query_ratings=per_query_ratings,
    )
    assert rows[0].n_results == 3
    assert rows[0].n_results_with_rating == 1


# ---------------------------------------------------------------------------
# Reproducibility provenance (#8a)
# ---------------------------------------------------------------------------


def test_sha256_of_path_stable(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"hello world")
    h = sha256_of_path(p)
    assert h.startswith("sha256:")
    # Same content → same hash.
    assert h == sha256_of_path(p)
    # Different content → different hash.
    p.write_bytes(b"hello other")
    assert h != sha256_of_path(p)


def test_provenance_block_contains_required_fields(tmp_path):
    corpus = tmp_path / "queries.jsonl"
    corpus.write_text('{"query":"x"}\n')
    labels = tmp_path / "labels.jsonl"
    labels.write_text('{"query":"x","result_id":"r","rating":2}\n')
    p = build_provenance(corpus, labels)
    assert set(p.keys()) >= {
        "corpus_hash",
        "labels_hash",
        "rka_head",
        "timestamp",
        "skill_rule",
    }
    assert p["skill_rule"] == "8a"
    assert p["corpus_hash"].startswith("sha256:")
    assert p["labels_hash"].startswith("sha256:")
    # ISO 8601 UTC shape: 2026-05-14T..Z
    assert p["timestamp"].endswith("Z")


def test_provenance_handles_missing_corpus(tmp_path):
    missing_corpus = tmp_path / "does-not-exist.jsonl"
    labels = tmp_path / "labels.jsonl"
    labels.write_text("\n")
    p = build_provenance(missing_corpus, labels)
    assert p["corpus_hash"] is None
    assert p["labels_hash"] is not None


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def test_load_labels_groups_by_query(tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        '{"query":"q1","result_id":"a","rating":2}\n'
        '{"query":"q1","result_id":"b","rating":0}\n'
        '{"query":"q2","result_id":"c","rating":1}\n'
    )
    out = load_labels(labels_path)
    assert out == {"q1": {"a": 2, "b": 0}, "q2": {"c": 1}}


def test_load_results_preserves_rank_order(tmp_path):
    raw_path = tmp_path / "config.jsonl"
    raw_path.write_text(
        json.dumps(
            {
                "query": "q1",
                "results": [
                    {"id": "c", "rank": 3},
                    {"id": "a", "rank": 1},
                    {"id": "b", "rank": 2},
                ],
            }
        )
        + "\n"
    )
    out = load_results_for_config(raw_path)
    assert out == {"q1": ["a", "b", "c"]}
