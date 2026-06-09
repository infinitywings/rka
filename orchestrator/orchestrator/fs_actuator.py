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


# --- Order-independent `rm` recursive+force detection (v0.6.11) ---
# The literal `rm\s+-rf` regex in _DENY/_RATIFY only matched that exact
# spelling, so `rm -fr`, `rm -Rf`, `rm -r -f`, `rm -rfv`, and
# `rm --recursive --force` slipped through BOTH tiers and auto-executed.
# This parser collects flags from every rm invocation regardless of order
# or grouping and reports whether it is recursive AND force, plus its
# non-flag target tokens.
_RM_SENSITIVE_TARGETS = ("/", "~", "$HOME", "${HOME}")


def _rm_recursive_force_targets(cmd: str) -> tuple[bool, list[str]]:
    """For the first recursive+force `rm` invocation in `cmd`, return
    `(True, target_tokens)`. Returns `(False, [])` if no rm invocation
    combines a recursive flag (-r/-R/--recursive) with a force flag
    (-f/--force)."""
    for m in re.finditer(r"\brm\b([^\n;&|]*)", cmd):
        recursive = force = False
        targets: list[str] = []
        for tok in m.group(1).split():
            if tok == "--recursive":
                recursive = True
            elif tok == "--force":
                force = True
            elif tok == "--":
                continue
            elif tok.startswith("--"):
                continue  # some other long flag
            elif re.fullmatch(r"-[A-Za-z]+", tok):
                chars = set(tok[1:])
                if chars & {"r", "R"}:
                    recursive = True
                if "f" in chars:
                    force = True
            else:
                targets.append(tok)
        if recursive and force:
            return (True, targets)
    return (False, [])


def _rm_targets_sensitive(targets: list[str]) -> bool:
    """True if any rm target is a host-root / $HOME / `~` (the DENY-tier
    catastrophe roots), in any of their common spellings."""
    for t in targets:
        t = t.strip().strip("\"'")
        if t in _RM_SENSITIVE_TARGETS:
            return True
        if t.startswith(("~/", "$HOME/", "${HOME}/")):
            return True
    return False


def is_destructive_bash(cmd: str) -> tuple[bool, str | None]:
    """Return `(matched, pattern_str)` if `cmd` contains a destructive
    pattern that requires PI ratification. The second element is the
    pattern string (for error messages); `None` when no match.

    Gap 4a — runs the AST-aware classifier first. If the AST detects a
    bypass (variable-resolved `$RM` → `rm -rf …`), reconstructs a
    normalized command string and applies the regex patterns against
    THAT. Falls back to direct regex on parse failure.

    v0.6.11 — any recursive+force `rm` (in any flag order/grouping)
    requires ratification, not just the literal `rm -rf`.
    """
    if not isinstance(cmd, str):
        return (False, None)
    # Try AST first; on success, also run regex against the
    # variable-resolved reconstruction so $RM-style indirection is caught.
    ast_normalized = _ast_normalize_command(cmd)
    for candidate in (cmd, ast_normalized):
        if candidate is None:
            continue
        rf, _targets = _rm_recursive_force_targets(candidate)
        if rf:
            return (True, "rm recursive+force (any flag order)")
        for pat in _RATIFY_BASH_PATTERNS:
            if pat.search(candidate):
                return (True, pat.pattern)
    return (False, None)


def is_denied_bash(cmd: str) -> tuple[bool, str | None]:
    """Return `(matched, pattern_str)` if `cmd` matches a DENY pattern
    (no PI override available — these are outright refused).

    Gap 4a — AST-aware: variable-resolved forms are matched too.

    v0.6.11 — a recursive+force `rm` targeting `/`, `$HOME`, or `~`
    (in any flag order/grouping) is DENY-tier, matching the original
    `rm -rf /` intent but order-independent.
    """
    if not isinstance(cmd, str):
        return (False, None)
    ast_normalized = _ast_normalize_command(cmd)
    for candidate in (cmd, ast_normalized):
        if candidate is None:
            continue
        rf, targets = _rm_recursive_force_targets(candidate)
        if rf and _rm_targets_sensitive(targets):
            return (True, "rm recursive+force on host-root/$HOME/~ (any flag order)")
        for pat in _DENY_PATTERNS:
            if pat.search(candidate):
                return (True, pat.pattern)
    return (False, None)


