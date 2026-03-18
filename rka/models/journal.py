"""Research journal models."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# v2.0 canonical types
JournalType = Literal["note", "log", "directive"]

# Legacy types accepted for backward compatibility (silently mapped to v2 types)
LegacyJournalType = Literal[
    "finding", "insight", "pi_instruction", "exploration",
    "idea", "observation", "hypothesis", "methodology", "summary",
]

# Combined type for input validation (accepts both old and new)
AnyJournalType = Literal[
    "finding", "insight", "pi_instruction", "exploration",
    "idea", "observation", "hypothesis", "methodology", "summary",
    "note", "log", "directive",
]

# Mapping from legacy types to v2 types
JOURNAL_TYPE_MAP: dict[str, str] = {
    "finding": "note",
    "insight": "note",
    "idea": "note",
    "observation": "note",
    "exploration": "note",
    "hypothesis": "note",
    "summary": "note",
    "methodology": "log",
    "pi_instruction": "directive",
    # v2 types map to themselves
    "note": "note",
    "log": "log",
    "directive": "directive",
}


def normalize_journal_type(raw_type: str) -> str:
    """Map any journal type (legacy or v2) to the canonical v2 type."""
    mapped = JOURNAL_TYPE_MAP.get(raw_type)
    if mapped is None:
        raise ValueError(f"Unknown journal type: {raw_type!r}")
    if mapped != raw_type:
        logger.debug("Mapped legacy journal type %r → %r", raw_type, mapped)
    return mapped


class JournalEntryCreate(BaseModel):
    """Create a new journal entry."""

    content: str
    type: AnyJournalType = "note"
    source: Literal["brain", "executor", "pi", "web_ui", "llm"] = "pi"
    phase: str | None = None
    related_decisions: list[str] | None = None
    related_literature: list[str] | None = None
    related_mission: str | None = None
    supersedes: str | None = None
    confidence: Literal["hypothesis", "tested", "verified", "superseded", "retracted"] = "hypothesis"
    importance: Literal["critical", "high", "normal", "low", "archived"] = "normal"
    status: Literal["draft", "active", "superseded", "retracted"] = "active"
    pinned: bool = False
    tags: list[str] = Field(default_factory=list)
    # v2.1: structured provenance and role identity
    provenance: dict | str | None = None
    role_id: str | None = None

    @model_validator(mode="after")
    def _normalize_type(self) -> JournalEntryCreate:
        self.type = normalize_journal_type(self.type)  # type: ignore[assignment]
        return self


class JournalEntryUpdate(BaseModel):
    """Partial update for journal entry."""

    content: str | None = None
    type: AnyJournalType | None = None
    summary: str | None = None
    source: Literal["brain", "executor", "pi", "web_ui", "llm"] | None = None
    phase: str | None = None
    confidence: Literal["hypothesis", "tested", "verified", "superseded", "retracted"] | None = None
    importance: Literal["critical", "high", "normal", "low", "archived"] | None = None
    status: Literal["draft", "active", "superseded", "retracted"] | None = None
    pinned: bool | None = None
    related_decisions: list[str] | None = None
    related_literature: list[str] | None = None
    related_mission: str | None = None
    tags: list[str] | None = None
    # v2.1
    provenance: dict | str | None = None
    role_id: str | None = None

    @model_validator(mode="after")
    def _normalize_type(self) -> JournalEntryUpdate:
        if self.type is not None:
            self.type = normalize_journal_type(self.type)  # type: ignore[assignment]
        return self


class JournalEntry(BaseModel):
    """Full journal entry from database."""

    id: str
    type: str
    content: str
    summary: str | None = None
    source: str
    phase: str | None = None
    related_decisions: list[str] | None = None
    related_literature: list[str] | None = None
    related_mission: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    confidence: str
    importance: str
    status: str = "active"
    pinned: bool = False
    tags: list[str] = Field(default_factory=list)
    enrichment_status: Literal["pending", "ready", "failed"] = "ready"
    # v2.1
    provenance: dict | str | None = None
    role_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
