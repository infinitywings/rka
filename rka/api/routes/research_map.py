"""Research map API routes (v2.0)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from rka.services.research_map import ResearchMapService
from rka.api.deps import get_scoped_research_map_service

router = APIRouter()


@router.get("/research-map")
async def get_research_map(
    svc: ResearchMapService = Depends(get_scoped_research_map_service),
):
    return await svc.get_full_map()


@router.get("/research-map/rq/{rq_id}")
async def get_rq_clusters(
    rq_id: str,
    svc: ResearchMapService = Depends(get_scoped_research_map_service),
):
    return await svc.get_clusters_for_rq(rq_id)


@router.get("/research-map/cluster/{cluster_id}")
async def get_cluster_detail(
    cluster_id: str,
    svc: ResearchMapService = Depends(get_scoped_research_map_service),
):
    detail = await svc.get_cluster_detail(cluster_id)
    if detail is None:
        raise HTTPException(404, f"Cluster {cluster_id} not found")
    return detail


@router.get("/research-map/cluster/{cluster_id}/claims")
async def get_cluster_claims(
    cluster_id: str,
    svc: ResearchMapService = Depends(get_scoped_research_map_service),
):
    return await svc.get_claims_for_cluster(cluster_id)
