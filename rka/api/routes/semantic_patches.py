"""REST surface for auditable workbench semantic patch proposals."""

from __future__ import annotations

import sqlite3
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from rka.api.deps import (
    get_config,
    get_scoped_semantic_patch_service,
    get_transport_actor,
)
from rka.config import RKAConfig
from rka.models.semantic_patch import (
    ContextManifestCreate,
    GeneratedProposalDraft,
    LMStudioProposalRequest,
    SemanticPatchProposalCreate,
    SemanticPatchProposalTransition,
)
from rka.services.lm_studio_proposals import LMStudioProposalAdapter, LMStudioResponseError
from rka.services.semantic_patch import (
    SemanticPatchConflictError,
    SemanticPatchNotFoundError,
    SemanticPatchService,
)


router = APIRouter(deprecated=True)


def _raise_error(exc: Exception) -> None:
    if isinstance(exc, SemanticPatchNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (SemanticPatchConflictError, sqlite3.IntegrityError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/semantic-patches/schema")
async def get_semantic_patch_schema() -> dict[str, Any]:
    """Return the exact host-agent generation schema."""
    return GeneratedProposalDraft.model_json_schema()


@router.post("/semantic-patches/context-manifests", status_code=201)
async def create_context_manifest(
    data: ContextManifestCreate,
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    try:
        return await service.create_context_manifest(data)
    except Exception as exc:
        _raise_error(exc)


@router.get("/semantic-patches/context-manifests/{manifest_id}")
async def get_context_manifest(
    manifest_id: str,
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    try:
        return await service.get_context_manifest(manifest_id)
    except Exception as exc:
        _raise_error(exc)


@router.post("/semantic-patches/proposals", status_code=201)
async def create_proposal(
    data: SemanticPatchProposalCreate,
    transport_actor: str = Depends(get_transport_actor),
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    if transport_actor == "executor" and data.origin == "human":
        raise HTTPException(
            status_code=403,
            detail=(
                "AI/MCP transports cannot label a semantic proposal as human; "
                "prepare a matching context manifest and declare the provider origin"
            ),
        )
    try:
        return await service.create_proposal(data)
    except Exception as exc:
        _raise_error(exc)


@router.get("/semantic-patches/proposals")
async def list_proposals(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_proposals(status=status, limit=limit)
    except Exception as exc:
        _raise_error(exc)


@router.get("/semantic-patches/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    try:
        return await service.get_proposal(proposal_id)
    except Exception as exc:
        _raise_error(exc)


@router.post("/semantic-patches/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    data: SemanticPatchProposalTransition,
    transport_actor: str = Depends(get_transport_actor),
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    if transport_actor != "web_ui" or data.actor != "web_ui":
        raise HTTPException(
            status_code=403,
            detail=(
                "AI/MCP transports may prepare proposals but cannot apply them; "
                "the reviewer actor must match the local web transport"
            ),
        )
    try:
        return await service.apply_proposal(proposal_id, data)
    except Exception as exc:
        _raise_error(exc)


@router.post("/semantic-patches/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    data: SemanticPatchProposalTransition,
    transport_actor: str = Depends(get_transport_actor),
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    if transport_actor != "web_ui" or data.actor != "web_ui":
        raise HTTPException(
            status_code=403,
            detail=(
                "AI/MCP transports may prepare proposals but cannot reject them; "
                "the reviewer actor must match the local web transport"
            ),
        )
    try:
        return await service.reject_proposal(proposal_id, data)
    except Exception as exc:
        _raise_error(exc)


@router.post("/semantic-patches/providers/lm-studio/proposals", status_code=201)
async def generate_lm_studio_proposal(
    data: LMStudioProposalRequest,
    config: RKAConfig = Depends(get_config),
    service: SemanticPatchService = Depends(get_scoped_semantic_patch_service),
) -> dict[str, Any]:
    try:
        return await LMStudioProposalAdapter(service, config).generate(data)
    except (httpx.HTTPError, LMStudioResponseError) as exc:
        raise HTTPException(status_code=502, detail=f"LM Studio request failed: {exc}") from exc
    except Exception as exc:
        _raise_error(exc)
