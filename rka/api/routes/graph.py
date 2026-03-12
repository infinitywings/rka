"""Graph API routes — entity relationship queries for the research map."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from rka.api.deps import get_graph_service, require_project
from rka.services.graph import GraphService

router = APIRouter()


@router.get("/graph")
async def get_full_graph(
    view: Literal["full", "condensed", "keynodes"] = Query(
        "full", description="Graph view: full, condensed, or keynodes"
    ),
    include_types: str | None = Query(None, description="Comma-separated entity types to include"),
    phase: str | None = None,
    limit: int = Query(500, le=2000),
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Return graph payload for full or condensed keynode-centric views."""
    types = [t.strip() for t in include_types.split(",")] if include_types else None
    return await svc.get_graph_view(
        project_id=project_id,
        view=view,
        include_types=types,
        phase=phase,
        limit=limit,
    )


@router.post("/graph/refresh")
async def refresh_graph_view(
    top_per_kind: int = Query(8, ge=2, le=30),
    min_importance: float = Query(0.45, ge=0.0, le=1.0),
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Rebuild condensed keynode view for research-map focus mode."""
    return await svc.refresh_condensed_view(
        project_id=project_id,
        top_per_kind=top_per_kind,
        min_importance=min_importance,
    )


@router.get("/graph/ego/{entity_id}")
async def get_ego_graph(
    entity_id: str,
    depth: int = Query(1, ge=1, le=3),
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Return subgraph centered on an entity up to `depth` hops."""
    return await svc.get_ego_graph(entity_id, depth=depth, project_id=project_id)


@router.get("/graph/decision-tree")
async def get_decision_tree(
    root_id: str | None = None,
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Return decisions as a tree with linked entities."""
    return await svc.get_decision_tree(root_id=root_id, project_id=project_id)


@router.get("/graph/timeline")
async def get_timeline(
    phase: str | None = None,
    since: str | None = None,
    limit: int = Query(100, le=1000),
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Return chronological event timeline."""
    return await svc.get_timeline(project_id=project_id, phase=phase, since=since, limit=limit)


@router.get("/graph/stats")
async def get_graph_stats(
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
):
    """Return graph statistics: node/edge counts by type."""
    return await svc.get_stats(project_id=project_id)
