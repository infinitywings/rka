"""Scoring for decision back-tracing scenarios.

Pure functions over (scenario, returned entity ids) — no I/O, no HTTP —
so the math is lockable by unit tests independently of the runner.
"""

from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean
from typing import Any

from v3.retention.scoring import score_probe

CRITICAL = "critical"
HUMAN_RUBRIC_KEYS = (
    "current_conclusion",
    "mandatory_coverage",
    "causal_reconstruction",
    "provenance_currentness",
    "distractor_rejection",
)


def anchor_reciprocal_rank(result_ids: list[str], anchor_decision: str) -> float:
    """1/rank of the anchor decision in a search result list; 0.0 if absent."""
    for index, entity_id in enumerate(result_ids, start=1):
        if entity_id == anchor_decision:
            return 1.0 / index
    return 0.0


def _ratio(found: int, expected: int) -> float | None:
    return round(found / expected, 4) if expected else None


def _edge_matches(expected: dict[str, Any], returned: dict[str, Any]) -> bool:
    """Return whether a concrete graph edge satisfies one gold edge contract."""
    source = expected.get("source")
    target = expected.get("target")
    direction = expected.get("direction", "forward")
    link_types = expected.get("link_types") or [expected.get("link_type")]
    allowed = {value for value in link_types if value}
    actual_type = returned.get("link_type") or returned.get("relation")
    type_ok = not allowed or actual_type in allowed
    if not type_ok:
        return False
    forward = returned.get("source") == source and returned.get("target") == target
    reverse = returned.get("source") == target and returned.get("target") == source
    return forward or (direction == "either" and reverse)


