"""Knowledge-pack API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgePackImportResult(BaseModel):
    """Import result summary."""

    project_id: str
    project_name: str
    source_project_id: str
    imported_counts: dict[str, int] = Field(default_factory=dict)
    artifact_files_restored: int = 0
