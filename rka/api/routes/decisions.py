"""Decision tree routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.decision import Decision, DecisionCreate, DecisionUpdate, DecisionTreeNode
from rka.services.decisions import DecisionService
from rka.api.deps import get_scoped_decision_service

router = APIRouter()


@router.post("/decisions", response_model=Decision, status_code=201)
async def create_decision(
    data: DecisionCreate,
    svc: DecisionService = Depends(get_scoped_decision_service),
):
    return await svc.create(data)


@router.get("/decisions", response_model=list[Decision])
async def list_decisions(
    phase: str | None = None,
    status: str | None = None,
    parent_id: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: DecisionService = Depends(get_scoped_decision_service),
):
    return await svc.list(phase=phase, status=status, parent_id=parent_id, limit=limit, offset=offset)


@router.get("/decisions/tree", response_model=list[DecisionTreeNode])
async def get_decision_tree(
    phase: str | None = None,
    active_only: bool = False,
    svc: DecisionService = Depends(get_scoped_decision_service),
):
    return await svc.get_tree(phase=phase, active_only=active_only)


@router.get("/decisions/{dec_id}", response_model=Decision)
async def get_decision(dec_id: str, svc: DecisionService = Depends(get_scoped_decision_service)):
    dec = await svc.get(dec_id)
    if dec is None:
        raise HTTPException(404, f"Decision {dec_id} not found")
    return dec


@router.put("/decisions/{dec_id}", response_model=Decision)
async def update_decision(
    dec_id: str,
    data: DecisionUpdate,
    actor: str = "web_ui",
    svc: DecisionService = Depends(get_scoped_decision_service),
):
    dec = await svc.get(dec_id)
    if dec is None:
        raise HTTPException(404, f"Decision {dec_id} not found")
    return await svc.update(dec_id, data, actor=actor)


@router.post("/decisions/{dec_id}/supersede", response_model=Decision, status_code=201)
async def supersede_decision(
    dec_id: str,
    new_data: DecisionCreate,
    svc: DecisionService = Depends(get_scoped_decision_service),
):
    """Atomically supersede a decision and trigger re-distillation."""
    try:
        return await svc.supersede_decision(dec_id, new_data)
    except ValueError as e:
        raise HTTPException(404, str(e))
