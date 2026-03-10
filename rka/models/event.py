"""Event stream models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Event(BaseModel):
    """Cross-entity event for causal chain tracking."""

    id: str
    timestamp: str | None = None
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    summary: str
    caused_by_event: str | None = None
    caused_by_entity: str | None = None
    phase: str | None = None
    details: dict[str, Any] | None = None
