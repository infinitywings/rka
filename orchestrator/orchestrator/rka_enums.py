"""Manual mirror of RKA Pydantic / schema enums for orchestrator-side use.

This module is the SINGLE SOURCE OF TRUTH inside the orchestrator package
for the enum values that RKA's POST /api/* endpoints accept. Three
consumers (Phase-X² polish PR):

  1. `BRAIN_SYSTEM` enumerates these so Brain doesn't propose
     out-of-enum values in its `proposed_actions` JSON block.
  2. `EXECUTOR_SYSTEM` enumerates the same set so Executor's
     proposed_actions stay in-spec.
  3. `execute_ratified_actions` calls `validate_action_args` to
     reject out-of-enum values BEFORE the network round-trip,
     short-circuiting the failure that Run-5's PA-2 hit (HTTP 422
     after Brain proposed `confidence='confirmed'`).

Bookkeeper invariant: this module **deliberately does NOT import from
`rka.*`**. The orchestrator talks to RKA only through the `MCPClient`
Protocol (`mcp_client.py`); importing RKA's Pydantic models here would
break that abstraction. The trade-off is that these enum tables can
drift from the RKA source-of-truth — drift is reconciled MANUALLY
when RKA's schema or Pydantic models change.

Source of truth (reconcile drift against these files):
  - `rka/db/schema.sql` (SQLite CHECK constraints — see migrations
    009 + 015 + 019 for journal/decision/checkpoint columns)
  - `rka/models/journal.py` (Pydantic JournalEntry — accepts the
    schema's CHECK set plus a legacy-normalized superset that the
    server silently maps via JOURNAL_TYPE_MAP for back-compat)
  - `rka/models/decision.py` (Pydantic Decision — kind / status /
    decided_by enums)
  - `rka/models/checkpoint.py` (Pydantic Checkpoint — type /
    resolved_by enums)
  - `rka/models/literature.py` (Pydantic Literature — status /
    added_by enums)
  - `rka/api/missions.py` (mission lifecycle status enum)

If you bump RKA's schema or Pydantic enums, search this file for
the affected frozenset and update both. The drift-detection tests
in `tests/test_rka_enums.py` lock the values that matter for the
shipped contract.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Journal (rka_add_note / rka_update_note)
# ---------------------------------------------------------------------------

# v2 canonical type set (`rka/db/schema.sql` migration 019). New writes
# should prefer these.
RKA_JOURNAL_TYPES_V2_CANONICAL: frozenset[str] = frozenset({
    "note", "log", "directive",
})

# Legacy types still accepted by the Pydantic model + JOURNAL_TYPE_MAP
# (silent normalization for back-compat with pre-migration writers).
RKA_JOURNAL_TYPES_LEGACY_ACCEPTED: frozenset[str] = frozenset({
    "finding", "insight", "pi_instruction", "exploration",
    "idea", "observation", "hypothesis", "methodology", "summary",
})

# Union — what the API will accept; what the validator should treat
# as legal.
RKA_JOURNAL_TYPES_ALL: frozenset[str] = (
    RKA_JOURNAL_TYPES_V2_CANONICAL | RKA_JOURNAL_TYPES_LEGACY_ACCEPTED
)

# Actor-of-record on every journal write (`rka/db/schema.sql`).
RKA_SOURCES: frozenset[str] = frozenset({
    "brain", "executor", "pi", "web_ui", "llm",
})

# Confidence on journal entries (`rka/db/schema.sql`). Run-5's PA-2
# failed with `confidence='confirmed'` — NOT in this set.
RKA_CONFIDENCES: frozenset[str] = frozenset({
    "hypothesis", "tested", "verified", "superseded", "retracted",
})

# Importance on journal entries (`rka/db/schema.sql`).
RKA_IMPORTANCES: frozenset[str] = frozenset({
    "critical", "high", "normal", "low", "archived",
})

# Lifecycle status on journal entries (`rka/db/schema.sql`).
RKA_JOURNAL_STATUSES: frozenset[str] = frozenset({
    "draft", "active", "superseded", "retracted",
})


# ---------------------------------------------------------------------------
# Decision (rka_add_decision / rka_update_decision)
# ---------------------------------------------------------------------------

# `decided_by` field (`rka/db/schema.sql`).
RKA_DECISION_DECIDED_BY: frozenset[str] = frozenset({
    "pi", "brain", "executor",
})

# Lifecycle status on decisions (`rka/db/schema.sql`).
RKA_DECISION_STATUSES: frozenset[str] = frozenset({
    "active", "abandoned", "superseded", "merged", "revisit",
})

# Kind of decision (`rka/db/schema.sql`). Run-5 v3 PA-2 misuse pinned
# the `research_question` requirement for `rka_advance_rq`.
RKA_DECISION_KINDS: frozenset[str] = frozenset({
    "research_question", "design_choice", "decision", "operational",
})


# ---------------------------------------------------------------------------
# Checkpoint (rka_submit_checkpoint)
# ---------------------------------------------------------------------------

RKA_CHECKPOINT_TYPES: frozenset[str] = frozenset({
    "decision", "clarification", "inspection", "gate",
})

RKA_CHECKPOINT_RESOLVED_BY: frozenset[str] = frozenset({
    "pi", "brain",
})


# ---------------------------------------------------------------------------
# Mission (rka_create_mission / rka_update_mission_status)
# ---------------------------------------------------------------------------

RKA_MISSION_STATUSES: frozenset[str] = frozenset({
    "pending", "active", "complete", "partial", "blocked", "cancelled",
})


# ---------------------------------------------------------------------------
# Literature (rka_add_literature / rka_update_literature)
# ---------------------------------------------------------------------------

RKA_LITERATURE_STATUSES: frozenset[str] = frozenset({
    "to_read", "reading", "read", "cited", "excluded",
})

RKA_LITERATURE_ADDED_BY: frozenset[str] = frozenset({
    "brain", "executor", "pi", "import", "web_ui",
})


# ---------------------------------------------------------------------------
# Per-tool argument → enum map (the pre-dispatch validator's lookup table)
# ---------------------------------------------------------------------------

# `tool_name -> {arg_name -> set_of_legal_values}`. Tools / args not in
# this map are treated as open-world (validator returns no violations).
# That's intentional: the goal is to short-circuit the empirically-
# observed failure modes (Run-5 PA-2 confidence='confirmed', the v3 PA-2
# kind-mismatch pattern), NOT to replicate RKA's full Pydantic validation
# inside the orchestrator. Unknown tools are also caught at the
# WRITE_TOOLS allowlist check upstream.
TOOL_ARG_ENUMS: dict[str, dict[str, frozenset[str]]] = {
    "rka_add_note": {
        "type": RKA_JOURNAL_TYPES_ALL,
        "source": RKA_SOURCES,
        "confidence": RKA_CONFIDENCES,
        "importance": RKA_IMPORTANCES,
        "status": RKA_JOURNAL_STATUSES,
    },
    "rka_update_note": {
        "type": RKA_JOURNAL_TYPES_ALL,
        "source": RKA_SOURCES,
        "confidence": RKA_CONFIDENCES,
        "importance": RKA_IMPORTANCES,
        "status": RKA_JOURNAL_STATUSES,
    },
    # `rka_bulk_update`: validator intentionally does not reach into
    # the nested `updates[i].data` dicts. Brain's bulk-update payload
    # carries per-entity PUT bodies with the same enum constraints as
    # the corresponding rka_update_* methods, but the validator's
    # narrow design (top-level kwarg only) trades off coverage for
    # simplicity. The per-entity REST endpoint's Pydantic guard
    # remains authoritative for those nested fields.
    "rka_add_decision": {
        "decided_by": RKA_DECISION_DECIDED_BY,
        "status": RKA_DECISION_STATUSES,
        "kind": RKA_DECISION_KINDS,
    },
    "rka_submit_checkpoint": {
        "type": RKA_CHECKPOINT_TYPES,
    },
    # `rka_create_mission` intentionally omitted — `MissionCreate`
    # (rka/models/mission.py) uses `extra="forbid"` and has no `status`
    # field. Including a `status` enum check here would advertise a
    # field the create endpoint rejects regardless of value, defeating
    # the validator's diagnostic purpose. Status only applies to
    # `rka_update_mission_status` below.
    "rka_update_mission_status": {
        "status": RKA_MISSION_STATUSES,
    },
    # `rka_ingest_document` — adversarial review wf_ed78d6f8 surfaced
    # this gap. It's in WRITE_TOOLS, its REST surface exposes
    # `source` (RKA_SOURCES at the DB layer) and `default_type`
    # (RKA_JOURNAL_TYPES_ALL via journal CHECK + JOURNAL_TYPE_MAP).
    # Without this entry, out-of-enum values reach the API and 422
    # — defeating the validator's mission.
    "rka_ingest_document": {
        "source": RKA_SOURCES,
        "default_type": RKA_JOURNAL_TYPES_ALL,
    },
    # `rka_update_decision`, `rka_add_literature`, `rka_update_literature`
    # are NOT currently in WRITE_TOOLS. They were originally pre-staged
    # here as forward-compat scaffolding, but per the adversarial review
    # we prune them so this map stays in sync with the dispatcher's
    # actual allowlist. Re-add if and when those tools land in
    # WRITE_TOOLS.
}


def validate_action_args(
    tool: str, args: dict,
) -> list[tuple[str, str, frozenset[str]]]:
    """Pre-dispatch enum validation for `execute_ratified_actions`.

    Returns a list of `(arg_name, observed_value, expected_set)` tuples
    for every enum violation in `args`. Empty list = no violations.

    Open-world tolerance:
      - Unknown `tool` (not in `TOOL_ARG_ENUMS`) → empty list. The
        WRITE_TOOLS allowlist check upstream catches unknown tools
        already with a different ErrorRecord (`ratified_action_tool_not_allowed`).
      - Unknown `arg_name` (not in the per-tool enum map) → skipped
        without complaint. Brain may include any number of legitimate
        args (project_id, content, related_mission, tags, ...) that
        don't have enum constraints.
      - Non-string value → skipped without complaint. Enum checks
        only apply to string fields; other types (bool, int, list,
        dict) are out of scope for this validator.

    The validator is intentionally narrow: catch the empirically-observed
    failure modes pre-dispatch, don't replicate RKA's full Pydantic
    validation. The API layer remains the source-of-truth — this is a
    diagnostic shortcut + a Brain-prompt-discipline backstop.
    """
    enum_map = TOOL_ARG_ENUMS.get(tool)
    if not enum_map:
        return []
    violations: list[tuple[str, str, frozenset[str]]] = []
    for arg_name, expected in enum_map.items():
        if arg_name not in args:
            continue
        value = args[arg_name]
        if not isinstance(value, str):
            continue
        if value not in expected:
            violations.append((arg_name, value, expected))
    return violations
