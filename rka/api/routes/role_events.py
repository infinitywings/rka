"""Role event routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from rka.models.role_event import RoleEvent, RoleEventCreate
from rka.services.role_events import RoleEventService
from rka.services.agent_roles import AgentRoleService
from rka.api.deps import get_scoped_role_event_service, get_scoped_agent_role_service

router = APIRouter()


class FanoutRequest(BaseModel):
    """Emit a role event with fan-out to all matching subscribers."""

    event_type: str
    source_role_id: str | None = None
    source_entity_id: str | None = None
    source_entity_type: str | None = None
    payload: dict | None = None
    priority: int = 100


class FanoutResponse(BaseModel):
    event_type: str
    created_event_ids: list[str]
    subscriber_count: int


@router.post("/role-events", response_model=RoleEvent, status_code=201)
async def emit_event(
    data: RoleEventCreate,
    svc: RoleEventService = Depends(get_scoped_role_event_service),
):
    return await svc.emit(data)


@router.post("/role-events/fanout", response_model=FanoutResponse, status_code=201)
async def fanout_event(
    data: FanoutRequest,
    evt_svc: RoleEventService = Depends(get_scoped_role_event_service),
    role_svc: AgentRoleService = Depends(get_scoped_agent_role_service),
):
    """Emit a role event with fan-out to all roles whose subscriptions match the event type."""
    ids = await evt_svc.emit_for_subscribers(
        data.event_type,
        source_entity_id=data.source_entity_id,
        source_entity_type=data.source_entity_type,
        source_role_id=data.source_role_id,
        payload=data.payload,
        priority=data.priority,
        agent_role_service=role_svc,
    )
    return FanoutResponse(
        event_type=data.event_type,
        created_event_ids=ids,
        subscriber_count=len(ids),
    )


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
