"""Mission lifecycle models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MissionTask(BaseModel):
    """A single task within a mission."""

    description: str
    status: Literal["pending", "in_progress", "complete", "blocked", "skipped"] = "pending"
    commit_hash: str | None = None
    completed_at: str | None = None


class MissionCreate(BaseModel):
    """Create a new mission."""

    phase: str
    objective: str
    tasks: list[MissionTask] | None = None
    context: str | None = None
    acceptance_criteria: str | None = None
    scope_boundaries: str | None = None
    checkpoint_triggers: str | None = None
    depends_on: str | None = None
    tags: list[str] = Field(default_factory=list)


class MissionUpdate(BaseModel):
    """Partial update for mission."""

    status: Literal["pending", "active", "complete", "partial", "blocked", "cancelled"] | None = None
    tasks: list[MissionTask] | None = None
    objective: str | None = None


class MissionReportCreate(BaseModel):
    """Executor's structured report for a completed mission."""

    tasks_completed: list[str] | None = None
    findings: list[str] | None = None
    anomalies: list[str] | None = None
    questions: list[str] | None = None
    codebase_state: str | None = None
    recommended_next: str | None = None


class MissionReport(BaseModel):
    """Stored mission report."""

    mission_id: str
    tasks_completed: list[str] | None = None
    findings: list[str] | None = None
    anomalies: list[str] | None = None
    questions: list[str] | None = None
    codebase_state: str | None = None
    recommended_next: str | None = None
    submitted_at: str | None = None


class Mission(BaseModel):
    """Full mission record from database."""

    id: str
    phase: str
    objective: str
    tasks: list[MissionTask] | None = None
    context: str | None = None
    acceptance_criteria: str | None = None
    scope_boundaries: str | None = None
    checkpoint_triggers: str | None = None
    status: str
    depends_on: str | None = None
    report: MissionReport | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    completed_at: str | None = None
