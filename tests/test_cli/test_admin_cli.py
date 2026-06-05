"""Tests for `rka admin ...` subgroup (v2.7.0.6).

The admin subgroup is the CLI surface for `rka.services.admin_repair`.
These tests cover the CLI's argument parsing + dry-run discipline +
JSON output, isolated from the full DB-mutation tests in
test_services/test_admin_repair.py.

CLI tests use Click's `CliRunner` and monkeypatch the underlying
service functions to capture call args without touching SQLite.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from rka.cli import main
from rka.services import admin_repair as admin_repair_mod
from rka.services.admin_repair import PairReport, StepReport


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_repair_requires_apply_flag(monkeypatch):
    """Without --apply, the command runs in dry-run mode and prints
    the DRY RUN banner. It does not raise."""
    captured_calls: list[dict] = []

    async def fake_repair(db, project_id, mapping, *, dry_run, actor):
        captured_calls.append(
            {"project_id": project_id, "mapping": mapping, "dry_run": dry_run, "actor": actor}
        )
        return [
            PairReport(
                old_decision_id="dec_old", new_decision_id="dec_new",
                project_id=project_id,
                steps=[
                    StepReport("scope_version_bump", "WOULD"),
                    StepReport("superseded_by_fk", "WOULD"),
                ],
            ),
        ]

    monkeypatch.setattr(admin_repair_mod, "repair_orphan_supersedes", fake_repair)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=dec_old=dec_new"],
    )
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert captured_calls[-1]["dry_run"] is True


def test_repair_with_apply_runs_in_apply_mode(monkeypatch):
    captured_calls: list[dict] = []

    async def fake_repair(db, project_id, mapping, *, dry_run, actor):
        captured_calls.append(
            {"project_id": project_id, "mapping": mapping, "dry_run": dry_run, "actor": actor}
        )
        return [
            PairReport(
                old_decision_id="dec_old", new_decision_id="dec_new",
                project_id=project_id,
                steps=[StepReport("scope_version_bump", "DONE")],
            ),
        ]

    monkeypatch.setattr(admin_repair_mod, "repair_orphan_supersedes", fake_repair)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=dec_old=dec_new",
         "--apply"],
    )
    assert result.exit_code == 0, result.output
    assert "APPLIED" in result.output
    assert captured_calls[-1]["dry_run"] is False


def test_repair_json_output(monkeypatch):
    """--json prints a parseable list[dict] with PairReport fields."""

    async def fake_repair(db, project_id, mapping, *, dry_run, actor):
        return [
            PairReport(
                old_decision_id="dec_old", new_decision_id="dec_new",
                project_id=project_id,
                steps=[
                    StepReport("scope_version_bump", "DONE", "1 -> 2"),
                    StepReport("superseded_by_fk", "DONE"),
                ],
            ),
        ]

    monkeypatch.setattr(admin_repair_mod, "repair_orphan_supersedes", fake_repair)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=dec_old=dec_new",
         "--apply", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert payload[0]["old_decision_id"] == "dec_old"
    assert payload[0]["new_decision_id"] == "dec_new"
    assert payload[0]["applied"] is True
    assert payload[0]["steps"][0]["name"] == "scope_version_bump"


def test_repair_map_parse_error_no_equals(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=invalid_value"],
    )
    assert result.exit_code != 0
    assert "must be old_id=new_id" in result.output


def test_repair_map_parse_error_empty_side(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map==dec_new"],
    )
    assert result.exit_code != 0
    assert "empty side" in result.output


def test_repair_map_duplicate_olds_rejected(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=dec_old=dec_a",
         "--map=dec_old=dec_b"],
    )
    assert result.exit_code != 0
    assert "listed more than once" in result.output


def test_repair_actor_choice_constraint(monkeypatch):
    """--actor=admin is rejected; only pi/brain/executor/system accepted.
    Without the Choice constraint a value like 'admin' would land in the
    events.actor column and fail the CHECK mid-transaction (silently
    triggering ROLLBACK in the apply path)."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=dec_old=dec_new",
         "--actor=admin"],
    )
    assert result.exit_code != 0
    assert "Invalid value" in result.output or "admin" in result.output


def test_repair_exit_nonzero_when_any_pair_rolled_back(monkeypatch):
    """When at least one pair failed, the command exits non-zero so CI
    sees the signal."""

    async def fake_repair(db, project_id, mapping, *, dry_run, actor):
        return [
            PairReport(
                old_decision_id="dec_old", new_decision_id="dec_new",
                project_id=project_id,
                steps=[StepReport("validate", "FAILED")],
                failure_reason="not found",
            ),
        ]

    monkeypatch.setattr(admin_repair_mod, "repair_orphan_supersedes", fake_repair)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "repair-supersedes",
         "--project=proj_default",
         "--map=dec_old=dec_new",
         "--apply"],
    )
    assert result.exit_code == 1, result.output
    assert "ROLLED BACK" in result.output


# ---------------------------------------------------------------------------
# list-orphan-supersedes
# ---------------------------------------------------------------------------


def test_list_orphan_supersedes_json_output(monkeypatch):
    """--json on the listing command emits a parseable list[dict]."""

    async def fake_list(db, project_id):
        return [
            {
                "id": "dec_old", "question": "Q?", "phase": "design",
                "decided_by": "brain", "chosen": "A", "scope_version": 1,
                "updated_at": "2026-06-05T12:00:00Z",
                "created_at": "2026-06-05T11:00:00Z",
            },
        ]

    monkeypatch.setattr(admin_repair_mod, "list_orphan_supersedes", fake_list)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "list-orphan-supersedes",
         "--project=proj_default", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["id"] == "dec_old"


def test_list_orphan_supersedes_text_output(monkeypatch):
    async def fake_list(db, project_id):
        return [
            {
                "id": "dec_old_xyz", "question": "Should we use A?",
                "phase": "design", "decided_by": "brain", "chosen": "A",
                "scope_version": 1, "updated_at": "2026-06-05T12:00:00Z",
                "created_at": "2026-06-05T11:00:00Z",
            },
        ]

    monkeypatch.setattr(admin_repair_mod, "list_orphan_supersedes", fake_list)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "list-orphan-supersedes", "--project=proj_default"],
    )
    assert result.exit_code == 0, result.output
    assert "dec_old_xyz" in result.output
    assert "Should we use A?" in result.output
    assert "repair-supersedes" in result.output


def test_list_orphan_supersedes_empty(monkeypatch):
    async def fake_list(db, project_id):
        return []

    monkeypatch.setattr(admin_repair_mod, "list_orphan_supersedes", fake_list)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["admin", "list-orphan-supersedes", "--project=proj_default"],
    )
    assert result.exit_code == 0
    assert "No orphan supersedes" in result.output
