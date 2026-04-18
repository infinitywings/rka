"""Decision tree models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DecisionOption(BaseModel):
    """A single option in a decision."""

    label: str
    description: str = ""
    explored: bool = False


class DecisionCreate(BaseModel):
    """Create a new decision node."""

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


class DecisionUpdate(BaseModel):
    """Partial update for a decision."""

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
