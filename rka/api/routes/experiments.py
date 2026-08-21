"""Project-scoped experiment/run/observation evidence endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_scoped_experiment_service
from rka.models.experiment import (
    EvidenceLocator,
    EvidenceLocatorCreate,
    Experiment,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentObservation,
    ExperimentObservationCreate,
    ExperimentObservationDetail,
    ExperimentPlanAppend,
    ExperimentRun,
    ExperimentRunCreate,
    ExperimentRunDetail,
    ExperimentRunTransition,
    ExperimentTransition,
    ExperimentStatus,
    ObservationDirection,
    ObservationKind,
    RunStatus,
)
from rka.services.experiments import (
    ExperimentConflictError,
    ExperimentNotFoundError,
    ExperimentService,
)


router = APIRouter()


def _raise_experiment_error(exc: Exception) -> None:
    if isinstance(exc, ExperimentNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (ExperimentConflictError, sqlite3.IntegrityError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post("/experiments", response_model=ExperimentDetail, status_code=201)
async def create_experiment(
    data: ExperimentCreate,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.create_experiment(data)
    except Exception as exc:
        _raise_experiment_error(exc)

@router.get("/experiments", response_model=list[Experiment])
async def list_experiments(
    status: ExperimentStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    return await service.list_experiments(status=status, limit=limit, offset=offset)


@router.get("/experiments/{experiment_id}", response_model=ExperimentDetail)
async def get_experiment(
    experiment_id: str,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    result = await service.get_experiment(experiment_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return result


@router.post("/experiments/{experiment_id}/plans", response_model=ExperimentDetail)
async def append_experiment_plan(
    experiment_id: str,
    data: ExperimentPlanAppend,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.append_plan(experiment_id, data)
    except Exception as exc:
        _raise_experiment_error(exc)


@router.post("/experiments/{experiment_id}/transition", response_model=ExperimentDetail)
async def transition_experiment(
    experiment_id: str,
    data: ExperimentTransition,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.transition_experiment(experiment_id, data)
    except Exception as exc:
        _raise_experiment_error(exc)


@router.post("/experiment-runs", response_model=ExperimentRunDetail, status_code=201)
async def create_experiment_run(
    data: ExperimentRunCreate,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.create_run(data)
    except Exception as exc:
        _raise_experiment_error(exc)


@router.get("/experiment-runs", response_model=list[ExperimentRun])
async def list_experiment_runs(
    experiment_id: str | None = None,
    status: RunStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    return await service.list_runs(
        experiment_id=experiment_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/experiment-runs/{run_id}", response_model=ExperimentRunDetail)
async def get_experiment_run(
    run_id: str,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    result = await service.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Experiment run {run_id} not found")
    return result


@router.post("/experiment-runs/{run_id}/transition", response_model=ExperimentRunDetail)
async def transition_experiment_run(
    run_id: str,
    data: ExperimentRunTransition,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.transition_run(run_id, data)
    except Exception as exc:
        _raise_experiment_error(exc)


@router.post(
    "/experiment-observations",
    response_model=ExperimentObservationDetail,
    status_code=201,
)
async def create_experiment_observation(
    data: ExperimentObservationCreate,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.create_observation(data)
    except Exception as exc:
        _raise_experiment_error(exc)


@router.get("/experiment-observations", response_model=list[ExperimentObservation])
async def list_experiment_observations(
    run_id: str | None = None,
    direction: ObservationDirection | None = None,
    kind: ObservationKind | None = None,
    claim_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    return await service.list_observations(
        run_id=run_id,
        direction=direction,
        kind=kind,
        claim_id=claim_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/experiment-observations/{observation_id}",
    response_model=ExperimentObservationDetail,
)
async def get_experiment_observation(
    observation_id: str,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    result = await service.get_observation(observation_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment observation {observation_id} not found",
        )
    return result


@router.post("/evidence-locators", response_model=EvidenceLocator, status_code=201)
async def create_evidence_locator(
    data: EvidenceLocatorCreate,
    service: ExperimentService = Depends(get_scoped_experiment_service),
):
    try:
        return await service.add_locator(data)
    except Exception as exc:
        _raise_experiment_error(exc)