def story_scores(
    story: dict[str, Any],
    returned_ids: set[str],
    returned_edges: list[dict[str, Any]] | None = None,
    entity_packet: dict[str, Any] | None = None,
    *,
    resolution_expected_ids: set[str] | None = None,
    expected_project_id: str | None = None,
) -> dict[str, Any]:
    """Score whether retrieval recovered a coherent, current research story.

    ``roles`` make the unit of recall a story function (rationale, current
    decision, mission, result), rather than a flat entity union.  Required
    edges test whether those entities form the expected causal substrate.
    Optional bulk-resolution data verifies load-bearing facts and currentness
    without trusting graph labels or search snippets.
    """
    returned_edges = returned_edges or []
    role_results: dict[str, dict[str, Any]] = {}
    required_roles = 0
    found_required_roles = 0
    allowed_ids: set[str] = set(story.get("optional_entities", []))
    for role, spec in story.get("roles", {}).items():
        candidates = set(spec.get("any_of", []))
        allowed_ids |= candidates
        hits = sorted(candidates & returned_ids)
        required = bool(spec.get("required", True))
        if required:
            required_roles += 1
            found_required_roles += bool(hits)
        role_results[role] = {
            "required": required,
            "found": bool(hits),
            "matched": hits,
        }

    required_edges = story.get("required_edges", [])
    edge_results = []
    for expected in required_edges:
        found = any(_edge_matches(expected, actual) for actual in returned_edges)
        edge_results.append({**expected, "found": found})
    found_edges = sum(1 for edge in edge_results if edge["found"])

    precision = len(allowed_ids & returned_ids) / len(returned_ids) if returned_ids else 0.0
    distractors_found = sorted(set(story.get("distractors", [])) & returned_ids)
    forbidden_found = sorted(set(story.get("forbidden_entities", [])) & returned_ids)
    foreign_found = sorted(set(story.get("foreign_must_exclude", [])) & returned_ids)

    current_entities = set(story.get("current_entities", []))
    historical_entities = set(story.get("historical_entities", []))
    current_found = sorted(current_entities & returned_ids)
    historical_found = sorted(historical_entities & returned_ids)
    stale_only = bool(historical_found and current_entities and not current_found)

    attested_project_id = expected_project_id or (
        entity_packet.get("project_id") if entity_packet else None
    )
    packet_scope_ok = bool(
        entity_packet
        and attested_project_id
        and entity_packet.get("project_id") == attested_project_id
    )
    entities = entity_packet.get("entities", {}) if packet_scope_ok else {}
    confirmed_ids = {
        entity_id
        for entity_id, resolution in entities.items()
        if resolution.get("found") is True
        and resolution.get("outcome") == "resolved"
        and resolution.get("project_id") == attested_project_id
    }
    wrong_project = sorted(
        entity_id
        for entity_id, resolution in entities.items()
        if resolution.get("outcome") == "wrong_project"
    )
    fact_results: list[dict[str, Any]] = []
    for fact in story.get("required_facts", []):
        candidates = fact.get("any_of_entities", [])
        needles = fact.get("contains", [])
        if isinstance(needles, str):
            needles = [needles]
        needles = [str(value).casefold() for value in needles]
        matched_entities = []
        for entity_id in candidates:
            resolution = entities.get(entity_id, {})
            text = json.dumps(
                resolution,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).casefold()
            if entity_id in confirmed_ids and all(needle in text for needle in needles):
                matched_entities.append(entity_id)
        fact_results.append(
            {
                "fact_id": fact.get("fact_id", "fact"),
                "found": bool(matched_entities),
                "matched_entities": matched_entities,
            }
        )

    currentness_results: list[dict[str, Any]] = []
    checks = story.get("currentness", {})
    for expected_current, ids in (
        (True, checks.get("must_be_current", [])),
        (False, checks.get("must_be_not_current", [])),
    ):
        for entity_id in ids:
            resolution = entities.get(entity_id, {})
            actual = (
                resolution.get("currentness", {}).get("is_current")
                if entity_id in confirmed_ids
                else None
            )
            currentness_results.append(
                {
                    "entity_id": entity_id,
                    "expected_current": expected_current,
                    "actual_current": actual,
                    "correct": actual is expected_current,
                }
            )

    facts_found = sum(1 for fact in fact_results if fact["found"])
    currentness_correct = sum(1 for check in currentness_results if check["correct"])
    role_coverage = _ratio(found_required_roles, required_roles)
    edge_coverage = _ratio(found_edges, len(required_edges))
    fact_coverage = _ratio(facts_found, len(fact_results))
    currentness_accuracy = _ratio(currentness_correct, len(currentness_results))

    resolution_required = bool(
        fact_results or currentness_results or resolution_expected_ids is not None
    )
    resolution_incomplete = sorted((resolution_expected_ids or set()) - confirmed_ids)
    min_precision = float(story.get("min_precision", 0.2))
    hard_failures = {
        "foreign_project": foreign_found or wrong_project,
        "forbidden_entity": forbidden_found,
        "stale_only": stale_only,
        "resolution_missing": resolution_required and entity_packet is None,
        "resolution_project_scope": bool(entity_packet and not packet_scope_ok),
        "resolution_incomplete": resolution_incomplete,
        "currentness": bool(currentness_results and currentness_accuracy != 1.0),
        "precision": precision < min_precision,
    }
    hard_failed = any(bool(value) for value in hard_failures.values())
    story_success = (
        role_coverage == 1.0
        and (edge_coverage in (None, 1.0))
        and (fact_coverage in (None, 1.0))
        and (currentness_accuracy in (None, 1.0))
        and not hard_failed
    )
    return {
        "story_success": story_success,
        "role_coverage": role_coverage,
        "missing_roles": sorted(
            role
            for role, result in role_results.items()
            if result["required"] and not result["found"]
        ),
        "roles": role_results,
        "required_edge_coverage": edge_coverage,
        "required_edges": edge_results,
        "fact_coverage": fact_coverage,
        "required_facts": fact_results,
        "currentness_accuracy": currentness_accuracy,
        "currentness": currentness_results,
        "precision": round(precision, 4),
        "min_precision": min_precision,
        "noise_ratio": round(1.0 - precision, 4) if returned_ids else 0.0,
        "distractors_found": distractors_found,
        "current_found": current_found,
        "historical_found": historical_found,
        "hard_failures": hard_failures,
        "returned_count": len(returned_ids),
    }


