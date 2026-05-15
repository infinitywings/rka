"""T11 invariants: grep-gate + audit-symmetry.

These tests formalize the discipline floor the Backbrief committed to:

  - **grep-gate** — orchestrator/ contains zero `from rka.*` / `import rka.*`
  - **audit-symmetry** — node `current_node` writes match NODE_NAMES, and
    state-write keys match the ResearchWorkflowState schema
"""

from __future__ import annotations

import ast
import re
import sys
import typing
from pathlib import Path

import pytest

from orchestrator import graph
from orchestrator.state import ResearchWorkflowState

ORCHESTRATOR_DIR = Path(__file__).resolve().parent.parent / "orchestrator"
NODE_DIR = ORCHESTRATOR_DIR / "nodes"


# ---------------------------------------------------------------------------
# grep-gate — zero rka.* imports from orchestrator/
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        # macOS / FuSpace AppleDouble metadata files match the .py glob
        # but are binary; the read in callers fails on these. Skip.
        if p.name.startswith("._"):
            continue
        yield p


def test_grep_gate_no_rka_imports_in_orchestrator_package():
    bad = []
    pattern = re.compile(r"^\s*(from\s+rka(\s|\.)|import\s+rka(\s|\.))")
    for path in _iter_python_files(ORCHESTRATOR_DIR):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.match(line):
                bad.append(f"{path.relative_to(ORCHESTRATOR_DIR.parent)}:{lineno}: {line.strip()}")
    assert not bad, (
        "grep-gate violation: orchestrator/ must not import from rka.*\n"
        + "\n".join(bad)
    )


def test_grep_gate_skips_test_directory():
    # The test directory is intentionally allowed to reference `rka` (e.g.,
    # to set up RKA-side conditions in future integration tests). Verify
    # the gate doesn't catch us out by scanning tests/.
    tests_dir = ORCHESTRATOR_DIR.parent / "tests"
    # Note: this loop is allowed to find rka imports in tests/; the test
    # simply documents that they're not policed by the gate.
    found_count = 0
    pattern = re.compile(r"^\s*(from\s+rka(\s|\.)|import\s+rka(\s|\.))")
    for path in _iter_python_files(tests_dir):
        for line in path.read_text().splitlines():
            if pattern.match(line):
                found_count += 1
    # Right now: zero rka imports in tests too. Don't lock this — but
    # do document the gate's scope.
    assert found_count == 0  # currently clean; tighten if we ever add legitimate uses


# ---------------------------------------------------------------------------
# audit-symmetry — NODE_NAMES, current_node writes, state schema
# ---------------------------------------------------------------------------


def _current_node_string_literals(tree: ast.AST) -> set[str]:
    """Pull every literal string assigned to the key 'current_node' in a dict."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "current_node":
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        if value.value:  # skip empty-string initialization
                            out.add(value.value)
    return out


def test_audit_symmetry_current_node_writes_match_node_names():
    declared = set(graph.NODE_NAMES)
    found = set()
    for path in NODE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        found |= _current_node_string_literals(tree)

    # Every string written into current_node should be one of the canonical 15.
    extra = found - declared
    assert not extra, (
        "audit-symmetry violation: node files write current_node values "
        "that are not in graph.NODE_NAMES:\n  " + ", ".join(sorted(extra))
    )

    # And every canonical name should have at least one node that writes it.
    # (catches a renamed node whose function name drifted from its label).
    missing = declared - found
    assert not missing, (
        "audit-symmetry violation: no node assigns current_node to:\n  "
        + ", ".join(sorted(missing))
    )


def test_node_names_match_compiled_graph_registration():
    # The compiled graph should register every name in NODE_NAMES.
    pytest.importorskip("langgraph")

    from tests._fakes import FakeMCP, FakeSDK  # local import to keep top tidy

    def _stub_interrupt(payload):
        return "approve"

    g = graph.build_graph(
        sdk=FakeSDK(), mcp=FakeMCP(), interrupt_fn=_stub_interrupt
    )
    registered = set(g.get_graph().nodes.keys())
    for name in graph.NODE_NAMES:
        assert name in registered, f"NODE_NAMES says {name!r} but graph did not register it"


# ---------------------------------------------------------------------------
# State-schema symmetry — every state-write key is declared in the TypedDict
# ---------------------------------------------------------------------------


_NODE_FN_NAMES = set(graph.NODE_NAMES)


def _state_write_keys(tree: ast.AST) -> set[str]:
    """Every key written into a top-level node's outer return dict.

    Limits the walk to function bodies whose name matches one of the
    canonical 15 (NODE_NAMES). Helper functions (`_artifact`, `_error`,
    etc.) return sub-records (ArtifactRef, ErrorRecord) whose keys are
    NOT meant to land in the top-level state schema — those would
    register false positives if we walked the whole module.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _NODE_FN_NAMES:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                    for key in inner.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            out.add(key.value)
    return out


def test_audit_symmetry_state_writes_match_schema_keys():
    declared = set(typing.get_type_hints(ResearchWorkflowState).keys())
    found = set()
    for path in NODE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        found |= _state_write_keys(tree)
    # Drop the few keys that nodes legitimately write but route-helpers
    # interpret separately (none in Phase 1 — current state).
    extra = found - declared
    assert not extra, (
        "audit-symmetry violation: nodes write state keys not in schema:\n  "
        + ", ".join(sorted(extra))
    )


# ---------------------------------------------------------------------------
# Test-count floor — Backbrief committed to ≥50 unit tests
# ---------------------------------------------------------------------------


def test_suite_meets_minimum_unit_test_floor():
    # Count test items across the orchestrator suite. ≥50 was the
    # Backbrief commitment; we land well above.
    import subprocess

    venv_py = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "python3"
    if not venv_py.exists():
        venv_py = Path(sys.executable)
    result = subprocess.run(
        [str(venv_py), "-m", "pytest", str(ORCHESTRATOR_DIR.parent), "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=str(ORCHESTRATOR_DIR.parent),
    )
    # Last "X tests collected" line.
    match = re.search(r"(\d+)\s+tests collected", result.stdout)
    assert match is not None, f"could not parse pytest collect output:\n{result.stdout[-400:]}"
    count = int(match.group(1))
    assert count >= 50, f"only {count} tests; Backbrief floor is ≥50"
