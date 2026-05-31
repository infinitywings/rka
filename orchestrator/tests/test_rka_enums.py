"""Tests for orchestrator/rka_enums.py — Phase-X² polish.

Covers three concerns:
  1. Bookkeeper invariant: module does NOT import from rka.*
  2. Enum constants match the canonical values (drift detection)
  3. validate_action_args behavior across all paths
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from orchestrator import rka_enums
from orchestrator.rka_enums import (
    RKA_CHECKPOINT_TYPES,
    RKA_CONFIDENCES,
    RKA_DECISION_KINDS,
    RKA_DECISION_STATUSES,
    RKA_IMPORTANCES,
    RKA_JOURNAL_STATUSES,
    RKA_JOURNAL_TYPES_ALL,
    RKA_JOURNAL_TYPES_V2_CANONICAL,
    RKA_MISSION_STATUSES,
    RKA_SOURCES,
    TOOL_ARG_ENUMS,
    validate_action_args,
)


# ---------------------------------------------------------------------------
# Bookkeeper-invariant guard
# ---------------------------------------------------------------------------


def test_module_does_not_import_rka() -> None:
    """rka_enums.py is a MANUAL MIRROR of RKA's schema; it must NEVER
    import from `rka.*`. Two checks: (a) AST scan of the source file,
    (b) sys.modules check after the rka_enums import."""
    src = Path(rka_enums.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("rka"), (
                    f"rka_enums.py imports {alias.name!r} — violates "
                    f"bookkeeper invariant (orchestrator must not import "
                    f"from rka.*)"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith("rka"), (
                f"rka_enums.py does `from {node.module!r} import ...` — "
                f"violates bookkeeper invariant"
            )
    # Defense in depth: confirm `rka` wasn't smuggled into sys.modules
    # by some transitive route during the orchestrator.rka_enums import.
    # (This won't fire in practice if (a) passed, but it's cheap.)
    assert "rka" not in sys.modules or "rka_enums" in sys.modules


# ---------------------------------------------------------------------------
# Enum-constant lock — drift detection
# ---------------------------------------------------------------------------


def test_rka_confidences_match_canonical() -> None:
    """Run-5's PA-2 failure pinned this exact set."""
    assert RKA_CONFIDENCES == frozenset({
        "hypothesis", "tested", "verified", "superseded", "retracted",
    })
    # The specific value Run-5 hit MUST NOT be in the set.
    assert "confirmed" not in RKA_CONFIDENCES


def test_rka_importances_match_canonical() -> None:
    assert RKA_IMPORTANCES == frozenset({
        "critical", "high", "normal", "low", "archived",
    })


def test_rka_sources_match_canonical() -> None:
    assert RKA_SOURCES == frozenset({
        "brain", "executor", "pi", "web_ui", "llm",
    })


def test_rka_journal_types_v2_canonical_match() -> None:
    assert RKA_JOURNAL_TYPES_V2_CANONICAL == frozenset({
        "note", "log", "directive",
    })


def test_rka_journal_types_all_is_union() -> None:
    """Legacy types are silently normalized server-side; the validator
    must accept the union."""
    assert RKA_JOURNAL_TYPES_V2_CANONICAL.issubset(RKA_JOURNAL_TYPES_ALL)
    assert "finding" in RKA_JOURNAL_TYPES_ALL  # legacy
    assert "observation" in RKA_JOURNAL_TYPES_ALL  # legacy
    assert "note" in RKA_JOURNAL_TYPES_ALL  # v2 canonical


def test_rka_decision_kinds_match_canonical() -> None:
    """Run-5 v3 PA-2 misuse pinned rka_advance_rq's research_question
    requirement."""
    assert RKA_DECISION_KINDS == frozenset({
        "research_question", "design_choice", "decision", "operational",
    })


def test_rka_decision_statuses_match_canonical() -> None:
    assert RKA_DECISION_STATUSES == frozenset({
        "active", "abandoned", "superseded", "merged", "revisit",
    })


def test_rka_journal_statuses_match_canonical() -> None:
    assert RKA_JOURNAL_STATUSES == frozenset({
        "draft", "active", "superseded", "retracted",
    })


def test_rka_checkpoint_types_match_canonical() -> None:
    assert RKA_CHECKPOINT_TYPES == frozenset({
        "decision", "clarification", "inspection", "gate",
    })


