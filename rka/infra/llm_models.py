"""Pydantic models for multimodal LLM extraction, summaries, and QA."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Figure & Table Extraction ----------

class FigureClaim(BaseModel):
    """A single factual claim extracted from a figure or table."""
    claim: str = Field(..., description="The factual claim text.")
    numeric_value: float | None = Field(None, description="Numeric value if the claim is quantitative.")
    unit: str | None = Field(None, description="Unit of measurement for the numeric value.")
    provenance: str | None = Field(
        None, description="Locator for the claim, e.g. 'page:5|figure:3'.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this claim (0=guess, 1=certain).")


class FigureExtraction(BaseModel):
    """Structured data extracted from a figure or image."""
    caption: str | None = Field(None, description="Extracted or inferred caption text.")
    caption_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in caption extraction.")
    summary: str = Field(..., description="One-paragraph summary of what the figure shows.")
    claims: list[FigureClaim] = Field(default_factory=list, description="Factual claims extracted from the figure.")
    table_like: bool = Field(False, description="Whether the figure is actually a table.")
    suggested_journal_entries: list[str] = Field(
        default_factory=list,
        description="Suggested journal entry texts for notable findings in this figure.",
    )


class TableRow(BaseModel):
    """A single row from an extracted table."""
    cells: list[str] = Field(..., description="Cell values in order.")


class TableExtraction(BaseModel):
    """Structured table data extracted from a document."""
    title: str | None = Field(None, description="Table title or caption.")
    headers: list[str] = Field(default_factory=list, description="Column headers.")
    rows: list[TableRow] = Field(default_factory=list, description="Table rows.")
    summary: str = Field(..., description="One-sentence summary of the table contents.")
    claims: list[FigureClaim] = Field(default_factory=list, description="Key factual claims from the table.")


# ---------- Multi-granularity Summaries ----------

class SummarySource(BaseModel):
    """A source reference for a generated summary."""
    entity_type: str = Field(..., description="Entity type: journal, decision, mission, literature, etc.")
    entity_id: str = Field(..., description="Entity ID.")
    excerpt: str = Field(..., description="Key excerpt from this source used in the summary.")
    loc: str | None = Field(None, description="Optional locator (page, section, etc.).")


class SummaryOutput(BaseModel):
    """Multi-granularity summary with source citations."""
    one_line: str = Field(..., max_length=300, description="One-line summary.")
    paragraph: str = Field(..., description="One-paragraph summary with key points.")
    narrative: str | None = Field(None, description="Multi-paragraph narrative (for 'narrative' granularity).")
    key_questions: list[str] = Field(
        default_factory=list,
        description="Open questions or gaps identified during summarization.",
    )
    sources: list[SummarySource] = Field(default_factory=list, description="Sources cited in the summary.")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Overall confidence in the summary.")


# ---------- QA (NotebookLM-style) ----------

class QASource(BaseModel):
    """A source reference for a QA answer."""
    entity_type: str = Field(..., description="Entity type: journal, decision, mission, literature, etc.")
    entity_id: str = Field(..., description="Entity ID.")
    excerpt: str = Field(..., description="Exact quoted excerpt from the source supporting the answer.")
    loc: str | None = Field(None, description="Optional locator.")


class QAAnswer(BaseModel):
    """Structured answer to a research question with grounded sources."""
    answer: str = Field(..., description="The answer text.")
    answer_type: Literal["short", "detailed", "list", "table"] = Field(
        "detailed", description="Format of the answer.",
    )
    sources: list[QASource] = Field(default_factory=list, description="Sources grounding the answer.")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence in the answer.")
    followups: list[str] = Field(
        default_factory=list,
        description="Suggested follow-up questions.",
    )


# ---------- Verification ----------

class VerificationResult(BaseModel):
    """Result of verifying a claimed excerpt against stored data."""
    verified: bool = Field(..., description="Whether the excerpt was found in the source.")
    matched_text: str | None = Field(None, description="Actual text that matched (if verified).")
    entity_type: str | None = None
    entity_id: str | None = None
    reason: str | None = Field(None, description="Why verification failed, if applicable.")
