"""Context engine routes (Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from rka.api.deps import (
    get_context_engine,
    get_db,
    get_llm,
    get_scoped_note_service,
    get_scoped_search_service,
    require_project,
)
from rka.infra.database import Database
from rka.infra.llm import LLMClient
from rka.models.context import ContextPackage, ContextRequest
from rka.models.journal import JournalEntryCreate
from rka.services.context import ContextEngine
from rka.services.notes import NoteService
from rka.services.search import SearchService

router = APIRouter()


@router.post("/context", response_model=ContextPackage)
async def get_context(
    data: ContextRequest,
    project_id: str = Depends(require_project),
    engine: ContextEngine | None = Depends(get_context_engine),
):
    """Get a focused context package for Brain/Executor."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Context engine not initialized")
    return await engine.get_context(
        topic=data.topic,
        phase=data.phase,
        depth=data.depth,
        max_tokens=data.max_tokens,
        project_id=project_id,
    )


class SummarizeRequest(BaseModel):
    topic: str | None = None
    phase: str | None = None
    entity_ids: list[str] | None = None


class SummarizeResponse(BaseModel):
    summary_id: str | None = None
    summary: str
    source_count: int = 0


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(
    data: SummarizeRequest,
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm),
    search: SearchService = Depends(get_scoped_search_service),
    note_svc: NoteService = Depends(get_scoped_note_service),
):
    """On-demand topic summarization, stored as journal entry."""
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not available for summarization")

    entries = []
    if data.entity_ids:
        for eid in data.entity_ids:
            for table in ("journal", "decisions", "literature", "missions"):
                row = await db.fetchone(
                    f"SELECT * FROM {table} WHERE id = ? AND project_id = ?",
                    [eid, project_id],
                )
                if row:
                    entries.append(row)
                    break
    elif data.topic:
        hits = await search.search(data.topic, limit=20)
        table_map = {
            "journal": "journal",
            "decision": "decisions",
            "literature": "literature",
            "mission": "missions",
        }
        for hit in hits:
            table = table_map.get(hit.entity_type)
            if not table:
                continue
            row = await db.fetchone(
                f"SELECT * FROM {table} WHERE id = ? AND project_id = ?",
                [hit.entity_id, project_id],
            )
            if row:
                entries.append(row)
    else:
        raise HTTPException(status_code=400, detail="Provide topic or entity_ids")

    if not entries:
        raise HTTPException(status_code=404, detail="No entries found to summarize")

    narrative = await llm.summarize_entries(entries, max_tokens=800)
    if not narrative:
        raise HTTPException(status_code=502, detail="LLM failed to produce summary")

    entry = await note_svc.create(
        JournalEntryCreate(
            type="insight",
            content=narrative,
            source="llm",
            phase=data.phase,
            confidence="tested",
            importance="normal",
            tags=["auto-summary"],
        ),
        actor="llm",
    )

    return SummarizeResponse(
        summary_id=entry.id,
        summary=narrative,
        source_count=len(entries),
    )


class EvictionItem(BaseModel):
    entity_type: str
    entity_id: str
    title: str
    reason: str


class EvictionProposal(BaseModel):
    proposed: list[EvictionItem] = Field(default_factory=list)
    dry_run: bool = True


@router.post("/eviction-sweep", response_model=EvictionProposal)
async def eviction_sweep(
    dry_run: bool = True,
    project_id: str = Depends(require_project),
    db: Database = Depends(get_db),
):
    """Rule-based eviction sweep — proposes entries for archival."""
    proposed: list[EvictionItem] = []

    rows = await db.fetchall(
        """SELECT id, content FROM journal
           WHERE confidence = 'superseded'
           AND project_id = ?
           AND created_at < datetime('now', '-7 days')
           LIMIT 50""",
        [project_id],
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="journal",
            entity_id=row["id"],
            title=(row.get("content") or "")[:80],
            reason="Superseded entry older than 7 days",
        ))

    rows = await db.fetchall(
        """SELECT id, question FROM decisions
           WHERE status = 'abandoned'
           AND project_id = ?
           AND updated_at < datetime('now', '-14 days')
           LIMIT 50""",
        [project_id],
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="decision",
            entity_id=row["id"],
            title=(row.get("question") or "")[:80],
            reason="Abandoned decision older than 14 days",
        ))

    rows = await db.fetchall(
        """SELECT id, title FROM literature
           WHERE status = 'excluded'
           AND project_id = ?
           AND related_decisions IS NULL
           LIMIT 50""",
        [project_id],
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="literature",
            entity_id=row["id"],
            title=(row.get("title") or "")[:80],
            reason="Excluded literature with no cross-references",
        ))

    rows = await db.fetchall(
        """SELECT id, objective FROM missions
           WHERE status = 'cancelled'
           AND project_id = ?
           AND created_at < datetime('now', '-14 days')
           LIMIT 50""",
        [project_id],
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="mission",
            entity_id=row["id"],
            title=(row.get("objective") or "")[:80],
            reason="Cancelled mission older than 14 days",
        ))

    return EvictionProposal(proposed=proposed, dry_run=dry_run)
