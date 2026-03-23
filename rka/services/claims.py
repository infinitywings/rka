"""Claim extraction, verification, and CRUD service (v2.0)."""

from __future__ import annotations

import logging

from rka.infra.ids import generate_id
from rka.models.claim import Claim, ClaimCreate, ClaimUpdate, ClaimEdge, ClaimEdgeCreate
from rka.services.base import BaseService, _now
from rka.services.jobs import JobQueue

logger = logging.getLogger(__name__)


class ClaimService(BaseService):
    """Manages claims extracted from journal entries."""

    _FTS_CONFIG = {
        **BaseService._FTS_CONFIG,
        "claim": {"table": "fts_claims", "columns": ["id", "content"]},
    }

    def _job_dedupe_key(self, entity_id: str, operation: str) -> str:
        return f"{self.project_id}:claim:{entity_id}:{operation}"

    # ── CRUD ─────────────────────────────────────────────────

    async def create(self, data: ClaimCreate) -> Claim:
        """Create a new claim."""
        claim_id = generate_id("claim")
        await self.db.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence, verified, stale,
                source_offset_start, source_offset_end, project_id)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            [
                claim_id, data.source_entry_id, data.claim_type, data.content,
                data.confidence, int(data.verified),
                data.source_offset_start, data.source_offset_end,
                self.project_id,
            ],
        )
        await self.db.commit()

        # FTS sync
        await self._sync_fts("claim", claim_id, {"content": data.content})

        # Entity link: derived_from
        await self.add_link(
            "claim", claim_id, "derived_from", "journal", data.source_entry_id,
            created_by="llm",
        )

        # Enqueue embedding job
        if self.embeddings:
            queue = JobQueue(self.db)
            await queue.enqueue(
                "claim_embed",
                project_id=self.project_id,
                entity_type="claim",
                entity_id=claim_id,
                dedupe_key=self._job_dedupe_key(claim_id, "embed"),
                priority=125,
            )

        await self.audit("create", "claim", claim_id, "llm")
        return await self.get(claim_id)

    async def get(self, claim_id: str) -> Claim | None:
        row = await self.db.fetchone(
            "SELECT * FROM claims WHERE id = ? AND project_id = ?",
            [claim_id, self.project_id],
        )
        if row is None:
            return None
        return self._row_to_model(row)

    async def list(
        self,
        source_entry_id: str | None = None,
        cluster_id: str | None = None,
        claim_type: str | None = None,
        verified: bool | None = None,
        stale: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Claim]:
        conditions = ["project_id = ?"]
        params: list = [self.project_id]

        if source_entry_id:
            conditions.append("source_entry_id = ?")
            params.append(source_entry_id)
        if claim_type:
            conditions.append("claim_type = ?")
            params.append(claim_type)
        if verified is not None:
            conditions.append("verified = ?")
            params.append(int(verified))
        if stale is not None:
            conditions.append("stale = ?")
            params.append(int(stale))

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        sql = f"SELECT * FROM claims WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"

        # If filtering by cluster, join through claim_edges
        if cluster_id:
            sql = f"""
                SELECT c.* FROM claims c
                JOIN claim_edges ce ON ce.source_claim_id = c.id AND ce.relation = 'member_of'
                WHERE ce.cluster_id = ? AND c.project_id = ?
                ORDER BY c.created_at DESC LIMIT ? OFFSET ?
            """
            params = [cluster_id, self.project_id, limit, offset]

        rows = await self.db.fetchall(sql, params)
        return [self._row_to_model(row) for row in rows]

    async def update(self, claim_id: str, data: ClaimUpdate) -> Claim:
        dump = data.model_dump(exclude_none=True)
        if not dump:
            return await self.get(claim_id)

        # Convert bool fields to int for SQLite
        for bfield in ("verified", "stale"):
            if bfield in dump:
                dump[bfield] = int(dump[bfield])

        dump["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in dump)
        values = list(dump.values()) + [claim_id, self.project_id]

        await self.db.execute(
            f"UPDATE claims SET {set_clause} WHERE id = ? AND project_id = ?",
            values,
        )
        await self.db.commit()
        await self.audit("update", "claim", claim_id, "system", {"fields": list(dump.keys())})
        return await self.get(claim_id)

    async def mark_stale_by_entry(self, entry_id: str) -> int:
        """Mark all claims from a journal entry as stale (for re-distillation)."""
        result = await self.db.execute(
            "UPDATE claims SET stale = 1, updated_at = ? WHERE source_entry_id = ? AND project_id = ?",
            [_now(), entry_id, self.project_id],
        )
        await self.db.commit()
        return result.rowcount if hasattr(result, "rowcount") else 0

    async def get_claims_for_entry(self, entry_id: str) -> list[Claim]:
        """Get all claims extracted from a specific journal entry."""
        return await self.list(source_entry_id=entry_id)

    # ── Claim Edges ──────────────────────────────────────────

    async def create_edge(self, data: ClaimEdgeCreate) -> ClaimEdge:
        edge_id = generate_id("claim_edge")
        await self.db.execute(
            """INSERT INTO claim_edges
               (id, source_claim_id, target_claim_id, cluster_id, relation, confidence, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                edge_id, data.source_claim_id, data.target_claim_id,
                data.cluster_id, data.relation, data.confidence, self.project_id,
            ],
        )
        await self.db.commit()
        return ClaimEdge(
            id=edge_id,
            source_claim_id=data.source_claim_id,
            target_claim_id=data.target_claim_id,
            cluster_id=data.cluster_id,
            relation=data.relation,
            confidence=data.confidence,
            project_id=self.project_id,
        )

    async def get_edges_for_cluster(self, cluster_id: str) -> list[ClaimEdge]:
        rows = await self.db.fetchall(
            "SELECT * FROM claim_edges WHERE cluster_id = ? AND project_id = ?",
            [cluster_id, self.project_id],
        )
        return [self._edge_to_model(row) for row in rows]

    # ── Background job handlers ──────────────────────────────

    async def process_extract_claims_job(self, entry_id: str) -> dict:
        """Extract claims from a journal entry using the LLM."""
        row = await self.db.fetchone(
            "SELECT content FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        # Get existing claims for dedup
        existing = await self.db.fetchall(
            "SELECT content FROM claims WHERE source_entry_id = ? AND project_id = ? AND stale = 0",
            [entry_id, self.project_id],
        )
        existing_contents = [r["content"] for r in existing]

        # Extract claims via LLM
        result = await self.llm.extract_claims(row["content"], existing_contents or None)

        created_ids = []
        for extracted in result.claims:
            claim = await self.create(ClaimCreate(
                source_entry_id=entry_id,
                claim_type=extracted.claim_type,
                content=extracted.content,
                source_offset_start=extracted.source_offset_start,
                source_offset_end=extracted.source_offset_end,
            ))
            created_ids.append(claim.id)

        return {"outcome": "updated", "claims_created": len(created_ids), "claim_ids": created_ids}

    async def process_verify_claim_job(self, claim_id: str) -> dict:
        """Verify a claim against its source text."""
        claim_row = await self.db.fetchone(
            "SELECT * FROM claims WHERE id = ? AND project_id = ?",
            [claim_id, self.project_id],
        )
        if claim_row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        source_row = await self.db.fetchone(
            "SELECT content FROM journal WHERE id = ? AND project_id = ?",
            [claim_row["source_entry_id"], self.project_id],
        )
        if source_row is None:
            return {"outcome": "skipped", "reason": "source_missing"}

        verification = await self.llm.verify_claim(claim_row["content"], source_row["content"])

        await self.db.execute(
            "UPDATE claims SET verified = ?, confidence = ?, updated_at = ? WHERE id = ? AND project_id = ?",
            [
                int(verification.exists_in_source and verification.number_accuracy and verification.direction_correct),
                verification.overall_confidence,
                _now(),
                claim_id,
                self.project_id,
            ],
        )
        await self.db.commit()

        # If verification failed, flag for review
        if not (verification.exists_in_source and verification.number_accuracy and verification.direction_correct):
            await self._flag_for_review(claim_id, "claim", verification.issues)

        return {
            "outcome": "updated",
            "verified": verification.exists_in_source and verification.number_accuracy and verification.direction_correct,
            "confidence": verification.overall_confidence,
        }

    async def process_embedding_job(self, claim_id: str) -> dict:
        """Generate embedding for a claim."""
        row = await self.db.fetchone(
            "SELECT content FROM claims WHERE id = ? AND project_id = ?",
            [claim_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.embeddings:
            return {"outcome": "skipped", "reason": "embeddings_disabled"}

        await self.embeddings.embed_and_store("claim", claim_id, row["content"], project_id=self.project_id)
        return {"outcome": "updated", "char_count": len(row["content"])}

    async def _flag_for_review(self, item_id: str, item_type: str, issues: list[str]) -> None:
        """Flag an item for Brain review."""
        import json
        review_id = generate_id("review")
        await self.db.execute(
            """INSERT OR IGNORE INTO review_queue
               (id, item_type, item_id, flag, context, priority, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                review_id, item_type, item_id, "low_confidence_cluster",
                json.dumps({"issues": issues}), 80, self.project_id,
            ],
        )
        await self.db.commit()

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_model(row: dict) -> Claim:
        return Claim(
            id=row["id"],
            source_entry_id=row["source_entry_id"],
            claim_type=row["claim_type"],
            content=row["content"],
            confidence=row.get("confidence", 0.5),
            verified=bool(row.get("verified", 0)),
            stale=bool(row.get("stale", 0)),
            source_offset_start=row.get("source_offset_start"),
            source_offset_end=row.get("source_offset_end"),
            project_id=row.get("project_id", "proj_default"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def _edge_to_model(row: dict) -> ClaimEdge:
        return ClaimEdge(
            id=row["id"],
            source_claim_id=row["source_claim_id"],
            target_claim_id=row.get("target_claim_id"),
            cluster_id=row.get("cluster_id"),
            relation=row["relation"],
            confidence=row.get("confidence", 0.5),
            project_id=row.get("project_id", "proj_default"),
            created_at=row.get("created_at"),
        )
