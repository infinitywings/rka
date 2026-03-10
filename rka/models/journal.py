"""Research journal models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JournalEntryCreate(BaseModel):
    """Create a new journal entry."""

    content: str
    type: Literal[
        "finding", "insight", "pi_instruction", "exploration",
        "idea", "observation", "hypothesis", "methodology", "summary",
    ] = "finding"
    source: Literal["brain", "executor", "pi", "web_ui", "llm"] = "pi"
    phase: str | None = None
    related_decisions: list[str] | None = None
    related_literature: list[str] | None = None
    related_mission: str | None = None
    supersedes: str | None = None
    confidence: Literal["hypothesis", "tested", "verified", "superseded", "retracted"] = "hypothesis"
    importance: Literal["critical", "high", "normal", "low", "archived"] = "normal"
    tags: list[str] = Field(default_factory=list)


class JournalEntryUpdate(BaseModel):
    """Partial update for journal entry."""

    content: str | None = None
    type: Literal[
        "finding", "insight", "pi_instruction", "exploration",
        "idea", "observation", "hypothesis", "methodology", "summary",
    ] | None = None
    summary: str | None = None
    confidence: Literal["hypothesis", "tested", "verified", "superseded", "retracted"] | None = None
    importance: Literal["critical", "high", "normal", "low", "archived"] | None = None
    related_decisions: list[str] | None = None
    related_literature: list[str] | None = None
    related_mission: str | None = None
    tags: list[str] | None = None


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
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
