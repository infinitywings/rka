"""Scoring for decision back-tracing scenarios.

Pure functions over (scenario, returned entity ids) — no I/O, no HTTP —
so the math is lockable by unit tests independently of the runner.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

CRITICAL = "critical"


def anchor_reciprocal_rank(result_ids: list[str], anchor_decision: str) -> float:
    """1/rank of the anchor decision in a search result list; 0.0 if absent."""
    for index, entity_id in enumerate(result_ids, start=1):
        if entity_id == anchor_decision:
            return 1.0 / index
    return 0.0


def trace_scores(
    expected_trace: list[dict[str, Any]], returned_ids: set[str]
) -> dict[str, Any]:
    """Recall (critical + expanded), per-relation recall, and precision."""
    critical = [e for e in expected_trace if e.get("importance") == CRITICAL]
    found_all = [e for e in expected_trace if e["entity_id"] in returned_ids]
    found_critical = [e for e in critical if e["entity_id"] in returned_ids]

    per_relation: dict[str, dict[str, int]] = defaultdict(
        lambda: {"expected": 0, "found": 0}
    )
    for entry in expected_trace:
        relation = entry.get("relation", "unknown")
        per_relation[relation]["expected"] += 1
        if entry["entity_id"] in returned_ids:
            per_relation[relation]["found"] += 1

    expected_ids = {e["entity_id"] for e in expected_trace}
    precision = (
        len(expected_ids & returned_ids) / len(returned_ids) if returned_ids else 0.0
    )
    return {
        "trace_recall": (len(found_critical) / len(critical)) if critical else None,
        "expanded_recall": (
            len(found_all) / len(expected_trace) if expected_trace else None
        ),
        "per_relation": dict(sorted(per_relation.items())),
        "precision": round(precision, 4),
        "returned_count": len(returned_ids),
    }


def pivot_score(pivot: dict[str, Any] | None, returned_ids: set[str]) -> dict[str, Any]:
    """Did the trace surface the superseding decision, or only the stale one?"""
    if not pivot:
        return {"applicable": False}
    superseding = pivot.get("superseding_decision_id")
    superseded = pivot.get("superseded_decision_id")
    superseding_found = superseding in returned_ids if superseding else False
    superseded_found = superseded in returned_ids if superseded else False
    return {
        "applicable": True,
        "superseding_found": superseding_found,
        "superseded_found": superseded_found,
        "stale_surfacing": superseded_found and not superseding_found,
    }


def score_scenario(
    scenario: dict[str, Any],
    surface_ids: dict[str, list[str]],
    search_ids: list[str] | None,
    divergences: list[str],
) -> dict[str, Any]:
    """Score one scenario.

    surface_ids: {"ego": [...], "multi_hop": [...]} — ids returned by each
    traversal surface. search_ids: ordered `/api/search` results (or None
    when the scenario has no nl_query).
    """
    union: set[str] = set()
    per_surface: dict[str, Any] = {}
    for surface, ids in surface_ids.items():
        id_set = set(ids)
        union |= id_set
        per_surface[surface] = trace_scores(scenario["expected_trace"], id_set)

    result: dict[str, Any] = {
        "scenario_id": scenario["scenario_id"],
        "union": trace_scores(scenario["expected_trace"], union),
        "per_surface": per_surface,
        "pivot": pivot_score(scenario.get("pivot"), union),
        "divergences": divergences,
    }
    if search_ids is not None:
        result["anchor_reciprocal_rank"] = anchor_reciprocal_rank(
            search_ids, scenario["anchor_decision"]
        )
    return result


def aggregate(scenario_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Corpus-level aggregation of per-scenario scores."""

    def collect(path: tuple[str, ...]) -> list[float]:
        values = []
        for result in scenario_results:
            node: Any = result
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, (int, float)):
                values.append(float(node))
        return values

    recalls = collect(("union", "trace_recall"))
    expanded = collect(("union", "expanded_recall"))
    precisions = collect(("union", "precision"))
    mrrs = collect(("anchor_reciprocal_rank",))

    pivots = [r["pivot"] for r in scenario_results if r["pivot"].get("applicable")]
    pivot_ok = sum(1 for p in pivots if p["superseding_found"])
    stale = sum(1 for p in pivots if p["stale_surfacing"])

    relation_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"expected": 0, "found": 0}
    )
    for result in scenario_results:
        for relation, stats in result["union"]["per_relation"].items():
            relation_totals[relation]["expected"] += stats["expected"]
            relation_totals[relation]["found"] += stats["found"]
    per_relation = {
        relation: {
            **stats,
            "recall": round(stats["found"] / stats["expected"], 4)
            if stats["expected"]
            else None,
        }
        for relation, stats in sorted(relation_totals.items())
    }

    divergent = [r["scenario_id"] for r in scenario_results if r["divergences"]]
    return {
        "n_scenarios": len(scenario_results),
        "trace_recall_mean": round(mean(recalls), 4) if recalls else None,
        "expanded_recall_mean": round(mean(expanded), 4) if expanded else None,
        "precision_mean": round(mean(precisions), 4) if precisions else None,
        "anchor_mrr": round(mean(mrrs), 4) if mrrs else None,
        "per_relation": per_relation,
        "pivot_scenarios": len(pivots),
        "pivot_correct": pivot_ok,
        "stale_surfacing": stale,
        "scenarios_with_divergences": divergent,
    }
