"""Event stream routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from rka.models.event import Event
from rka.services.events import EventService
from rka.api.deps import get_event_service

router = APIRouter()


@router.get("/events", response_model=list[Event])
async def list_events(
    phase: str | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    svc: EventService = Depends(get_event_service),
):
    return await svc.list(
        phase=phase, event_type=event_type, entity_type=entity_type,
        actor=actor, since=since, limit=limit, offset=offset,
    )
