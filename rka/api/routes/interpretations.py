"""Project-scoped Interpretation Staging REST endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_scoped_interpretation_service
from rka.models.interpretation import (
    CandidateDisposition,
    EpistemicKind,
    InterpretationCandidate,
    InterpretationCandidateCreate,
    InterpretationCandidateDetail,
    InterpretationHintCreate,
    InterpretationSourceType,
    InterpretationTriage,
    ReviewStatus,
)
from rka.services.interpretation import (
    InterpretationConflictError,
    InterpretationNotFoundError,
    InterpretationService,
)

router = APIRouter()


def _raise_interpretation_error(exc: Exception) -> None:
    if isinstance(exc, InterpretationNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, InterpretationConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, sqlite3.IntegrityError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post(
    "/interpretations",
    response_model=InterpretationCandidate,
    status_code=201,
)
async def create_interpretation_candidate(
    data: InterpretationCandidateCreate,
    svc: InterpretationService = Depends(get_scoped_interpretation_service),
):
    try:
        return await svc.create(data)
    except Exception as exc:
        _raise_interpretation_error(exc)

@router.get("/interpretations", response_model=list[InterpretationCandidate])
async def list_interpretation_candidates(
    review_status: ReviewStatus | None = None,
    disposition: CandidateDisposition | None = None,
    epistemic_kind: EpistemicKind | None = None,
    source_type: InterpretationSourceType | None = None,
    source_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    svc: InterpretationService = Depends(get_scoped_interpretation_service),
):
    return await svc.list(
        review_status=review_status,
        disposition=disposition,
        epistemic_kind=epistemic_kind,
        source_type=source_type,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/interpretations/{candidate_id}",
    response_model=InterpretationCandidateDetail,
)
async def get_interpretation_candidate(
    candidate_id: str,
    svc: InterpretationService = Depends(get_scoped_interpretation_service),
):
    candidate = await svc.get_detail(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found")
    return candidate


@router.post(
    "/interpretations/{candidate_id}/hints",
    response_model=InterpretationCandidateDetail,
    status_code=201,
)
async def add_interpretation_hint(
    candidate_id: str,
    data: InterpretationHintCreate,
    svc: InterpretationService = Depends(get_scoped_interpretation_service),
):
    try:
        return await svc.add_hint(candidate_id, data)
    except Exception as exc:
        _raise_interpretation_error(exc)


@router.post(
    "/interpretations/{candidate_id}/triage",
    response_model=InterpretationCandidateDetail,
)
async def triage_interpretation_candidate(
    candidate_id: str,
    data: InterpretationTriage,
    svc: InterpretationService = Depends(get_scoped_interpretation_service),
):
    try:
        return await svc.triage(candidate_id, data)
    except Exception as exc:
        _raise_interpretation_error(exc)
