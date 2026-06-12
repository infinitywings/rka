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


@router.get("/maintenance/summary")
async def get_maintenance_summary(
    svc: MaintenanceService = Depends(_get_maintenance_service),
):
    """Lightweight COUNT-only summary used to decorate rka_get_status / rka_search.

    Returns {total_items, top_categories: [{name, count}, ...]} sorted by
    count descending, top 3. Per dec_01KQQPER3XSSBACGZANFJCVQ66.
    """
    return await svc.get_backlog_summary()


@router.get("/maintenance/research-health")
async def research_health(
    svc: MaintenanceService = Depends(_get_maintenance_service),
):
    """Live research-health metrics: provenance coverage, research-debt
    trajectory, mission-cycle stats, bookkeeping-overhead share (the paper's
    section-7.1 instruments, computed from the KB)."""
    return await svc.research_health()
