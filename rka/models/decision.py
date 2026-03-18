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
    # v2.1
    role_id: str | None = None


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
    enrichment_status: Literal["pending", "ready", "failed"] = "ready"
    # v2.1
    role_id: str | None = None
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
