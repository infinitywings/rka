"""Manuscript REST endpoints (Phase 3 per dec_01KS2WPKMRVSJ2R0PP74722PEH).

Three endpoints proxy the rka-writer-tools surface for manuscript manifests
(Option 2 representation per dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q1):

  POST /api/manuscripts                          register a new manuscript
  GET  /api/manuscripts/{manuscript_id}          read a manuscript manifest
  POST /api/manuscripts/{manuscript_id}/validate-reference
                                                  validate a single reference
                                                  through Stage B-G

The MCP layer (rka/mcp/server.py) exposes the same operations as
rka_register_manuscript, rka_get_manuscript, and rka_validate_reference
respectively.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from rka.api.deps import (
    get_db,
    get_embeddings,
    get_llm,
    require_project,
)
from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.infra.llm import LLMClient
from rka.services.manuscript import ManuscriptService
from rka.services.notes import NoteService

router = APIRouter()


# Inline Pydantic models for the route layer. Kept here (rather than in
# rka/models/) so the bookkeeper exemption stays scoped to the spec'd
# 3 files: rka/services/manuscript.py + rka/api/routes/manuscripts.py +
# rka/mcp/server.py.


class ManuscriptRegisterRequest(BaseModel):
    """Inputs to POST /api/manuscripts."""

    model_config = ConfigDict(extra="forbid")

    venue: str = Field(..., description="Target venue (CHI, EMNLP, USENIX, etc.)")
    title: str = Field(..., description="Manuscript title (PI authored)")
    abstract: str | None = Field(default=None, description="Manuscript abstract (PI authored)")
    sections: list[str] | None = Field(default=None, description="Initial section ids; outlined status by default")


class ReferenceValidationRequest(BaseModel):
    """Inputs to POST /api/manuscripts/{id}/validate-reference."""

    model_config = ConfigDict(extra="forbid")

    DOI: str | None = Field(default=None, description="Reference DOI; preferred")
    title: str | None = Field(default=None, description="Reference title; fallback search key")
    author: list[dict[str, str]] | None = Field(
        default=None,
        description="CSL-JSON author list: [{'family': 'Smith', 'given': 'J'}, ...]",
    )


def get_scoped_manuscript_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm),
    embeddings: EmbeddingService | None = Depends(get_embeddings),
) -> ManuscriptService:
    notes = NoteService(db=db, llm=llm, embeddings=embeddings, project_id=project_id)
    return ManuscriptService(db=db, notes=notes, project_id=project_id)


@router.post("/manuscripts", status_code=201)
async def register_manuscript(
    data: ManuscriptRegisterRequest,
    svc: ManuscriptService = Depends(get_scoped_manuscript_service),
) -> dict[str, Any]:
    """Create a new manuscript manifest (jrn_ entry tagged 'manuscript')."""
    entry = await svc.register(
        venue=data.venue,
        title=data.title,
        abstract=data.abstract,
        sections=data.sections,
    )
    return {
        "id": entry.id,
        "title": data.title,
        "venue": data.venue,
        "phase": "draft",
        "created_at": entry.created_at,
    }


@router.get("/manuscripts/{manuscript_id}")
async def get_manuscript(
    manuscript_id: str,
    svc: ManuscriptService = Depends(get_scoped_manuscript_service),
) -> dict[str, Any]:
    """Read a manuscript manifest by id.

    Returns 404 if the journal entry does not exist OR if it is not
    tagged 'manuscript' (in which case it is a regular journal entry,
    not a Writer manuscript manifest).
    """
    manuscript = await svc.get(manuscript_id)
    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail=f"Manuscript {manuscript_id} not found (or not tagged 'manuscript')",
        )
    return manuscript


@router.post("/manuscripts/{manuscript_id}/validate-reference")
async def validate_reference(
    manuscript_id: str,
    data: ReferenceValidationRequest,
    svc: ManuscriptService = Depends(get_scoped_manuscript_service),
) -> dict[str, Any]:
    """Validate a single reference via the Writer's Stage B-G pipeline.

    Verifies the manuscript exists; proxies the reference dict to
    scripts/validate_references.py through ManuscriptService; returns the
    audit verdict (one of 7 statuses per Phase 2 contract).
    """
    manuscript = await svc.get(manuscript_id)
    if manuscript is None:
        raise HTTPException(
            status_code=404,
            detail=f"Manuscript {manuscript_id} not found",
        )
    reference_dict = data.model_dump(exclude_none=True)
    if not reference_dict.get("DOI") and not reference_dict.get("title"):
        raise HTTPException(
            status_code=422,
            detail="Reference must carry at least DOI or title.",
        )
    return await svc.validate_reference(
        reference_dict,
        manuscript_id=manuscript_id,
    )
