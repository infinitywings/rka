"""Graph API routes — entity relationship queries for the research map."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rka.api.deps import get_graph_service, get_scoped_search_service, require_project
from rka.services.graph import GraphService
from rka.services.search import SearchService

router = APIRouter()


class MultiHopRequest(BaseModel):
    """Request for query-anchored multi-hop subgraph retrieval.

    v2.5.1 (mis_01KRRM8CJP34KTN8KJMZQH2PFP / dec_01KRRM5WKSSX7C3ZXZME0BMVQ9):
    ``query`` is now optional when ``seeds`` is provided. Either of:

      - ``query`` only — SearchService.search(query) supplies the seeds
        (existing v2.4-era behavior).
      - ``seeds`` only — explicit anchor entities; bypasses search.
      - both — explicit seeds win; query is recorded but search step is
        bypassed by the service layer.

    Neither-provided yields a 422 with the Affordance-G structured body
    (``{error, detail, hint}``) from the route handler. Pre-v2.5.1 the
    field was ``query: str`` with no default, which silently rejected
    seeds-only invocations with FastAPI's default per-field-error 422 —
    exactly the shape Eval-v2's runner ran into
    (jrn_01KRPGY39DJA2K9KV20XD733GK live-run finding).
    """

    query: str | None = None
    seeds: list[str] | None = None
    max_depth: int = Field(default=3, ge=1, le=5)
    max_nodes: int = Field(default=50, ge=1, le=500)
    edge_weights: dict[str, float] | None = None


class ReportContextRequest(BaseModel):
    """Request for report-scoped context collection.

    ``description`` is the PI's prose description of the report scope.
    ``angle_queries`` are short (1–4 word) seed queries decomposing the
    description into search angles — strongly recommended; the LLM caller
    decomposes far better than server-side stopword stripping.
    """

    description: str = Field(min_length=3)
    angle_queries: list[str] | None = None
    max_depth: int = Field(default=2, ge=1, le=4)
    max_nodes: int = Field(default=60, ge=1, le=500)
    seed_limit: int = Field(default=8, ge=1, le=50)
    edge_weights: dict[str, float] | None = None


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


@router.post("/graph/multi-hop")
async def multi_hop_retrieval(
    data: MultiHopRequest,
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
    search: SearchService = Depends(get_scoped_search_service),
):
    """Query-anchored ranked subgraph retrieval.

    Seeds via SearchService.search(query) (or accepts explicit `seeds=` for
    tests / when caller has anchor entities), BFS-expands using per-edge
    weights from dec_01KQQRZ0CJHB68P2F6233AHEJ5, returns a connected
    relevance-ranked subgraph capped at `max_nodes`.

    v2.5.1: rejects a body that provides neither ``query`` nor ``seeds``
    with a 422 carrying the Affordance-G shape so the caller sees an
    actionable hint instead of FastAPI's default per-field array.
    """
    if not data.query and not data.seeds:
        return JSONResponse(
            status_code=422,
            content={
                "error": "multi_hop_invalid_request",
                "detail": "either `query` or `seeds` must be provided",
                "hint": (
                    'send {"query": "<text>"} for search-based seeding, '
                    'or {"seeds": ["<entity_id>", ...]} for explicit anchor '
                    "entities (both together is also accepted; the service "
                    "uses explicit seeds when present)"
                ),
            },
        )
    return await svc.multi_hop_retrieval(
        # Service signature is `query: str`; pass empty string when the
        # caller relied solely on seeds. The service's seeds-set branch
        # bypasses the search step entirely, so an empty query is unused.
        query=data.query or "",
        seeds=data.seeds,
        max_depth=data.max_depth,
        max_nodes=data.max_nodes,
        edge_weights=data.edge_weights,
        project_id=project_id,
        search_service=search,
    )


@router.post("/graph/report-context")
async def collect_report_context(
    data: ReportContextRequest,
    project_id: str = Depends(require_project),
    svc: GraphService = Depends(get_graph_service),
    search: SearchService = Depends(get_scoped_search_service),
):
    """Assemble the node set relevant to a report described in prose.

    Composite retrieval: seeds from every angle query (plus the keyword-
    normalized description), BFS-expands through entity_links/claim_edges
    with provenance-weighted edges, protects seeds from cap displacement,
    and annotates every node with ``included_via`` inclusion provenance.
    """
    return await svc.collect_report_context(
        description=data.description,
        angle_queries=data.angle_queries,
        max_depth=data.max_depth,
        max_nodes=data.max_nodes,
        seed_limit=data.seed_limit,
        edge_weights=data.edge_weights,
        project_id=project_id,
        search_service=search,
    )


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
