"""Retrieval-quality metrics for the eval harness.

Mission mis_01KRKJ9G20EM5XMA147JTKQCFF — Task T2 (metrics module) + T5
(computation entry point).

Three metrics, graded 0/1/2 relevance, top-10 cutoff:

  - **Precision@10**: fraction of top-10 results with rating ≥ 1,
    averaged across queries.

  - **MRR (Mean Reciprocal Rank)**: 1/rank of the first result with
    rating ≥ 1, averaged across queries. Queries with no rating-≥1
    result inside top-10 contribute 0.

  - **NDCG@10 (graded, linear gain)**: uses the 0/1/2 rating as the
    gain value directly (per mission Q3 lock: "uses graded 0/1/2
    directly; reports normalized score 0–1"). DCG = Σ rating_i /
    log2(i+1) over i=1..10; IDCG sorts the union of rated results
    descending; NDCG = DCG / IDCG (or 0 when IDCG = 0).

Output `results/metrics.json` carries the mandatory
reproducibility-provenance block per Brain skill rule #8a
(`jrn_01KRKN3QD9EPTFHWRSSGQ8X7MY`): corpus_hash, labels_hash,
per-config fingerprint, RKA HEAD short SHA, UTC timestamp.

CLI usage::

    python -m eval_harness.metrics \\
        --results-dir results/raw \\
        --labels results/labels/labels.jsonl \\
        --queries corpus/queries.jsonl \\
        --configs configs/ \\
        --output results/metrics.json \\
        --per-query-csv results/per_query.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_K = 10
RELEVANT_THRESHOLD = 1  # ratings ≥ this count as relevant for P@k and MRR


# ---------------------------------------------------------------------------
# Pure metric functions — small + reference-validated by test_metrics.py
# ---------------------------------------------------------------------------


def precision_at_k(
    ranked_ids: list[str],
    ratings: Mapping[str, int],
    k: int = DEFAULT_K,
) -> float:
    """Fraction of the top-k results whose rating is ≥ `RELEVANT_THRESHOLD`.

    Missing IDs (not in `ratings`) score 0. Always divides by `k` —
    NOT by `len(ranked_ids)` — so a query that returned fewer than k
    results is penalized in proportion. This matches the conventional
    P@k definition used in retrieval-eval literature.
    """
    if k <= 0:
        return 0.0
    relevant = sum(
        1 for rid in ranked_ids[:k] if ratings.get(rid, 0) >= RELEVANT_THRESHOLD
    )
    return relevant / k


def reciprocal_rank(
    ranked_ids: list[str],
    ratings: Mapping[str, int],
    k: int = DEFAULT_K,
) -> float:
    """1/rank of the first rating-≥1 result inside top-k. 0 if none.

    Per mission spec: "queries with no relevant result in top-10
    contribute 0." Truncation at k is intentional — a relevant result
    at rank 50 doesn't help a user scanning the first page.
    """
    for i, rid in enumerate(ranked_ids[:k], start=1):
        if ratings.get(rid, 0) >= RELEVANT_THRESHOLD:
            return 1.0 / i
    return 0.0


def ndcg_at_k(
    ranked_ids: list[str],
    ratings: Mapping[str, int],
    k: int = DEFAULT_K,
) -> float:
    """Graded NDCG@k with LINEAR gain (gain = rating).

    Mission Q3 lock: "uses graded 0/1/2 directly." The ideal ranking
    is computed from `ratings` (the union of rated IDs for this query
    across all configs); IDCG = DCG of that ideal sorted ranking,
    truncated to k. NDCG = DCG / IDCG (or 0 when IDCG = 0).
    """
    if k <= 0:
        return 0.0

    def gain(rating: int) -> float:
        return float(max(0, rating))

    dcg = sum(
        gain(ratings.get(rid, 0)) / math.log2(i + 1)
        for i, rid in enumerate(ranked_ids[:k], start=1)
    )

    ideal_ratings = sorted(
        (r for r in ratings.values() if r > 0), reverse=True
    )[:k]
    idcg = sum(
        gain(r) / math.log2(i + 1) for i, r in enumerate(ideal_ratings, start=1)
    )

    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# Aggregation across queries
# ---------------------------------------------------------------------------


@dataclass
class ConfigMetrics:
    """Aggregate metric values for one configuration."""

    config_name: str
    config_fingerprint: str
    n_queries: int
    n_queries_with_relevant_in_top_k: int
    precision_at_10: float
    mrr: float
    ndcg_at_10: float

    def to_dict(self) -> dict:
        return {
            "config_fingerprint": self.config_fingerprint,
            "n_queries": self.n_queries,
            "n_queries_with_relevant_in_top_10": self.n_queries_with_relevant_in_top_k,
            "precision_at_10": round(self.precision_at_10, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_10": round(self.ndcg_at_10, 4),
        }


@dataclass
class PerQueryRow:
    """One row of the per_query.csv table — for T6 narrative sourcing."""

    query: str
    config_name: str
    precision_at_10: float
    reciprocal_rank: float
    ndcg_at_10: float
    n_results: int
    n_results_with_rating: int


def aggregate_for_config(
    config_name: str,
    config_fingerprint: str,
    per_query_results: Mapping[str, list[str]],
    per_query_ratings: Mapping[str, Mapping[str, int]],
    k: int = DEFAULT_K,
) -> tuple[ConfigMetrics, list[PerQueryRow]]:
    """Compute per-config aggregates + per-query breakdown rows.

    `per_query_results[query] = [ranked_id, ranked_id, ...]` for this config.
    `per_query_ratings[query] = {result_id: rating}` for ALL rated results
    of that query across configs (the deduplicated label set).
    """
    p_sum = 0.0
    rr_sum = 0.0
    ndcg_sum = 0.0
    n_queries = 0
    n_with_relevant = 0
    rows: list[PerQueryRow] = []

    for query, ranked in per_query_results.items():
        ratings = per_query_ratings.get(query, {})
        p = precision_at_k(ranked, ratings, k)
        rr = reciprocal_rank(ranked, ratings, k)
        ndcg = ndcg_at_k(ranked, ratings, k)

        p_sum += p
        rr_sum += rr
        ndcg_sum += ndcg
        n_queries += 1
        if rr > 0:
            n_with_relevant += 1

        rows.append(
            PerQueryRow(
                query=query,
                config_name=config_name,
                precision_at_10=p,
                reciprocal_rank=rr,
                ndcg_at_10=ndcg,
                n_results=len(ranked),
                n_results_with_rating=sum(1 for r in ranked if r in ratings),
            )
        )

    metrics = ConfigMetrics(
        config_name=config_name,
        config_fingerprint=config_fingerprint,
        n_queries=n_queries,
        n_queries_with_relevant_in_top_k=n_with_relevant,
        precision_at_10=(p_sum / n_queries) if n_queries else 0.0,
        mrr=(rr_sum / n_queries) if n_queries else 0.0,
        ndcg_at_10=(ndcg_sum / n_queries) if n_queries else 0.0,
    )
    return metrics, rows


# ---------------------------------------------------------------------------
# Reproducibility provenance (Brain skill rule #8a)
# ---------------------------------------------------------------------------


def sha256_of_path(path: Path) -> str:
    """Canonical bytes hash. The full content is read; for the
    corpus/labels JSONL files this is the deliverable identity."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def rka_head_short_sha() -> str:
    """Best-effort `git rev-parse --short HEAD`. Returns 'unknown' if
    not in a git repo or git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def build_provenance(
    corpus_path: Path,
    labels_path: Path,
) -> dict:
    """The mandatory reproducibility-provenance block per Brain skill
    rule #8a. Lands inside `results/metrics.json` so any future
    consumer can verify exactly which inputs the metrics were
    computed against."""
    return {
        "corpus_hash": sha256_of_path(corpus_path) if corpus_path.exists() else None,
        "labels_hash": sha256_of_path(labels_path) if labels_path.exists() else None,
        "rka_head": rka_head_short_sha(),
        "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skill_rule": "8a",
    }


# ---------------------------------------------------------------------------
# JSONL / CSV I/O helpers
# ---------------------------------------------------------------------------


def load_queries(path: Path) -> list[str]:
    """Return the canonical query strings from `corpus/queries.jsonl`."""
    queries: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line)["query"])
    return queries


def load_results_for_config(path: Path) -> dict[str, list[str]]:
    """Return `{query: [ranked_id, ...]}` from a per-config raw results
    JSONL. Each line shape:
        {"query": "...", "results": [{"id": "...", "rank": 1, ...}, ...]}
    Output IDs are in rank order (rank=1 first).
    """
    out: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            query = row["query"]
            ranked = sorted(row["results"], key=lambda r: r.get("rank", 0))
            out[query] = [r["id"] for r in ranked]
    return out


def load_labels(path: Path) -> dict[str, dict[str, int]]:
    """Return `{query: {result_id: rating}}` from labels.jsonl.

    Each line shape:
        {"query": "...", "result_id": "...", "rating": 0|1|2}
    """
    out: dict[str, dict[str, int]] = defaultdict(dict)
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[row["query"]][row["result_id"]] = int(row["rating"])
    return dict(out)


def write_per_query_csv(rows: Iterable[PerQueryRow], path: Path) -> int:
    """Write the per-query breakdown table. Used by T6 narrative."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "query",
                "config",
                "precision_at_10",
                "reciprocal_rank",
                "ndcg_at_10",
                "n_results",
                "n_results_with_rating",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.query,
                    r.config_name,
                    round(r.precision_at_10, 4),
                    round(r.reciprocal_rank, 4),
                    round(r.ndcg_at_10, 4),
                    r.n_results,
                    r.n_results_with_rating,
                ]
            )
            n += 1
    return n


