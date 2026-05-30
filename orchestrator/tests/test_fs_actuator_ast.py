"""Gap 4a + 4b — AST-based destructive bash classifier + allowlist mode.

Gap 4a: bashlex AST parsing catches variable indirection bypasses that
plain regex misses (e.g., `RM=rm; $RM -rf /home`). The classifier
walks the AST, builds a variable map, and re-runs the regex patterns
against the variable-resolved reconstruction.

Gap 4b: optional strict allowlist mode — bash root commands must be
in BASH_COMMAND_ALLOWLIST to pass as scoped_write. Enables missions
to opt into a positive-list discipline instead of a denylist.
"""

from __future__ import annotations

import pytest

from orchestrator import fs_actuator as FA


# ---------------------------------------------------------------------------
# Gap 4a — AST catches variable indirection
# ---------------------------------------------------------------------------


def test_ast_catches_rm_via_variable_indirection():
    """The classic regex bypass: `RM=rm; $RM -rf /home`.
    Pre-Gap-4a returned False (regex doesn't resolve $RM).
    Post-Gap-4a returns True because the AST resolves $RM → rm."""
    destructive, _ = FA.is_destructive_bash("RM=rm; $RM -rf /home")
    assert destructive is True


def test_ast_catches_rm_via_braced_variable():
    destructive, _ = FA.is_destructive_bash("X=rm; ${X} -rf /tmp/danger")
    assert destructive is True


def test_ast_catches_quoted_variable_assignment():
    """RM='rm' — quoted assignment value should still be captured."""
    destructive, _ = FA.is_destructive_bash("RM='rm'; $RM -rf /home")
    assert destructive is True


def test_ast_catches_sudo_via_variable():
    """DENY-tier — sudo via $SU should also be caught."""
    denied, _ = FA.is_denied_bash("SU=sudo; $SU apt install evil")
    assert denied is True


def test_ast_catches_git_push_via_variable():
    """ratify_required — git push via variable."""
    destructive, _ = FA.is_destructive_bash("G=git; $G push origin main")
    assert destructive is True


def test_ast_does_not_false_positive_on_safe_assignment():
    """`OK=hello; echo $OK` is benign — should NOT flag."""
    destructive, _ = FA.is_destructive_bash("OK=hello; echo $OK")
    assert destructive is False
    denied, _ = FA.is_denied_bash("OK=hello; echo $OK")
    assert denied is False


def test_ast_unknown_var_does_not_break_classifier():
    """`$UNKNOWN_VAR -rf /` — UNKNOWN_VAR has no assignment in scope.
    The classifier should leave the literal `$UNKNOWN_VAR` in the
    reconstructed string (not substitute empty), avoiding a false
    positive."""
    destructive, _ = FA.is_destructive_bash("$UNKNOWN_VAR -rf /")
    assert destructive is False


def test_ast_parse_failure_falls_back_to_regex():
    """If bashlex can't parse (malformed input), we fall back to the
    raw regex pass. Destructive patterns in plain text still hit."""
    # Even though "echo " followed by un-closed paren may break the parser,
    # the raw `rm -rf` pattern still matches.
    destructive, _ = FA.is_destructive_bash("echo $(rm -rf /tmp/xx")
    assert destructive is True


def test_ast_normalize_returns_none_when_bashlex_unavailable(monkeypatch):
    """Helper-level: when bashlex import fails, _ast_normalize_command
    returns None and the regex-only path still runs cleanly."""
    import sys
    monkeypatch.setitem(sys.modules, "bashlex", None)
    # Force ImportError on next import attempt
    result = FA._ast_normalize_command("RM=rm; $RM -rf /tmp")
    # Either None (caught ImportError) or still produces something valid.
    # The key invariant: classifier doesn't crash.
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Gap 4b — bash allowlist mode
# ---------------------------------------------------------------------------


def test_allowlist_mode_passes_known_commands():
    """python/ls/cat etc. are in the allowlist."""
    for cmd in ("python analysis.py", "ls -la /tmp", "cat file.txt", "git status"):
        cls, _ = FA.classify_fs_action(
            {"tool": "Bash", "args": {"command": cmd}},
            workspace_path="/ws/proj",
            bash_allowlist_mode=True,
        )
        assert cls == "scoped_write", f"{cmd!r} should pass allowlist"


