"""Project-scoped semantic change cursor and manuscript impact reads."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_db, require_project
from rka.infra.database import Database
from rka.services.change_tracking import ChangeTrackingService
from rka.services.manuscript_native import ManuscriptNotFoundError


router = APIRouter()


def get_change_tracking_service(
    db: Annotated[Database, Depends(get_db)],
    project_id: Annotated[str, Depends(require_project)],
) -> ChangeTrackingService:
    return ChangeTrackingService(db, project_id=project_id)


@router.get("/changes")
async def changes_since(
    service: Annotated[
        ChangeTrackingService,
        Depends(get_change_tracking_service),
    ],
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict:
    """Return deterministic project changes strictly after an opaque cursor."""
    return await service.changes_since(cursor, limit=limit)


@router.get("/manuscripts/{manuscript_id}/impact")
async def get_manuscript_impact(
    manuscript_id: str,
    service: Annotated[
        ChangeTrackingService,
        Depends(get_change_tracking_service),
    ],
    since_cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict:
    """Map a page of changed dependencies to Writer claims and file units."""
    try:
        return await service.get_manuscript_impact(
            manuscript_id,
            since_cursor=since_cursor,
            limit=limit,
        )
    except ManuscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
