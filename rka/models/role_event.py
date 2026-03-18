"""Role event models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RoleEventCreate(BaseModel):
    """Emit a role event (typically internal, but exposed for manual injection)."""

    target_role_id: str
    event_type: str
    source_role_id: str | None = None
    source_entity_id: str | None = None
    source_entity_type: str | None = None
    payload: dict | None = None
    priority: int = 100
    depends_on: str | None = None


class RoleEventAck(BaseModel):
    """Acknowledge a role event."""

    pass


class RoleEvent(BaseModel):
    """Full role event record from database."""

    id: str
    project_id: str
    target_role_id: str
    event_type: str
    source_role_id: str | None = None
    source_entity_id: str | None = None
    source_entity_type: str | None = None
    payload: dict | None = None
    status: Literal["pending", "processing", "acked", "expired"] = "pending"
    priority: int = 100
    depends_on: str | None = None
    created_at: str | None = None
    processed_at: str | None = None
    acked_at: str | None = None
