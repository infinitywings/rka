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
    TOOL_REQUIRED_FIELDS,
    check_action_capability,
    check_required_fields,
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


# ---------------------------------------------------------------------------
# Phase-X²' polish — TOOL_REQUIRED_FIELDS + check_required_fields
# ---------------------------------------------------------------------------


def test_check_required_fields_happy_path() -> None:
    """All required alias-sets satisfied → empty list."""
    args = {
        "description": "checkpoint body",
        "mission_id": "mis_test",
        "type": "decision",
    }
    assert check_required_fields("rka_submit_checkpoint", args) == []


def test_check_required_fields_missing_canonical_description() -> None:
    """Empirical 2026-06-01 bug shape — `rka_submit_checkpoint(content=...)`
    instead of description= and the validator flags missing alias-set."""
    args = {"mission_id": "mis_test"}  # no description/message/reason/content
    errors = check_required_fields("rka_submit_checkpoint", args)
    assert len(errors) == 1
    assert "rka_submit_checkpoint" in errors[0]
    assert "description" in errors[0]
    assert "content" in errors[0]  # Layer 1 alias mentioned in alts
    assert "message" in errors[0]
    assert "reason" in errors[0]


def test_check_required_fields_content_alias_satisfies_after_layer_1() -> None:
    """Phase-X²' Layer 1 added `content` as a fourth alias on
    rka_submit_checkpoint's body field. The validator must reflect this
    so `{content: 'foo', mission_id: '...'}` is NOT flagged as missing.
    """
    args = {"content": "checkpoint body", "mission_id": "mis_test"}
    assert check_required_fields("rka_submit_checkpoint", args) == []


def test_check_required_fields_message_alias_still_satisfies() -> None:
    """Pre-Phase-X²' aliases (`message`, `reason`) continue to satisfy."""
    args = {"message": "checkpoint body", "mission_id": "mis_test"}
    assert check_required_fields("rka_submit_checkpoint", args) == []
    args = {"reason": "checkpoint body", "related_mission": "mis_test"}
    assert check_required_fields("rka_submit_checkpoint", args) == []


def test_check_required_fields_multi_missing_returns_multiple_errors() -> None:
    """rka_add_decision requires BOTH content AND related_journal. Missing
    both → two errors."""
    errors = check_required_fields("rka_add_decision", {})
    assert len(errors) == 2
    error_text = "\n".join(errors)
    assert "content" in error_text
    assert "related_journal" in error_text


def test_check_required_fields_unknown_tool_open_world() -> None:
    """Unknown tool → empty list (open-world tolerance)."""
    assert check_required_fields("rka_unknown_tool", {"foo": "bar"}) == []
    assert check_required_fields("rka_unknown_tool", {}) == []


def test_check_required_fields_explicit_none_treated_as_missing() -> None:
    """{description: None} must be flagged the same as {} — None signals
    a missing value at the dispatcher seam."""
    args = {"description": None, "mission_id": "mis_test"}
    errors = check_required_fields("rka_submit_checkpoint", args)
    assert len(errors) == 1
    assert "description" in errors[0]


def test_check_required_fields_excludes_project_id() -> None:
    """Invariant: project_id is dispatcher-injected by RestMCPClient and
    must NEVER appear in TOOL_REQUIRED_FIELDS — otherwise every action
    would false-positive (the dispatcher strips project_id before the
    validator runs in Phase-E6)."""
    for tool, sets in TOOL_REQUIRED_FIELDS.items():
        all_fields = set().union(*sets)
        assert "project_id" not in all_fields, (
            f"{tool} has project_id in TOOL_REQUIRED_FIELDS — invariant "
            f"violation"
        )


def test_tool_required_fields_per_tool_lock() -> None:
    """Lock-tests pin the per-tool entries against silent drift. When
    the RestMCPClient adapter signature changes, the test fails loudly
    and forces a manual sync (matching the TOOL_ARG_ENUMS posture)."""
    assert TOOL_REQUIRED_FIELDS["rka_add_note"] == [frozenset({"content"})]
    assert TOOL_REQUIRED_FIELDS["rka_add_decision"] == [
        frozenset({"content"}),
        frozenset({"related_journal"}),
    ]
    assert TOOL_REQUIRED_FIELDS["rka_submit_checkpoint"] == [
        frozenset({"description", "message", "reason", "content"}),
        frozenset({"mission_id", "related_mission"}),
    ]
    assert TOOL_REQUIRED_FIELDS["rka_submit_report"] == [
        frozenset({"mission_id", "related_mission"}),
    ]
    assert TOOL_REQUIRED_FIELDS["rka_create_mission"] == [
        frozenset({"objective"}),
        frozenset({"motivated_by_decision"}),
        frozenset({"acceptance_criteria"}),
    ]
    assert TOOL_REQUIRED_FIELDS["rka_update_note"] == [frozenset({"id"})]
    assert TOOL_REQUIRED_FIELDS["rka_update_mission_status"] == [
        frozenset({"id"}),
    ]
    assert TOOL_REQUIRED_FIELDS["rka_bulk_update"] == [frozenset({"updates"})]
    assert TOOL_REQUIRED_FIELDS["rka_ingest_document"] == [
        frozenset({"content"}),
    ]


