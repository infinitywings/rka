#!/usr/bin/env python3
"""Score drafting arms for the Writer grounding & evidence-utilization eval.

Consumes one or more scenario JSON files (see scenario.example.json): each
names the section, the PI-ratified expected-evidence set, and per-arm the
verify_provenance.py JSON report for that arm's draft. Emits per-arm
grounding/utilization metrics and deltas against the baseline arm.

Produce the verifier reports first, e.g.:
    python rka/skills/writer/scripts/verify_provenance.py draft_A.tex \
        --project prj_... --output reports/A.json

Then:
    python eval-harness/v3/writer/score_drafts.py \
        --scenario scenario.json --out results/comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_V3_DIR = Path(__file__).resolve().parent.parent
if str(_V3_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V3_DIR.parent))

from v3.writer.metrics import compare_arms, score_arm  # noqa: E402


def load_verifier_report(path: Path) -> dict:
    """First FileReport from a verify_provenance --output JSON (or a bare report)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "files" in payload:
        files = payload["files"]
        if not files:
            raise ValueError(f"{path}: verifier output contains no file reports")
        return files[0]
    return payload


def score_scenario(scenario: dict, scenario_dir: Path) -> dict:
    for field in ("scenario_id", "expected_evidence", "arms"):
        if field not in scenario:
            raise ValueError(f"scenario missing required field {field!r}")
    arm_scores = {}
    for arm, spec in scenario["arms"].items():
        report_path = scenario_dir / spec["verifier_report"]
        arm_scores[arm] = score_arm(
            load_verifier_report(report_path), scenario["expected_evidence"]
        )
    return {
        "scenario_id": scenario["scenario_id"],
        "comparison": compare_arms(
            arm_scores, baseline=scenario.get("baseline_arm", "B")
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scenario", action="append", required=True, help="scenario JSON (repeatable)"
    )
    parser.add_argument("--out", help="write combined results JSON here")
    args = parser.parse_args(argv)

    results = []
    for scenario_arg in args.scenario:
        scenario_path = Path(scenario_arg)
        try:
            scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
            results.append(score_scenario(scenario, scenario_path.parent))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: {scenario_path}: {exc}", file=sys.stderr)
            return 2

    rendered = json.dumps({"scenarios": results}, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
