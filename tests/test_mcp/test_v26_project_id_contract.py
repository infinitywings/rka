"""v2.6 project-scoping contract regression tests.

The v2.6 BREAKING contract change (PR #32 / commit 82fe9cc /
`feat(mcp)!: require project_id on every project-scoped tool`)
made `project_id` a kwarg-only requirement on every MCP tool that
hits a project-scoped REST endpoint. Two regressions slipped through
because no contract-level test existed:

- `rka_link_literature_to_zotero` (added in commit 6e7a2d6, 2026-05-28,
  the Phase-3.4 zotero linker) was authored without the kwarg. The
  REST layer's `get_scoped_literature_service` falls back to
  `proj_default`, `LiteratureService.get(lit_id)` filters by
  `project_id='proj_default'` against literature rows owned by a real
  project, returns None, and the REST handler raises a misleading
  HTTPException(404, "Literature lit_... not found"). The PI's
  reproduction was 404 on `lit_01KSNPRCZR7...` in project
  `prj_01KSMW9RBFXRY6HRRADH3SX7ZP` despite `rka_get` + `rka_get_literature`
  retrieving it cleanly.
- `rka_session_digest` (line 3494) referred to an undefined `project_id`
  symbol inside `async with _client(project_id) as c`, NameError at
  runtime — also added without the v2.6 kwarg.

These tests close that gap so the next regression fails loudly:

1. Per-tool signature contracts — pin the kwarg-only-with-no-default
   shape for the two empirically-affected tools.
2. AST contract scan — walks every `@tool()`-decorated function in
   `rka/mcp/server.py`, finds calls to `_client(...)`, and asserts the
   call either passes a non-empty argument OR the tool is on the
   explicit `_UNSCOPED_TOOLS_ALLOWLIST`. Catches the regression shape
   automatically for any future tool addition.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from rka.mcp import server as mcp_server


# ---------------------------------------------------------------------------
# Per-tool signature contracts — the two empirically-affected regressions
# ---------------------------------------------------------------------------


def _kwarg_only_with_no_default(fn, name: str) -> tuple[bool, str]:
    """Returns (passes, reason)."""
    sig = inspect.signature(fn)
    if name not in sig.parameters:
        return (False, f"parameter {name!r} not in signature: {sig}")
    p = sig.parameters[name]
    if p.kind != inspect.Parameter.KEYWORD_ONLY:
        return (False, f"parameter {name!r} kind={p.kind.name}, expected KEYWORD_ONLY")
    if p.default is not inspect.Parameter.empty:
        return (False, f"parameter {name!r} has default={p.default!r}, expected no default")
    return (True, "ok")


def test_rka_link_literature_to_zotero_requires_project_id_kwarg():
    """Regression: commit 6e7a2d6 added rka_link_literature_to_zotero
    without the v2.6 kwarg. Without project_id the tool 404'd because
    the REST layer fell back to proj_default and LiteratureService.get
    couldn't match the literature row's real project."""
    passes, reason = _kwarg_only_with_no_default(
        mcp_server.rka_link_literature_to_zotero, "project_id"
    )
    assert passes, f"rka_link_literature_to_zotero v2.6 contract: {reason}"


def test_rka_session_digest_requires_project_id_kwarg():
    """Sibling regression to rka_link_literature_to_zotero: same
    missing-kwarg shape, but worse — referenced project_id as an
    undefined symbol inside the function body, NameError at runtime."""
    passes, reason = _kwarg_only_with_no_default(
        mcp_server.rka_session_digest, "project_id"
    )
    assert passes, f"rka_session_digest v2.6 contract: {reason}"


# ---------------------------------------------------------------------------
# AST contract scan — catches the next regression of this shape automatically
# ---------------------------------------------------------------------------


# Tools that are LEGITIMATELY unscoped (operate across or before any project).
# Every other @tool()-decorated function that calls _client() must thread a
# non-empty argument to _client(...).
_UNSCOPED_TOOLS_ALLOWLIST: frozenset[str] = frozenset({
    # Cross-project read — lists projects to choose from.
    "rka_list_projects",
    # Project-creation tool — no project_id YET (creates one).
    "rka_create_project",
    # Deprecated no-op in v2.6+ — preserved for backwards-compat error message.
    "rka_set_project",
    # Global changelog read — not project-scoped at the REST layer.
    "rka_get_changelog",
    # v2.7.0-alpha — unscoped meta verb. Dispatches between scoped and
    # unscoped actions internally: list_projects/create_project/set_project/
    # reset/health/help are unscoped; digest/export/generate_claude_md
    # explicitly check + require project_id at the per-action handler. The
    # function signature reflects this with `project_id: str | None = None`.
    "rka_session",
    # v2.7.0a3 — rka_query dispatches between scoped (most reads) and
    # unscoped (list_projects, health) operations. The signature is
    # `project_id: str | None = None` and the body raises a structured
    # error when project_id is missing on a scoped operation. The
    # unscoped operations call `_client()` with no argument.
    "rka_query",
    # v2.7.0a3 — rka_describe is fully UNSCOPED (no project_id at all);
    # it returns operation schemas without touching any REST endpoint.
    "rka_describe",
})


def _walk_at_tool_functions():
    """Yield (name, ast_node) for every @tool()-decorated function in
    rka/mcp/server.py."""
    src = Path(mcp_server.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        is_tool = any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Name)
            and d.func.id == "tool"
            for d in node.decorator_list
        )
        if is_tool:
            yield node.name, node


def _client_calls(node: ast.AST):
    """Yield every `_client(...)` Call node inside the given function."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "_client"
        ):
            yield sub