def test_tool_required_fields_covers_write_tools_in_arg_enums() -> None:
    """The required-field validator should cover at least every tool
    that the enum-value validator covers. Drift detection: if a future
    PR adds a new tool to TOOL_ARG_ENUMS without adding the matching
    TOOL_REQUIRED_FIELDS entry, the asymmetry is flagged.
    """
    enum_tools = set(TOOL_ARG_ENUMS.keys())
    required_tools = set(TOOL_REQUIRED_FIELDS.keys())
    missing = enum_tools - required_tools
    assert not missing, (
        f"Tools in TOOL_ARG_ENUMS but not TOOL_REQUIRED_FIELDS: "
        f"{sorted(missing)}. Add the required-field entries or document "
        f"the intentional omission."
    )


def test_tool_required_fields_matches_write_tools_set() -> None:
    """Drift-detection (adversarial review NIT #3): TOOL_REQUIRED_FIELDS
    must cover every WRITE_TOOL. If a future PR adds a write tool
    without updating the required-field table, the validator silently
    no-ops on it (open-world tolerance) — defeating the Phase-X²'
    polish goal. Pin the coverage.
    """
    from orchestrator.llm_client import WRITE_TOOLS

    required_tools = set(TOOL_REQUIRED_FIELDS.keys())
    write_tools = set(WRITE_TOOLS)
    missing = write_tools - required_tools
    extra = required_tools - write_tools
    assert not missing, (
        f"WRITE_TOOLS missing from TOOL_REQUIRED_FIELDS: {sorted(missing)} "
        f"— add the required-field entries"
    )
    assert not extra, (
        f"TOOL_REQUIRED_FIELDS has entries for non-WRITE_TOOLS: "
        f"{sorted(extra)} — remove them or add to WRITE_TOOLS"
    )


# Adversarial review MEDIUM #1 — validator must reject empty / whitespace
# strings the same way the adapter does (truthy-check semantics).


def test_check_required_fields_rejects_empty_string() -> None:
    """`{description: '', mission_id: 'mis_x'}` previously passed the
    validator and then failed at the adapter — the validator now
    rejects empty strings as missing (matching mcp_client.py:585's
    `if not description:` semantics)."""
    args = {"description": "", "mission_id": "mis_x"}
    errors = check_required_fields("rka_submit_checkpoint", args)
    assert len(errors) == 1
    assert "description" in errors[0]


def test_check_required_fields_rejects_whitespace_only_string() -> None:
    """`{description: '   '}` is also rejected (mirrors
    rka_ingest_document's `if not content or not content.strip()` at
    mcp_client.py:967)."""
    args = {"description": "   \n  ", "mission_id": "mis_x"}
    errors = check_required_fields("rka_submit_checkpoint", args)
    assert len(errors) == 1
    assert "description" in errors[0]


def test_check_required_fields_rejects_empty_collection_for_required_list() -> None:
    """Required list-typed fields (e.g. rka_create_mission's
    `acceptance_criteria: list[str]`) reject empty lists — truthy
    semantics apply uniformly."""
    args = {
        "objective": "test",
        "motivated_by_decision": "dec_x",
        "acceptance_criteria": [],
    }
    errors = check_required_fields("rka_create_mission", args)
    assert any("acceptance_criteria" in e for e in errors)


def test_check_required_fields_accepts_meaningful_string() -> None:
    """Non-empty non-whitespace strings continue to satisfy
    (regression guard against the truthy-check tightening)."""
    args = {"description": "real content", "mission_id": "mis_x"}
    assert check_required_fields("rka_submit_checkpoint", args) == []


# ---------------------------------------------------------------------------
# v2.6.0+agentic.6 — check_action_capability tests
# ---------------------------------------------------------------------------


def test_check_action_capability_empty_allowlist_permits_everything() -> None:
    """Pre-2.14 semantics — empty/None allowlist means no restriction.
    Pins backward compatibility with existing workflows that never
    set allowed_capabilities."""
    assert check_action_capability("rka_add_note", set()) == []
    assert check_action_capability("rka_update_mission_status", []) == []
    assert check_action_capability("rka_submit_checkpoint", ()) == []
    # None-equivalent — passing None directly is the same shape the
    # state field carries when unset.
    assert check_action_capability("rka_add_note", None) == []  # type: ignore[arg-type]


