"""Project state models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectState(BaseModel):
    """Singleton project state."""

    project_name: str
    project_description: str | None = None
    current_phase: str | None = None
    phases_config: list[str] | None = Field(
        default=None,
        description="Ordered list of phase names",
    )
    summary: str | None = None
    blockers: str | None = None
    metrics: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectStateUpdate(BaseModel):
    """Partial update for project state."""

    project_name: str | None = None
    project_description: str | None = None
    current_phase: str | None = None
    phases_config: list[str] | None = None
    summary: str | None = None
    blockers: str | None = None
    metrics: dict[str, Any] | None = None
