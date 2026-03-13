"""Audit log routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from rka.models.audit import AuditEntry
from rka.services.audit import AuditService
from rka.api.deps import get_scoped_audit_service

router = APIRouter()


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit(
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    svc: AuditService = Depends(get_scoped_audit_service),
):
    return await svc.list(
        action=action, entity_type=entity_type, entity_id=entity_id,
        actor=actor, since=since, limit=limit, offset=offset,
    )


@router.get("/audit/counts")
async def audit_counts(svc: AuditService = Depends(get_scoped_audit_service)):
    return await svc.count()
