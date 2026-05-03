"""Context engine models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContextRequest(BaseModel):
    """Request for context preparation.

    `max_tokens` was removed in v2.4 (Improvement 1, dec_01KQQPD6Y6B362T3K08368BDMP):
    the context engine now ranks by SQL-time importance + entity_links centrality
    and returns the full ranked list. Frontier model context windows make a
    bookkeeper-imposed token budget unnecessary.
    """

    topic: str | None = None
    phase: str | None = None
    depth: Literal["summary", "detailed"] = "summary"


class ContextPackage(BaseModel):
    """Prepared context package for Brain/Executor.

    `entries` is the ranked list (highest-importance + most-central + most-recent
    first). The legacy `hot_entries` / `warm_entries` / `cold_entries` buckets
    are retained for backward-compat with existing UI code; the engine populates
    only `entries` going forward and leaves the bucket fields empty.
    """

    topic: str | None = None
    phase: str | None = None
    entries: list[str] = Field(default_factory=list)
    # Legacy buckets — kept to avoid breaking existing UI consumers.
    hot_entries: list[str] = Field(default_factory=list)
    warm_entries: list[str] = Field(default_factory=list)
    cold_entries: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    narrative: str | None = None
    note: str | None = None
    # Retained as informational; no longer drives truncation.
    token_estimate: int = 0
