"""Drift test: orchestrator enum mirror vs RKA's canonical Literal source.

Makes the hand-maintained mirror in rka_enums.py a CI-enforced contract
against rka/mcp/_enums.py. Reads the RKA source by FILE PATH (no import rka),
so it stays inside the grep-gate. Skips gracefully when the RKA source tree
is absent (orchestrator-only install).

See orchestrator/scripts/rka_enum_drift.py for the comparison logic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_DRIFT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "rka_enum_drift.py"
_spec = importlib.util.spec_from_file_location("rka_enum_drift", _DRIFT_PATH)
drift_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift_mod)


def test_rka_enum_mirror_in_sync_with_rka_source():
    if drift_mod.find_rka_enums_source() is None:
        pytest.skip("rka/mcp/_enums.py not present (orchestrator-only install)")
    drift = drift_mod.compute_drift()
    assert drift == [], (
        "orchestrator/orchestrator/rka_enums.py has drifted from "
        "rka/mcp/_enums.py. Run `python orchestrator/scripts/rka_enum_drift.py` "
        "and update the named frozenset(s):\n" + "\n".join(drift))


def test_every_equality_pair_resolves_on_both_sides():
    # Guards the mapping table itself: a typo'd Literal/frozenset name would
    # otherwise make the drift check silently vacuous.
    if drift_mod.find_rka_enums_source() is None:
        pytest.skip("rka/mcp/_enums.py not present")
    canonical = drift_mod.extract_literals(drift_mod.find_rka_enums_source())
    from orchestrator import rka_enums
    for lit_name, fs_name in drift_mod.EQUALITY_MAP.items():
        assert lit_name in canonical, f"{lit_name} not found in rka/mcp/_enums.py"
        assert hasattr(rka_enums, fs_name), f"rka_enums.{fs_name} missing"


def test_extractor_parses_literal_forms():
    # Sanity-check the AST extractor against both tuple and single-element
    # Literal forms, independent of the live RKA source.
    import ast
    import tempfile
    src = 'from typing import Literal\nA = Literal["x", "y"]\nB = Literal["only"]\nC = 1\n'
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        path = Path(fh.name)
    try:
        out = drift_mod.extract_literals(path)
        assert out["A"] == frozenset({"x", "y"})
        assert out["B"] == frozenset({"only"})
        assert "C" not in out
    finally:
        path.unlink()
        del ast  # silence unused in some linters
