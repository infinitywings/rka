"""Phase O, O3.1 — hygiene_pass node tests.

Covers:
  - Clean RKA: empty hygiene_findings, no checkpoint emitted
  - Integrity-issue normalization: per-entry expansion + bucketed
    (no-entries) variant
  - Freshness-issue normalization: stale_entries / entries fallback
  - Pending-maintenance normalization: required vs info severity
  - Required-severity findings emit a checkpoint
  - MCP failures don't crash; degrade to empty findings on that tool
  - hygiene_pass keeps findings from the tools that DID succeed
  - graph.ONBOARDING_NODE_NAMES contains 'hygiene_pass'
"""

from __future__ import annotations

import pytest

from orchestrator import graph
from orchestrator.nodes import onboarding

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# Clean path
# ---------------------------------------------------------------------------


def test_hygiene_pass_clean_rka_no_findings_no_checkpoint():
    out = onboarding.hygiene_pass_node({"project_id": "prj_x"}, FakeSDK(), FakeMCP())
    assert out["current_node"] == "hygiene_pass"
    assert out["hygiene_findings"] == []
    assert "checkpoints" not in out


def test_hygiene_pass_calls_all_three_rka_tools():
    mcp = FakeMCP()
    onboarding.hygiene_pass_node({"project_id": "prj_x"}, FakeSDK(), mcp)
    ops = [c["op"] for c in mcp.calls]
    assert "rka_check_integrity" in ops
    assert "rka_check_freshness" in ops
    assert "rka_get_pending_maintenance" in ops


# ---------------------------------------------------------------------------
# Integrity normalization
# ---------------------------------------------------------------------------


def test_hygiene_pass_normalizes_integrity_entries():
    mcp = FakeMCP()
    mcp.integrity_response = {
        "total_issues": 3,
        "issues": [
            {
                "type": "orphan_decision",
                "count": 2,
                "severity": "info",
                "entries": [
                    {"id": "dec_aa", "detail": "no related_journal"},
                    {"id": "dec_bb", "detail": "no related_journal"},
                ],
            },
            {
                "type": "missing_provenance",
                "count": 1,
                "severity": "warning",
                "entries": [{"id": "jrn_cc", "detail": "no source"}],
            },
        ],
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    findings = out["hygiene_findings"]
    assert len(findings) == 3
    kinds = [f["kind"] for f in findings]
    assert "integrity:orphan_decision" in kinds
    assert "integrity:missing_provenance" in kinds
    # Targets propagated.
    targets = [f["target_id"] for f in findings]
    assert "dec_aa" in targets
    assert "jrn_cc" in targets


def test_hygiene_pass_integrity_no_entries_emits_bucketed_finding():
    mcp = FakeMCP()
    mcp.integrity_response = {
        "total_issues": 5,
        "issues": [
            {
                "type": "untagged_notes",
                "count": 5,
                "severity": "info",
                # No "entries" key — RKA gives just a count
            }
        ],
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    findings = out["hygiene_findings"]
    assert len(findings) == 1
    assert findings[0]["kind"] == "integrity:untagged_notes"
    assert findings[0]["target_id"] is None
    assert "5" in findings[0]["detail"]


# ---------------------------------------------------------------------------
# Freshness normalization
# ---------------------------------------------------------------------------


def test_hygiene_pass_normalizes_freshness_entries():
    mcp = FakeMCP()
    mcp.freshness_response = {
        "stale_entries": [
            {"id": "jrn_aa", "reason": "no update in 45d", "severity": "warning"},
            {"id": "jrn_bb", "days_since_update": 60},
        ]
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    findings = out["hygiene_findings"]
    assert len(findings) == 2
    assert all(f["kind"] == "freshness:stale" for f in findings)
    assert findings[0]["detail"] == "no update in 45d"
    # Second has no 'reason' so falls back to days_since_update.
    assert "60d" in findings[1]["detail"]


def test_hygiene_pass_freshness_alternative_entries_key():
    """Some RKA versions use 'entries' instead of 'stale_entries'."""
    mcp = FakeMCP()
    mcp.freshness_response = {
        "entries": [{"id": "jrn_x", "reason": "stale"}]
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    assert any(f["kind"] == "freshness:stale" for f in out["hygiene_findings"])


# ---------------------------------------------------------------------------
# Pending-maintenance normalization
# ---------------------------------------------------------------------------


def test_hygiene_pass_pending_maintenance_info_severity():
    mcp = FakeMCP()
    mcp.pending_maintenance_response = {
        "items": [
            {"id": "task_aa", "kind": "review_cluster", "detail": "needs review"},
        ]
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    f = out["hygiene_findings"][0]
    assert f["kind"] == "maintenance:review_cluster"
    assert f["severity"] == "info"  # required=False → info
    assert "checkpoints" not in out


def test_hygiene_pass_required_pending_maintenance_emits_checkpoint():
    mcp = FakeMCP()
    mcp.pending_maintenance_response = {
        "items": [
            {
                "id": "task_required",
                "kind": "resolve_contradiction",
                "detail": "claim conflict",
                "required": True,
            },
            {
                "id": "task_required_2",
                "kind": "fix_orphan",
                "required": True,
            },
        ]
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    # Both items marked required → both in findings AND a checkpoint.
    assert all(f["severity"] == "required" for f in out["hygiene_findings"])
    assert "checkpoints" in out
    chk = out["checkpoints"][0]
    assert chk["type"] == "decision"
    assert "2 required" in chk["reason"]
    assert chk["resolved"] is False


# ---------------------------------------------------------------------------
# MCP failure tolerance
# ---------------------------------------------------------------------------


def test_hygiene_pass_tolerates_integrity_failure():
    class _IntegrityFail(FakeMCP):
        def rka_check_integrity(self):
            raise RuntimeError("rka down")

    mcp = _IntegrityFail()
    mcp.freshness_response = {
        "stale_entries": [{"id": "jrn_x", "reason": "stale"}]
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    # Integrity contributed nothing, but freshness's finding survives.
    assert any(f["kind"] == "freshness:stale" for f in out["hygiene_findings"])


def test_hygiene_pass_tolerates_all_three_failures():
    class _AllFail(FakeMCP):
        def rka_check_integrity(self):
            raise RuntimeError("down")

        def rka_check_freshness(self, days_threshold: int = 30):
            raise RuntimeError("down")

        def rka_get_pending_maintenance(self):
            raise RuntimeError("down")

    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), _AllFail())
    assert out["hygiene_findings"] == []
    assert out["current_node"] == "hygiene_pass"
    assert "checkpoints" not in out


# ---------------------------------------------------------------------------
# Required-severity checkpoint summary truncation
# ---------------------------------------------------------------------------


def test_hygiene_pass_truncates_checkpoint_summary_above_10():
    mcp = FakeMCP()
    mcp.pending_maintenance_response = {
        "items": [
            {"id": f"task_{i:02d}", "kind": "x", "required": True}
            for i in range(15)
        ]
    }
    out = onboarding.hygiene_pass_node({"project_id": "p"}, FakeSDK(), mcp)
    chk = out["checkpoints"][0]
    assert "15 required" in chk["reason"]
    assert "…" in chk["reason"]  # ellipsis past 10


# ---------------------------------------------------------------------------
# Graph registry wiring
# ---------------------------------------------------------------------------


def test_graph_onboarding_node_names_include_hygiene_pass():
    assert "hygiene_pass" in graph.ONBOARDING_NODE_NAMES
