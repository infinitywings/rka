"""Project-scoped manuscript-planning branch and artifact endpoints."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_scoped_manuscript_planning_service
from rka.models.planning import (
    PlanningArtifactVersionAppend,
    PlanningBranchCreate,
    PlanningBranchTransition,
    PlanningContributionProposalPrepare,
    PlanningContributionRatification,
    PlanningResearchQuestionPromotion,
)
from rka.services.planning import (
    ManuscriptPlanningService,
    PlanningConflictError,
    PlanningNotFoundError,
)


router = APIRouter()


def _raise_planning_error(exc: Exception) -> None:
    if isinstance(exc, PlanningNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (PlanningConflictError, sqlite3.IntegrityError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post("/planning/branches", status_code=201)
async def create_planning_branch(
    data: PlanningBranchCreate,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.create_branch(data)
    except Exception as exc:
        _raise_planning_error(exc)


@router.get("/planning/branches")
async def list_planning_branches(
    manuscript_id: str | None = None,
    include_archived: bool = True,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> list[dict[str, Any]]:
    return await service.list_branches(
        manuscript_id=manuscript_id,
        include_archived=include_archived,
    )


@router.get("/planning/resume")
async def resume_planning_branch(
    manuscript_id: str | None = None,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any] | None:
    return await service.resume(manuscript_id=manuscript_id)


@router.get("/planning/branches/compare")
async def compare_planning_branches(
    base_branch_id: str = Query(min_length=1),
    other_branch_id: str = Query(min_length=1),
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.compare_branches(base_branch_id, other_branch_id)
    except Exception as exc:
        _raise_planning_error(exc)


@router.get("/planning/branches/{branch_id}")
async def get_planning_branch(
    branch_id: str,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.get_branch(branch_id)
    except Exception as exc:
        _raise_planning_error(exc)


@router.get("/planning/branches/{branch_id}/argument-workflow")
async def get_planning_argument_workflow(
    branch_id: str,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    """Project one branch into deterministic seed-to-contribution guidance."""
    try:
        return await service.argument_workflow(branch_id)
    except Exception as exc:
        _raise_planning_error(exc)


@router.get("/planning/branches/{branch_id}/promotions")
async def list_planning_promotion_events(
    branch_id: str,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_promotion_events(branch_id)
    except Exception as exc:
        _raise_planning_error(exc)


@router.post("/planning/branches/{branch_id}/promote-rq", status_code=201)
async def promote_planning_research_question(
    branch_id: str,
    data: PlanningResearchQuestionPromotion,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.promote_research_question(branch_id, data)
    except Exception as exc:
        _raise_planning_error(exc)


@router.post("/planning/branches/{branch_id}/prepare-contribution", status_code=201)
async def prepare_planning_contribution(
    branch_id: str,
    data: PlanningContributionProposalPrepare,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.prepare_contribution_proposal(branch_id, data)
    except Exception as exc:
        _raise_planning_error(exc)


@router.post("/planning/branches/{branch_id}/ratify-contribution", status_code=201)
async def ratify_planning_contribution(
    branch_id: str,
    data: PlanningContributionRatification,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.ratify_contribution(branch_id, data)
    except Exception as exc:
        _raise_planning_error(exc)


@router.post("/planning/branches/{branch_id}/transition")
async def transition_planning_branch(
    branch_id: str,
    data: PlanningBranchTransition,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.transition_branch(branch_id, data)
    except Exception as exc:
        _raise_planning_error(exc)


@router.post("/planning/branches/{branch_id}/artifacts")
async def append_planning_artifact_version(
    branch_id: str,
    data: PlanningArtifactVersionAppend,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> dict[str, Any]:
    try:
        return await service.append_artifact_version(branch_id, data)
    except Exception as exc:
        _raise_planning_error(exc)


@router.get("/planning/artifacts/{artifact_id}/versions")
async def list_planning_artifact_versions(
    artifact_id: str,
    service: ManuscriptPlanningService = Depends(get_scoped_manuscript_planning_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_artifact_versions(artifact_id)
    except Exception as exc:
        _raise_planning_error(exc)