# Gap 4a — AST normalization.
# Walks bashlex's parse tree, builds a `{var: value}` map from
# AssignmentNode entries, and emits a "normalized" command string where
# `$VAR` / `${VAR}` references inside word tokens are replaced with
# their assigned values. The replacement is intentionally simple: we
# don't model dynamic scope, function definitions, or command
# substitution semantics — just the common assign-then-use pattern
# that regex misses.


def _ast_normalize_command(cmd: str) -> str | None:
    """Return a regex-checkable normalization of `cmd` that resolves
    `$VAR` references using same-script assignments. Returns None when
    parsing fails entirely (callers should treat as "no AST signal"
    and rely on the raw regex pass).

    Adversarial-review #4: bashlex fails on `arr=(a b)` and other
    array/bash-only syntax. When the AST parse fails, fall back to a
    regex-based assignment extractor that catches the simple
    `VAR=value` shape and substitutes `$VAR` references. Catches the
    `arr[0]=rm; ${arr[0]} -rf` bypass and the `RM=rm; eval $RM -rf`
    pattern in the AST-parse-failure path.
    """
    try:
        import bashlex  # local import — only loaded when needed
    except ImportError:
        return _regex_assignment_normalize(cmd)
    try:
        trees = bashlex.parse(cmd)
    except Exception:  # noqa: BLE001 — bashlex raises a custom exception hierarchy
        return _regex_assignment_normalize(cmd)

    var_map: dict[str, str] = {}
    parts: list[str] = []
    for tree in trees:
        _ast_walk_collect(tree, var_map, parts)
    if not parts:
        return _regex_assignment_normalize(cmd)
    return " ; ".join(parts)


_ASSIGNMENT_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s;|&]+))"
)
_VAR_REF_RE = re.compile(
    r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]*\])?\}?"
)


def _regex_assignment_normalize(cmd: str) -> str | None:
    """Adversarial-review #4 fallback: when bashlex can't parse, extract
    `VAR=value` assignments via regex and substitute `$VAR` /
    `${VAR}` / `${VAR[0]}` references. Best-effort — won't catch every
    indirection form but does catch the simple assign-then-use case
    that the AST would otherwise have handled."""
    if not cmd or not isinstance(cmd, str):
        return None
    var_map: dict[str, str] = {}
    for m in _ASSIGNMENT_RE.finditer(cmd):
        name = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4) or ""
        var_map[name] = value
    if not var_map:
        # No assignments found — nothing meaningful to normalize beyond
        # the raw cmd. Return None so the caller's regex pass handles it.
        return None

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        return var_map.get(name, m.group(0))

    return _VAR_REF_RE.sub(_sub, cmd)


def _ast_walk_collect(
    node, var_map: dict[str, str], out_parts: list[str]
) -> None:
    """Recursive walk: capture assignments, resolve references, emit
    each top-level command as a space-joined word string into
    out_parts."""
    kind = getattr(node, "kind", "")
    if kind == "command":
        _ast_emit_command(node, var_map, out_parts)
        return
    if kind == "list":
        for child in getattr(node, "parts", []) or []:
            _ast_walk_collect(child, var_map, out_parts)
        return
    if kind == "compound":
        for child in getattr(node, "list", []) or []:
            _ast_walk_collect(child, var_map, out_parts)
        return
    if kind == "pipeline":
        for child in getattr(node, "parts", []) or []:
            _ast_walk_collect(child, var_map, out_parts)
        return
    # operator / function / other — recurse into parts if present
    for child in getattr(node, "parts", []) or []:
        _ast_walk_collect(child, var_map, out_parts)


