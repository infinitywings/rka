"""Shared Literal enum type aliases for the RKA MCP surface.

Single source of truth for RKA enum surfaces. Promotes
``Annotated[Literal[...]]`` enum sets from ``rka/mcp/server.py`` module-level
aliases into a shared module so v2.7.0 verbs and any future v2.6.x patches
consume the same source. The orchestrator-side mirror at
``orchestrator/orchestrator/rka_enums.py`` MUST stay in sync — bookkeeper
invariant forbids the orchestrator from importing from ``rka``.

Each name here is a **plain** ``typing.Literal[...]`` alias — NOT
``Annotated``. Wrappers like
``Annotated[ConfidenceLit, Field(description="...")]`` live at the call
site (in ``server.py`` verbs) per FastMCP norms; the description belongs
with the parameter, not with the type.

Source of truth (reconcile drift against these files):
  - ``rka/db/schema.sql`` (SQLite CHECK constraints — migrations
    009 + 015 + 019 cover journal / decision / checkpoint columns)
  - ``rka/models/journal.py`` (JournalEntry — accepts the schema's CHECK
    set plus a legacy-normalized superset that the server silently maps
    via ``JOURNAL_TYPE_MAP`` for back-compat)
  - ``rka/models/decision.py`` (Decision — kind / status / decided_by)
  - ``rka/models/checkpoint.py`` (Checkpoint — type / resolved_by)
  - ``rka/models/literature.py`` (Literature — status / added_by)
  - ``rka/models/claim.py`` (Claim / EvidenceCluster — claim_type /
    cluster confidence)
  - ``rka/models/calibration.py`` (Outcome on rka_record_outcome)
  - ``rka/api/missions.py`` (mission lifecycle status enum)
  - ``rka/services/researcher_tools.py`` (RQ lifecycle, staleness
    levels, gate verdicts — string sets validated at the service
    layer, mirrored here for FastMCP enum rendering)

If you bump RKA's schema or Pydantic enums, search this file for the
affected Literal and update both. The orchestrator-side mirror at
``orchestrator/orchestrator/rka_enums.py`` is independently maintained
under the bookkeeper invariant — coordinate updates manually.
"""

from __future__ import annotations

from typing import Literal


# ---------------------------------------------------------------------------
# Journal entries (rka_record_note / rka_add_note / rka_update_note)
# ---------------------------------------------------------------------------

# Confidence on journal entries — see ``rka/db/schema.sql`` CHECK on
# ``journal.confidence`` and ``rka/models/journal.py``. Run-5's empirical
# Brain hallucination was ``'confirmed'`` — NOT in this set.
ConfidenceLit = Literal[
    "hypothesis", "tested", "verified", "superseded", "retracted",
]

# Importance on journal entries — ``rka/db/schema.sql`` CHECK on
# ``journal.importance``.
ImportanceLit = Literal[
    "critical", "high", "normal", "low", "archived",
]

# Actor-of-record across journal / decision / literature writes —
# ``rka/db/schema.sql`` CHECK on ``journal.source`` (note: ``import`` is
# not in the journal-source set; the document-ingestion path widens it
# via ``IngestSourceLit`` below).
SourceLit = Literal["brain", "executor", "pi", "web_ui", "llm"]

# Journal type — v2 canonical set plus legacy-accepted superset (silently
# normalized via ``JOURNAL_TYPE_MAP``). See ``rka/models/journal.py``
# ``AnyJournalType``.
NoteTypeLit = Literal[
    # v2 canonical
    "note", "log", "directive",
    # Legacy (accepted; normalized to one of the v2 set above)
    "finding", "insight", "pi_instruction", "exploration",
    "idea", "observation", "hypothesis", "methodology", "summary",
]


# ---------------------------------------------------------------------------
# Decisions (rka_record_decision / rka_add_decision / rka_update_decision)
# ---------------------------------------------------------------------------

# Who decided this — ``rka/db/schema.sql`` CHECK on ``decisions.decided_by``.
# PI for ratified, Brain for proposed; Executor for self-reported
# operational decisions.
DecidedByLit = Literal["pi", "brain", "executor"]

