"""Literature routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.literature import Literature, LiteratureCreate, LiteratureUpdate
from rka.services.literature import LiteratureService
from rka.api.deps import get_scoped_literature_service

router = APIRouter()


@router.post("/literature", response_model=Literature, status_code=201)
async def create_literature(
    data: LiteratureCreate,
    svc: LiteratureService = Depends(get_scoped_literature_service),
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
    svc: LiteratureService = Depends(get_scoped_literature_service),
):
    return await svc.list(
        status=status, year_min=year_min, year_max=year_max,
        venue=venue, query=query, limit=limit, offset=offset,
    )


@router.get("/literature/{lit_id}", response_model=Literature)
async def get_literature(lit_id: str, svc: LiteratureService = Depends(get_scoped_literature_service)):
    lit = await svc.get(lit_id)
    if lit is None:
        raise HTTPException(404, f"Literature {lit_id} not found")
    return lit


@router.put("/literature/{lit_id}", response_model=Literature)
async def update_literature(
    lit_id: str,
    data: LiteratureUpdate,
    actor: str = "web_ui",
    svc: LiteratureService = Depends(get_scoped_literature_service),
):
    lit = await svc.get(lit_id)
    if lit is None:
        raise HTTPException(404, f"Literature {lit_id} not found")
    return await svc.update(lit_id, data, actor=actor)


@router.post("/literature/{lit_id}/link_zotero")
async def link_literature_to_zotero(
    lit_id: str,
    actor: str = "system",
    svc: LiteratureService = Depends(get_scoped_literature_service),
) -> dict:
    """Resolve a literature entry to its Zotero item key via DOI / arXiv ID /
    URL / ISBN / title-author-year fallback. Persists the link on success.

    Returns:
      {"zotero_item_key": "...", "matched_by": "doi"|"arxiv_id"|...}
      {"zotero_item_key": null, "reason": "no_match"|"multiple_matches_below_threshold"|
       "weak_match_needs_confirmation"|"zotero_not_configured", "candidates": [...]}
    """
    import asyncio
    from rka.services.zotero_linker import link_literature

    lit = await svc.get(lit_id)
    if lit is None:
        raise HTTPException(404, f"Literature {lit_id} not found")

    result = await asyncio.to_thread(
        link_literature,
        title=lit.title,
        authors=lit.authors,
        year=lit.year,
        doi=lit.doi,
        url=lit.url,
    )

    if result.zotero_item_key:
        await svc.update(
            lit_id,
            LiteratureUpdate(
                zotero_item_key=result.zotero_item_key,
                zotero_match_method=result.matched_by,  # type: ignore[arg-type]
            ),
            actor=actor,
        )
    return result.to_dict()
