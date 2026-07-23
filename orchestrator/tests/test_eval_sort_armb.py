"""Isolation and artifact-accounting tests for the plain-Claude eval arm."""

from __future__ import annotations

import pytest

from orchestrator.eval.graders import grade_capability
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.sort_crossover import SORT_EXPERIMENT_CAPABILITY_KINDS
from scripts import eval_sort_armB as arm_b
from scripts import eval_sort_driver as arm_a_driver


def test_main_uses_the_plain_sdk_factory(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    captured = {}

    class FakeSDK:
        last_call_cost_usd = 0.0

        def complete(self, prompt, *, system=None, timeout_s=None):
            assert "Research question:" in prompt
            return "FINAL CLAIM: performance depends on size and ordering"

    def fake_make_plain_sdk(*, workspace_path, model):
        captured.update(workspace_path=workspace_path, model=model)
        return FakeSDK()

    monkeypatch.setattr(
        "orchestrator.llm_client.make_plain_sdk",
        fake_make_plain_sdk,
    )

    assert arm_b.main([
        "--workspace", str(workspace),
        "--output-dir", str(output),
        "--model", "claude-test",
    ]) == 0
    assert captured == {
        "workspace_path": str(workspace),
        "model": "claude-test",
    }


def test_workspace_delta_ignores_stale_and_hidden_files(tmp_path):
    stale_report = tmp_path / "armB_report.md"
    stale_report.write_text("FINAL CLAIM: stale result\n")
    changed_code = tmp_path / "analysis.py"
    changed_code.write_text("print('old')\n")
    hidden = tmp_path / ".claude" / "state.json"
    hidden.parent.mkdir()
    hidden.write_text('{"old": true}\n')

    before = arm_b._workspace_snapshot(str(tmp_path))

    changed_code.write_text("print('new')\n")
    new_figure = tmp_path / "armB_figure.txt"
    new_figure.write_text("comparison plot\n")
    hidden.write_text('{"new": true}\n')

    produced = arm_b._changed_workspace_files(str(tmp_path), before)
    assert produced == [changed_code, new_figure]

    artifacts = arm_b._classify_workspace_artifacts(produced)
    assert [(a["id"], a["kind"]) for a in artifacts] == [
        (str(changed_code), "journal"),
        (str(new_figure), "diagram"),
    ]

    claim = arm_b._extract_claim(
        "FINAL CLAIM: fresh completion result",
        str(tmp_path),
        produced,
    )
    assert claim == "FINAL CLAIM: fresh completion result"


def test_nonempty_workspace_is_rejected_before_a_run(tmp_path):
    (tmp_path / "armB_report.md").write_text("prior answer\n")
    with pytest.raises(ValueError, match="new, empty workspace"):
        arm_b._require_fresh_workspace(str(tmp_path))


def test_modified_report_can_supply_this_runs_claim(tmp_path):
    report = tmp_path / "armB_report.md"
    report.write_text("FINAL CLAIM: stale result\n")
    before = arm_b._workspace_snapshot(str(tmp_path))

    report.write_text("notes\nFINAL CLAIM: measured interaction\n")
    produced = arm_b._changed_workspace_files(str(tmp_path), before)

    assert produced == [report]
    assert (
        arm_b._extract_claim("completion without a labelled claim", str(tmp_path), produced)
        == "FINAL CLAIM: measured interaction"
    )


def test_workspace_snapshot_ignores_symlinks(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("not part of the arm\n")
    (tmp_path / "outside-link.txt").symlink_to(outside)

    assert arm_b._workspace_snapshot(str(tmp_path)) == {}


def test_config_filename_is_not_misclassified_as_a_figure(tmp_path):
    config = tmp_path / "config.json"
    figure = tmp_path / "fig-1.txt"
    config.write_text("{}\n")
    figure.write_text("plot\n")

    artifacts = arm_b._classify_workspace_artifacts([config, figure])
    assert [(a["id"], a["kind"]) for a in artifacts] == [
        (str(config), "journal"),
        (str(figure), "diagram"),
    ]


def test_capability_contract_does_not_double_count_provenance():
    arm_a = RunRecord(
        arc="mission",
        run_label="A",
        artifacts=[
            {"id": "jrn", "kind": "journal"},
            {"id": "dec", "kind": "decision"},
            {"id": "clm", "kind": "claim"},
            {"id": "rep", "kind": "report"},
        ],
    )
    arm_b = RunRecord(
        arc="mission",
        run_label="B",
        artifacts=[
            {"id": "code", "kind": "journal"},
            {"id": "rep", "kind": "report"},
        ],
    )

    assert grade_capability(
        arm_a, expected_kinds=SORT_EXPERIMENT_CAPABILITY_KINDS
    ).score == 1.0
    assert grade_capability(
        arm_b, expected_kinds=SORT_EXPERIMENT_CAPABILITY_KINDS
    ).score == 1.0
    assert (
        arm_a_driver._capability_kinds_for_run_label("M3-experiment-and-pivot")
        == SORT_EXPERIMENT_CAPABILITY_KINDS
    )
