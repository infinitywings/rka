"""Pydantic models for the v2.3 hook system (migration 019).

See ``rka/skills/brain/decision_ux.md`` (v2.2.x override-rate) for drift hooks
and ``rka/skills/brain/workflows.md`` for hook registration patterns.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


HookEvent = Literal[
    "session_start",
    "post_journal_create",
    "post_claim_extract",
    "post_record_outcome",
    "periodic",
]

HandlerType = Literal["sql", "mcp_tool", "brain_notify"]

ExecutionStatus = Literal[
    "success",
    "error",
    "aborted_depth_limit",
    "skipped_disabled",
]

NotificationSeverity = Literal["info", "warning", "critical"]


class HookCreate(BaseModel):
    """Create payload for a hook registration."""

    model_config = ConfigDict(extra="forbid")

    event: HookEvent
    handler_type: HandlerType
    handler_config: dict[str, Any]
    name: str
    enabled: bool = True
    created_by: Literal["pi", "brain", "executor", "system"] = "pi"


class Hook(BaseModel):
    """Full hook row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    event: HookEvent
    scope: Literal["project"] = "project"
    project_id: str
    handler_type: HandlerType
    handler_config: dict[str, Any]
    enabled: bool
    name: str
    created_by: str
    created_at: str
    failure_policy: Literal["silent"] = "silent"


class HookExecution(BaseModel):
    """Full hook_executions row — audit entry for one hook firing."""

    model_config = ConfigDict(extra="forbid")

    id: str
    hook_id: str
    project_id: str
    fired_at: str
    payload: dict[str, Any] | None = None
    handler_result: dict[str, Any] | None = None
    status: ExecutionStatus
    error_message: str | None = None
    depth: int = 0


class BrainNotification(BaseModel):
    """Row from brain_notifications — an async message surfaced at session_start."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    hook_id: str | None = None
    created_at: str
    cleared_at: str | None = None
    content: dict[str, Any]
    severity: NotificationSeverity = "info"