# ---------------------------------------------------------------------------
# CLI — runs T5's "compute metrics" deliverable end to end
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compute Precision@10, MRR, NDCG@10 per config from raw "
            "retrieval results + PI labels. Writes results/metrics.json + "
            "results/per_query.csv."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Directory containing <config>.jsonl raw results.",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        required=True,
        help="labels.jsonl path.",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        required=True,
        help="corpus/queries.jsonl path (for provenance hash + query count).",
    )
    parser.add_argument(
        "--configs",
        type=Path,
        required=True,
        help="configs/ directory with <config>.yaml files (for fingerprint).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="metrics.json output path.",
    )
    parser.add_argument(
        "--per-query-csv",
        type=Path,
        required=True,
        help="per_query.csv output path.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=DEFAULT_K,
        help=f"Top-k cutoff (default: {DEFAULT_K}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # Provenance — same for every config (the inputs are shared).
    provenance = build_provenance(args.queries, args.labels)

    labels = load_labels(args.labels)

    out_configs: dict[str, dict] = {}
    all_rows: list[PerQueryRow] = []

    for raw_path in sorted(args.results_dir.glob("*.jsonl")):
        config_name = raw_path.stem
        config_yaml = args.configs / f"{config_name}.yaml"
        fingerprint = (
            sha256_of_path(config_yaml) if config_yaml.exists() else "sha256:<missing-yaml>"
        )
        per_query_results = load_results_for_config(raw_path)

        metrics, rows = aggregate_for_config(
            config_name=config_name,
            config_fingerprint=fingerprint,
            per_query_results=per_query_results,
            per_query_ratings=labels,
            k=args.k,
        )
        out_configs[config_name] = metrics.to_dict()
        all_rows.extend(rows)

    output = {
        "reproducibility": provenance,
        "k": args.k,
        "n_configs": len(out_configs),
        "configs": out_configs,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    rows_written = write_per_query_csv(all_rows, args.per_query_csv)

    print(
        f"wrote {args.output} ({len(out_configs)} configs) + "
        f"{args.per_query_csv} ({rows_written} rows)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
