"""Mechanical scoring for the retention (fade) benchmark.

Pure functions — no I/O, no HTTP, no model calls — so the math is
lockable by unit tests and runs are reproducible.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def score_probe(expect: dict[str, Any], response: str) -> dict[str, Any]:
    """Evaluate one probe response against its expectation block."""
    lowered = response.lower()
    checks: dict[str, Any] = {}

    if "must_include" in expect:
        missing = [t for t in expect["must_include"] if t.lower() not in lowered]
        checks["must_include"] = {"passed": not missing, "missing": missing}

    if "must_not_include" in expect:
        leaked = [t for t in expect["must_not_include"] if t.lower() in lowered]
        checks["must_not_include"] = {"passed": not leaked, "leaked": leaked}

    if "expected_citations" in expect:
        absent = [e for e in expect["expected_citations"] if e not in response]
        checks["expected_citations"] = {"passed": not absent, "absent": absent}

    if "numeric" in expect:
        target = float(expect["numeric"]["value"])
        tolerance = float(expect["numeric"].get("tolerance", 0.0))
        numbers = [float(n) for n in _NUMBER_RE.findall(response)]
        hit = any(abs(n - target) <= tolerance for n in numbers)
        checks["numeric"] = {"passed": hit, "target": target}

    passed = bool(checks) and all(c["passed"] for c in checks.values())
    return {"passed": passed, "checks": checks}


def _bucket(distance: int, edges: list[int]) -> str:
    for edge in edges:
        if distance <= edge:
            return f"<={edge}"
    return f">{edges[-1]}" if edges else "all"


def retention_curve(
    probe_results: list[dict[str, Any]],
    bucket_edges: list[int] = [2_000, 10_000, 50_000, 150_000],
) -> dict[str, Any]:
    """Pass rate per arm per context-distance bucket, plus per-kind rates.

    Each probe_result needs: arm, distance_tokens, passed, kind
    (directive|evidence).
    """
    by_arm_bucket: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: defaultdict(list)
    )
    by_arm_kind: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for result in probe_results:
        bucket = _bucket(result["distance_tokens"], bucket_edges)
        by_arm_bucket[result["arm"]][bucket].append(result["passed"])
        by_arm_kind[result["arm"]][result.get("kind", "unknown")].append(
            result["passed"]
        )

    def rates(groups: dict[str, list[bool]]) -> dict[str, Any]:
        return {
            key: {"n": len(values), "pass_rate": round(sum(values) / len(values), 4)}
            for key, values in sorted(groups.items())
        }

    return {
        "bucket_edges": bucket_edges,
        "by_arm": {
            arm: {
                "by_distance": rates(buckets),
                "by_kind": rates(by_arm_kind[arm]),
                "overall_pass_rate": round(
                    sum(v for vs in buckets.values() for v in vs)
                    / sum(len(vs) for vs in buckets.values()),
                    4,
                ),
            }
            for arm, buckets in sorted(by_arm_bucket.items())
        },
    }
