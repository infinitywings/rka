"""Project state routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from rka.models.project import ProjectState, ProjectStateUpdate
from rka.services.project import ProjectService
from rka.api.deps import get_project_service

router = APIRouter()


@router.get("/status", response_model=ProjectState)
async def get_status(svc: ProjectService = Depends(get_project_service)):
    state = await svc.get()
    if state is None:
        raise HTTPException(404, "Project not initialized. Run `rka init` first.")
    return state


@router.put("/status", response_model=ProjectState)
async def update_status(
    data: ProjectStateUpdate,
    actor: str = "web_ui",
    svc: ProjectService = Depends(get_project_service),
):
    return await svc.update(data, actor=actor)