# Decision kind — ``rka/db/schema.sql`` and ``rka/models/decision.py``.
# ``research_question`` is reserved for advanceable RQs (see
# ``rka_advance_rq``); most decisions are ``decision`` or ``design_choice``.
DecisionKindLit = Literal[
    "research_question", "design_choice", "decision", "operational",
]


# ---------------------------------------------------------------------------
# Literature (rka_record_literature / rka_add_literature / rka_update_literature)
# ---------------------------------------------------------------------------

# Reading lifecycle on a literature entry — ``rka/db/schema.sql`` CHECK
# on ``literature.status``.
LitStatusLit = Literal[
    "to_read", "reading", "read", "cited", "excluded",
]


# ---------------------------------------------------------------------------
# Missions (rka_mission)
# ---------------------------------------------------------------------------

# Mission lifecycle status — ``rka/db/schema.sql`` CHECK on
# ``missions.status``.
MissionStatusLit = Literal[
    "pending", "active", "complete", "partial", "blocked", "cancelled",
]


# ---------------------------------------------------------------------------
# Checkpoints + Gates (rka_checkpoint)
# ---------------------------------------------------------------------------

# Checkpoint type — ``rka/db/schema.sql`` CHECK on ``checkpoints.type``
# (note: schema lists 'decision', 'clarification', 'inspection'; the
# Pydantic ``CheckpointCreate`` in ``rka/models/checkpoint.py`` widens
# to include ``'gate'`` for the validation-gate subtype). The v2.7.0
# verb surface accepts the Pydantic-level set.
ChkTypeLit = Literal[
    "decision", "clarification", "inspection", "gate",
]

# Validation-gate subtype — string-set validated in
# ``rka/services/researcher_tools.py`` and the legacy
# ``rka_create_gate`` MCP tool.
GateTypeLit = Literal[
    "problem_framing", "plan_validation", "evidence_review",
    "synthesis_validation",
]

# Gate verdict — string-set validated in
# ``rka/services/researcher_tools.py`` and the legacy
# ``rka_evaluate_gate`` MCP tool.
VerdictLit = Literal["go", "kill", "hold", "recycle"]


# ---------------------------------------------------------------------------
# Claims + Clusters (rka_review on claim / cluster targets)
# ---------------------------------------------------------------------------

# Claim type — ``rka/models/claim.py`` ``ClaimType``.
ClaimTypeLit = Literal[
    "hypothesis", "evidence", "method", "result", "observation", "assumption",
]

# Cluster confidence — ``rka/models/claim.py`` ``ClusterConfidence``.
ClusterConfLit = Literal[
    "strong", "moderate", "emerging", "contested", "refuted",
]


# ---------------------------------------------------------------------------
# Research questions (rka_mission action='advance_rq')
# ---------------------------------------------------------------------------

# RQ lifecycle status — string-set validated in
# ``rka/services/researcher_tools.py::advance_rq``. Stored as ``rq:*`` tag
# on the underlying decision row (the ``decisions.status`` column owns
# the decision-level lifecycle and is a different CHECK set).
RQStatusLit = Literal[
    "open", "partially_answered", "answered", "reframed", "closed",
]


# ---------------------------------------------------------------------------
# Calibration outcomes (rka_review target='outcome')
# ---------------------------------------------------------------------------

# Outcome on a calibration record — ``rka/models/calibration.py``
# ``Outcome`` (matches the ``calibration_outcomes`` CHECK constraint).
OutcomeLit = Literal["succeeded", "failed", "mixed", "unresolved"]


# ---------------------------------------------------------------------------
# Staleness (rka_review target='stale')
# ---------------------------------------------------------------------------

# Staleness severity — string-set validated in
# ``rka/services/researcher_tools.py::flag_stale``. Stored on
# ``claims.staleness`` / ``evidence_clusters.staleness`` columns.
StalenessLit = Literal["yellow", "red"]


# ---------------------------------------------------------------------------
# Document ingestion (rka_ingest_document)
# ---------------------------------------------------------------------------

# Actor-of-record for the ingested document. Widens ``SourceLit`` with
# ``'import'`` for batch-import workflows (mirrors
# ``rka/db/schema.sql`` ``literature.added_by`` CHECK set).
IngestSourceLit = Literal["brain", "executor", "pi", "import", "web_ui"]
