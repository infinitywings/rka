"""Literature routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.literature import Literature, LiteratureCreate, LiteratureUpdate
from rka.services.literature import LiteratureService
from rka.api.deps import get_literature_service

router = APIRouter()


@router.post("/literature", response_model=Literature, status_code=201)
async def create_literature(
    data: LiteratureCreate,
    svc: LiteratureService = Depends(get_literature_service),
):
    return await svc.create(data)


@router.get("/literature", response_model=list[Literature])
async def list_literature(
    status: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    venue: str | None = None,
    query: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    svc: LiteratureService = Depends(get_literature_service),
):
    return await svc.list(
        status=status, year_min=year_min, year_max=year_max,
        venue=venue, query=query, limit=limit, offset=offset,
    )


@router.get("/literature/{lit_id}", response_model=Literature)
async def get_literature(lit_id: str, svc: LiteratureService = Depends(get_literature_service)):
    lit = await svc.get(lit_id)
    if lit is None:
        raise HTTPException(404, f"Literature {lit_id} not found")
    return lit


@router.put("/literature/{lit_id}", response_model=Literature)
async def update_literature(
    lit_id: str,
    data: LiteratureUpdate,
    actor: str = "web_ui",
    svc: LiteratureService = Depends(get_literature_service),
):
    lit = await svc.get(lit_id)
    if lit is None:
        raise HTTPException(404, f"Literature {lit_id} not found")
    return await svc.update(lit_id, data, actor=actor)