def score_story_variant(
    scenario: dict[str, Any],
    variant: dict[str, Any],
    surface_ids: dict[str, list[str]],
    surface_edges: dict[str, list[dict[str, Any]]],
    search_ids: list[str],
    entity_packet: dict[str, Any] | None,
    divergences: list[str],
    anchor_k: int = 20,
) -> dict[str, Any]:
    """Score one natural-language variant without oracle anchor assistance."""
    union_ids: set[str] = set()
    union_edges: list[dict[str, Any]] = []
    per_surface: dict[str, Any] = {}
    seen_edges: set[tuple[Any, Any, Any]] = set()
    for surface, ids in surface_ids.items():
        id_set = set(ids)
        edges = surface_edges.get(surface, [])
        union_ids |= id_set
        for edge in edges:
            key = (
                edge.get("source"),
                edge.get("target"),
                edge.get("link_type") or edge.get("relation"),
            )
            if key not in seen_edges:
                seen_edges.add(key)
                union_edges.append(edge)
        per_surface[surface] = story_scores(scenario["story"], id_set, edges)

    # Resolver-induced edges connect confirmed records, but resolver closure
    # is not raw candidate recall.  Keep these edges out of per-surface/raw-ID
    # diagnostics while allowing them to support the confirmed headline.
    for edge in surface_edges.get("resolve", []):
        key = (
            edge.get("source"),
            edge.get("target"),
            edge.get("link_type") or edge.get("relation"),
        )
        if key not in seen_edges:
            seen_edges.add(key)
            union_edges.append(edge)

    expected_project_id = scenario.get("project_id")
    packet_entities = entity_packet.get("entities", {}) if entity_packet else {}
    packet_scope_ok = bool(
        entity_packet
        and (expected_project_id is None or entity_packet.get("project_id") == expected_project_id)
    )
    confirmed_ids = {
        entity_id
        for entity_id, resolution in packet_entities.items()
        if packet_scope_ok
        and resolution.get("found") is True
        and resolution.get("outcome") == "resolved"
        and resolution.get("project_id") == expected_project_id
    }
    confirmed_edges = [
        edge
        for edge in union_edges
        if edge.get("source") in confirmed_ids and edge.get("target") in confirmed_ids
    ]
    headline_ids = confirmed_ids if expected_project_id else union_ids
    headline_edges = confirmed_edges if expected_project_id else union_edges
    raw_candidate = story_scores(scenario["story"], union_ids, union_edges)
    anchor = scenario["anchor_decision"]
    return {
        "scenario_id": scenario["scenario_id"],
        "variant_id": variant["variant_id"],
        "style": variant.get("style", "unspecified"),
        "query": variant["query"],
        "anchor_reciprocal_rank": anchor_reciprocal_rank(search_ids, anchor),
        "anchor_hit_at_k": anchor in search_ids[:anchor_k],
        "anchor_k": anchor_k,
        "headline": story_scores(
            scenario["story"],
            headline_ids,
            headline_edges,
            entity_packet,
            resolution_expected_ids=union_ids if expected_project_id else None,
            expected_project_id=expected_project_id,
        ),
        "raw_candidate_recall": {
            "role_coverage": raw_candidate["role_coverage"],
            "missing_roles": raw_candidate["missing_roles"],
            "returned_count": raw_candidate["returned_count"],
        },
        "per_surface": per_surface,
        "divergences": divergences,
    }


def _aggregate_story_core(results: list[dict[str, Any]]) -> dict[str, Any]:
    def avg(key: str) -> float | None:
        values = [
            result["headline"].get(key)
            for result in results
            if isinstance(result["headline"].get(key), (int, float))
        ]
        return round(mean(values), 4) if values else None

    hard_failures: dict[str, int] = defaultdict(int)
    for result in results:
        for failure, value in result["headline"]["hard_failures"].items():
            hard_failures[failure] += bool(value)
    return {
        "n_variants": len(results),
        "story_success_rate": _ratio(
            sum(bool(result["headline"]["story_success"]) for result in results),
            len(results),
        ),
        "role_coverage_mean": avg("role_coverage"),
        "required_edge_coverage_mean": avg("required_edge_coverage"),
        "fact_coverage_mean": avg("fact_coverage"),
        "currentness_accuracy_mean": avg("currentness_accuracy"),
        "precision_mean": avg("precision"),
        "anchor_mrr": round(mean(result["anchor_reciprocal_rank"] for result in results), 4)
        if results
        else None,
        "anchor_hit_rate": _ratio(
            sum(bool(result["anchor_hit_at_k"]) for result in results),
            len(results),
        ),
        "anchor_k_values": sorted({result["anchor_k"] for result in results}),
        "hard_failures": dict(sorted(hard_failures.items())),
        "variants_with_divergences": [
            f"{result['scenario_id']}:{result['variant_id']}"
            for result in results
            if result["divergences"]
        ],
    }


