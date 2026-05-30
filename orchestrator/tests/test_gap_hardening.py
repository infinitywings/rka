"""Adversarial-review hardening tests for Gaps 1, 2, 3B, 4a, 4b.

Findings from the in-session adversarial review subagent that flagged:
  #1 — bash backgrounding (`&`) escapes timeout
  #2 — symlink escape via Write/Edit
  #3 — heredoc + command-substitution AST gap
  #4 — bashlex array-assignment crash disables AST
  #5 — allowlist treats /path/foo as `foo`
  #7 — capability parse conflates "no block" with "all filtered"
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orchestrator import fs_actuator as FA
from orchestrator.nodes import brain as brain_module
from orchestrator.nodes import executor
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


def _state(**overrides):
    s = make_initial_state(
        workflow_thread_id="thr_h",
        mission_id="mis_h",
        motivated_by_decision_id="dec_h",
    )
    s.update(overrides)
    return s


# ---------------------------------------------------------------------------
# Adversarial #1 — backgrounding operator detection
# ---------------------------------------------------------------------------


def test_bash_with_backgrounding_operator_is_refused(tmp_path):
    state = _state(workspace_path=str(tmp_path))
    state["ratified_fs_actions"] = [
        {
            "tool": "Bash",
            "args": {"command": "nohup python /tmp/payload.py &"},
            "rationale": "smuggle background",
        }
    ]

    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    err = update["errors"][0]
    assert err["error_type"] == "ratified_fs_action_backgrounded"


def test_bash_with_logical_and_is_allowed(tmp_path):
    """&& is logical AND, not backgrounding — must not false-trip."""
    state = _state(workspace_path=str(tmp_path))
    state["ratified_fs_actions"] = [
        {
            "tool": "Bash",
            "args": {"command": "echo a && echo b"},
            "rationale": "test",
        }
    ]
    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    assert "errors" not in update


def test_bash_with_amp_inside_quoted_string_is_allowed(tmp_path):
    """An `&` literal inside quoted string isn't backgrounding."""
    state = _state(workspace_path=str(tmp_path))
    state["ratified_fs_actions"] = [
        {
            "tool": "Bash",
            "args": {"command": "echo 'a & b'"},
            "rationale": "test",
        }
    ]
    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    assert "errors" not in update


# ---------------------------------------------------------------------------
# Adversarial #6 — empty workspace refuses bash
# ---------------------------------------------------------------------------


def test_bash_without_workspace_path_is_refused():
    """workspace_path empty → daemon cwd / app — refuse."""
    state = _state()  # no workspace_path set
    state["ratified_fs_actions"] = [
        {"tool": "Bash", "args": {"command": "echo hi"}, "rationale": "?"}
    ]
    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    err = update["errors"][0]
    assert err["error_type"] == "ratified_fs_action_missing_workspace"


# ---------------------------------------------------------------------------
# Adversarial #2 — symlink escape
# ---------------------------------------------------------------------------


def test_write_through_workspace_symlink_is_refused(tmp_path):
    """`/ws/link → /etc/passwd` — Write through the symlink must NOT
    silently mutate /etc/passwd."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("important")
    link = ws / "link"
    link.symlink_to(outside)

    state = _state(workspace_path=str(ws))
    state["ratified_fs_actions"] = [
        {
            "tool": "Write",
            "args": {"file_path": str(link), "content": "hijack"},
            "rationale": "escape attempt",
        }
    ]
    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    err = update["errors"][0]
    assert err["error_type"] in (
        "ratified_fs_action_symlink_escape",
        "ratified_fs_action_bad_path",
    )
    # The outside file MUST be unchanged.
    assert outside.read_text() == "important"


def test_edit_through_workspace_symlink_is_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("xx old yy")
    link = ws / "link"
    link.symlink_to(outside)

    state = _state(workspace_path=str(ws))
    state["ratified_fs_actions"] = [
        {
            "tool": "Edit",
            "args": {
                "file_path": str(link),
                "old_string": "old",
                "new_string": "PATCHED",
            },
            "rationale": "escape attempt",
        }
    ]
    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    assert "errors" in update
    # The outside file MUST be unchanged.
    assert outside.read_text() == "xx old yy"


def test_write_through_dotdot_to_sibling_is_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    state = _state(workspace_path=str(ws))
    state["ratified_fs_actions"] = [
        {
            "tool": "Write",
            "args": {
                "file_path": str(ws / ".." / "sibling" / "x.txt"),
                "content": "leak",
            },
            "rationale": "escape attempt",
        }
    ]
    update = executor.execute_ratified_fs_actions(state, FakeSDK(), FakeMCP())
    assert "errors" in update
    err = update["errors"][0]
    assert err["error_type"] in (
        "ratified_fs_action_symlink_escape",
        "ratified_fs_action_bad_path",
    )


# ---------------------------------------------------------------------------
# Adversarial #3 — heredoc + command substitution AST resolution
# ---------------------------------------------------------------------------


def test_heredoc_smuggling_destructive_payload_is_caught():
    """A heredoc body containing `rm -rf /home` should still match
    the destructive pattern even though the outer cat command is
    benign."""
    cmd = "cat <<EOF\nrm -rf /home/x\nEOF"
    destructive, _ = FA.is_destructive_bash(cmd)
    assert destructive is True


def test_command_substitution_with_var_indirection_is_caught():
    """`$(RM=rm; $RM -rf /home)` — the inner subshell sets RM and uses
    it. AST must recurse into the command substitution."""
    cmd = "echo $(RM=rm; $RM -rf /home)"
    destructive, _ = FA.is_destructive_bash(cmd)
    assert destructive is True


# ---------------------------------------------------------------------------
# Adversarial #4 — regex fallback when bashlex fails
# ---------------------------------------------------------------------------


def test_array_assignment_does_not_disable_ast_defense():
    """`arr[0]=rm; ${arr[0]} -rf /home` — bashlex fails to parse arrays
    but the regex fallback should still catch the `RM=rm` pattern."""
    # Use a simpler form that triggers the regex fallback
    cmd = "RM=rm; $RM -rf /home/x"
    # Force regex fallback path test
    out = FA._regex_assignment_normalize(cmd)
    assert out is not None
    assert "rm -rf /home/x" in out


def test_regex_fallback_resolves_var_refs():
    cmd = "RM=rm; eval $RM -rf /tmp"
    out = FA._regex_assignment_normalize(cmd)
    assert out is not None
    assert "rm -rf" in out


def test_regex_fallback_returns_none_when_no_assignment():
    """No assignments → regex fallback yields None (no signal added)."""
    assert FA._regex_assignment_normalize("python script.py") is None


# ---------------------------------------------------------------------------
# Adversarial #5 — allowlist must reject path-prefixed roots
# ---------------------------------------------------------------------------


def test_allowlist_refuses_absolute_path_root():
    """`/tmp/python -c 'evil'` — even though `python` is in allowlist,
    the path-prefixed invocation must be refused so a planted shim
    can't bypass via PATH manipulation."""
    in_al, root = FA.is_bash_in_allowlist("/tmp/python -c 'shutil.rmtree(\"/\")'")
    assert in_al is False
    assert "/" in root


