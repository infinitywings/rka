"""Review queue models (v2.0 — Brain-augmented enrichment)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


ReviewFlag = Literal[
    "low_confidence_cluster",
    "potential_contradiction",
    "complex_synthesis_needed",
    "re_distill_review",
    "cross_topic_link",
    "stale_theme",
]

ReviewStatus = Literal["pending", "acknowledged", "resolved", "dismissed"]


class ReviewItemCreate(BaseModel):
    """Flag an item for Brain review."""

    item_type: str
    item_id: str
    flag: ReviewFlag
    context: Any = None
    priority: int = 100
    raised_by: str = "llm"


class ReviewItemResolve(BaseModel):
    """Resolve a review queue item."""

    status: ReviewStatus = "resolved"
    resolved_by: str
    resolution: str


class ReviewItem(BaseModel):
    """Full review queue item from database."""

    id: str
    item_type: str
    item_id: str
    flag: str
    context: Any = None
    priority: int = 100
    status: str = "pending"
    raised_by: str = "llm"
    resolved_by: str | None = None
    resolution: str | None = None
    project_id: str = "proj_default"
    created_at: str | None = None
    resolved_at: str | None = None
