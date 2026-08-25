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

    v2.5.4 (D4 — dec_01KS0C4PG88F29YBR91VQ3RRXY): `anchor_aware_present` and
    `anchor_aware_ids` enable bundle-truncation when the caller's composed
    sequence already includes anchor-aware tools (rka_get_ego_graph /
    rka_multi_hop_retrieval / rka_assemble_evidence). The context engine caps
    its overview-path bundle to top-K (env-configurable via
    `RKA_CTX_BUNDLE_K`, default 30) and UNIONs anchor-aware tool outputs
    through the cap. Backward compat: defaults preserve v2.5.3 behavior.
    """

    topic: str | None = None
    phase: str | None = None
    anchor_aware_present: bool = False
    anchor_aware_ids: list[str] | None = None


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
