"""RKA enum drift checker (eval-v3 architecture-review item 3).

The orchestrator's enum tables in ``orchestrator/orchestrator/rka_enums.py``
are a HAND-MAINTAINED mirror of RKA's canonical Literal aliases in
``rka/mcp/_enums.py`` (the bookkeeper invariant forbids importing ``rka.*``
from the orchestrator package). Historically this drifted silently and was
reconciled only when a live run hit a 422.

This script makes drift LOUD and mechanical. It AST-parses ``rka/mcp/_enums.py``
*by file path* (no ``import rka`` — grep-gate safe) and compares each canonical
Literal set against the orchestrator's vendored frozenset. The companion test
``orchestrator/tests/test_rka_enum_drift.py`` fails CI when they diverge, naming
exactly which frozenset to update.

Run standalone for a human-readable report:

    python orchestrator/scripts/rka_enum_drift.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# orchestrator-side frozensets are the orchestrator's own module, importable.
from orchestrator import rka_enums

# Canonical Literal alias (in rka/mcp/_enums.py)  ->  orchestrator frozenset.
# All 13 are EQUALITY mappings as of orchestrator 0.6.13: the orchestrator
# validator must accept exactly what RKA's typed surface accepts. If RKA
# legitimately diverges (e.g. a tool-specific subset), move that pair to
# SUBSET_MAP below with a comment.
EQUALITY_MAP: dict[str, str] = {
    "ConfidenceLit": "RKA_CONFIDENCES",
    "ImportanceLit": "RKA_IMPORTANCES",
    "SourceLit": "RKA_SOURCES",
    "NoteTypeLit": "RKA_JOURNAL_TYPES_ALL",
    "DecidedByLit": "RKA_DECISION_DECIDED_BY",
    "DecisionKindLit": "RKA_DECISION_KINDS",
    "DecisionStatusLit": "RKA_DECISION_STATUSES",
    "ChkTypeLit": "RKA_CHECKPOINT_TYPES",
    "CheckpointResolvedByLit": "RKA_CHECKPOINT_RESOLVED_BY",
    "MissionStatusLit": "RKA_MISSION_STATUSES",
    "LitStatusLit": "RKA_LITERATURE_STATUSES",
    "JournalStatusLit": "RKA_JOURNAL_STATUSES",
    "IngestSourceLit": "RKA_LITERATURE_ADDED_BY",
}


def find_rka_enums_source() -> Path | None:
    """Locate rka/mcp/_enums.py relative to this script, or return None.

    Returns None when the RKA source tree is absent (e.g. an
    orchestrator-only install); callers should skip rather than fail.
    """
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "rka" / "mcp" / "_enums.py"
        if candidate.is_file():
            return candidate
    return None


def extract_literals(enums_path: Path) -> dict[str, frozenset[str]]:
    """AST-parse ``Name = Literal["a", "b", ...]`` assignments by file path.

    No ``import rka`` — the module is parsed as text, so this stays inside
    the grep-gate. Only string-constant members are collected; any
    non-string Literal arg is ignored (none exist today).
    """
    tree = ast.parse(enums_path.read_text(encoding="utf-8"), filename=str(enums_path))
    out: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if not (isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Name)
                and value.value.id == "Literal"):
            continue
        # py3.9+: subscript slice is the expression directly (Tuple or Constant).
        sl = value.slice
        elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
        members = {e.value for e in elts
                   if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if members:
            out[target.id] = frozenset(members)
    return out


def compute_drift() -> list[str]:
    """Return human-readable drift messages; empty list means in sync.

    Returns a single sentinel message when the RKA source is unavailable
    (callers may choose to skip on that).
    """
    src = find_rka_enums_source()
    if src is None:
        return ["__SOURCE_UNAVAILABLE__"]
    canonical = extract_literals(src)
    messages: list[str] = []
    for lit_name, fs_name in EQUALITY_MAP.items():
        rka_set = canonical.get(lit_name)
        orch_set = getattr(rka_enums, fs_name, None)
        if rka_set is None:
            messages.append(
                f"{lit_name}: not found in {src} — RKA may have renamed/removed it; "
                f"update EQUALITY_MAP and rka_enums.{fs_name}.")
            continue
        if orch_set is None:
            messages.append(f"rka_enums.{fs_name}: missing from the orchestrator mirror.")
            continue
        orch_set = frozenset(orch_set)
        missing = rka_set - orch_set        # RKA accepts, orchestrator would reject (false 422-avoidance gaps)
        extra = orch_set - rka_set          # orchestrator accepts, RKA rejects (stale-extra)
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"RKA has but orchestrator MISSING: {sorted(missing)}")
            if extra:
                parts.append(f"orchestrator has but RKA dropped: {sorted(extra)}")
            messages.append(
                f"DRIFT {fs_name} <-> {lit_name}: " + "; ".join(parts)
                + f"  (fix: edit orchestrator/orchestrator/rka_enums.py {fs_name})")
    return messages


def main() -> int:
    drift = compute_drift()
    if drift == ["__SOURCE_UNAVAILABLE__"]:
        print("rka/mcp/_enums.py not found next to the orchestrator — nothing to check.")
        return 0
    if not drift:
        print(f"OK — all {len(EQUALITY_MAP)} enum mirrors in sync with rka/mcp/_enums.py.")
        return 0
    print("RKA ENUM DRIFT DETECTED:\n")
    for m in drift:
        print("  - " + m)
    return 1


if __name__ == "__main__":
    sys.exit(main())
