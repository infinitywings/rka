"""Checkpoint models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CheckpointOption(BaseModel):
    """A single option in a checkpoint."""

    label: str
    description: str = ""
    consequence: str = ""


class CheckpointCreate(BaseModel):
    """Create a new checkpoint (Executor submits)."""

    mission_id: str
    task_reference: str | None = None
    type: Literal["decision", "clarification", "inspection"]
    description: str
    context: str | None = None
    options: list[CheckpointOption] | None = None
    recommendation: str | None = None
    blocking: bool = True


class CheckpointResolve(BaseModel):
    """Resolve a checkpoint (Brain/PI resolves)."""

    resolution: str
    resolved_by: Literal["pi", "brain"]
    rationale: str | None = None
    create_decision: bool = False


class Checkpoint(BaseModel):
    """Full checkpoint record from database."""

    id: str
    mission_id: str | None = None
    task_reference: str | None = None
    type: str
    description: str
    context: str | None = None
    options: list[CheckpointOption] | None = None
    recommendation: str | None = None
    blocking: bool = True
    resolution: str | None = None
    resolved_by: str | None = None
    resolution_rationale: str | None = None
    linked_decision_id: str | None = None
    status: str = "open"
    created_at: str | None = None
    resolved_at: str | None = None
