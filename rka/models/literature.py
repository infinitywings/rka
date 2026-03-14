"""Literature models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LiteratureCreate(BaseModel):
    """Create a new literature entry."""

    title: str
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    bibtex: str | None = None
    pdf_path: str | None = None
    abstract: str | None = None
    status: Literal["to_read", "reading", "read", "cited", "excluded"] = "to_read"
    key_findings: list[str] | None = None
    methodology_notes: str | None = None
    relevance: str | None = None
    relevance_score: float | None = None
    related_decisions: list[str] | None = None
    added_by: Literal["brain", "executor", "pi", "import", "web_ui"] = "pi"
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class LiteratureUpdate(BaseModel):
    """Partial update for literature."""

    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    bibtex: str | None = None
    pdf_path: str | None = None
    abstract: str | None = None
    status: Literal["to_read", "reading", "read", "cited", "excluded"] | None = None
    key_findings: list[str] | None = None
    methodology_notes: str | None = None
    relevance: str | None = None
    relevance_score: float | None = None
    related_decisions: list[str] | None = None
    notes: str | None = None
    tags: list[str] | None = None


class Literature(BaseModel):
    """Full literature record from database."""

    id: str
    title: str
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    bibtex: str | None = None
    pdf_path: str | None = None
    abstract: str | None = None
    status: str
    key_findings: list[str] | None = None
    methodology_notes: str | None = None
    relevance: str | None = None
    relevance_score: float | None = None
    related_decisions: list[str] | None = None
    added_by: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    enrichment_status: Literal["pending", "ready", "failed"] = "ready"
    created_at: str | None = None
    updated_at: str | None = None
