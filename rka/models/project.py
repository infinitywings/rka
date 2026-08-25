"""Project state models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    """Partial update for project state.

    extra="forbid": undeclared fields raise 422 instead of silently stripping.
    See mis_01KQJH9MB65AR0GSVPQBT8707X (silent-write-failure fix) for context.
    """

    model_config = ConfigDict(extra="forbid")

    project_name: str | None = None
    project_description: str | None = None
    current_phase: str | None = None
    phases_config: list[str] | None = None
    summary: str | None = None
    blockers: str | list[str] | None = None
    metrics: dict[str, Any] | None = None

    @field_validator("blockers", mode="before")
    @classmethod
    def _blockers_to_text(cls, v: Any) -> Any:
        """Accept a list, store the free text the column is declared as.

        `project_status.blockers` is `TEXT -- Current blockers (free text)`,
        and this model matched it. The typed MCP surface advertises
        `Optional[list[str]]`, so every list sent through the connector died
        at this boundary with `Input should be a valid string` — the two
        halves of one field disagreed, and the half a caller reads in
        `rka_describe` was the half that could not be written.

        Widening here rather than joining in the MCP dispatcher fixes it for
        REST and the web UI too, and leaves storage and the read model alone.
        Entries are joined verbatim, without renumbering: callers that
        already number their own lines must not get numbered twice.
        """
        if isinstance(v, list):
            joined = "\n".join(str(item).strip() for item in v if str(item).strip())
            return joined or None
        return v


class ProjectInfo(BaseModel):
    """Project metadata."""

    id: str
    name: str
    description: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectCreate(BaseModel):
    """Create a new project container.

    extra="forbid" defense-in-depth — see Mission C
    (mis_01KR43RX9KY11GAPTPPGK9XSDE) for context.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    description: str | None = None
    phases_config: list[str] | None = None
