"""Claims API routes (v2.0)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.claim import Claim, ClaimCreate, ClaimUpdate
from rka.services.claims import ClaimService
from rka.api.deps import get_scoped_claim_service

router = APIRouter()


@router.post("/claims", response_model=Claim, status_code=201)
async def create_claim(
    data: ClaimCreate,
    svc: ClaimService = Depends(get_scoped_claim_service),
):
    return await svc.create(data)


@router.get("/claims", response_model=list[Claim])
async def list_claims(
    source_entry_id: str | None = None,
    cluster_id: str | None = None,
    claim_type: str | None = None,
    verified: bool | None = None,
    stale: bool | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: ClaimService = Depends(get_scoped_claim_service),
):
    return await svc.list(
        source_entry_id=source_entry_id,
        cluster_id=cluster_id,
        claim_type=claim_type,
        verified=verified,
        stale=stale,
        limit=limit,
        offset=offset,
    )


@router.get("/claims/{claim_id}", response_model=Claim)
async def get_claim(
    claim_id: str,
    svc: ClaimService = Depends(get_scoped_claim_service),
):
    claim = await svc.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return claim


@router.put("/claims/{claim_id}", response_model=Claim)
async def update_claim(
    claim_id: str,
    data: ClaimUpdate,
    svc: ClaimService = Depends(get_scoped_claim_service),
):
    claim = await svc.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return await svc.update(claim_id, data)
