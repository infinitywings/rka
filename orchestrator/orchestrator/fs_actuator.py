"""Phase G — FS Actuator policy module.

The Executor subprocess holds raw Bash/Write/Edit tools so it can do
mission work in the PI's mounted workspace. That's fine for scoped,
recoverable mutations (writing a result CSV, editing a code probe,
running a `python -c "..."` analysis). It's NOT fine for destructive
operations (rm -rf, git push, npm publish, sudo …) or mutations that
escape `{workspace_path}`.

This module provides:

  - `FS_ACTUATOR_MUTATING_TOOLS` — the FS tools that produce side
    effects in the host workspace
  - `FS_ACTUATOR_READ_TOOLS` — the FS tools that only read (never need
    ratification)
  - `classify_fs_action(action)` — return one of:
        "read"             — pure observation; auto-allow
        "scoped_write"     — write/edit/bash inside workspace_path;
                             auto-allow (Phase G default)
        "ratify_required"  — destructive bash, escape of workspace,
                             or unsafe pattern; LLM MUST defer to PI
                             via state["proposed_fs_actions"]
        "deny"             — explicit refusal: no PI override
                             available (e.g., `rm -rf /`, sudo)
  - `is_destructive_bash(cmd)` / `is_workspace_escape(path)` helpers
    used by classify_fs_action

Phase G MVP (this commit): the classifier + policy is the load-bearing
contribution. The graph wiring that actually intercepts FS-tool calls
and reroutes destructive ones into `state["proposed_fs_actions"]` is
deferred to Phase G2 (requires SDK-side hook plumbing). For now the
classifier lives here and the Brain/Executor prompts (orchestrator/
nodes/brain.py + executor.py) instruct the LLMs to *self-classify*
each FS action and defer ratify_required ones via the
proposed_fs_actions JSON block.

When Phase G2 lands, the SDK hook will call `classify_fs_action` on
every Bash/Write/Edit invocation and short-circuit ratify_required
ones into a pending interrupt. Until then, the LLM is the enforcement
point — which is why the policy MUST also live in the system prompts.

ADVERSARIAL-REVIEW DISCLAIMER: regex-on-source-text is fundamentally
weak. Forms NOT caught by these patterns include:
  - variable indirection: `RM=rm; $RM -rf /home`
  - subshell / command substitution: `$(echo rm -rf /)`
  - Python invocations: `python -c "import shutil; shutil.rmtree('/')"`
  - perl/ruby one-liners with FS-mutating side effects
  - inline heredocs piped into shell
  - `xargs` with destructive subcommands
  - encoded payloads decoded at runtime (base64, etc.)
These bypasses are accepted in Phase G MVP because the LLM-level
self-classification is the primary boundary; Phase G2's SDK hook will
add a second boundary by actually intercepting tool calls. Defense in
depth, not perfect pattern matching, is the design.
"""

from __future__ import annotations

import os.path
import re
from typing import Literal

FS_ACTUATOR_MUTATING_TOOLS: tuple[str, ...] = ("Bash", "Write", "Edit")
FS_ACTUATOR_READ_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob")

FSClassification = Literal["read", "scoped_write", "ratify_required", "deny"]


# Patterns the classifier treats as DENY regardless of workspace scope —
# these have no legitimate use case from an unsupervised subprocess.
_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""\brm\s+-rf\s+/(?:\s|$|["';])"""),  # rm -rf /
    re.compile(r"""\brm\s+-rf\s+\$HOME(?:\s|$|["';])"""),  # rm -rf $HOME
    re.compile(r"""\brm\s+-rf\s+~(?:\s|/|$|["';])"""),  # rm -rf ~ or ~/
    re.compile(r"\bsudo\b"),  # any sudo
    re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b"),  # world-writable
    re.compile(r":\(\)\s*\{.*:&\s*\};:"),  # classic fork-bomb signature
    re.compile(r"\bmkfs\.\w+"),  # filesystem format
    re.compile(r"\bdd\b.*of=/dev/"),  # raw device write
    re.compile(r">\s*/dev/sd[a-z]\b"),  # raw disk redirect
    re.compile(r"\bcurl\b.*\|\s*(sh|bash|zsh)\b"),  # curl | sh
    re.compile(r"\bwget\b.*\|\s*(sh|bash|zsh)\b"),  # wget | sh
)


