"""Role event routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.role_event import RoleEvent, RoleEventCreate
from rka.services.role_events import RoleEventService
from rka.api.deps import get_scoped_role_event_service

router = APIRouter()


@router.post("/role-events", response_model=RoleEvent, status_code=201)
async def emit_event(
    data: RoleEventCreate,
    svc: RoleEventService = Depends(get_scoped_role_event_service),
):
    return await svc.emit(data)


@router.get("/role-events/{event_id}", response_model=RoleEvent)
async def get_event(
    event_id: str,
    svc: RoleEventService = Depends(get_scoped_role_event_service),
):
    event = await svc.get(event_id)
    if event is None:
        raise HTTPException(404, f"Role event {event_id} not found")
    return event


@router.get("/roles/{role_id}/events", response_model=list[RoleEvent])
async def list_role_events(
    role_id: str,
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: RoleEventService = Depends(get_scoped_role_event_service),
):
    return await svc.list_for_role(role_id, status=status, limit=limit, offset=offset)


@router.post("/role-events/{event_id}/process", response_model=RoleEvent)
async def mark_processing(
    event_id: str,
    svc: RoleEventService = Depends(get_scoped_role_event_service),
):
    event = await svc.get(event_id)
    if event is None:
        raise HTTPException(404, f"Role event {event_id} not found")
    result = await svc.mark_processing(event_id)
    if result is None:
        raise HTTPException(404, f"Role event {event_id} not found")
    return result


@router.post("/role-events/{event_id}/ack", response_model=RoleEvent)
async def ack_event(
    event_id: str,
    svc: RoleEventService = Depends(get_scoped_role_event_service),
):
    event = await svc.get(event_id)
    if event is None:
        raise HTTPException(404, f"Role event {event_id} not found")
    result = await svc.ack(event_id)
    if result is None:
        raise HTTPException(404, f"Role event {event_id} not found")
    return result
