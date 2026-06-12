"""Verification routes — KB-wide audit/currency reads (eval-v3 themes B/C).

Thin adapters only; logic lives in VerificationService and GraphService.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_db, get_graph_service, require_project
from rka.infra.database import Database
from rka.services.graph import GraphService
from rka.services.verification import VerificationService

router = APIRouter()


def get_scoped_verification_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
) -> VerificationService:
    return VerificationService(db, project_id=project_id)


@router.get("/graph/staleness-impact/{entity_id}")
async def staleness_impact(
    entity_id: str,
    max_depth: int = Query(default=3, ge=1, le=5),
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Downstream blast-radius of a stale (or about-to-be-stale) entity."""
    return await svc.staleness_impact(
        entity_id, max_depth=max_depth, project_id=project_id
    )


@router.get("/verification/link-support")
async def link_support_audit(
    limit: int = Query(default=200, ge=1, le=1000),
    svc: VerificationService = Depends(get_scoped_verification_service),
):
    """Content-level support audit behind provenance links (advisory)."""
    return await svc.audit_link_support(limit=limit)


@router.post("/verification/file-staleness-reviews")
async def file_staleness_reviews(
    max_depth: int = Query(default=1, ge=1, le=3),
    svc: VerificationService = Depends(get_scoped_verification_service),
):
    """File 'stale_dependency' review items for dependents of stale roots."""
    return await svc.file_staleness_reviews(max_depth=max_depth)


@router.get("/missions/{mission_id}/guard")
async def mission_guard(
    mission_id: str,
    svc: VerificationService = Depends(get_scoped_verification_service),
):
    """Negative knowledge relevant to a mission (retracted / superseded /
    contradicted), for Executor pickup."""
    try:
        return await svc.mission_guard(mission_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/graph/as-of")
async def belief_as_of(
    date: str = Query(min_length=10, description="ISO date or timestamp, e.g. 2026-03-15"),
    svc: VerificationService = Depends(get_scoped_verification_service),
):
    """Reconstruct the believed-current knowledge state at a past date."""
    return await svc.belief_as_of(date)