def test_check_action_capability_permits_tool_in_allowed_capability() -> None:
    """Happy path — tool's capability is in the allowlist → no errors.
    Pins the canonical case the empirical PA-1/2/3 dispatch hit."""
    # record_knowledge tools
    assert check_action_capability("rka_add_note", {"record_knowledge"}) == []
    assert check_action_capability(
        "rka_add_decision", {"record_knowledge", "execution_gates"}
    ) == []
    # execution_gates tools
    assert check_action_capability("rka_submit_checkpoint", {"execution_gates"}) == []
    assert check_action_capability("rka_submit_report", {"execution_gates"}) == []


def test_check_action_capability_rejects_tool_outside_allowlist() -> None:
    """The empirical PA-4 failure shape — rka_update_mission_status
    requires mission_lifecycle but workflow holds only
    ['execution_gates', 'record_knowledge']. The error message must
    name the tool, its capability, and the allowed set."""
    errors = check_action_capability(
        "rka_update_mission_status",
        {"execution_gates", "record_knowledge"},
    )
    assert len(errors) == 1
    msg = errors[0]
    assert "rka_update_mission_status" in msg
    assert "mission_lifecycle" in msg
    assert "execution_gates" in msg
    assert "record_knowledge" in msg


def test_check_action_capability_unknown_tool_returns_empty() -> None:
    """Unknown tool defers to ratified_action_tool_not_allowed upstream;
    no double-fire. Open-world tolerance matches validate_action_args
    + check_required_fields posture."""
    assert check_action_capability("rka_unknown_tool", {"record_knowledge"}) == []
    assert check_action_capability("foo_bar_baz", {"execution_gates"}) == []


def test_check_action_capability_accepts_list_tuple_set() -> None:
    """allowed_capabilities can be a list (from JSON), tuple (Phase-2.14
    legacy), or set (set arithmetic). All three shapes work
    identically — pins the Phase-2.14 callsite tolerance."""
    perms = {"execution_gates"}
    list_form = ["execution_gates"]
    tuple_form = ("execution_gates",)
    assert check_action_capability("rka_submit_checkpoint", perms) == []
    assert check_action_capability("rka_submit_checkpoint", list_form) == []
    assert check_action_capability("rka_submit_checkpoint", tuple_form) == []
    # Rejection invariant across shapes.
    assert check_action_capability("rka_update_mission_status", perms) != []
    assert check_action_capability("rka_update_mission_status", list_form) != []
    assert check_action_capability("rka_update_mission_status", tuple_form) != []


def test_check_action_capability_all_capabilities_permits_all_tools() -> None:
    """Pin the full-capability case — useful for tests + admin tooling."""
    full = {
        "record_knowledge", "update_knowledge",
        "mission_lifecycle", "execution_gates", "ingestion",
    }
    from orchestrator.llm_client import TOOL_CAPABILITIES
    for tool in TOOL_CAPABILITIES:
        assert check_action_capability(tool, full) == [], (
            f"{tool} rejected under full-capability allowlist"
        )


def test_check_action_capability_diagnostic_message_actionable() -> None:
    """The error message must point operators at the two correct
    remediations: widen the allowlist OR rewrite to use an authorized
    tool. Symmetric to check_required_fields's diagnostic posture."""
    errors = check_action_capability(
        "rka_create_mission", {"record_knowledge"}
    )
    assert len(errors) == 1
    msg = errors[0]
    assert "widen" in msg.lower() or "allowlist" in msg.lower()
    assert "authorized" in msg.lower() or "capability" in msg.lower()


# ---------------------------------------------------------------------------
# BRAIN_SYSTEM capability-set enumeration (v2.6.0+agentic.6 prompt anchor)
# ---------------------------------------------------------------------------


def test_brain_system_enumerates_canonical_capability_buckets() -> None:
    """The Phase-X²''-style prompt block must list the five canonical
    capability buckets so Brain self-prunes mission_lifecycle (and
    update_knowledge, ingestion) proposals when those aren't in the
    workflow's ratified allowlist.
    """
    from orchestrator.nodes.brain import BRAIN_SYSTEM

    assert "record_knowledge" in BRAIN_SYSTEM
    assert "update_knowledge" in BRAIN_SYSTEM
    assert "mission_lifecycle" in BRAIN_SYSTEM
    assert "execution_gates" in BRAIN_SYSTEM
    assert "ingestion" in BRAIN_SYSTEM


def test_brain_system_warns_against_mission_lifecycle_in_execution_segments() -> None:
    """Empirical PA-4 callout — Brain proposed `rka_update_mission_status`
    in an execution-segment workflow. The prompt must explicitly name
    this hallucination class so future Brain emissions self-prune."""
    from orchestrator.nodes.brain import BRAIN_SYSTEM

    assert "rka_update_mission_status" in BRAIN_SYSTEM
    # Must explicitly call out PI-actor scope for lifecycle transitions.
    assert "PI-actor" in BRAIN_SYSTEM or "out-of-band" in BRAIN_SYSTEM
