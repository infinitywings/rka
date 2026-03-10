"""Context engine models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContextRequest(BaseModel):
    """Request for context preparation."""

    topic: str | None = None
    phase: str | None = None
    depth: Literal["summary", "detailed"] = "summary"
    max_tokens: int = 2000


class ContextPackage(BaseModel):
    """Prepared context package for Brain/Executor."""

    topic: str | None = None
    phase: str | None = None
    hot_entries: list[str] = Field(default_factory=list)
    warm_entries: list[str] = Field(default_factory=list)
    cold_entries: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    narrative: str | None = None
    note: str | None = None
    token_estimate: int = 0
