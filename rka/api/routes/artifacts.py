"""Artifact API routes — file management and figure extraction."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from rka.api.deps import get_artifact_service
from rka.services.artifacts import ArtifactService

router = APIRouter()


class RegisterArtifactRequest(BaseModel):
    filepath: str = Field(..., description="Path to the file on disk")
    filename: str | None = None
    filetype: str | None = None
    mime: str | None = None
    created_by: str = "system"
    metadata: dict | None = None


@router.post("/artifacts")
async def register_artifact(
    req: RegisterArtifactRequest,
    svc: ArtifactService = Depends(get_artifact_service),
):
    """Register a file artifact."""
    return await svc.register(
        filepath=req.filepath,
        filename=req.filename,
        filetype=req.filetype,
        mime=req.mime,
        created_by=req.created_by,
        metadata=req.metadata,
    )


@router.get("/artifacts")
async def list_artifacts(
    status: str | None = None,
    limit: int = Query(50, le=200),
    svc: ArtifactService = Depends(get_artifact_service),
):
    """List artifacts."""
    return await svc.list_artifacts(status=status, limit=limit)


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    svc: ArtifactService = Depends(get_artifact_service),
):
    """Get an artifact by ID."""
    result = await svc.get(artifact_id)
    if result is None:
        return {"error": "Artifact not found"}
    return result


@router.post("/artifacts/{artifact_id}/extract")
async def extract_figures(
    artifact_id: str,
    svc: ArtifactService = Depends(get_artifact_service),
):
    """Extract figures and tables from an artifact."""
    return await svc.extract_figures(artifact_id)


@router.get("/artifacts/{artifact_id}/figures")
async def get_figures(
    artifact_id: str,
    svc: ArtifactService = Depends(get_artifact_service),
):
    """Get all figures for an artifact."""
    return await svc.get_figures(artifact_id)


@router.get("/figures/{figure_id}")
async def get_figure(
    figure_id: str,
    svc: ArtifactService = Depends(get_artifact_service),
):
    """Get a single figure by ID."""
    result = await svc.get_figure(figure_id)
    if result is None:
        return {"error": "Figure not found"}
    return result