def _ast_emit_command(
    cmd_node, var_map: dict[str, str], out_parts: list[str]
) -> None:
    """Process one CommandNode: capture any AssignmentNode prefix into
    var_map; resolve $VAR references in WordNodes; emit a
    space-joined string of the resolved words to out_parts.

    Adversarial-review #3: recurse into HeredocNode bodies and
    CommandsubstitutionNode children so payloads smuggled via
    `cat <<EOF ... EOF` and `$(...)` are also normalized.
    """
    words: list[str] = []
    for child in getattr(cmd_node, "parts", []) or []:
        kind = getattr(child, "kind", "")
        if kind == "assignment":
            word = getattr(child, "word", "") or ""
            if "=" in word:
                k, _, v = word.partition("=")
                # Strip simple shell quoting.
                v = v.strip()
                if (v.startswith("'") and v.endswith("'")) or (
                    v.startswith('"') and v.endswith('"')
                ):
                    v = v[1:-1]
                var_map[k.strip()] = v
            continue
        if kind in ("word", "parameter", "commandsubstitution", "processsubstitution"):
            words.append(_ast_resolve_word(child, var_map))
            # Adversarial-review #3: recurse into command-substitution
            # children so `$(RM=rm; $RM -rf /home)` is normalized too.
            # CommandsubstitutionNodes can be at the child level OR
            # nested inside a WordNode's `parts` (bashlex puts them
            # there when the word contains a $() expression).
            _recurse_into_command_subs(child, var_map, out_parts)
            continue
        # Adversarial-review #3: heredoc body — preserve its text so
        # `cat <<EOF ... rm -rf / ... EOF` still trips destructive
        # patterns on the body.
        if kind == "redirect":
            heredoc_body = getattr(child, "heredoc", None)
            if heredoc_body is not None:
                body_word = getattr(heredoc_body, "value", None)
                if isinstance(body_word, str) and body_word.strip():
                    out_parts.append(body_word)
            # Continue with raw form below so `>/etc/` still matches
        # operator/redirect/etc — preserve raw form so patterns like
        # ">/etc/" still match.
        raw_word = getattr(child, "word", None)
        if isinstance(raw_word, str):
            words.append(raw_word)
    if words:
        out_parts.append(" ".join(words))


def _recurse_into_command_subs(node, var_map: dict[str, str], out_parts: list[str]) -> None:
    """Adversarial-review #3: walk into CommandsubstitutionNode found
    anywhere in a WordNode subtree and process its embedded `command`
    (the inner ListNode/CommandNode) via _ast_walk_collect — so a
    payload like `$(RM=rm; $RM -rf /home)` lands in out_parts as a
    normalized command string."""
    kind = getattr(node, "kind", "")
    if kind == "commandsubstitution":
        inner = getattr(node, "command", None)
        if inner is not None:
            _ast_walk_collect(inner, var_map, out_parts)
        return
    for child in getattr(node, "parts", None) or []:
        _recurse_into_command_subs(child, var_map, out_parts)


def _ast_resolve_word(node, var_map: dict[str, str]) -> str:
    """Replace any ParameterNode references inside `node` with their
    assigned values. For unknown vars, leaves the literal form ($VAR)
    so downstream regex doesn't false-match on accidental substitution
    of an empty string."""
    word = getattr(node, "word", "") or ""
    # Inline parameter expansion: $VAR or ${VAR}
    if not word.startswith("$"):
        # Walk subparts to find embedded parameter refs
        parts = getattr(node, "parts", []) or []
        if not parts:
            return word
        # Reconstruct: for each part, if it's a ParameterNode with
        # known value, substitute.
        result = []
        last_end = 0
        for p in parts:
            p_kind = getattr(p, "kind", "")
            if p_kind == "parameter":
                value_name = getattr(p, "value", "")
                p_pos = getattr(p, "pos", None)
                if p_pos and isinstance(p_pos, tuple) and len(p_pos) == 2:
                    start, end = p_pos
                    # Translate absolute positions to word-relative.
                    word_start = getattr(node, "pos", (0, 0))[0]
                    rel_start = start - word_start
                    rel_end = end - word_start
                    result.append(word[last_end:rel_start])
                    result.append(var_map.get(value_name, f"${value_name}"))
                    last_end = rel_end
        result.append(word[last_end:])
        return "".join(result) or word
    # Bare $VAR / ${VAR}
    stripped = word.lstrip("$").strip("{}")
    return var_map.get(stripped, word)