# Patterns that demand PI ratification but aren't outright denied.
_RATIFY_BASH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-rf\b"),  # any rm -rf
    re.compile(r"\bfind\b[^|;&\n]*-delete\b"),  # find ... -delete
    re.compile(r"\b(?:bash|sh|zsh)\s+-c\b"),  # shell wrappers (defer ratify)
    re.compile(r"\beval\s"),  # eval wrapper
    re.compile(r"\btee\b[^|;&\n]*/etc/"),  # tee under /etc
    re.compile(r"\bmv\b[^|;&\n]*\s+/etc/"),  # mv to /etc
    re.compile(r"\bcp\b[^|;&\n]*\s+/etc/"),  # cp to /etc
    re.compile(r"\bgit\s+push\b"),  # publish to remote
    re.compile(r"\bgit\s+(reset|clean)\s+(--hard|-f)"),  # destructive git
    re.compile(r"\bgit\s+(rebase|merge)\b"),  # history mutations
    re.compile(r"\bnpm\s+(publish|unpublish)\b"),  # registry publish
    re.compile(r"\bpip\s+install\b.*--system\b"),  # system pip install
    re.compile(r"\bdocker\s+(rmi|system\s+prune|volume\s+rm)\b"),  # destructive docker
    re.compile(r"\bdocker\s+push\b"),  # registry publish
    re.compile(r"\bkubectl\s+delete\b"),  # cluster mutation
    re.compile(r"\bterraform\s+(apply|destroy)\b"),  # infra mutation
    re.compile(r"\bgcloud\b[^|;&\n]*\bdelete\b"),  # cloud delete
    re.compile(r"\baws\b[^|;&\n]*\bdelete\b"),  # cloud delete
    re.compile(r"\bsystemctl\s+(stop|disable|mask)\b"),  # service mutation
    re.compile(r"\bcrontab\s+-r\b"),  # cron wipe
    re.compile(r">\s*/etc/"),  # write under /etc
)


def is_destructive_bash(cmd: str) -> tuple[bool, str | None]:
    """Return `(matched, pattern_str)` if `cmd` contains a destructive
    pattern that requires PI ratification. The second element is the
    pattern string (for error messages); `None` when no match."""
    if not isinstance(cmd, str):
        return (False, None)
    for pat in _RATIFY_BASH_PATTERNS:
        if pat.search(cmd):
            return (True, pat.pattern)
    return (False, None)


def is_denied_bash(cmd: str) -> tuple[bool, str | None]:
    """Return `(matched, pattern_str)` if `cmd` matches a DENY pattern
    (no PI override available — these are outright refused)."""
    if not isinstance(cmd, str):
        return (False, None)
    for pat in _DENY_PATTERNS:
        if pat.search(cmd):
            return (True, pat.pattern)
    return (False, None)


def is_workspace_escape(path: str, workspace_path: str) -> bool:
    """Return True if `path` resolves outside `workspace_path`.

    Both args are treated as absolute strings; relative paths and `~`
    are NOT pre-expanded here (the SDK normalizes paths before the
    hook fires, and per Phase D2.1 we've forbidden tilde paths at the
    onboarding interrupt). Trailing slashes are normalized.

    Phase G adversarial-review hardening: normalize with `os.path.normpath`
    BEFORE prefix-matching so `/ws/proj/../etc/passwd` is detected as an
    escape (without normalization, simple prefix-matching would accept
    it). Normpath collapses `..` and `.` segments deterministically.
    Tilde and env-var expansion are NOT performed here; callers must
    pass absolute paths (caller-side concern enforced upstream).
    """
    if not path or not workspace_path:
        return False
    p = os.path.normpath(path).rstrip("/") or "/"
    w = os.path.normpath(workspace_path).rstrip("/") or "/"
    # Identity is allowed (path == workspace_path itself).
    if p == w:
        return False
    # Path is inside workspace iff it starts with workspace_path + "/"
    return not p.startswith(w + "/")


def classify_fs_action(
    action: dict,
    *,
    workspace_path: str = "",
) -> tuple[FSClassification, str]:
    """Classify an FS tool invocation.

    Args:
      action: `{"tool": "Bash" | "Write" | "Edit" | "Read" | "Grep" |
                       "Glob",
                "args": {...}}`
      workspace_path: the PI's mounted workspace root for this run.
                      If empty, escape-detection is skipped (treat
                      every write as scoped — used in tests).

    Returns `(classification, rationale)`. Rationale is a one-line
    human-readable reason callers can surface on the proposed_fs_actions
    interrupt payload or error log.
    """
    if not isinstance(action, dict):
        return ("deny", "action is not a dict")
    tool = action.get("tool", "")
    args = action.get("args", {}) or {}

    if tool in FS_ACTUATOR_READ_TOOLS:
        return ("read", f"{tool} is read-only")

    if tool not in FS_ACTUATOR_MUTATING_TOOLS:
        return ("deny", f"unknown FS tool {tool!r}")

    # Bash — string-match destructive patterns first.
    if tool == "Bash":
        cmd = args.get("command", "") or ""
        denied, dpat = is_denied_bash(cmd)
        if denied:
            return ("deny", f"bash matches DENY pattern: {dpat}")
        destructive, rpat = is_destructive_bash(cmd)
        if destructive:
            return ("ratify_required", f"bash matches ratify pattern: {rpat}")
        # No destructive pattern. Treat as scoped — the subprocess can
        # only mutate paths the OS lets it touch, and writes outside
        # workspace_path would only matter for explicit Write/Edit.
        return ("scoped_write", "bash invocation: no destructive pattern matched")

    # Write / Edit — check workspace escape.
    if tool in ("Write", "Edit"):
        target = args.get("file_path") or args.get("path") or ""
        if workspace_path and is_workspace_escape(target, workspace_path):
            return (
                "ratify_required",
                f"{tool} target {target!r} escapes workspace_path={workspace_path!r}",
            )
        return ("scoped_write", f"{tool} target inside workspace_path")

    return ("deny", f"unhandled tool {tool!r}")
