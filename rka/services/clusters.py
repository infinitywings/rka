"""Evidence cluster management and synthesis service (v2.0)."""

from __future__ import annotations

import logging

from rka.infra.ids import generate_id
from rka.models.claim import (
    EvidenceCluster, EvidenceClusterCreate, EvidenceClusterUpdate,
    ClaimEdgeCreate,
)
from rka.services.base import BaseService, _now
from rka.services.jobs import JobQueue

logger = logging.getLogger(__name__)


class ClusterService(BaseService):
    """Manages evidence clusters, LLM clustering, and theme synthesis."""

    # ── CRUD ─────────────────────────────────────────────────

    async def create(self, data: EvidenceClusterCreate) -> EvidenceCluster:
        cluster_id = generate_id("cluster")
        await self.db.execute(
            """INSERT INTO evidence_clusters
               (id, research_question_id, label, synthesis, confidence, project_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                cluster_id, data.research_question_id, data.label,
                data.synthesis, data.confidence, self.project_id,
            ],
        )
        await self.db.commit()
        await self._sync_fts("cluster", cluster_id, {
            "label": data.label, "synthesis": data.synthesis or "",
        })
        await self.audit("create", "cluster", cluster_id, "llm")
        return await self.get(cluster_id)

    async def get(self, cluster_id: str) -> EvidenceCluster | None:
        row = await self.db.fetchone(
            "SELECT * FROM evidence_clusters WHERE id = ? AND project_id = ?",
            [cluster_id, self.project_id],
        )
        if row is None:
            return None
        return self._row_to_model(row)

    async def list(
        self,
        research_question_id: str | None = None,
        confidence: str | None = None,
        needs_reprocessing: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvidenceCluster]:
        conditions = ["project_id = ?"]
        params: list = [self.project_id]

        if research_question_id:
            conditions.append("research_question_id = ?")
            params.append(research_question_id)
        if confidence:
            conditions.append("confidence = ?")
            params.append(confidence)
        if needs_reprocessing is not None:
            conditions.append("needs_reprocessing = ?")
            params.append(int(needs_reprocessing))

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM evidence_clusters WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [self._row_to_model(row) for row in rows]

    async def update(self, cluster_id: str, data: EvidenceClusterUpdate) -> EvidenceCluster:
        dump = data.model_dump(exclude_none=True)
        if not dump:
            return await self.get(cluster_id)

        # Validate research_question_id if provided
        if "research_question_id" in dump:
            rq_id = dump["research_question_id"]
            rq = await self.db.fetchone(
                "SELECT id, kind FROM decisions WHERE id = ? AND project_id = ?",
                [rq_id, self.project_id],
            )
            if not rq:
                raise ValueError(f"Decision {rq_id} not found")
            if rq["kind"] != "research_question":
                raise ValueError(
                    f"Decision {rq_id} is not a research_question (kind={rq['kind']})"
                )

        if "needs_reprocessing" in dump:
            dump["needs_reprocessing"] = int(dump["needs_reprocessing"])

        dump["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in dump)
        values = list(dump.values()) + [cluster_id, self.project_id]

        await self.db.execute(
            f"UPDATE evidence_clusters SET {set_clause} WHERE id = ? AND project_id = ?",
            values,
        )
        await self.db.commit()
        if "label" in dump or "synthesis" in dump:
            row = await self.db.fetchone(
                "SELECT label, synthesis FROM evidence_clusters WHERE id = ? AND project_id = ?",
                [cluster_id, self.project_id],
            )
            if row:
                await self._sync_fts("cluster", cluster_id, dict(row))
        await self.audit("update", "cluster", cluster_id, "system", {"fields": list(dump.keys())})
        return await self.get(cluster_id)

    async def mark_needs_reprocessing(self, cluster_id: str) -> None:
        """Flag a cluster for re-distillation."""
        await self.db.execute(
            "UPDATE evidence_clusters SET needs_reprocessing = 1, updated_at = ? WHERE id = ? AND project_id = ?",
            [_now(), cluster_id, self.project_id],
        )
        await self.db.commit()

    # ── Background job handlers ──────────────────────────────

    async def process_cluster_update_job(self, claim_id: str) -> dict:
        """Assign a verified claim to a cluster and score inter-claim relations."""
        claim_row = await self.db.fetchone(
            "SELECT * FROM claims WHERE id = ? AND project_id = ?",
            [claim_id, self.project_id],
        )
        if claim_row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        # Get existing clusters for this project
        clusters = await self.db.fetchall(
            "SELECT id, label, claim_count FROM evidence_clusters WHERE project_id = ? ORDER BY claim_count DESC LIMIT 30",
            [self.project_id],
        )

        # Get nearby claims (most recent verified claims)
        nearby = await self.db.fetchall(
            """SELECT id, claim_type, content FROM claims
               WHERE project_id = ? AND verified = 1 AND stale = 0 AND id != ?
               ORDER BY created_at DESC LIMIT 20""",
            [self.project_id, claim_id],
        )

        assignment = await self.llm.assign_to_cluster(
            claim_content=claim_row["content"],
            claim_type=claim_row["claim_type"],
            existing_clusters=[dict(c) for c in clusters],
            nearby_claims=[dict(n) for n in nearby],
        )

        # Create or find cluster
        if assignment.cluster_id:
            cluster_id = assignment.cluster_id
        else:
            # Create new cluster
            cluster = await self.create(EvidenceClusterCreate(
                label=assignment.cluster_label,
            ))
            cluster_id = cluster.id

        # Create member_of edge
        from rka.services.claims import ClaimService
        claim_svc = ClaimService(self.db, llm=self.llm, embeddings=self.embeddings, project_id=self.project_id)
        await claim_svc.create_edge(ClaimEdgeCreate(
            source_claim_id=claim_id,
            cluster_id=cluster_id,
            relation="member_of",
        ))

        # Create inter-claim relation edges
        for rel in assignment.relations:
            # Validate target exists
            target = await self.db.fetchone(
                "SELECT id FROM claims WHERE id = ? AND project_id = ?",
                [rel.target_claim_id, self.project_id],
            )
            if target:
                await claim_svc.create_edge(ClaimEdgeCreate(
                    source_claim_id=claim_id,
                    target_claim_id=rel.target_claim_id,
                    cluster_id=cluster_id,
                    relation=rel.relation,
                    confidence=rel.confidence,
                ))

        # Update cluster claim count
        count_row = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM claim_edges WHERE cluster_id = ? AND relation = 'member_of'",
            [cluster_id],
        )
        claim_count = count_row["cnt"] if count_row else 0
        await self.db.execute(
            "UPDATE evidence_clusters SET claim_count = ?, updated_at = ? WHERE id = ?",
            [claim_count, _now(), cluster_id],
        )
        await self.db.commit()

        # Note: theme synthesis and contradiction checks are now Brain tasks,
        # not automated LLM jobs. Use rka_review_cluster and rka_resolve_contradiction.

        return {"outcome": "updated", "cluster_id": cluster_id, "relations": len(assignment.relations)}

    async def process_theme_synthesize_job(self, cluster_id: str) -> dict:
        """Generate/regenerate synthesis for a cluster."""
        cluster = await self.get(cluster_id)
        if cluster is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        # Get all claims in this cluster
        claims = await self.db.fetchall(
            """SELECT c.* FROM claims c
               JOIN claim_edges ce ON ce.source_claim_id = c.id
               WHERE ce.cluster_id = ? AND ce.relation = 'member_of' AND c.stale = 0
               ORDER BY c.confidence DESC""",
            [cluster_id],
        )
        if not claims:
            return {"outcome": "noop", "reason": "no_claims"}

        synthesis = await self.llm.synthesize_theme(
            cluster_label=cluster.label,
            claims=[dict(c) for c in claims],
        )

        await self.db.execute(
            """UPDATE evidence_clusters
               SET synthesis = ?, confidence = ?, gap_count = ?, needs_reprocessing = 0, updated_at = ?
               WHERE id = ? AND project_id = ?""",
            [
                synthesis.synthesis, synthesis.confidence,
                len(synthesis.gaps), _now(),
                cluster_id, self.project_id,
            ],
        )
        await self.db.commit()
        await self._sync_fts("cluster", cluster_id, {
            "label": cluster.label, "synthesis": synthesis.synthesis,
        })

        # Flag for Brain review if complex
        if len(claims) >= 10 or synthesis.confidence == "contested":
            review_id = generate_id("review")
            import json
            flag = "complex_synthesis_needed" if len(claims) >= 10 else "potential_contradiction"
            await self.db.execute(
                """INSERT OR IGNORE INTO review_queue
                   (id, item_type, item_id, flag, context, priority, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    review_id, "cluster", cluster_id, flag,
                    json.dumps({
                        "claim_count": len(claims),
                        "confidence": synthesis.confidence,
                        "gaps": synthesis.gaps,
                        "contradictions": synthesis.contradictions,
                    }),
                    70 if flag == "potential_contradiction" else 90,
                    self.project_id,
                ],
            )
            await self.db.commit()

        return {
            "outcome": "updated",
            "confidence": synthesis.confidence,
            "gap_count": len(synthesis.gaps),
        }

    async def process_contradiction_check_job(self, claim_id: str, payload: dict | None = None) -> dict:
        """Check if a new claim contradicts existing claims in the same cluster."""
        claim_row = await self.db.fetchone(
            "SELECT * FROM claims WHERE id = ? AND project_id = ?",
            [claim_id, self.project_id],
        )
        if claim_row is None:
            return {"outcome": "missing"}

        cluster_id = (payload or {}).get("cluster_id")
        if not cluster_id:
            return {"outcome": "skipped", "reason": "no_cluster"}

        # Check existing contradicts edges
        contradictions = await self.db.fetchall(
            """SELECT * FROM claim_edges
               WHERE cluster_id = ? AND relation = 'contradicts' AND project_id = ?""",
            [cluster_id, self.project_id],
        )

        if contradictions:
            # Flag for review
            import json
            review_id = generate_id("review")
            await self.db.execute(
                """INSERT OR IGNORE INTO review_queue
                   (id, item_type, item_id, flag, context, priority, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    review_id, "cluster", cluster_id, "potential_contradiction",
                    json.dumps({"claim_id": claim_id, "contradiction_count": len(contradictions)}),
                    70, self.project_id,
                ],
            )
            await self.db.commit()
            return {"outcome": "flagged", "contradictions": len(contradictions)}

        return {"outcome": "clean"}

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_model(row: dict) -> EvidenceCluster:
        return EvidenceCluster(
            id=row["id"],
            research_question_id=row.get("research_question_id"),
            label=row["label"],
            synthesis=row.get("synthesis"),
            confidence=row.get("confidence", "emerging"),
            claim_count=row.get("claim_count", 0),
            gap_count=row.get("gap_count", 0),
            needs_reprocessing=bool(row.get("needs_reprocessing", 0)),
            synthesized_by=row.get("synthesized_by", "llm"),
            project_id=row.get("project_id", "proj_default"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
