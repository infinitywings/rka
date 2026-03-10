"""Tags routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from rka.infra.database import Database
from rka.api.deps import get_db

router = APIRouter()


class TagCount(BaseModel):
    tag: str
    count: int


@router.get("/tags", response_model=list[TagCount])
async def list_tags(
    entity_type: str | None = None,
    db: Database = Depends(get_db),
):
    """List all tags with usage counts."""
    if entity_type:
        rows = await db.fetchall(
            "SELECT tag, COUNT(*) as count FROM tags WHERE entity_type = ? GROUP BY tag ORDER BY count DESC",
            [entity_type],
        )
    else:
        rows = await db.fetchall(
            "SELECT tag, COUNT(*) as count FROM tags GROUP BY tag ORDER BY count DESC"
        )
    return [TagCount(tag=row["tag"], count=row["count"]) for row in rows]
