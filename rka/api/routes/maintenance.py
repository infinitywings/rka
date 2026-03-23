"""Maintenance manifest routes — gap detection for knowledge base hygiene."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from rka.api.deps import get_db, require_project
from rka.infra.database import Database
from rka.services.maintenance import MaintenanceService

router = APIRouter()


def _get_maintenance_service(
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
) -> MaintenanceService:
    return MaintenanceService(db, project_id=project_id)


@router.get("/maintenance")
async def get_pending_maintenance(
    svc: MaintenanceService = Depends(_get_maintenance_service),
):
    """Return a maintenance manifest of all detected gaps in the knowledge base."""
    return await svc.get_pending_maintenance()
