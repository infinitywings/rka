"""Hook system REST routes (Mission 2 Phase B).

Eight CRUD endpoints + one server-side fire endpoint that the MCP layer
hits to dispatch composite events (session_start, post_claim_extract).
Server-side service code calls ``HookDispatcher`` directly without going
through the fire endpoint.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from rka.api.deps import get_db, get_scoped_hooks_service, require_project
from rka.infra.database import Database
from rka.models.hooks import (
    BrainNotification,
    Hook,
    HookCreate,
    HookEvent,
    HookExecution,
)
from rka.services.hook_dispatcher import HookDispatcher
from rka.services.hooks_service import HooksService


router = APIRouter()


# ----------------------------------------------------------- hooks CRUD


@router.post("/hooks", response_model=Hook, status_code=201)
async def add_hook(
    data: HookCreate,
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    return await svc.add(data)


@router.get("/hooks", response_model=list[Hook])
async def list_hooks(
    event: str | None = Query(None),
    enabled_only: bool = Query(False),
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    return await svc.list_hooks(event=event, enabled_only=enabled_only)


@router.get("/hooks/{hook_id}", response_model=Hook)
async def get_hook(
    hook_id: str,
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    h = await svc.get(hook_id)
    if h is None:
        raise HTTPException(404, f"Hook {hook_id} not found")
    return h


@router.put("/hooks/{hook_id}/enable", response_model=Hook)
async def enable_hook(
    hook_id: str,
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    h = await svc.set_enabled(hook_id, True)
    if h is None:
        raise HTTPException(404, f"Hook {hook_id} not found")
    return h


@router.put("/hooks/{hook_id}/disable", response_model=Hook)
async def disable_hook(
    hook_id: str,
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    h = await svc.set_enabled(hook_id, False)
    if h is None:
        raise HTTPException(404, f"Hook {hook_id} not found")
    return h


@router.delete("/hooks/{hook_id}", status_code=204)
async def delete_hook(
    hook_id: str,
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    deleted = await svc.delete(hook_id)
    if not deleted:
        raise HTTPException(404, f"Hook {hook_id} not found")
    return None


# ------------------------------------------------------------- audit query


@router.get("/hooks/executions/list", response_model=list[HookExecution])
async def list_hook_executions(
    hook_id: str | None = Query(None),
    since: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=500),
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    return await svc.list_executions(
        hook_id=hook_id, since=since, status=status, limit=limit,
    )


# ------------------------------------------------ brain_notifications queue


@router.get("/notifications", response_model=list[BrainNotification])
async def list_brain_notifications(
    since: str | None = Query(None),
    include_cleared: bool = Query(False),
    limit: int = Query(100, le=500),
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    return await svc.list_notifications(
        since=since, include_cleared=include_cleared, limit=limit,
    )


class ClearNotificationsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str]


@router.post("/notifications/clear")
async def clear_brain_notifications(
    body: ClearNotificationsBody,
    svc: HooksService = Depends(get_scoped_hooks_service),
):
    cleared = await svc.clear_notifications(body.ids)
    return {"cleared": cleared}


# ----------------------------------------------------------- fire endpoint


class FireEventBody(BaseModel):
    """Server-side fire trigger used by the MCP layer for composite events.

    Server-side service code (notes.py, calibration.py, etc.) calls
    HookDispatcher.fire directly without going through this endpoint.
    """

    model_config = ConfigDict(extra="forbid")
    event: HookEvent
    payload: dict[str, Any] = {}


@router.post("/hooks/fire")
async def fire_event(
    body: FireEventBody,
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
):
    dispatcher = HookDispatcher(db)
    execution_ids = await dispatcher.fire(
        event=body.event,
        payload=body.payload,
        project_id=project_id,
    )
    return {"event": body.event, "fired_executions": execution_ids}
