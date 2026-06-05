"""Decision tree models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DecisionOption(BaseModel):
    """A single option in a decision."""

    label: str
    description: str = ""
    explored: bool = False


class DecisionCreate(BaseModel):
    """Create a new decision node.

    extra="forbid": undeclared fields raise 422 instead of silently stripping.
    Mirrors the DecisionUpdate guard added by Bug A; closes the parallel
    CREATE-path silent-write hole identified by Mission C
    (mis_01KR43RX9KY11GAPTPPGK9XSDE) — `assumptions` was being silently
    dropped by rka_add_decision callers because Bug A's commit added it
    to DecisionUpdate but missed DecisionCreate.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[DecisionOption] | None = None
    chosen: str | None = None
    rationale: str | None = None
    decided_by: Literal["pi", "brain", "executor"]
    parent_id: str | None = None
    phase: str
    related_missions: list[str] | None = None
    related_literature: list[str] | None = None
    related_journal: list[str] | None = None
    status: Literal["active", "abandoned", "superseded", "merged", "revisit"] = "active"
    kind: Literal["research_question", "design_choice", "decision", "operational"] = "decision"
    tags: list[str] = Field(default_factory=list)
    # Migration 014 — assumptions this decision rests on. Bug A added this
    # to DecisionUpdate but missed DecisionCreate; Mission C closes the gap.
    assumptions: list[str] | None = None


class DecisionSupersedeBody(BaseModel):
    """Body for POST /api/decisions/{old}/supersede (v2.7.0.6).

    Same shape as `DecisionCreate` EXCEPT `phase` is optional. When
    omitted (or empty string), the service layer inherits the phase
    from the OLD decision being superseded — under the v2.7.0.6
    ratified semantic, a supersede 'overturns the decision in its
    original phase slot' rather than re-tagging it to the PI session's
    current phase. Callers crossing phases on supersede must supply
    `phase` explicitly.

    Defense-in-depth: this model is bound on the supersede route ONLY;
    plain POST /api/decisions still binds to `DecisionCreate` whose
    `phase: str` is required-no-default.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[DecisionOption] | None = None
    chosen: str | None = None
    rationale: str | None = None
    decided_by: Literal["pi", "brain", "executor"]
    parent_id: str | None = None
    # v2.7.0.6 — phase optional; service inherits from OLD when empty.
    phase: str | None = None
    related_missions: list[str] | None = None
    related_literature: list[str] | None = None
    related_journal: list[str] | None = None
    status: Literal["active", "abandoned", "superseded", "merged", "revisit"] = "active"
    kind: Literal["research_question", "design_choice", "decision", "operational"] = "decision"
    tags: list[str] = Field(default_factory=list)
    assumptions: list[str] | None = None


class DecisionUpdate(BaseModel):
    """Partial update for a decision.

    extra="forbid": undeclared fields raise 422 instead of silently stripping.
    See mis_01KQJH9MB65AR0GSVPQBT8707X (silent-write-failure fix) for context.
    """

    model_config = ConfigDict(extra="forbid")

    question: str | None = None
    options: list[DecisionOption] | None = None
    chosen: str | None = None
    rationale: str | None = None
    status: Literal["active", "abandoned", "superseded", "merged", "revisit"] | None = None
    abandonment_reason: str | None = None
    parent_id: str | None = None
    related_missions: list[str] | None = None
    related_literature: list[str] | None = None
    related_journal: list[str] | None = None
    kind: Literal["research_question", "design_choice", "decision", "operational"] | None = None
    phase: str | None = None
    tags: list[str] | None = None
    # Migration 014 — assumptions this decision rests on.
    assumptions: list[str] | None = None
    # Migration 017 multi-choice columns (v2.2). pi_selected_option_id and
    # pi_override_rationale go through PUT /decisions/{id}/pi_selection rather
    # than this endpoint; only presentation_method is a general-update field.
    presentation_method: str | None = None


class Decision(BaseModel):
    """Full decision record from database."""

    id: str
    parent_id: str | None = None
    phase: str
    question: str
    options: list[DecisionOption] | None = None
    chosen: str | None = None
    rationale: str | None = None
    decided_by: str
    status: str
    abandonment_reason: str | None = None
    related_missions: list[str] | None = None
    related_literature: list[str] | None = None
    related_journal: list[str] | None = None
    superseded_by: str | None = None
    scope_version: int = 1
    kind: str = "decision"
    tags: list[str] = Field(default_factory=list)
    # Migration 014 — assumptions this decision rests on.
    assumptions: list[str] | None = None
    # Migration 017 — multi-choice decision UX columns (v2.2).
    recommended_option_id: str | None = None
    pi_selected_option_id: str | None = None
    pi_override_rationale: str | None = None
    presentation_method: str | None = None
    enrichment_status: Literal["pending", "ready", "failed"] = "ready"
    created_at: str | None = None
    updated_at: str | None = None


class DecisionTreeNode(BaseModel):
    """Decision tree node with children (for tree rendering)."""

    id: str
    question: str
    status: str
    chosen: str | None = None
    phase: str
    children: list[DecisionTreeNode] = Field(default_factory=list)
