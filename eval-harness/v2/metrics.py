"""Eval-v2 metrics — composed-context coverage scoring.

Mission `mis_01KRPF3DERZS2W5VFDYE9E9GKM` Task T4.

Per the upfront Backbrief (A3) + the spec, each scenario gets 5 scores:

  recall          = |returned ∩ expected_critical| / |expected_critical|
                    (recall over critical-tagged entities only — the
                     entities that absolutely must appear)
  expanded_recall = |returned ∩ expected_all| / |expected_all|
                    (recall over all expected entities including
                     useful + nice-to-have)
  ordering_score  = NDCG-style positional metric where the gain of an
                    expected entity is its importance weight (critical=3,
                    useful=2, nice-to-have=1) and non-expected entities
                    contribute zero gain
  breadth         = number of distinct entity_type categories present in
                    the returned bundle among the expected set
  efficiency      = |returned ∩ expected_all| / |returned|
                    (signal-to-noise ratio: how dense is the bundle in
                     expected entities vs padding)

Per-corpus aggregates: mean of each metric + per-actor breakdown +
per-tool contribution breakdown.

Output written by ``compute_corpus_metrics`` to
``eval-harness/v2/results/metrics.json`` with a reproducibility section
(corpus SHA + RKA HEAD + timestamp), mirroring Eval-v1's pattern at
``eval-harness/results/metrics.json``.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Importance → gain mapping (NDCG weights)
# ---------------------------------------------------------------------------

_GAIN: dict[str, float] = {
    "critical": 3.0,
    "useful": 2.0,
    "nice-to-have": 1.0,
}


def _now_iso_z() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Per-scenario metric primitives
# ---------------------------------------------------------------------------


def recall(returned: Iterable[str], expected_critical: set[str]) -> float:
    """Recall over critical-tagged entities only.

    Returns 0.0 when ``expected_critical`` is empty (vacuous case —
    caller should not invoke for scenarios without critical anchors;
    Eval-v2's schema validator already enforces ≥3 critical per
    scenario).
    """
    if not expected_critical:
        return 0.0
    return len(set(returned) & expected_critical) / len(expected_critical)


def expanded_recall(returned: Iterable[str], expected_all: set[str]) -> float:
    """Recall over the full expected set (critical + useful + nice-to-have)."""
    if not expected_all:
        return 0.0
    return len(set(returned) & expected_all) / len(expected_all)


def ordering_score(
    returned: list[str], expected_entities: list[dict[str, Any]]
) -> float:
    """NDCG-style positional score over the expected entities' positions
    in the returned bundle.

    Gain function: ``_GAIN[importance]`` for each expected entity at its
    position; 0 for non-expected. DCG uses log2(i + 2) discount.

    IDCG is computed over the best possible ordering: expected entities
    sorted by gain descending, packed into positions 0, 1, 2, ...

    Returns 0.0 when there are no expected entities (vacuous).
    """
    if not expected_entities:
        return 0.0
    expected_gain: dict[str, float] = {
        e["entity_id"]: _GAIN[e["importance"]] for e in expected_entities
    }
    dcg = sum(
        expected_gain.get(eid, 0.0) / math.log2(i + 2)
        for i, eid in enumerate(returned)
    )
    # IDCG: pack the highest-gain expected items into the top positions.
    ideal_gains = sorted(expected_gain.values(), reverse=True)
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_gains))
    return dcg / idcg if idcg > 0 else 0.0


def breadth(
    returned: Iterable[str], expected_entities: list[dict[str, Any]]
) -> int:
    """Number of distinct entity_type categories present in ``returned``
    that are also present among the expected entities."""
    expected_by_id = {e["entity_id"]: e["entity_type"] for e in expected_entities}
    types: set[str] = set()
    for eid in returned:
        if eid in expected_by_id:
            types.add(expected_by_id[eid])
    return len(types)


def efficiency(returned: Iterable[str], expected_all: set[str]) -> float:
    """Signal-to-noise: fraction of returned entities that are expected."""
    returned_list = list(returned)
    if not returned_list:
        return 0.0
    return len(set(returned_list) & expected_all) / len(returned_list)


# ---------------------------------------------------------------------------
# Per-scenario record
# ---------------------------------------------------------------------------


@dataclass
class ScenarioMetrics:
    scenario_id: str
    actor: str
    recall: float
    expanded_recall: float
    ordering_score: float
    breadth: int
    efficiency: float
    # Per-tool contribution: for each tool the scenario invoked, what
    # fraction of the critical-set did THAT tool's response alone cover?
    per_tool_critical_coverage: dict[str, float] = field(default_factory=dict)
    n_expected_critical: int = 0
    n_expected_total: int = 0
    n_returned: int = 0


def score_scenario(
    scenario: dict[str, Any], bundle: dict[str, Any]
) -> ScenarioMetrics:
    """Compute the 5 metrics + per-tool contribution for one scenario.

    ``scenario`` is the corpus record; ``bundle`` is the runner's
    serialized ScenarioBundle (read from
    ``results/raw/<scenario_id>.jsonl``).
    """
    expected_entities = scenario["expected_entities"]
    expected_all = {e["entity_id"] for e in expected_entities}
    expected_critical = {
        e["entity_id"] for e in expected_entities if e["importance"] == "critical"
    }
    returned = list(bundle["combined_ranking"])

    per_tool_coverage: dict[str, float] = {}
    for inv in bundle.get("invocations", []):
        tool_ids = set(inv.get("entity_ids") or [])
        if expected_critical:
            cov = len(tool_ids & expected_critical) / len(expected_critical)
        else:
            cov = 0.0
        per_tool_coverage[inv["tool"]] = cov

    return ScenarioMetrics(
        scenario_id=scenario["scenario_id"],
        actor=scenario["actor"],
        recall=recall(returned, expected_critical),
        expanded_recall=expanded_recall(returned, expected_all),
        ordering_score=ordering_score(returned, expected_entities),
        breadth=breadth(returned, expected_entities),
        efficiency=efficiency(returned, expected_all),
        per_tool_critical_coverage=per_tool_coverage,
        n_expected_critical=len(expected_critical),
        n_expected_total=len(expected_all),
        n_returned=len(returned),
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class CorpusAggregate:
    n_scenarios: int
    mean_recall: float
    mean_expanded_recall: float
    mean_ordering_score: float
    mean_breadth: float
    mean_efficiency: float
    # Per-actor: same 5 metrics, restricted to scenarios with that actor
    per_actor: dict[str, dict[str, float]] = field(default_factory=dict)
    # Per-tool: mean critical-coverage contribution across scenarios that
    # invoked this tool
    per_tool_mean_critical_coverage: dict[str, float] = field(default_factory=dict)
    # Floor check (per mission spec acceptance criteria): mean recall
    # over critical-tagged entities must be >=0.85
    critical_recall_floor: float = 0.85
    floor_passed: bool = False


def aggregate(scenario_metrics: list[ScenarioMetrics]) -> CorpusAggregate:
    if not scenario_metrics:
        return CorpusAggregate(
            n_scenarios=0,
            mean_recall=0.0,
            mean_expanded_recall=0.0,
            mean_ordering_score=0.0,
            mean_breadth=0.0,
            mean_efficiency=0.0,
        )

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    mean_recall_v = _mean([m.recall for m in scenario_metrics])

    # Per-actor breakdown
    per_actor: dict[str, dict[str, float]] = {}
    for actor in {m.actor for m in scenario_metrics}:
        subset = [m for m in scenario_metrics if m.actor == actor]
        per_actor[actor] = {
            "n_scenarios": len(subset),
            "mean_recall": _mean([m.recall for m in subset]),
            "mean_expanded_recall": _mean([m.expanded_recall for m in subset]),
            "mean_ordering_score": _mean([m.ordering_score for m in subset]),
            "mean_breadth": _mean([float(m.breadth) for m in subset]),
            "mean_efficiency": _mean([m.efficiency for m in subset]),
        }

    # Per-tool breakdown — average each tool's critical-coverage across
    # the scenarios that invoked it (NOT across all scenarios; tools that
    # never run for a scenario shouldn't pull its mean down).
    tool_buckets: dict[str, list[float]] = {}
    for m in scenario_metrics:
        for tool, coverage in m.per_tool_critical_coverage.items():
            tool_buckets.setdefault(tool, []).append(coverage)
    per_tool = {tool: _mean(vals) for tool, vals in tool_buckets.items()}

    return CorpusAggregate(
        n_scenarios=len(scenario_metrics),
        mean_recall=mean_recall_v,
        mean_expanded_recall=_mean([m.expanded_recall for m in scenario_metrics]),
        mean_ordering_score=_mean([m.ordering_score for m in scenario_metrics]),
        mean_breadth=_mean([float(m.breadth) for m in scenario_metrics]),
        mean_efficiency=_mean([m.efficiency for m in scenario_metrics]),
        per_actor=per_actor,
        per_tool_mean_critical_coverage=per_tool,
        floor_passed=mean_recall_v >= 0.85,
    )


# ---------------------------------------------------------------------------
# Reproducibility provenance (Eval-v1 pattern at jrn_01KRKYCFZA8M9CC7ZHB9P0MX5W)
# ---------------------------------------------------------------------------


def sha256_of_path(path: Path) -> str:
    if not path.exists():
        return "sha256:missing"
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{h}"


def _rka_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent.parent,
        ).decode().strip()[:12]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_provenance(corpus_path: Path) -> dict[str, Any]:
    """Provenance block to merge into the metrics.json output."""
    return {
        "corpus_hash": sha256_of_path(corpus_path),
        "rka_head": _rka_head(),
        "timestamp": _now_iso_z(),
        "eval_version": "v2",
        "skill_rule": "8a",  # carry-over from Eval-v1
    }


# ---------------------------------------------------------------------------
# Top-level driver — reads corpus + raw bundles, writes metrics.json
# ---------------------------------------------------------------------------


def compute_corpus_metrics(
    *,
    corpus_path: Path,
    raw_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Read the corpus + every raw bundle, compute per-scenario metrics
    and the corpus aggregate, write to ``output_path``, and return the
    JSON-shaped result dict.
    """
    import sys
    sys.path.insert(0, str(corpus_path.parent.parent.parent))
    from v2.schema_validator import load_corpus

    scenarios = load_corpus(corpus_path)
    by_id = {s["scenario_id"]: s for s in scenarios}

    scenario_metrics: list[ScenarioMetrics] = []
    missing_bundles: list[str] = []
    for scenario_id, scenario in by_id.items():
        bundle_path = raw_dir / f"{scenario_id}.jsonl"
        if not bundle_path.exists():
            missing_bundles.append(scenario_id)
            continue
        bundle = json.loads(bundle_path.read_text())
        scenario_metrics.append(score_scenario(scenario, bundle))

    aggregate_result = aggregate(scenario_metrics)
    provenance = build_provenance(corpus_path)

    output: dict[str, Any] = {
        "provenance": provenance,
        "n_scenarios_corpus": len(scenarios),
        "n_scenarios_scored": len(scenario_metrics),
        "missing_bundles": missing_bundles,
        "aggregate": asdict(aggregate_result),
        "per_scenario": [asdict(m) for m in scenario_metrics],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Eval-v2 metrics aggregator")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("eval-harness/v2/corpus/scenarios.jsonl"),
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("eval-harness/v2/results/raw"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval-harness/v2/results/metrics.json"),
    )
    args = parser.parse_args()

    result = compute_corpus_metrics(
        corpus_path=args.corpus,
        raw_dir=args.raw_dir,
        output_path=args.output,
    )
    agg = result["aggregate"]
    print(f"wrote {args.output}")
    print(
        f"  scenarios scored: {result['n_scenarios_scored']} / "
        f"{result['n_scenarios_corpus']}"
    )
    print(f"  mean recall (critical):    {agg['mean_recall']:.3f}")
    print(f"  mean expanded_recall:      {agg['mean_expanded_recall']:.3f}")
    print(f"  mean ordering_score:       {agg['mean_ordering_score']:.3f}")
    print(f"  mean breadth:              {agg['mean_breadth']:.2f}")
    print(f"  mean efficiency:           {agg['mean_efficiency']:.3f}")
    mark = "PASSED" if agg["floor_passed"] else "FAILED"
    print(
        f"  critical-recall floor ({agg['critical_recall_floor']:.2f}): {mark}"
    )
    return 0 if agg["floor_passed"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
