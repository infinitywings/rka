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


# ---------------------------------------------------------------------------
# Phase-X²' polish — per-tool required-field validation
# ---------------------------------------------------------------------------
#
# Closes the field-NAME validation gap that the enum-VALUE validator
# (TOOL_ARG_ENUMS / validate_action_args) left open. The 2026-06-01
# hyperscaler-auditing PA-2 failure surfaced this: Brain emitted
# `rka_submit_checkpoint(content=...)` instead of `description=...`. The
# enum validator returned empty (no enum violations); the adapter then
# raised ValueError at dispatch time and EC8 escalated to a failure
# checkpoint.
#
# Design: per-tool list of ALIAS SETS. Each set is a "required-OR" — if
# ANY field in the set is present (and not None), the requirement is
# satisfied. This matches how the RestMCPClient adapters absorb Brain
# shape variation:
#
#   rka_submit_checkpoint accepts description / message / reason /
#   content as aliases for the body field; mission_id / related_mission
#   as aliases for the mission anchor. The required-set declaration
#   reflects the post-Layer-1 adapter surface so this validator stays
#   consistent with what the adapter will and will not accept.
#
# Bookkeeper invariant: the table is a MANUAL MIRROR of the RestMCPClient
# adapter signatures at `orchestrator/mcp_client.py`. NO `from rka` /
# `import rka` here or in the lock-tests. Drift is reconciled MANUALLY
# when the adapter's alias surface changes.
#
# Source of truth for each per-tool entry below: the adapter signature
# and pop chain in `orchestrator/mcp_client.py`. Cited lines refer to
# the live tree at this PR's tip.
#
# project_id is INTENTIONALLY excluded from every required set: the
# orchestrator's RestMCPClient injects it from the workflow's project
# binding via query params (see RestMCPClient._params); the executor's
# project_id consistency guard (`cross_project_write_attempted`) is the
# upstream check that catches per-action project_id mismatches.

TOOL_REQUIRED_FIELDS: dict[str, list[frozenset[str]]] = {
    # rka_add_note(content: str, **kw) — content is positional-required.
    "rka_add_note": [
        frozenset({"content"}),
    ],
    # rka_add_decision(content: str, *, related_journal: list[str], ...)
    # — content + related_journal are no-default required.
    "rka_add_decision": [
        frozenset({"content"}),
        frozenset({"related_journal"}),
    ],
    # rka_submit_checkpoint(*args, **kw) — description-alias-set
    # (POST-Layer-1, so `content` is included) + mission_id-alias-set.
    # type defaults to "decision" at the adapter, so it is NOT required.
    "rka_submit_checkpoint": [
        frozenset({"description", "message", "reason", "content"}),
        frozenset({"mission_id", "related_mission"}),
    ],
    # rka_submit_report(*args, **kw) — mission_id-alias-set is the
    # hard requirement; summary tolerates absence at the adapter (defaults
    # to "") so we don't enforce it pre-dispatch.
    "rka_submit_report": [
        frozenset({"mission_id", "related_mission"}),
    ],
    # rka_create_mission(objective: str, *, motivated_by_decision: str,
    # acceptance_criteria: list[str], ...) — three no-default required.
    "rka_create_mission": [
        frozenset({"objective"}),
        frozenset({"motivated_by_decision"}),
        frozenset({"acceptance_criteria"}),
    ],
    # rka_update_note(id: str, **kw) — id raises ValueError if empty.
    "rka_update_note": [
        frozenset({"id"}),
    ],
    # rka_update_mission_status(id: str, **kw) — id raises ValueError if
    # empty. status goes through _drop_none (falls through if None), so
    # the adapter tolerates status-less calls; we don't enforce it.
    "rka_update_mission_status": [
        frozenset({"id"}),
    ],
    # rka_bulk_update(updates: list[dict]) — updates is positional-required.
    "rka_bulk_update": [
        frozenset({"updates"}),
    ],
    # rka_ingest_document(content: str, **kw) — content raises
    # ValueError if empty or whitespace-only.
    "rka_ingest_document": [
        frozenset({"content"}),
    ],
}


def check_required_fields(tool: str, args: dict) -> list[str]:
    """Return a list of human-readable error reasons for any required
    alias-set in `tool`'s TOOL_REQUIRED_FIELDS entry that is NOT
    satisfied by `args`.

    Semantics:
      - For each alias-set, the requirement is satisfied if ANY field
        in the set is present in `args` with a truthy-string value
        (non-empty, non-whitespace-only) OR a truthy non-string value
        (e.g. a non-empty list / dict / a non-zero number).
      - A field whose value is None / '' / '   ' (whitespace-only) is
        treated as MISSING. This mirrors the adapter truthy-checks at
        mcp_client.py (e.g. `if not description:` in
        rka_submit_checkpoint at line 585; `if not content or not
        content.strip():` in rka_ingest_document at line 967) so the
        validator catches the empirical failure modes BEFORE the
        adapter-layer ValueError.
      - Unknown tool (not in TOOL_REQUIRED_FIELDS) returns []. The
        upstream WRITE_TOOLS allowlist check handles unknown-tool
        cases via `ratified_action_tool_not_allowed`.

    Open-world tolerance mirrors validate_action_args: this validator
    catches the empirical "missing-required-field" failure modes (e.g.
    rka_submit_checkpoint(content=...) without a description/message/
    reason alias) BEFORE the network round-trip. It does NOT replicate
    RKA's full Pydantic validation; the REST 422 path remains
    authoritative for the long-tail of field requirements.
    """
    required_sets = TOOL_REQUIRED_FIELDS.get(tool)
    if not required_sets:
        return []

    def _is_satisfied(value: object) -> bool:
        """True iff `value` would survive the adapter's truthy-check.

        Adversarial-review MEDIUM #1: the adapter truthy-checks reject
        '' and '   '; the validator must mirror this or the pre-dispatch
        guard is defeated for whitespace-only emissions.
        """
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        # Non-string truthy semantics: empty list/dict/0/False are also
        # rejected. The adapter's `if not X:` check applies uniformly.
        return bool(value)

    errors: list[str] = []
    for required_set in required_sets:
        satisfied = any(
            field in args and _is_satisfied(args[field])
            for field in required_set
        )
        if satisfied:
            continue
        sorted_alts = sorted(required_set)
        if len(sorted_alts) == 1:
            errors.append(
                f"{tool}: required field {sorted_alts[0]!r} is missing, "
                f"None, or empty"
            )
        else:
            errors.append(
                f"{tool}: at least one of {sorted_alts!r} is required "
                f"(all missing, None, or empty) — these are adapter-"
                f"accepted aliases for the same field"
            )
    return errors
