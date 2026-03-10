"""Context engine routes (Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from rka.api.deps import get_context_engine, get_note_service, get_search_service
from rka.models.context import ContextPackage, ContextRequest

router = APIRouter()


# ---- Context ----

@router.post("/context", response_model=ContextPackage)
async def get_context(data: ContextRequest):
    """Get a focused context package for Brain/Executor."""
    engine = get_context_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Context engine not initialized")
    return await engine.get_context(
        topic=data.topic,
        phase=data.phase,
        depth=data.depth,
        max_tokens=data.max_tokens,
    )


# ---- Summarize ----

class SummarizeRequest(BaseModel):
    topic: str | None = None
    phase: str | None = None
    entity_ids: list[str] | None = None


class SummarizeResponse(BaseModel):
    summary_id: str | None = None
    summary: str
    source_count: int = 0


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(data: SummarizeRequest):
    """On-demand topic summarization, stored as journal entry."""
    from rka.api.deps import get_db, get_llm
    from rka.models.journal import JournalEntryCreate

    db = get_db()
    llm = get_llm()
    search = get_search_service()

    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not available for summarization")

    # Gather entries to summarize
    entries = []
    if data.entity_ids:
        # Fetch specific entities
        for eid in data.entity_ids:
            for table in ("journal", "decisions", "literature", "missions"):
                row = await db.fetchone(f"SELECT * FROM {table} WHERE id = ?", [eid])
                if row:
                    entries.append(row)
                    break
    elif data.topic and search:
        hits = await search.search(data.topic, limit=20)
        table_map = {"journal": "journal", "decision": "decisions", "literature": "literature", "mission": "missions"}
        for hit in hits:
            t = table_map.get(hit.entity_type)
            if t:
                row = await db.fetchone(f"SELECT * FROM {t} WHERE id = ?", [hit.entity_id])
                if row:
                    entries.append(row)
    else:
        raise HTTPException(status_code=400, detail="Provide topic or entity_ids")

    if not entries:
        raise HTTPException(status_code=404, detail="No entries found to summarize")

    # Produce summary via LLM
    narrative = await llm.summarize_entries(entries, max_tokens=800)
    if not narrative:
        raise HTTPException(status_code=502, detail="LLM failed to produce summary")

    # Store as a journal entry
    svc = get_note_service()
    entry = await svc.create(
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


# ---- Eviction Sweep ----

class EvictionItem(BaseModel):
    entity_type: str
    entity_id: str
    title: str
    reason: str


class EvictionProposal(BaseModel):
    proposed: list[EvictionItem] = Field(default_factory=list)
    dry_run: bool = True


@router.post("/eviction-sweep", response_model=EvictionProposal)
async def eviction_sweep(dry_run: bool = True):
    """Rule-based eviction sweep — proposes entries for archival."""
    from rka.api.deps import get_db
    db = get_db()

    proposed: list[EvictionItem] = []

    # Rule 1: Superseded journal entries older than 7 days
    rows = await db.fetchall(
        """SELECT id, content FROM journal
           WHERE confidence = 'superseded'
           AND created_at < datetime('now', '-7 days')
           LIMIT 50""",
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="journal",
            entity_id=row["id"],
            title=(row.get("content") or "")[:80],
            reason="Superseded entry older than 7 days",
        ))

    # Rule 2: Abandoned decisions older than 14 days
    rows = await db.fetchall(
        """SELECT id, question FROM decisions
           WHERE status = 'abandoned'
           AND updated_at < datetime('now', '-14 days')
           LIMIT 50""",
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="decision",
            entity_id=row["id"],
            title=(row.get("question") or "")[:80],
            reason="Abandoned decision older than 14 days",
        ))

    # Rule 3: Excluded literature with no cross-references
    rows = await db.fetchall(
        """SELECT id, title FROM literature
           WHERE status = 'excluded'
           AND related_decisions IS NULL
           LIMIT 50""",
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="literature",
            entity_id=row["id"],
            title=(row.get("title") or "")[:80],
            reason="Excluded literature with no cross-references",
        ))

    # Rule 4: Cancelled missions older than 14 days
    rows = await db.fetchall(
        """SELECT id, objective FROM missions
           WHERE status = 'cancelled'
           AND created_at < datetime('now', '-14 days')
           LIMIT 50""",
    )
    for row in rows:
        proposed.append(EvictionItem(
            entity_type="mission",
            entity_id=row["id"],
            title=(row.get("objective") or "")[:80],
            reason="Cancelled mission older than 14 days",
        ))

    return EvictionProposal(proposed=proposed, dry_run=dry_run)
