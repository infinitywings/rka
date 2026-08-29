"""Project-scoped safe source registration and explicit admission endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_scoped_source_service
from rka.models.sources import (
    OwnershipKind,
    RegisterSourceRequest,
    RegisteredSource,
    RegisteredSourceDetail,
    RegisterSourceResult,
    SourceAdmission,
    SourceAdmissionCreate,
    SourceKind,
)
from rka.services.interpretation import (
    InterpretationConflictError,
    InterpretationNotFoundError,
)
from rka.services.sources import SourceRegistrationError, SourceService


router = APIRouter()


def _raise_source_error(exc: Exception) -> None:
    if isinstance(exc, InterpretationNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (InterpretationConflictError, sqlite3.IntegrityError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (SourceRegistrationError, ValueError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post("/sources", response_model=RegisterSourceResult, status_code=201)
async def register_source(
    data: RegisterSourceRequest,
    svc: SourceService = Depends(get_scoped_source_service),
):
    try:
        return await svc.register(data)
    except Exception as exc:
        _raise_source_error(exc)


@router.get("/sources", response_model=list[RegisteredSource])
async def list_sources(
    source_kind: SourceKind | None = None,
    ownership_kind: OwnershipKind | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    svc: SourceService = Depends(get_scoped_source_service),
):
    return await svc.list(
        source_kind=source_kind,
        ownership_kind=ownership_kind,
        limit=limit,
        offset=offset,
    )


@router.get("/sources/{source_id}", response_model=RegisteredSourceDetail)
async def get_source(
    source_id: str,
    svc: SourceService = Depends(get_scoped_source_service),
):
    source = await svc.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return source


@router.post(
    "/sources/{source_id}/admissions",
    response_model=SourceAdmission,
    status_code=201,
)
async def admit_source_interpretation(
    source_id: str,
    data: SourceAdmissionCreate,
    svc: SourceService = Depends(get_scoped_source_service),
):
    try:
        return await svc.admit(source_id, data)
    except Exception as exc:
        _raise_source_error(exc)
