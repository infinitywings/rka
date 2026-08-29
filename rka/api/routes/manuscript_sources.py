"""Local-only manuscript Markdown/LaTeX source synchronization routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import get_scoped_manuscript_source_service, get_transport_actor
from rka.models.manuscript_source import (
    ManuscriptSourcePath,
    ManuscriptSourceProposalCreate,
    ManuscriptSourceProposalTransition,
)
from rka.services.manuscript_native import ManuscriptNotFoundError
from rka.services.manuscript_source import (
    ManuscriptSourceConflictError,
    ManuscriptSourceNotFoundError,
    ManuscriptSourceSecurityError,
    ManuscriptSourceService,
)


router = APIRouter(deprecated=True)


def _require_web_actor(actor: str) -> None:
    if actor != "web_ui":
        raise HTTPException(
            status_code=403,
            detail="manuscript source content is restricted to the local web transport",
        )


def _raise_source_error(exc: Exception) -> None:
    if isinstance(exc, (ManuscriptNotFoundError, ManuscriptSourceNotFoundError)):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ManuscriptSourceConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ManuscriptSourceSecurityError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/manuscripts/{manuscript_id}/source")
async def get_manuscript_source_overview(
    manuscript_id: str,
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> dict:
    _require_web_actor(actor)
    try:
        return await service.get_overview(manuscript_id)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)


@router.post("/manuscripts/{manuscript_id}/source/read")
async def read_manuscript_source_file(
    manuscript_id: str,
    data: ManuscriptSourcePath,
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> dict:
    _require_web_actor(actor)
    try:
        return await service.read_file(manuscript_id, data.relative_path)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)


@router.post("/manuscripts/{manuscript_id}/source/proposals", status_code=201)
async def create_manuscript_source_proposal(
    manuscript_id: str,
    data: ManuscriptSourceProposalCreate,
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> dict:
    _require_web_actor(actor)
    if data.created_by != "web_ui":
        raise HTTPException(
            status_code=403,
            detail="local web source proposals must be attributed to web_ui",
        )
    try:
        return await service.create_proposal(manuscript_id, data)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)


@router.get("/manuscripts/{manuscript_id}/source/proposals")
async def list_manuscript_source_proposals(
    manuscript_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> list[dict]:
    _require_web_actor(actor)
    try:
        return await service.list_proposals(manuscript_id, status=status, limit=limit)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)


@router.get("/manuscript-source-proposals/{proposal_id}")
async def get_manuscript_source_proposal(
    proposal_id: str,
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> dict:
    _require_web_actor(actor)
    try:
        return await service.get_proposal(proposal_id)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)


@router.post("/manuscript-source-proposals/{proposal_id}/apply")
async def apply_manuscript_source_proposal(
    proposal_id: str,
    data: ManuscriptSourceProposalTransition,
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> dict:
    _require_web_actor(actor)
    if data.actor != "web_ui":
        raise HTTPException(status_code=403, detail="local web apply requires actor=web_ui")
    try:
        return await service.apply_proposal(proposal_id, data)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)


@router.post("/manuscript-source-proposals/{proposal_id}/reject")
async def reject_manuscript_source_proposal(
    proposal_id: str,
    data: ManuscriptSourceProposalTransition,
    actor: str = Depends(get_transport_actor),
    service: ManuscriptSourceService = Depends(get_scoped_manuscript_source_service),
) -> dict:
    _require_web_actor(actor)
    if data.actor != "web_ui":
        raise HTTPException(status_code=403, detail="local web reject requires actor=web_ui")
    try:
        return await service.reject_proposal(proposal_id, data)
    except (ValueError, OSError, UnicodeError) as exc:
        _raise_source_error(exc)
