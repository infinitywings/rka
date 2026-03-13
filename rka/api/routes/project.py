"""Project state routes."""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from rka.api.deps import (
    get_project_service,
    get_scoped_knowledge_pack_service,
    get_knowledge_pack_service,
    require_project,
)
from rka.models.knowledge_pack import KnowledgePackImportResult
from rka.models.project import ProjectCreate, ProjectInfo, ProjectState, ProjectStateUpdate
from rka.services.knowledge_pack import KnowledgePackService
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
    try:
        return await svc.create_project(data, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        if "projects.name" in message:
            raise HTTPException(
                status_code=409,
                detail=f"Project name '{data.name}' already exists",
            ) from exc
        if "projects.id" in message:
            project_id = data.id or "generated"
            raise HTTPException(
                status_code=409,
                detail=f"Project '{project_id}' already exists",
            ) from exc
        raise


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


@router.get("/projects/export")
async def export_project_pack(
    project_id: str = Depends(require_project),
    svc: KnowledgePackService = Depends(get_scoped_knowledge_pack_service),
):
    try:
        path, filename = await svc.export_pack(project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: os.unlink(path) if os.path.exists(path) else None),
    )


@router.post("/projects/import", response_model=KnowledgePackImportResult)
async def import_project_pack(
    file: UploadFile = File(...),
    project_id: str | None = Form(default=None),
    project_name: str | None = Form(default=None),
    svc: KnowledgePackService = Depends(get_knowledge_pack_service),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Knowledge pack file is required")
    try:
        return await svc.import_pack(
            fileobj=file.file,
            project_id=project_id,
            project_name=project_name,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 409 if "already exists" in message or "already contain" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    finally:
        await file.close()
