"""Orchestration control plane routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from rka.models.orchestration import (
    CircuitBreakerReset,
    CostLogCreate,
    CostLogEntry,
    CostSummary,
    OrchestrationConfig,
    OrchestrationConfigUpdate,
    OrchestrationStatus,
    PIOverride,
    RoleCostSummary,
)
from rka.services.orchestration import OrchestrationService
from rka.api.deps import get_scoped_orchestration_service

router = APIRouter()


# ── Config ──────────────────────────────────────────────────

@router.get("/orchestration/config", response_model=OrchestrationConfig)
async def get_orchestration_config(
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.get_config()


@router.put("/orchestration/config", response_model=OrchestrationConfig)
async def update_orchestration_config(
    data: OrchestrationConfigUpdate,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.update_config(data)


# ── Autonomy Mode ──────────────────────────────────────────

@router.get("/orchestration/autonomy-mode")
async def get_autonomy_mode(
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    mode = await svc.get_autonomy_mode()
    return {"autonomy_mode": mode}


@router.put("/orchestration/autonomy-mode")
async def set_autonomy_mode(
    data: dict,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    mode = data.get("autonomy_mode")
    if mode not in ("manual", "supervised", "autonomous", "paused"):
        raise HTTPException(400, f"Invalid autonomy mode: {mode}")
    config = await svc.set_autonomy_mode(mode, actor=data.get("actor", "pi"))
    return config


# ── Circuit Breaker ────────────────────────────────────────

@router.post("/orchestration/circuit-breaker/check")
async def check_circuit_breaker(
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    tripped = await svc.check_circuit_breaker()
    return {"tripped": tripped}


@router.post("/orchestration/circuit-breaker/reset", response_model=OrchestrationConfig)
async def reset_circuit_breaker(
    data: CircuitBreakerReset,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.reset_circuit_breaker(actor=data.actor)


# ── Cost Tracking ──────────────────────────────────────────

@router.post("/orchestration/costs", response_model=CostLogEntry, status_code=201)
async def log_cost(
    data: CostLogCreate,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.log_cost(data)


@router.get("/orchestration/costs/summary", response_model=CostSummary)
async def get_cost_summary(
    window_hours: int | None = None,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.get_cost_summary(window_hours=window_hours)


@router.get("/orchestration/costs/by-role", response_model=list[RoleCostSummary])
async def get_cost_by_role(
    window_hours: int | None = None,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.get_cost_by_role(window_hours=window_hours)


# ── PI Override ────────────────────────────────────────────

@router.post("/orchestration/pi-override")
async def pi_override(
    data: PIOverride,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    result = await svc.pi_override(
        directive=data.directive,
        target_role_id=data.target_role_id,
        target_role_name=data.target_role_name,
        halt_current=data.halt_current,
    )
    return result


# ── Stuck Events ───────────────────────────────────────────

@router.get("/orchestration/stuck-events")
async def get_stuck_events(
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    events = await svc.get_stuck_events()
    return events


@router.post("/orchestration/stuck-events/{event_id}/retry")
async def retry_stuck_event(
    event_id: str,
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    result = await svc.retry_stuck_event(event_id)
    if result["status"] == "not_found":
        raise HTTPException(404, f"Event {event_id} not found")
    return result


# ── Full Status ────────────────────────────────────────────

@router.get("/orchestration/status", response_model=OrchestrationStatus)
async def get_orchestration_status(
    svc: OrchestrationService = Depends(get_scoped_orchestration_service),
):
    return await svc.get_status()