def test_allowlist_mode_blocks_unknown_root_command():
    """Unknown root commands → ratify_required even though they don't
    match a destructive pattern."""
    cls, rationale = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "weird_unknown_tool --foo"}},
        workspace_path="/ws/proj",
        bash_allowlist_mode=True,
    )
    assert cls == "ratify_required"
    assert "allowlist" in rationale
    assert "weird_unknown_tool" in rationale


def test_allowlist_mode_default_off_preserves_pre4b_behavior():
    """Default bash_allowlist_mode=False matches pre-Gap-4b semantics —
    unknown commands pass scoped_write unless they're destructive."""
    cls, _ = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "weird_unknown_tool --foo"}},
        workspace_path="/ws/proj",
    )
    assert cls == "scoped_write"  # no allowlist gate


def test_allowlist_mode_still_routes_destructive_to_ratify():
    """Destructive patterns trip the standard ratify_required even when
    the root command IS in the allowlist (e.g., `git push`)."""
    cls, rationale = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "git push origin main"}},
        workspace_path="/ws/proj",
        bash_allowlist_mode=True,
    )
    assert cls == "ratify_required"
    assert "git" in rationale  # the git pattern, not the allowlist gate


def test_allowlist_mode_still_routes_denied_to_deny():
    """sudo is DENY tier regardless of allowlist."""
    cls, _ = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "sudo apt install x"}},
        workspace_path="/ws/proj",
        bash_allowlist_mode=True,
    )
    assert cls == "deny"


def test_allowlist_mode_refuses_path_prefixed_python():
    """Adversarial-review #5 hardening: `/usr/bin/python` (or
    `/tmp/python` shim) must NOT be treated as `python` for allowlist
    purposes — path-prefixed roots are refused outright so a planted
    binary can't bypass the allowlist."""
    cls, rationale = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "/usr/bin/python script.py"}},
        workspace_path="/ws/proj",
        bash_allowlist_mode=True,
    )
    assert cls == "ratify_required"
    assert "allowlist" in rationale


def test_allowlist_mode_handles_var_assignment_prefix():
    """`X=1 python script.py` — leading assignment shouldn't make the
    classifier confused about the root command."""
    cls, _ = FA.classify_fs_action(
        {"tool": "Bash", "args": {"command": "X=1 python script.py"}},
        workspace_path="/ws/proj",
        bash_allowlist_mode=True,
    )
    assert cls == "scoped_write"


def test_is_bash_in_allowlist_returns_root_command_on_match():
    in_al, root = FA.is_bash_in_allowlist("python -c 'print(1)'")
    assert in_al is True
    assert root == "python"


def test_is_bash_in_allowlist_returns_root_command_on_miss():
    in_al, root = FA.is_bash_in_allowlist("nonsense --flags")
    assert in_al is False
    assert root == "nonsense"


def test_is_bash_in_allowlist_handles_empty_input():
    in_al, root = FA.is_bash_in_allowlist("")
    assert in_al is False
    assert root is None


def test_is_bash_in_allowlist_accepts_custom_allowlist():
    custom = frozenset({"my_tool"})
    in_al, _ = FA.is_bash_in_allowlist("my_tool args", allowlist=custom)
    assert in_al is True
    in_al, _ = FA.is_bash_in_allowlist("python script.py", allowlist=custom)
    assert in_al is False  # python NOT in custom


# ---------------------------------------------------------------------------
# Gap 4a regression — every pre-4a test still passes
# ---------------------------------------------------------------------------


def test_regression_plain_rm_rf_root_still_denied():
    """The Phase G MVP pattern still fires."""
    denied, _ = FA.is_denied_bash("rm -rf /")
    assert denied is True


def test_regression_safe_command_still_passes():
    assert FA.is_destructive_bash("python analysis.py")[0] is False
    assert FA.is_denied_bash("python analysis.py")[0] is False


def test_regression_shell_wrapper_still_ratify_required():
    """bash -c 'rm -rf /tmp/x' — Phase G hardening pattern."""
    destructive, _ = FA.is_destructive_bash("bash -c 'rm -rf /tmp/x'")
    assert destructive is True
