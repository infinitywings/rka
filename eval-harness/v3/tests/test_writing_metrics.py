"""Locks for the Writer grounding & evidence-utilization scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_EVAL_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_EVAL_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_HARNESS_DIR))

from v3.writer.metrics import (  # noqa: E402
    cited_ids,
    compare_arms,
    evidence_utilization,
    grounding_metrics,
    score_arm,
)
from v3.writer.score_drafts import (  # noqa: E402
    load_verifier_report,
    main,
    score_scenario,
)


def _citation(entity_id: str, verdict: str, acknowledged: bool = False) -> dict:
    return {"entity_id": entity_id, "line": 1, "verdict": verdict, "acknowledged": acknowledged}


REPORT_A = {
    "path": "A.tex",
    "substantive_blocks": 10,
    "uncovered_blocks": 1,
    "verdict": "WARN",
    "citations": [
        _citation("clm_ev", "OK"),
        _citation("jrn_dir", "OK"),
        _citation("lit_base", "LOW_SUPPORT"),
        _citation("dec_old", "STALE", acknowledged=True),
        _citation("", "UNCOVERED"),
    ],
}

REPORT_B = {
    "path": "B.tex",
    "substantive_blocks": 10,
    "uncovered_blocks": 6,
    "verdict": "BLOCK",
    "citations": [
        _citation("clm_fake", "MISSING"),
        _citation("dec_old", "STALE"),
        _citation("clm_ev", "OK"),
    ],
}

EXPECTED = [
    {"entity_id": "clm_ev", "importance": "critical"},
    {"entity_id": "jrn_dir", "importance": "critical"},
    {"entity_id": "lit_base", "importance": "useful"},
]


def test_grounding_metrics_excludes_coverage_findings_and_acked_stale() -> None:
    grounding = grounding_metrics(REPORT_A)
    assert grounding["total_citations"] == 4  # UNCOVERED row not a citation
    assert grounding["coverage_rate"] == 0.9
    assert grounding["fabrication_rate"] == 0.0
    assert grounding["stale_rate"] == 0.0  # acknowledged stale is deliberate history
    assert grounding["weak_support_rate"] == 0.25
    assert grounding["ok_rate"] == 0.5


def test_grounding_metrics_flags_fabrication_and_stale() -> None:
    grounding = grounding_metrics(REPORT_B)
    assert grounding["fabrication_rate"] == round(1 / 3, 4)
    assert grounding["stale_rate"] == round(1 / 3, 4)
    assert grounding["coverage_rate"] == 0.4


def test_evidence_utilization_missed_critical() -> None:
    utilization = evidence_utilization(EXPECTED, cited_ids(REPORT_B))
    assert utilization["utilization_critical"] == 0.5  # jrn_dir missed
    assert utilization["missed_critical"] == ["jrn_dir"]
    full = evidence_utilization(EXPECTED, cited_ids(REPORT_A))
    assert full["utilization_critical"] == 1.0
    assert full["utilization_expanded"] == 1.0


def test_compare_arms_deltas() -> None:
    arms = {"A": score_arm(REPORT_A, EXPECTED), "B": score_arm(REPORT_B, EXPECTED)}
    comparison = compare_arms(arms, baseline="B")
    deltas = comparison["deltas_vs_baseline"]["A"]
    assert deltas["grounding.coverage_rate"] == 0.5
    assert deltas["grounding.fabrication_rate"] == round(-1 / 3, 4)
    assert deltas["utilization.utilization_critical"] == 0.5


def test_score_scenario_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "A.json").write_text(
        json.dumps({"version": "1.0", "files": [REPORT_A]}), encoding="utf-8"
    )
    (tmp_path / "reports" / "B.json").write_text(
        json.dumps(REPORT_B), encoding="utf-8"  # bare report shape also accepted
    )
    scenario = {
        "scenario_id": "s1",
        "expected_evidence": EXPECTED,
        "arms": {
            "A": {"verifier_report": "reports/A.json"},
            "B": {"verifier_report": "reports/B.json"},
        },
    }
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    result = score_scenario(scenario, tmp_path)
    assert result["comparison"]["arms"]["B"]["grounding"]["verifier_verdict"] == "BLOCK"

    out = tmp_path / "out.json"
    assert main(["--scenario", str(scenario_path), "--out", str(out)]) == 0
    combined = json.loads(out.read_text(encoding="utf-8"))
    assert combined["scenarios"][0]["scenario_id"] == "s1"


def test_missing_scenario_field_is_clean_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected_evidence"):
        score_scenario({"scenario_id": "x", "arms": {}}, tmp_path)


def test_empty_verifier_files_list_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"files": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no file reports"):
        load_verifier_report(empty)
