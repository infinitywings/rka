"""Tags routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from rka.infra.database import Database
from rka.api.deps import get_db, require_project

router = APIRouter()


class TagCount(BaseModel):
    tag: str
    count: int


@router.get("/tags", response_model=list[TagCount])
async def list_tags(
    entity_type: str | None = None,
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
):
    """List all tags with usage counts."""
    if entity_type:
        rows = await db.fetchall(
            "SELECT tag, COUNT(*) as count FROM tags WHERE entity_type = ? AND project_id = ? GROUP BY tag ORDER BY count DESC",
            [entity_type, project_id],
        )
    else:
        rows = await db.fetchall(
            "SELECT tag, COUNT(*) as count FROM tags WHERE project_id = ? GROUP BY tag ORDER BY count DESC",
            [project_id],
        )
    return [TagCount(tag=row["tag"], count=row["count"]) for row in rows]