# Gap 4b — Bash allowlist mode.
#
# Optional strict mode: only commands whose root binary appears in
# `BASH_COMMAND_ALLOWLIST` are scoped_write; everything else is
# ratify_required. Enabled per-workflow by setting
# `state["bash_allowlist_mode"] = True` (or globally via
# FS_ACTUATOR_BASH_ALLOWLIST_MODE=1 env). The allowlist is intentionally
# minimal — common analysis/probe commands that missions actually need.

BASH_COMMAND_ALLOWLIST: frozenset[str] = frozenset({
    # Read-side / observational
    "ls", "cat", "head", "tail", "less", "more", "wc", "stat", "file",
    "find", "grep", "rg", "ag", "fd", "tree", "du", "df",
    # Process / environment introspection
    "ps", "env", "pwd", "whoami", "id", "uname", "hostname", "uptime",
    # Python / Node / R analysis (mission probes)
    "python", "python3", "node", "deno", "Rscript", "ruby", "perl",
    # Git read ops
    "git",  # NB: git push/etc still caught by destructive-pattern; allowlist permits the binary
    # Common compute / text tools
    "echo", "printf", "true", "false", "test", "expr", "seq",
    "awk", "sed", "cut", "sort", "uniq", "tr", "tee", "diff", "patch",
    # Archive / format
    "tar", "gzip", "gunzip", "zip", "unzip", "jq", "yq",
    # Network probes (read-only)
    "curl", "wget",
    # Build / Python tooling (mostly read-side but useful)
    "pip", "uv", "poetry", "make",
})


def is_bash_in_allowlist(cmd: str, *, allowlist: frozenset[str] | None = None) -> tuple[bool, str | None]:
    """Return (True, root_cmd) if the first word of `cmd` (after AST
    parsing strips assignments) is in the allowlist. Returns
    (False, root_cmd_or_None) otherwise.

    Used by classify_fs_action when state["bash_allowlist_mode"] is
    True: bash invocations whose root binary isn't in the allowlist
    are forced to ratify_required even if they don't match any
    destructive pattern. This is the "missions only run these
    commands" strict mode.

    Adversarial-review #5: any root command whose token contains '/'
    is rejected outright (force-fail to ratify_required). Otherwise an
    LLM could drop a shim at /tmp/python and bypass the allowlist via
    `/tmp/python -c 'import shutil; shutil.rmtree(...)'`. Allowlist
    mode requires PATH-resolved binaries by name only.
    """
    al = allowlist if allowlist is not None else BASH_COMMAND_ALLOWLIST
    if not isinstance(cmd, str) or not cmd.strip():
        return (False, None)
    root_raw = _bash_root_command_raw(cmd)
    if root_raw is None:
        return (False, None)
    if "/" in root_raw:
        # Path-prefixed roots refused in strict mode — return the FULL
        # path-bearing string as `root` so the rationale reflects what
        # the LLM tried to invoke.
        return (False, root_raw)
    return (root_raw in al, root_raw)