def aggregate_story(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate story-retrieval results overall and by query style."""
    overall = _aggregate_story_core(results)
    styles = sorted({result["style"] for result in results})
    overall["by_style"] = {
        style: _aggregate_story_core([result for result in results if result["style"] == style])
        for style in styles
    }
    return overall


def causal_order_score(
    required_edges: list[dict[str, Any] | list[str]], ordered_ids: list[str]
) -> dict[str, Any]:
    """Score whether a response orders each gold cause before its effect."""
    duplicate_ids = sorted(
        entity_id for entity_id in set(ordered_ids) if ordered_ids.count(entity_id) > 1
    )
    positions = {entity_id: index for index, entity_id in enumerate(ordered_ids)}
    pairs = []
    for edge in required_edges:
        if isinstance(edge, dict):
            source = edge.get("source")
            target = edge.get("target")
        else:
            source, target = edge[:2]
        correct = (
            source in positions and target in positions and positions[source] < positions[target]
        )
        pairs.append({"source": source, "target": target, "correct": correct})
    return {
        "accuracy": _ratio(sum(pair["correct"] for pair in pairs), len(pairs)),
        "pairs": pairs,
        "duplicate_ids": duplicate_ids,
    }


def score_story_response(scenario: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Score one externally produced cold-session answer artifact.

    The harness does not run an LLM.  PI/Brain/Executor sessions independently
    use RKA and save a compact answer artifact; this function checks its cited
    substrate, causal ordering, current verdict, distractor handling, and
    independent human rubric without letting a high human score mask a hard
    fail. Retrieval and resolution ids are injected from an independently
    captured trace by the artifact scorer; they are not authored by the
    evaluated session.
    """
    story = scenario["story"]
    cited = set(response.get("cited_entity_ids", []))
    current = set(response.get("current_entity_ids", []))
    causal_chain = response.get("causal_chain", [])
    rejected = set(response.get("rejected_entity_ids", []))
    retrieved = set(response.get("retrieved_entity_ids", []))
    resolved = set(response.get("resolved_entity_ids", []))

    substrate = story_scores(story, cited)
    causal_contract = story.get("causal_edges") or []
    order = causal_order_score(causal_contract, causal_chain)
    forbidden = sorted(set(story.get("forbidden_entities", [])) & cited)
    foreign = sorted(set(story.get("foreign_must_exclude", [])) & cited)
    distractors_cited = sorted(set(story.get("distractors", [])) & cited)
    currentness = story.get("currentness", {})
    expected_current = set(currentness.get("must_be_current", story.get("current_entities", [])))
    forbidden_current = set(
        currentness.get("must_be_not_current", story.get("historical_entities", []))
    ) | set(story.get("forbidden_current_entities", []))
    stale_as_current = sorted(forbidden_current & current)
    current_missing = sorted(expected_current - current) if expected_current else []
    current_not_cited = sorted(current - cited)
    causal_not_cited = sorted(set(causal_chain) - cited)

    conclusion = story.get("current_conclusion", {})
    expected_verdict = conclusion.get("verdict")
    verdict_match = (
        response.get("verdict") == expected_verdict if expected_verdict is not None else None
    )
    conclusion_checks = [
        score_probe(check, response.get("answer", "")) for check in conclusion.get("checks", [])
    ]
    conclusion_passed = (
        all(check["passed"] for check in conclusion_checks) if conclusion_checks else None
    )

    human_scores = response.get("human_scores")
    human_valid = (
        isinstance(human_scores, dict)
        and set(human_scores) == set(HUMAN_RUBRIC_KEYS)
        and all(
            isinstance(human_scores[key], (int, float)) and 0 <= human_scores[key] <= 4
            for key in HUMAN_RUBRIC_KEYS
        )
    )
    human_total = sum(human_scores[key] for key in HUMAN_RUBRIC_KEYS) if human_valid else None
    human_min_score = float(story.get("human_min_score", 3.0))
    human_pass = bool(
        human_valid and all(human_scores[key] >= human_min_score for key in HUMAN_RUBRIC_KEYS)
    )

    hard_failures = {
        "missing_conclusion_contract": not bool(conclusion.get("checks")),
        "missing_causal_contract": not bool(causal_contract),
        "missing_retrieval_trace": not bool(retrieved and resolved),
        "resolved_not_retrieved": sorted(resolved - retrieved),
        "citation_not_attested": sorted(cited - resolved),
        "citation_precision": substrate["precision"] < substrate["min_precision"],
        "rejection_not_retrieved": sorted(rejected - retrieved),
        "foreign_project": foreign,
        "forbidden_entity": forbidden,
        "distractor_as_support": distractors_cited,
        "stale_as_current": stale_as_current,
        "current_missing": current_missing,
        "current_not_cited": current_not_cited,
        "causal_not_cited": causal_not_cited,
        "causal_duplicates": order["duplicate_ids"],
        "verdict_mismatch": verdict_match is False,
    }
    hard_failed = any(bool(value) for value in hard_failures.values())
    mechanical_pass = (
        substrate["role_coverage"] == 1.0
        and order["accuracy"] in (None, 1.0)
        and verdict_match in (None, True)
        and conclusion_passed in (None, True)
        and not hard_failed
    )
    if not mechanical_pass:
        overall_status = "mechanical_fail"
    elif human_scores is None:
        overall_status = "pending_human_review"
    elif not human_valid:
        overall_status = "invalid_human_review"
    elif human_pass:
        overall_status = "pass"
    else:
        overall_status = "human_fail"
    return {
        "scenario_id": scenario["scenario_id"],
        "query_variant": response["query_variant"],
        "role": response.get("role", "unspecified"),
        "run_id": response.get("run_id"),
        "session_id": response.get("session_id"),
        "response_sha256": response.get("response_sha256"),
        "style": response.get("style", response["query_variant"]),
        "mechanical_pass": mechanical_pass,
        "overall_status": overall_status,
        "role_coverage": substrate["role_coverage"],
        "missing_roles": substrate["missing_roles"],
        "citation_precision": substrate["precision"],
        "causal_order": order,
        "verdict_match": verdict_match,
        "conclusion_checks": conclusion_checks,
        "conclusion_passed": conclusion_passed,
        "distractors_cited": distractors_cited,
        "distractors_rejected": sorted(set(story.get("distractors", [])) & rejected),
        "hard_failures": hard_failures,
        "hard_fail": hard_failed,
        "human_scores": human_scores,
        "human_reviewer_id": response.get("human_reviewer_id"),
        "human_scores_valid": human_valid,
        "human_total": human_total,
        "human_min_score": human_min_score,
        "human_pass": human_pass,
    }


def aggregate_story_responses(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate cold-session answer scores overall and by query style."""

    def core(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "n_responses": len(items),
            "mechanical_pass_rate": _ratio(
                sum(bool(item["mechanical_pass"]) for item in items), len(items)
            ),
            "overall_pass_rate": _ratio(
                sum(item["overall_status"] == "pass" for item in items), len(items)
            ),
            "pending_human_review": sum(
                item["overall_status"] == "pending_human_review" for item in items
            ),
            "hard_failures": sum(bool(item["hard_fail"]) for item in items),
            "role_coverage_mean": round(mean(item["role_coverage"] for item in items), 4)
            if items
            else None,
            "causal_order_accuracy_mean": round(
                mean(
                    item["causal_order"]["accuracy"]
                    for item in items
                    if item["causal_order"]["accuracy"] is not None
                ),
                4,
            )
            if any(item["causal_order"]["accuracy"] is not None for item in items)
            else None,
            "human_total_mean": round(
                mean(item["human_total"] for item in items if item["human_total"] is not None),
                4,
            )
            if any(item["human_total"] is not None for item in items)
            else None,
        }

    overall = core(results)
    overall["by_style"] = {
        style: core([result for result in results if result["style"] == style])
        for style in sorted({result["style"] for result in results})
    }
    overall["by_role"] = {
        role: core([result for result in results if result["role"] == role])
        for role in sorted({result["role"] for result in results})
    }
    return overall


def trace_scores(expected_trace: list[dict[str, Any]], returned_ids: set[str]) -> dict[str, Any]:
    """Recall (critical + expanded), per-relation recall, and precision."""
    critical = [e for e in expected_trace if e.get("importance") == CRITICAL]
    found_all = [e for e in expected_trace if e["entity_id"] in returned_ids]
    found_critical = [e for e in critical if e["entity_id"] in returned_ids]

    per_relation: dict[str, dict[str, int]] = defaultdict(lambda: {"expected": 0, "found": 0})
    for entry in expected_trace:
        relation = entry.get("relation", "unknown")
        per_relation[relation]["expected"] += 1
        if entry["entity_id"] in returned_ids:
            per_relation[relation]["found"] += 1

    expected_ids = {e["entity_id"] for e in expected_trace}
    precision = len(expected_ids & returned_ids) / len(returned_ids) if returned_ids else 0.0
    return {
        "trace_recall": (len(found_critical) / len(critical)) if critical else None,
        "expanded_recall": (len(found_all) / len(expected_trace) if expected_trace else None),
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

    relation_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"expected": 0, "found": 0})
    for result in scenario_results:
        for relation, stats in result["union"]["per_relation"].items():
            relation_totals[relation]["expected"] += stats["expected"]
            relation_totals[relation]["found"] += stats["found"]
    per_relation = {
        relation: {
            **stats,
            "recall": round(stats["found"] / stats["expected"], 4) if stats["expected"] else None,
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