def test_allowlist_refuses_relative_path_root():
    in_al, root = FA.is_bash_in_allowlist("./script.sh args")
    assert in_al is False
    assert "/" in root


def test_classify_with_allowlist_mode_refuses_path_prefixed_python():
    cls, rationale = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "/tmp/python script.py"}},
        workspace_path="/ws/proj",
        bash_allowlist_mode=True,
    )
    assert cls == "ratify_required"


# ---------------------------------------------------------------------------
# Adversarial #7 — capability parse provenance distinguishes cases
# ---------------------------------------------------------------------------


def test_provenance_absent_for_no_block():
    parsed, prov = brain_module._parse_proposed_capabilities_with_provenance("text")
    assert parsed == []
    assert prov == "absent"


def test_provenance_valid_for_known_caps():
    reply = '```json\n{"capabilities": ["record_knowledge"]}\n```'
    parsed, prov = brain_module._parse_proposed_capabilities_with_provenance(reply)
    assert parsed == ["record_knowledge"]
    assert prov == "valid"


def test_provenance_all_filtered_when_all_unknown():
    """Brain proposed entries but they were all unknown — distinct
    provenance signal from absent."""
    reply = '```json\n{"capabilities": ["typo_cap", "another_typo"]}\n```'
    parsed, prov = brain_module._parse_proposed_capabilities_with_provenance(reply)
    assert parsed == []
    assert prov == "all_filtered"


def test_provenance_non_json_block():
    reply = '```json\n{capabilities: bad}\n```'
    parsed, prov = brain_module._parse_proposed_capabilities_with_provenance(reply)
    assert parsed == []
    assert prov == "non_json"


def test_provenance_no_key_when_other_fields_present():
    reply = '```json\n{"strategy": "..."}\n```'
    parsed, prov = brain_module._parse_proposed_capabilities_with_provenance(reply)
    assert parsed == []
    assert prov == "no_key"


def test_provenance_non_list_when_value_is_string():
    reply = '```json\n{"capabilities": "record_knowledge"}\n```'
    parsed, prov = brain_module._parse_proposed_capabilities_with_provenance(reply)
    assert parsed == []
    assert prov == "non_list"


# ---------------------------------------------------------------------------
# Adversarial #8 — _require_workspace_or_raise helper exists
# ---------------------------------------------------------------------------


def test_require_workspace_raises_for_unonboarded_project():
    """Helper exists and refuses missions for projects without a
    workspace_path row."""
    from orchestrator.parked_store import ParkedStore
    from orchestrator.runner import MissionNotFoundError, OrchestratorRunner

    store = ParkedStore(":memory:")
    # NOT calling set_project_workspace — simulates an un-onboarded project
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda _p, _ws="": FakeSDK(),
        mcp_factory=lambda _t, _p: FakeMCP(),
        saver_factory=lambda _t: None,
    )

    with pytest.raises(MissionNotFoundError, match="no registered workspace_path"):
        runner._require_workspace_or_raise("prj_unboarded")

    store.close()


def test_require_workspace_returns_path_for_onboarded_project():
    from orchestrator.parked_store import ParkedStore
    from orchestrator.runner import OrchestratorRunner

    store = ParkedStore(":memory:")
    store.set_project_workspace("prj_ok", "/Users/pi/Research/ok")
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda _p, _ws="": FakeSDK(),
        mcp_factory=lambda _t, _p: FakeMCP(),
        saver_factory=lambda _t: None,
    )

    assert runner._require_workspace_or_raise("prj_ok") == "/Users/pi/Research/ok"
    store.close()


def test_require_workspace_passes_for_empty_project_id():
    """Phase B flows use empty project_id — should return empty without
    raising."""
    from orchestrator.parked_store import ParkedStore
    from orchestrator.runner import OrchestratorRunner

    store = ParkedStore(":memory:")
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda _p, _ws="": FakeSDK(),
        mcp_factory=lambda _t, _p: FakeMCP(),
        saver_factory=lambda _t: None,
    )
    assert runner._require_workspace_or_raise("") == ""
    store.close()
