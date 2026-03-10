"""Workspace bootstrap routes — scan, ingest, review."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from rka.models.workspace import (
    WorkspaceScanRequest,
    WorkspaceIngestRequest,
    ScanManifest,
    WorkspaceIngestResponse,
    BootstrapReview,
)
from rka.services.workspace import WorkspaceService
from rka.api.deps import get_workspace_service

router = APIRouter()


@router.post("/workspace/scan", response_model=ScanManifest)
async def scan_workspace(
    data: WorkspaceScanRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
):
    """Scan a workspace folder and classify files for ingestion.

    Returns a manifest with classified files and their proposed
    ingestion targets. The manifest is ephemeral (not stored in DB).
    """
    try:
        return await svc.scan(
            folder_path=data.folder_path,
            ignore_patterns=data.ignore_patterns,
            include_preview=data.include_preview,
            max_file_size_mb=data.max_file_size_mb,
            use_llm=data.use_llm,
            max_files=data.max_files,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/workspace/ingest", response_model=WorkspaceIngestResponse)
async def ingest_workspace(
    data: WorkspaceIngestRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
):
    """Ingest files from a scan manifest into the knowledge base.

    Each file is dispatched to the appropriate service based on its
    classification in the manifest.
    """
    return await svc.ingest(data)


@router.get("/workspace/review/{scan_id}", response_model=BootstrapReview)
async def review_bootstrap(
    scan_id: str,
    svc: WorkspaceService = Depends(get_workspace_service),
):
    """Review a completed bootstrap for Brain handoff.

    Returns entry counts by type/tag, entries needing attention,
    and suggested next actions for reorganization.
    """
    return await svc.review(scan_id)
