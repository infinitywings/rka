"""Audit log models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AuditEntry(BaseModel):
    """Audit log entry from database."""

    id: int
    action: str
    entity_type: str
    entity_id: str | None = None
    actor: str | None = None
    details: dict[str, Any] | None = None
    created_at: str | None = None
