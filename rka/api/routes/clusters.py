"""Evidence cluster API routes (v2.0)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.claim import EvidenceCluster, EvidenceClusterCreate, EvidenceClusterUpdate
from rka.services.clusters import ClusterService
from rka.services.research_map import ResearchMapService
from rka.api.deps import get_scoped_cluster_service, get_scoped_research_map_service

router = APIRouter()


@router.post("/clusters", response_model=EvidenceCluster, status_code=201)
async def create_cluster(
    data: EvidenceClusterCreate,
    svc: ClusterService = Depends(get_scoped_cluster_service),
):
    return await svc.create(data)


@router.get("/clusters", response_model=list[EvidenceCluster])
async def list_clusters(
    research_question_id: str | None = None,
    confidence: str | None = None,
    needs_reprocessing: bool | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: ClusterService = Depends(get_scoped_cluster_service),
):
    return await svc.list(
        research_question_id=research_question_id,
        confidence=confidence,
        needs_reprocessing=needs_reprocessing,
        limit=limit,
        offset=offset,
    )


@router.get("/clusters/{cluster_id}")
async def get_cluster(
    cluster_id: str,
    include_claims: bool = False,
    svc: ClusterService = Depends(get_scoped_cluster_service),
    map_svc: ResearchMapService = Depends(get_scoped_research_map_service),
):
    cluster = await svc.get(cluster_id)
    if cluster is None:
        raise HTTPException(404, f"Cluster {cluster_id} not found")
    result = cluster.model_dump()
    if include_claims:
        claims = await map_svc.get_claims_for_cluster(cluster_id)
        result["claims"] = claims
    return result


@router.put("/clusters/{cluster_id}", response_model=EvidenceCluster)
async def update_cluster(
    cluster_id: str,
    data: EvidenceClusterUpdate,
    svc: ClusterService = Depends(get_scoped_cluster_service),
):
    cluster = await svc.get(cluster_id)
    if cluster is None:
        raise HTTPException(404, f"Cluster {cluster_id} not found")
    try:
        return await svc.update(cluster_id, data)
    except ValueError as e:
        raise HTTPException(422, str(e))