def test_every_scoped_tool_threads_project_id_to_client():
    """Contract scan: every @tool()-decorated function in
    rka/mcp/server.py that calls _client(...) MUST pass a non-empty
    argument (the v2.6 project-scoping contract) UNLESS the function
    name is on the _UNSCOPED_TOOLS_ALLOWLIST. This is the test the
    workflow recommended as the primary recurrence-prevention surface:
    the next time someone adds a new @tool() with `_client()` no-arg,
    this test fails loudly at PR time rather than the bug shipping
    to production.

    Empirical: this test would have caught BOTH the
    rka_link_literature_to_zotero AND rka_session_digest regressions
    without any per-tool changes."""
    violations: list[str] = []
    for name, node in _walk_at_tool_functions():
        for call in _client_calls(node):
            arity = len(call.args) + len(call.keywords)
            if arity == 0 and name not in _UNSCOPED_TOOLS_ALLOWLIST:
                violations.append(
                    f"{name} (line {call.lineno}): _client() called with "
                    f"no argument. Add `*, project_id: str` to the function "
                    f"signature and pass `_client(project_id)`, OR if this "
                    f"tool is legitimately unscoped add it to "
                    f"_UNSCOPED_TOOLS_ALLOWLIST in this test."
                )
    assert not violations, (
        "v2.6 project-scoping contract violation(s):\n  "
        + "\n  ".join(violations)
    )


def test_every_scoped_tool_declares_project_id_kwarg():
    """Companion contract: not only must scoped tools pass project_id
    to _client, they must also DECLARE project_id as a kwarg-only
    parameter in their signature (so callers can't omit it). Same
    allowlist for legitimately-unscoped tools."""
    violations: list[str] = []
    for name, node in _walk_at_tool_functions():
        # Only check tools that call _client (the project-scoping signal).
        calls_client = any(True for _ in _client_calls(node))
        if not calls_client:
            continue
        if name in _UNSCOPED_TOOLS_ALLOWLIST:
            continue
        # Look up the real function so we get the resolved signature
        # (with decorators applied — kw-only args still surface).
        fn = getattr(mcp_server, name, None)
        if fn is None:
            continue
        sig = inspect.signature(fn)
        if "project_id" not in sig.parameters:
            violations.append(
                f"{name}: signature does not declare `project_id` parameter"
            )
            continue
        p = sig.parameters["project_id"]
        if p.kind != inspect.Parameter.KEYWORD_ONLY:
            violations.append(
                f"{name}: project_id is {p.kind.name}, expected KEYWORD_ONLY"
            )
    assert not violations, (
        "v2.6 project-scoping signature contract violation(s):\n  "
        + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# Allowlist hygiene — keep the unscoped list honest
# ---------------------------------------------------------------------------


def test_unscoped_allowlist_only_contains_real_tools():
    """Sanity: every name in _UNSCOPED_TOOLS_ALLOWLIST must correspond
    to a real @tool()-decorated function in rka/mcp/server.py. If
    someone renames or removes one of these tools without updating
    the allowlist, the next regression scan would silently exempt a
    non-existent tool."""
    declared = {name for name, _ in _walk_at_tool_functions()}
    stale = _UNSCOPED_TOOLS_ALLOWLIST - declared
    assert not stale, (
        f"_UNSCOPED_TOOLS_ALLOWLIST contains names that are no longer "
        f"@tool() functions: {sorted(stale)}"
    )
