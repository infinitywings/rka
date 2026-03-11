"""Batch LLM enrichment endpoint — retroactively link existing entries."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from rka.api.deps import get_note_service, get_db, get_llm

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/enrich")
async def enrich_all(
    limit: int = 50,
    fix_types: bool = True,
    note_svc=Depends(get_note_service),
    db=Depends(get_db),
    llm=Depends(get_llm),
):
    """Re-run semantic linking on journal entries that have no relationships set.

    - Populates related_decisions, related_literature, related_mission
    - Optionally corrects misclassified types (fix_types=true)

    Returns a summary of how many entries were updated.
    """
    if not llm:
        return {"status": "skipped", "reason": "LLM not enabled"}

    # Fetch unlinked entries
    rows = await db.fetchall(
        """SELECT id, type, content FROM journal
           WHERE (related_decisions IS NULL OR related_decisions = '[]')
             AND (related_literature IS NULL OR related_literature = '[]')
             AND related_mission IS NULL
             AND confidence != 'superseded'
           ORDER BY created_at DESC LIMIT ?""",
        [limit],
    )

    updated = 0
    type_fixes = 0

    for row in rows:
        links = await note_svc._auto_link(row["content"], row["type"])
        if not links:
            continue

        updates: dict = {}
        if links.related_decision_ids:
            updates["related_decisions"] = note_svc._json_dumps(links.related_decision_ids)
        if links.related_literature_ids:
            updates["related_literature"] = note_svc._json_dumps(links.related_literature_ids)
        if links.related_mission_id:
            updates["related_mission"] = links.related_mission_id
        if fix_types and links.suggested_type and links.suggested_type != row["type"]:
            updates["type"] = links.suggested_type
            type_fixes += 1

        if updates:
            from rka.services.base import _now
            updates["updated_at"] = _now()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            await db.execute(
                f"UPDATE journal SET {set_clause} WHERE id = ?",
                list(updates.values()) + [row["id"]],
            )
            await db.commit()
            updated += 1
            logger.info("Enriched %s: links=%s type_fix=%s", row["id"], list(updates.keys()), "type" in updates)

    return {
        "status": "ok",
        "scanned": len(rows),
        "updated": updated,
        "type_fixes": type_fixes,
    }
