"""Scoring for the Writer grounding & evidence-utilization eval.

Pure functions over verify_provenance.py JSON reports and PI-ratified
expected-evidence sets — no I/O, no HTTP — so the math is lockable by
unit tests. The drafting arms are produced elsewhere (see protocol.md);
this module only compares their artifacts.
"""

from __future__ import annotations

from typing import Any

CRITICAL = "critical"

# verify_provenance verdicts grouped by what they mean for the eval
FABRICATED = {"MISSING"}
STALE = {"STALE", "RETRACTED"}
WEAK = {"LOW_SUPPORT", "CONTRADICTED"}
COVERAGE_FINDINGS = {"MALFORMED", "ORPHAN", "UNCOVERED"}


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def grounding_metrics(file_report: dict[str, Any]) -> dict[str, Any]:
    """Mechanical grounding profile of one draft from its verifier report."""
    citations = [
        c
        for c in file_report.get("citations", [])
        if c.get("verdict") not in COVERAGE_FINDINGS
    ]
    total = len(citations)
    substantive = file_report.get("substantive_blocks", 0)
    uncovered = file_report.get("uncovered_blocks", 0)
    fabricated = sum(1 for c in citations if c["verdict"] in FABRICATED)
    stale = sum(
        1 for c in citations if c["verdict"] in STALE and not c.get("acknowledged")
    )
    weak = sum(1 for c in citations if c["verdict"] in WEAK)
    ok = sum(1 for c in citations if c["verdict"] == "OK")
    return {
        "total_citations": total,
        "coverage_rate": _rate(substantive - uncovered, substantive),
        "fabrication_rate": _rate(fabricated, total),
        "stale_rate": _rate(stale, total),
        "weak_support_rate": _rate(weak, total),
        "ok_rate": _rate(ok, total),
        "verifier_verdict": file_report.get("verdict"),
    }


def cited_ids(file_report: dict[str, Any]) -> set[str]:
    """Entity ids the draft actually cited (coverage findings excluded)."""
    return {
        c["entity_id"]
        for c in file_report.get("citations", [])
        if c.get("verdict") not in COVERAGE_FINDINGS and c.get("entity_id")
    }


def evidence_utilization(
    expected_evidence: list[dict[str, Any]], draft_cited: set[str]
) -> dict[str, Any]:
    """How much of the section's ratified evidence set the draft used."""
    critical = [e for e in expected_evidence if e.get("importance") == CRITICAL]
    used_all = [e for e in expected_evidence if e["entity_id"] in draft_cited]
    used_critical = [e for e in critical if e["entity_id"] in draft_cited]
    return {
        "utilization_critical": _rate(len(used_critical), len(critical)),
        "utilization_expanded": _rate(len(used_all), len(expected_evidence)),
        "missed_critical": sorted(
            e["entity_id"] for e in critical if e["entity_id"] not in draft_cited
        ),
    }


def score_arm(
    file_report: dict[str, Any], expected_evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "grounding": grounding_metrics(file_report),
        "utilization": evidence_utilization(expected_evidence, cited_ids(file_report)),
    }


_DELTA_KEYS = (
    ("grounding", "coverage_rate"),
    ("grounding", "fabrication_rate"),
    ("grounding", "stale_rate"),
    ("grounding", "ok_rate"),
    ("utilization", "utilization_critical"),
)


def compare_arms(
    arm_scores: dict[str, dict[str, Any]], baseline: str = "B"
) -> dict[str, Any]:
    """Side-by-side arms with deltas against the baseline arm (when present)."""
    comparison: dict[str, Any] = {"arms": arm_scores, "baseline": baseline}
    base = arm_scores.get(baseline)
    if base is None:
        return comparison
    deltas: dict[str, dict[str, float]] = {}
    for arm, scores in arm_scores.items():
        if arm == baseline:
            continue
        arm_delta = {}
        for section, key in _DELTA_KEYS:
            ours, theirs = scores[section].get(key), base[section].get(key)
            if isinstance(ours, (int, float)) and isinstance(theirs, (int, float)):
                arm_delta[f"{section}.{key}"] = round(ours - theirs, 4)
        deltas[arm] = arm_delta
    comparison["deltas_vs_baseline"] = deltas
    return comparison