def test_rka_mission_statuses_match_canonical() -> None:
    assert RKA_MISSION_STATUSES == frozenset({
        "pending", "active", "complete", "partial", "blocked", "cancelled",
    })


# ---------------------------------------------------------------------------
# TOOL_ARG_ENUMS coverage
# ---------------------------------------------------------------------------


def test_tool_arg_enums_covers_rka_add_note() -> None:
    """rka_add_note is the single most-frequently-proposed tool; it must
    have enum lookups for every CHECK-constrained column."""
    assert "rka_add_note" in TOOL_ARG_ENUMS
    note_enums = TOOL_ARG_ENUMS["rka_add_note"]
    for field in ("type", "source", "confidence", "importance", "status"):
        assert field in note_enums, f"rka_add_note missing {field!r} enum"


def test_tool_arg_enums_covers_rka_add_decision() -> None:
    assert "rka_add_decision" in TOOL_ARG_ENUMS
    dec_enums = TOOL_ARG_ENUMS["rka_add_decision"]
    for field in ("decided_by", "status", "kind"):
        assert field in dec_enums


def test_tool_arg_enums_covers_supported_update_tools() -> None:
    """rka_update_note + rka_update_mission_status mirror their rka_add_*
    counterparts. rka_update_decision is intentionally pruned per the
    adversarial-review must-fix (not currently in WRITE_TOOLS — re-add
    if and when it lands in the dispatcher allowlist)."""
    assert "rka_update_note" in TOOL_ARG_ENUMS
    assert "rka_update_mission_status" in TOOL_ARG_ENUMS


# ---------------------------------------------------------------------------
# validate_action_args behavior
# ---------------------------------------------------------------------------


def test_validate_action_args_returns_empty_for_valid_note() -> None:
    args = {
        "project_id": "prj_x",
        "content": "ok",
        "source": "brain",
        "confidence": "verified",
        "importance": "high",
        "type": "note",
        "status": "active",
        # Non-enum fields — must be ignored cleanly.
        "tags": ["foo", "bar"],
        "related_mission": "mis_y",
    }
    assert validate_action_args("rka_add_note", args) == []


def test_validate_action_args_flags_run5_pa2_confidence_confirmed() -> None:
    """Run-5 PA-2 EXACT regression. Brain proposed confidence='confirmed';
    the validator must flag it before dispatch."""
    args = {
        "project_id": "prj_x",
        "content": "T3 findings",
        "source": "brain",
        "confidence": "confirmed",  # ← invalid
        "importance": "high",
        "related_mission": "mis_y",
    }
    violations = validate_action_args("rka_add_note", args)
    assert len(violations) == 1
    arg, value, expected = violations[0]
    assert arg == "confidence"
    assert value == "confirmed"
    assert expected == RKA_CONFIDENCES


def test_validate_action_args_flags_multiple_violations_in_one_call() -> None:
    """A single rka_add_note with two bad enum values produces two
    violations (one per field), not a single combined one."""
    args = {
        "source": "brain",
        "confidence": "confirmed",  # ← invalid
        "importance": "very-high",  # ← invalid
        "content": "x",
    }
    violations = validate_action_args("rka_add_note", args)
    flagged_args = {v[0] for v in violations}
    assert flagged_args == {"confidence", "importance"}


def test_validate_action_args_flags_decision_kind_mismatch() -> None:
    """rka_advance_rq is forbidden (not in WRITE_TOOLS), so we can't test
    Run-5 v3 PA-2's kind-mismatch directly via the dispatcher. But the
    same enum table catches the equivalent on rka_add_decision."""
    violations = validate_action_args(
        "rka_add_decision",
        {"content": "x", "kind": "research-question"},  # ← hyphen, not underscore
    )
    assert len(violations) == 1
    assert violations[0][0] == "kind"
    assert violations[0][1] == "research-question"


def test_validate_action_args_unknown_tool_returns_empty() -> None:
    """Open-world tolerance: unknown tool returns no violations. The
    WRITE_TOOLS allowlist catches unknown tools upstream."""
    violations = validate_action_args(
        "rka_madeup_tool", {"confidence": "confirmed"}
    )
    assert violations == []


def test_validate_action_args_unknown_arg_skipped() -> None:
    """Brain may include any number of non-enum args (project_id,
    content, tags, related_mission, supersedes, ...) — those skip
    cleanly."""
    violations = validate_action_args(
        "rka_add_note",
        {"content": "x", "tags": ["foo"], "supersedes": "jrn_y"},
    )
    assert violations == []


