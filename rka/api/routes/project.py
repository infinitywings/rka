"""Project state routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from rka.api.deps import get_project_service, require_project
from rka.models.project import ProjectCreate, ProjectInfo, ProjectState, ProjectStateUpdate
from rka.services.project import ProjectService

router = APIRouter()


@router.get("/projects", response_model=list[ProjectInfo])
async def list_projects(svc: ProjectService = Depends(get_project_service)):
    return await svc.list_projects()


@router.post("/projects", response_model=ProjectInfo)
async def create_project(
    data: ProjectCreate,
    actor: str = "web_ui",
    svc: ProjectService = Depends(get_project_service),
):
    return await svc.create_project(data, actor=actor)


@router.get("/status", response_model=ProjectState)
async def get_status(
    project_id: str = Depends(require_project),
    svc: ProjectService = Depends(get_project_service),
):
    state = await svc.get(project_id=project_id)
    if state is None:
        raise HTTPException(404, "Project not initialized. Run `rka init` first.")
    return state


@router.put("/status", response_model=ProjectState)
async def update_status(
    data: ProjectStateUpdate,
    actor: str = "web_ui",
    project_id: str = Depends(require_project),
    svc: ProjectService = Depends(get_project_service),
):
    return await svc.update(data, actor=actor, project_id=project_id)