def _bash_root_command_raw(cmd: str) -> str | None:
    """Like `_bash_root_command` but returns the raw first non-assignment
    token without path-stripping. Used by `is_bash_in_allowlist` so
    callers can detect (and refuse) path-prefixed invocations."""
    try:
        import bashlex
        trees = bashlex.parse(cmd)
    except Exception:  # noqa: BLE001
        for tok in cmd.strip().split():
            if "=" not in tok or tok.startswith(("-", "/")):
                return tok  # raw — keep path if present
        return None
    for tree in trees:
        root = _extract_root_command_raw(tree)
        if root:
            return root
    return None


def _extract_root_command_raw(node) -> str | None:
    """Like `_extract_root_command` but does NOT strip leading path."""
    kind = getattr(node, "kind", "")
    if kind == "command":
        for child in getattr(node, "parts", []) or []:
            ck = getattr(child, "kind", "")
            if ck == "assignment":
                continue
            if ck == "word":
                return getattr(child, "word", "") or ""
        return None
    for child in (
        getattr(node, "parts", None)
        or getattr(node, "list", None)
        or []
    ):
        root = _extract_root_command_raw(child)
        if root:
            return root
    return None


def _bash_root_command(cmd: str) -> str | None:
    """Extract the first command name from `cmd`, ignoring leading
    assignments. Uses AST when available; falls back to simple
    word-split."""
    try:
        import bashlex
        trees = bashlex.parse(cmd)
    except Exception:  # noqa: BLE001
        # Fallback — drop leading VAR=value tokens, take first word
        for tok in cmd.strip().split():
            if "=" not in tok or tok.startswith(("-", "/")):
                # First non-assignment token is the command.
                # Strip path: /usr/bin/ls → ls.
                return tok.rsplit("/", 1)[-1]
            # else it's an assignment; keep scanning
        return None

    for tree in trees:
        root = _extract_root_command(tree)
        if root:
            return root
    return None


def _extract_root_command(node) -> str | None:
    """Find the first CommandNode and return the root command name
    (skipping AssignmentNode prefixes)."""
    kind = getattr(node, "kind", "")
    if kind == "command":
        for child in getattr(node, "parts", []) or []:
            ck = getattr(child, "kind", "")
            if ck == "assignment":
                continue
            if ck == "word":
                word = getattr(child, "word", "") or ""
                # Strip a leading $VAR resolution: if word is just $VAR,
                # we can't statically resolve here without var_map; the
                # AST normalization already handles destructive-pattern
                # matching for that case. For allowlist purposes, an
                # unresolved $VAR root is treated as "unknown" → not
                # in allowlist → ratify_required. Conservative is correct.
                return word.rsplit("/", 1)[-1]
        return None
    # Recurse into containers
    for child in (
        getattr(node, "parts", None)
        or getattr(node, "list", None)
        or []
    ):
        root = _extract_root_command(child)
        if root:
            return root
    return None


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
    bash_allowlist_mode: bool = False,
) -> tuple[FSClassification, str]:
    """Classify an FS tool invocation.

    Args:
      action: `{"tool": "Bash" | "Write" | "Edit" | "Read" | "Grep" |
                       "Glob",
                "args": {...}}`
      workspace_path: the PI's mounted workspace root for this run.
                      If empty, escape-detection is skipped (treat
                      every write as scoped — used in tests).
      bash_allowlist_mode: Gap 4b — when True, only Bash commands
                      whose root binary is in BASH_COMMAND_ALLOWLIST
                      pass as scoped_write; everything else is
                      ratify_required even if it doesn't match a
                      destructive pattern. Strict mode for missions
                      that don't need shell exotica.

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
        # Gap 4b — strict allowlist mode. Only mission-approved root
        # commands pass as scoped_write; everything else needs PI
        # ratification regardless of destructive-pattern hits.
        if bash_allowlist_mode:
            in_allowlist, root = is_bash_in_allowlist(cmd)
            if not in_allowlist:
                return (
                    "ratify_required",
                    f"bash allowlist mode: root command {root!r} not in "
                    f"BASH_COMMAND_ALLOWLIST",
                )
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