def test_validate_action_args_non_string_value_skipped() -> None:
    """Enum checks only apply to string fields. Non-string values
    (bool, int, list, dict) are out of scope — RKA's Pydantic will
    catch shape errors at the API boundary."""
    violations = validate_action_args(
        "rka_add_note",
        {"confidence": None, "importance": 42, "source": ["brain"]},
    )
    assert violations == []


def test_validate_action_args_legacy_journal_types_accepted() -> None:
    """Legacy types (finding, insight, ...) are silently normalized by
    RKA's JOURNAL_TYPE_MAP; the validator must accept them as valid."""
    for legacy_type in ("finding", "observation", "hypothesis", "summary"):
        args = {"content": "x", "type": legacy_type}
        assert validate_action_args("rka_add_note", args) == [], (
            f"legacy type {legacy_type!r} must be accepted"
        )


def test_validate_action_args_v2_canonical_types_accepted() -> None:
    for canonical in ("note", "log", "directive"):
        args = {"content": "x", "type": canonical}
        assert validate_action_args("rka_add_note", args) == []


def test_validate_action_args_update_note_validates_partial_args() -> None:
    """rka_update_note accepts partial args; the validator must check
    only the fields present, not require all of them."""
    # Just status, valid
    assert validate_action_args(
        "rka_update_note", {"id": "jrn_x", "status": "retracted"}
    ) == []
    # Just status, invalid
    violations = validate_action_args(
        "rka_update_note", {"id": "jrn_x", "status": "deleted"}
    )
    assert len(violations) == 1
    assert violations[0][0] == "status"


def test_validate_action_args_open_world_returns_immutable_view() -> None:
    """Returned expected-set MUST be the same frozenset object (so callers
    can do identity-comparison or use it as a key); not a fresh copy."""
    violations = validate_action_args(
        "rka_add_note", {"confidence": "confirmed"}
    )
    _, _, expected = violations[0]
    assert expected is RKA_CONFIDENCES  # identity, not equality


# ---------------------------------------------------------------------------
# Adversarial-review wf_ed78d6f8 must-fix regressions
# ---------------------------------------------------------------------------


def test_rka_ingest_document_in_tool_arg_enums() -> None:
    """Adversarial review surfaced this gap: rka_ingest_document IS in
    WRITE_TOOLS, accepts `source` (RKA_SOURCES) and `default_type`
    (RKA_JOURNAL_TYPES_ALL via the journal CHECK + JOURNAL_TYPE_MAP).
    Without TOOL_ARG_ENUMS coverage, out-of-enum values would reach the
    API. Lock the entry so it can't be silently dropped."""
    assert "rka_ingest_document" in TOOL_ARG_ENUMS
    ingest = TOOL_ARG_ENUMS["rka_ingest_document"]
    assert ingest["source"] is RKA_SOURCES
    assert "default_type" in ingest


def test_rka_ingest_document_rejects_invalid_source() -> None:
    """The Run-5-pattern equivalent on the ingestion path."""
    violations = validate_action_args(
        "rka_ingest_document",
        {"path": "/x", "source": "system"},  # ← 'system' not in RKA_SOURCES
    )
    assert len(violations) == 1
    assert violations[0][0] == "source"


def test_rka_create_mission_not_in_tool_arg_enums() -> None:
    """Adversarial review removed this entry: MissionCreate has no
    `status` field (extra='forbid'). If a future contributor re-adds
    this entry, this test fails loudly so they reconsider."""
    assert "rka_create_mission" not in TOOL_ARG_ENUMS


def test_validate_action_args_create_mission_passes_through() -> None:
    """rka_create_mission with no enum coverage: validator must return
    [] (open-world tolerance). The dispatcher / API would still catch
    any malformed kwargs at the network layer."""
    violations = validate_action_args(
        "rka_create_mission",
        {"objective": "x", "status": "pending"},
    )
    assert violations == []


def test_rka_update_decision_not_in_tool_arg_enums() -> None:
    """Pruned per adversarial review (not currently in WRITE_TOOLS).
    Re-add if rka_update_decision is added to the dispatcher allowlist."""
    assert "rka_update_decision" not in TOOL_ARG_ENUMS


def test_rka_literature_tools_not_in_tool_arg_enums() -> None:
    """Same rationale as rka_update_decision."""
    assert "rka_add_literature" not in TOOL_ARG_ENUMS
    assert "rka_update_literature" not in TOOL_ARG_ENUMS
