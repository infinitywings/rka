"""Research map service — composes the three-level view (v2.0)."""

from __future__ import annotations

from rka.services.base import BaseService


class ResearchMapService(BaseService):
    """Composes the three-level research map: RQs → Clusters → Claims."""

    async def get_research_questions(self) -> list[dict]:
        """Get all research questions (decisions with kind='research_question')."""
        rqs = await self.db.fetchall(
            """SELECT id, question, status, phase, kind, created_at
               FROM decisions
               WHERE project_id = ? AND kind = 'research_question'
               ORDER BY created_at DESC""",
            [self.project_id],
        )

        result = []
        for rq in rqs:
            # Count clusters and claims for this RQ
            stats = await self.db.fetchone(
                """SELECT
                       COUNT(*) as cluster_count,
                       COALESCE(SUM(claim_count), 0) as total_claims,
                       COALESCE(SUM(gap_count), 0) as total_gaps,
                       SUM(CASE WHEN confidence = 'contested' THEN 1 ELSE 0 END) as contradiction_count
                   FROM evidence_clusters
                   WHERE research_question_id = ? AND project_id = ?""",
                [rq["id"], self.project_id],
            )
            result.append({
                "id": rq["id"],
                "question": rq["question"],
                "status": rq["status"],
                "phase": rq.get("phase"),
                "cluster_count": (stats["cluster_count"] or 0) if stats else 0,
                "total_claims": (stats["total_claims"] or 0) if stats else 0,
                "gap_count": (stats["total_gaps"] or 0) if stats else 0,
                "contradiction_count": (stats["contradiction_count"] or 0) if stats else 0,
                "created_at": rq.get("created_at"),
            })
        return result

    async def get_clusters_for_rq(self, rq_id: str) -> list[dict]:
        """Get evidence clusters for a specific research question."""
        clusters = await self.db.fetchall(
            """SELECT * FROM evidence_clusters
               WHERE research_question_id = ? AND project_id = ?
               ORDER BY claim_count DESC""",
            [rq_id, self.project_id],
        )

        result = []
        for c in clusters:
            # Get inter-cluster edges
            edges = await self.db.fetchall(
                """SELECT DISTINCT ce.relation, ce.target_claim_id, ce.confidence
                   FROM claim_edges ce
                   JOIN claim_edges ce2 ON ce.target_claim_id = ce2.source_claim_id
                   WHERE ce.cluster_id = ? AND ce2.cluster_id != ?
                     AND ce.relation IN ('supports', 'contradicts', 'qualifies')
                   LIMIT 20""",
                [c["id"], c["id"]],
            )
            result.append({
                "id": c["id"],
                "label": c["label"],
                "synthesis": c.get("synthesis"),
                "confidence": c.get("confidence", "emerging"),
                "claim_count": c.get("claim_count", 0),
                "gap_count": c.get("gap_count", 0),
                "needs_reprocessing": bool(c.get("needs_reprocessing", 0)),
                "synthesized_by": c.get("synthesized_by", "llm"),
                "edges": [dict(e) for e in edges],
            })
        return result

    async def get_claims_for_cluster(self, cluster_id: str) -> list[dict]:
        """Get individual claims in a cluster with provenance."""
        claims = await self.db.fetchall(
            """SELECT c.*, j.content as source_content, j.type as source_type,
                      j.source as source_actor
               FROM claims c
               JOIN claim_edges ce ON ce.source_claim_id = c.id AND ce.relation = 'member_of'
               LEFT JOIN journal j ON j.id = c.source_entry_id
               WHERE ce.cluster_id = ? AND c.project_id = ?
               ORDER BY c.confidence DESC""",
            [cluster_id, self.project_id],
        )
        return [
            {
                "id": c["id"],
                "claim_type": c["claim_type"],
                "content": c["content"],
                "confidence": c.get("confidence", 0.5),
                "verified": bool(c.get("verified", 0)),
                "stale": bool(c.get("stale", 0)),
                "source_entry_id": c["source_entry_id"],
                "source_offset_start": c.get("source_offset_start"),
                "source_offset_end": c.get("source_offset_end"),
                "source_type": c.get("source_type"),
                "source_actor": c.get("source_actor"),
            }
            for c in claims
        ]

    async def get_full_map(self) -> dict:
        """Get the complete three-level research map."""
        rqs = await self.get_research_questions()

        # Unassigned clusters (no RQ)
        unassigned = await self.db.fetchall(
            """SELECT * FROM evidence_clusters
               WHERE research_question_id IS NULL AND project_id = ?
               ORDER BY claim_count DESC""",
            [self.project_id],
        )

        # Summary stats
        total_claims = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM claims WHERE project_id = ? AND stale = 0",
            [self.project_id],
        )
        total_clusters = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM evidence_clusters WHERE project_id = ?",
            [self.project_id],
        )
        pending_review = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM review_queue WHERE project_id = ? AND status = 'pending'",
            [self.project_id],
        )

        return {
            "research_questions": rqs,
            "unassigned_clusters": [
                {
                    "id": c["id"],
                    "label": c["label"],
                    "claim_count": c.get("claim_count", 0),
                    "confidence": c.get("confidence", "emerging"),
                }
                for c in unassigned
            ],
            "summary": {
                "total_rqs": len(rqs),
                "total_clusters": total_clusters["cnt"] if total_clusters else 0,
                "total_claims": total_claims["cnt"] if total_claims else 0,
                "total_gaps": sum(rq.get("gap_count", 0) for rq in rqs),
                "total_contradictions": sum(rq.get("contradiction_count", 0) for rq in rqs),
                "pending_review": pending_review["cnt"] if pending_review else 0,
            },
        }
