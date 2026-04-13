"""Maintenance manifest service — pure SQL gap detection for knowledge base hygiene."""

from __future__ import annotations

import logging
from typing import Any

from rka.infra.database import Database
from rka.services.base import BaseService

logger = logging.getLogger(__name__)


class MaintenanceService(BaseService):
    """Detects provenance gaps, orphaned entities, and missing enrichments via SQL queries.

    No LLM required — all checks are structural queries against the database.
    """

    def __init__(self, db: Database, project_id: str = "proj_default"):
        super().__init__(db, project_id=project_id)

    async def get_pending_maintenance(self) -> dict[str, Any]:
        """Run all gap-detection queries and return a compact manifest."""
        pid = self.project_id

        entries_without_tags = await self._entries_without_tags(pid)
        entries_without_claims = await self._entries_without_claims(pid)
        clusters_needing_synthesis = await self._clusters_needing_synthesis(pid)
        flagged_contradictions = await self._flagged_contradictions(pid)
        entries_missing_cross_refs = await self._entries_missing_cross_refs(pid)
        decisions_without_justified_by = await self._decisions_without_justified_by(pid)
        missions_without_motivated_by = await self._missions_without_motivated_by(pid)
        unassigned_clusters = await self._unassigned_clusters(pid)
        stale_claims = await self._stale_claims(pid)
        stale_clusters = await self._stale_clusters(pid)

        categories = {
            "entries_without_tags": entries_without_tags,
            "entries_without_claims": entries_without_claims,
            "clusters_needing_synthesis": clusters_needing_synthesis,
            "flagged_contradictions": flagged_contradictions,
            "entries_missing_cross_refs": entries_missing_cross_refs,
            "decisions_without_justified_by": decisions_without_justified_by,
            "missions_without_motivated_by": missions_without_motivated_by,
            "unassigned_clusters": unassigned_clusters,
            "stale_claims": stale_claims,
            "stale_clusters": stale_clusters,
        }

        total_items = sum(len(c["ids"]) for c in categories.values())
        # Estimate: ~1 tool call per item to fix
        estimated_tool_calls = sum(c["fix_calls_per_item"] * len(c["ids"]) for c in categories.values())

        return {
            "total_items": total_items,
            "estimated_tool_calls": estimated_tool_calls,
            "categories": categories,
        }

    # ---- Individual gap-detection queries ----

    async def _entries_without_tags(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT j.id FROM journal j
               WHERE j.project_id = ?
                 AND j.status != 'retracted'
                 AND NOT EXISTS (
                     SELECT 1 FROM tags t
                     WHERE t.entity_type = 'journal' AND t.entity_id = j.id AND t.project_id = ?
                 )
               ORDER BY j.created_at DESC LIMIT 50""",
            [pid, pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Journal entries with no tags",
            "fix_action": "rka_update_note(id, tags=[...])",
            "fix_calls_per_item": 1,
        }

    async def _entries_without_claims(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT j.id FROM journal j
               WHERE j.project_id = ?
                 AND j.type IN ('note', 'finding', 'insight', 'methodology', 'observation')
                 AND j.status != 'retracted'
                 AND NOT EXISTS (
                     SELECT 1 FROM claims c
                     WHERE c.source_entry_id = j.id AND c.project_id = ?
                 )
               ORDER BY j.created_at DESC LIMIT 50""",
            [pid, pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Substantive entries with no claims extracted",
            "fix_action": "Brain reads entry and manually extracts claims via rka_add_note or review",
            "fix_calls_per_item": 2,
        }

    async def _clusters_needing_synthesis(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT ec.id FROM evidence_clusters ec
               WHERE ec.project_id = ?
                 AND (ec.synthesis IS NULL OR ec.synthesis = '')
                 AND ec.claim_count > 0
               ORDER BY ec.claim_count DESC LIMIT 50""",
            [pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Evidence clusters with claims but no synthesis",
            "fix_action": "rka_review_cluster(cluster_id, confidence, synthesis)",
            "fix_calls_per_item": 1,
        }

    async def _flagged_contradictions(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT rq.id, rq.item_id FROM review_queue rq
               WHERE rq.project_id = ?
                 AND rq.flag = 'potential_contradiction'
                 AND rq.status = 'pending'
               ORDER BY rq.priority DESC LIMIT 50""",
            [pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Pending contradiction flags in review queue",
            "fix_action": "rka_resolve_contradiction(cluster_id, resolution)",
            "fix_calls_per_item": 1,
        }

    async def _entries_missing_cross_refs(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT j.id FROM journal j
               WHERE j.project_id = ?
                 AND j.status != 'retracted'
                 AND (j.related_decisions IS NULL OR j.related_decisions = '[]' OR j.related_decisions = 'null')
                 AND NOT EXISTS (
                     SELECT 1 FROM entity_links el
                     WHERE el.source_id = j.id AND el.project_id = ?
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM entity_links el
                     WHERE el.target_id = j.id AND el.project_id = ?
                 )
               ORDER BY j.created_at DESC LIMIT 50""",
            [pid, pid, pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Journal entries with no cross-references (no related_decisions and no entity_links)",
            "fix_action": "rka_update_note(id, related_decisions=[...]) or Brain adds links",
            "fix_calls_per_item": 1,
        }

    async def _decisions_without_justified_by(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT d.id FROM decisions d
               WHERE d.project_id = ?
                 AND d.status = 'active'
                 AND NOT EXISTS (
                     SELECT 1 FROM entity_links el
                     WHERE el.source_type = 'decision' AND el.source_id = d.id
                       AND el.link_type = 'justified_by' AND el.project_id = ?
                 )
               ORDER BY d.created_at DESC LIMIT 50""",
            [pid, pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Active decisions with no justified_by links",
            "fix_action": "Brain adds related_journal when updating decision or adds entity_links",
            "fix_calls_per_item": 1,
        }

    async def _missions_without_motivated_by(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT m.id FROM missions m
               WHERE m.project_id = ?
                 AND m.status NOT IN ('cancelled')
                 AND NOT EXISTS (
                     SELECT 1 FROM entity_links el
                     WHERE el.target_type = 'mission' AND el.target_id = m.id
                       AND el.link_type = 'motivated' AND el.project_id = ?
                 )
               ORDER BY m.created_at DESC LIMIT 50""",
            [pid, pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Missions without motivated_by_decision links",
            "fix_action": "Brain creates missions with motivated_by_decision parameter",
            "fix_calls_per_item": 1,
        }

    async def _unassigned_clusters(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT ec.id FROM evidence_clusters ec
               WHERE ec.project_id = ?
                 AND (ec.research_question_id IS NULL OR ec.research_question_id = '')
                 AND ec.claim_count > 0
               ORDER BY ec.claim_count DESC LIMIT 50""",
            [pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Evidence clusters not assigned to any research question",
            "fix_action": "rka_review_cluster(cluster_id, ..., research_question_id=dec_id)",
            "fix_calls_per_item": 1,
        }

    async def _stale_claims(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT id FROM claims
               WHERE project_id = ? AND staleness IN ('yellow', 'red')
               ORDER BY updated_at DESC LIMIT 50""",
            [pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Claims flagged stale needing review",
            "fix_action": "Brain reviews claim, updates or resolves staleness",
            "fix_calls_per_item": 1,
        }

    async def _stale_clusters(self, pid: str) -> dict:
        rows = await self.db.fetchall(
            """SELECT id FROM evidence_clusters
               WHERE project_id = ? AND staleness IN ('yellow', 'red')
               ORDER BY updated_at DESC LIMIT 50""",
            [pid],
        )
        return {
            "count": len(rows),
            "ids": [r["id"] for r in rows],
            "description": "Clusters with stale evidence needing re-synthesis",
            "fix_action": "Brain re-reviews cluster with fresh evidence",
            "fix_calls_per_item": 1,
        }
