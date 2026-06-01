"""Mission lifecycle models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MissionTask(BaseModel):
    """A single task within a mission."""

    description: str
    status: Literal["pending", "in_progress", "complete", "blocked", "skipped"] = "pending"
    commit_hash: str | None = None
    completed_at: str | None = None


class MissionCreate(BaseModel):
    """Create a new mission.

    extra="forbid": undeclared fields raise 422 instead of silently stripping.
    Mirrors the MissionUpdate guard added by Bug A; closes the parallel
    CREATE-path silent-write hole identified by Mission C
    (mis_01KR43RX9KY11GAPTPPGK9XSDE).
    """

    model_config = ConfigDict(extra="forbid")

    phase: str
    objective: str
    tasks: list[MissionTask] | None = None
    context: str | None = None
    acceptance_criteria: str | None = None
    scope_boundaries: str | None = None
    checkpoint_triggers: str | None = None
    depends_on: str | None = None
    motivated_by_decision: str | None = None
    tags: list[str] = Field(default_factory=list)


class MissionUpdate(BaseModel):
    """Partial update for mission.

    extra="forbid": undeclared fields raise 422 instead of silently stripping.
    See mis_01KQJH9MB65AR0GSVPQBT8707X (silent-write-failure fix) for context.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "active", "complete", "partial", "blocked", "cancelled"] | None = None
    tasks: list[MissionTask] | None = None
    objective: str | None = None
    phase: str | None = None
    context: str | None = None
    acceptance_criteria: str | None = None
    scope_boundaries: str | None = None
    checkpoint_triggers: str | None = None
    depends_on: str | None = None
    parent_mission_id: str | None = None
    motivated_by_decision: str | None = None
    tags: list[str] | None = None


class MissionReportCreate(BaseModel):
    """Executor's structured report for a completed mission.

    extra="forbid" defense-in-depth — see MissionCreate for context.

    v2.6.1 — `summary` is now a first-class field on the schema. The
    MCP tool `rka_submit_report` previously exposed `summary: str` in
    its signature but synthesised it as `tasks_completed=[summary]`
    in the wrapper (rka/mcp/server.py:1313) — a schema-lie that
    misled any Brain LLM reading the canonical OpenAPI schema. Per
    the Phase-X²' polish roadmap (v2.6.x cycle, see
    orchestrator/docs/v2.6.x-roadmap.md §6), summary is now stored
    in its own field; the synthetic tasks_completed=[summary] wrap
    is retained for one release as a back-compat fallback for
    downstream readers that haven't migrated.
    """

    model_config = ConfigDict(extra="forbid")

    # v2.6.1 — first-class `summary` field. Was synthesised via
    # tasks_completed=[summary] pre-v2.6.1; both code paths populated
    # for one-release migration window.
    summary: str | None = None
    tasks_completed: list[str] | None = None
    findings: list[str] | None = None
    anomalies: list[str] | None = None
    questions: list[str] | None = None
    codebase_state: str | None = None
    recommended_next: str | None = None


class MissionReport(BaseModel):
    """Stored mission report."""

    mission_id: str
    # v2.6.1 — first-class `summary` (see MissionReportCreate
    # docstring for the migration note).
    summary: str | None = None
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
    iteration: int = 1
    parent_mission_id: str | None = None
    motivated_by_decision: str | None = None
    tags: list[str] = Field(default_factory=list)
    enrichment_status: Literal["pending", "ready", "failed"] = "ready"
    created_at: str | None = None
    completed_at: str | None = None
