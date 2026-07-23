"""Project-attested bulk entity resolution."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from rka.api.deps import get_db, require_project
from rka.infra.database import Database
from rka.services.entity_resolver import EntityResolverService

router = APIRouter()


class EntityResolutionRequest(BaseModel):
    """Inputs to the read-only heterogeneous entity resolver."""

    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(default_factory=list, max_length=1000)
    include_sources: bool = False
    include_edges: bool = False


def get_entity_resolver(
    db: Annotated[Database, Depends(get_db)],
) -> EntityResolverService:
    return EntityResolverService(db)


@router.post("/entities/resolve")
async def resolve_entities(
    data: EntityResolutionRequest,
    project_id: Annotated[str, Depends(require_project)],
    service: Annotated[EntityResolverService, Depends(get_entity_resolver)],
) -> dict:
    """Resolve every requested ID without leaking foreign-project content."""
    try:
        return await service.resolve_entities(
            project_id,
            data.ids,
            include_sources=data.include_sources,
            include_edges=data.include_edges,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
