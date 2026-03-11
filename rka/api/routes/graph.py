"""Graph API routes — entity relationship queries for the research map."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from rka.api.deps import get_graph_service
from rka.services.graph import GraphService

router = APIRouter()


@router.get("/graph")
async def get_full_graph(
    include_types: str | None = Query(None, description="Comma-separated entity types to include"),
    phase: str | None = None,
    limit: int = Query(500, le=2000),
    svc: GraphService = Depends(get_graph_service),
):
    """Return the full knowledge graph as {nodes, edges}."""
    types = [t.strip() for t in include_types.split(",")] if include_types else None
    return await svc.get_full_graph(include_types=types, phase=phase, limit=limit)


@router.get("/graph/ego/{entity_id}")
async def get_ego_graph(
    entity_id: str,
    depth: int = Query(1, ge=1, le=3),
    svc: GraphService = Depends(get_graph_service),
):
    """Return subgraph centered on an entity up to `depth` hops."""
    return await svc.get_ego_graph(entity_id, depth=depth)


@router.get("/graph/decision-tree")
async def get_decision_tree(
    root_id: str | None = None,
    svc: GraphService = Depends(get_graph_service),
):
    """Return decisions as a tree with linked entities."""
    return await svc.get_decision_tree(root_id=root_id)


@router.get("/graph/timeline")
async def get_timeline(
    phase: str | None = None,
    since: str | None = None,
    limit: int = Query(100, le=1000),
    svc: GraphService = Depends(get_graph_service),
):
    """Return chronological event timeline."""
    return await svc.get_timeline(phase=phase, since=since, limit=limit)


@router.get("/graph/stats")
async def get_graph_stats(
    svc: GraphService = Depends(get_graph_service),
):
    """Return graph statistics: node/edge counts by type."""
    return await svc.get_stats()
