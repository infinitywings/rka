"""Workspace bootstrap models — scan, classify, ingest."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------- Enums ----------

class FileCategory(str, Enum):
    """Extension-based file category."""
    markdown = "markdown"
    text = "text"
    bibtex = "bibtex"
    pdf = "pdf"
    code = "code"
    document = "document"
    data = "data"
    unknown = "unknown"


class ContentHint(str, Enum):
    """Content heuristic classification for text-based files."""
    meeting_notes = "meeting_notes"
    paper_manuscript = "paper_manuscript"
    brainstorm = "brainstorm"
    action_items = "action_items"
    code_documentation = "code_documentation"
    structured_document = "structured_document"
    literature_review = "literature_review"
    experimental_results = "experimental_results"
    general = "general"


class IngestionTarget(str, Enum):
    """How a file should be ingested into the knowledge base."""
    ingest_document = "ingest_document"
    import_bibtex = "import_bibtex"
    journal_entry = "journal_entry"
    literature_entry = "literature_entry"
    skip = "skip"


# ---------- Scan models ----------

class ScannedFile(BaseModel):
    """A single file discovered during workspace scanning."""
    path: str
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    category: FileCategory
    content_hint: ContentHint = ContentHint.general
    ingestion_target: IngestionTarget
    proposed_type: str = "finding"  # journal entry type
    proposed_tags: list[str] = Field(default_factory=list)
    file_hash: str  # SHA-256
    is_duplicate: bool = False
    preview: str | None = None  # First ~500 chars for text files
    llm_classified: bool = False  # Whether LLM enhanced the classification
    title_suggestion: str | None = None  # LLM-suggested title


class ScanSummary(BaseModel):
    """Summary statistics for a workspace scan."""
    by_category: dict[str, int] = Field(default_factory=dict)
    by_target: dict[str, int] = Field(default_factory=dict)
    by_content_hint: dict[str, int] = Field(default_factory=dict)
    total_size_bytes: int = 0
    duplicate_count: int = 0
    llm_classified_count: int = 0


class ScanCapabilities(BaseModel):
    """Available optional features during scanning."""
    pymupdf_available: bool = False
    python_docx_available: bool = False
    llm_available: bool = False


class ScanManifest(BaseModel):
    """Result of scanning a workspace folder."""
    scan_id: str
    root_path: str
    total_files_found: int
    total_files_scanned: int
    files: list[ScannedFile] = Field(default_factory=list)
    summary: ScanSummary = Field(default_factory=ScanSummary)
    warnings: list[str] = Field(default_factory=list)
    capabilities: ScanCapabilities = Field(default_factory=ScanCapabilities)


# ---------- Request / Response models ----------

class WorkspaceScanRequest(BaseModel):
    """Request body for POST /workspace/scan."""
    folder_path: str
    ignore_patterns: list[str] = Field(default_factory=list)
    include_preview: bool = True
    max_file_size_mb: float = 50.0
    use_llm: bool = True


class WorkspaceIngestRequest(BaseModel):
    """Request body for POST /workspace/ingest."""
    manifest: ScanManifest
    skip_files: list[str] = Field(
        default_factory=list,
        description="Relative paths of files to skip during ingestion.",
    )
    override_tags: list[str] = Field(
        default_factory=list,
        description="Tags to add to all ingested entries.",
    )
    phase: str | None = None
    source: Literal["brain", "executor", "pi", "web_ui", "llm"] = "pi"
    dry_run: bool = False


class IngestResult(BaseModel):
    """Result for a single file ingestion."""
    relative_path: str
    category: str
    ingestion_target: str
    success: bool
    entity_ids: list[str] = Field(default_factory=list)
    entity_count: int = 0
    error: str | None = None


class WorkspaceIngestResponse(BaseModel):
    """Response from workspace ingestion."""
    scan_id: str
    total_processed: int
    total_created: int
    total_skipped: int
    total_errors: int
    results: list[IngestResult] = Field(default_factory=list)


# ---------- Review models (for Brain handoff) ----------

class ReviewSuggestion(BaseModel):
    """A suggested next action for the Brain."""
    priority: Literal["high", "medium", "low"] = "medium"
    action: str
    details: str


class BootstrapReview(BaseModel):
    """Post-bootstrap summary for Brain to start reorganization."""
    scan_id: str
    total_entries_created: int
    entries_by_type: dict[str, int] = Field(default_factory=dict)
    entries_by_category: dict[str, int] = Field(default_factory=dict)
    all_tags: list[str] = Field(default_factory=list)
    singleton_tags: list[str] = Field(default_factory=list)
    needs_attention: list[str] = Field(
        default_factory=list,
        description="Entity IDs that need further processing (e.g. PDFs without abstracts).",
    )
    suggestions: list[ReviewSuggestion] = Field(default_factory=list)
    narrative: str | None = None  # LLM-generated overview if available
