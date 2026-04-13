"""Researcher experience tools — changelog, evidence assembly, cluster ops, paper processing, RQ lifecycle."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from rka.infra.ids import generate_id
from rka.services.base import BaseService, _now


class ResearcherToolsService(BaseService):
    """Lightweight tools that compose existing data — no new tables, no LLM, no background jobs."""

    # ------------------------------------------------------------------
    # 1. Changelog
    # ------------------------------------------------------------------

    async def get_changelog(self, since: str, limit: int = 50) -> dict:
        """Cross-entity temporal view of what changed since a given date."""
        rows = await self.db.fetchall(
            """
            SELECT entity_type, id, label, created_at, updated_at FROM (
                SELECT 'journal' AS entity_type, id, SUBSTR(content, 1, 80) AS label,
                       created_at, updated_at FROM journal
                WHERE project_id = ? AND (created_at >= ? OR updated_at >= ?)
                UNION ALL
                SELECT 'decision', id, SUBSTR(question, 1, 80),
                       created_at, updated_at FROM decisions
                WHERE project_id = ? AND (created_at >= ? OR updated_at >= ?)
                UNION ALL
                SELECT 'literature', id, SUBSTR(title, 1, 80),
                       created_at, updated_at FROM literature
                WHERE project_id = ? AND (created_at >= ? OR updated_at >= ?)
                UNION ALL
                SELECT 'claim', id, SUBSTR(content, 1, 80),
                       created_at, updated_at FROM claims
                WHERE project_id = ? AND (created_at >= ? OR updated_at >= ?)
                UNION ALL
                SELECT 'cluster', id, SUBSTR(label, 1, 80),
                       created_at, updated_at FROM evidence_clusters
                WHERE project_id = ? AND (created_at >= ? OR updated_at >= ?)
                UNION ALL
                SELECT 'mission', id, SUBSTR(objective, 1, 80),
                       created_at, created_at FROM missions
                WHERE project_id = ? AND created_at >= ?
            )
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT ?
            """,
            # 5 tables with (project_id, since, since) + missions with (project_id, since) + limit
            [self.project_id, since, since] * 5 + [self.project_id, since] + [limit],
        )

        created = []
        modified = []
        stats: dict[str, int] = {}
        for row in rows:
            entry = {
                "entity_type": row["entity_type"],
                "id": row["id"],
                "label": row["label"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            stats[row["entity_type"]] = stats.get(row["entity_type"], 0) + 1
            if row["created_at"] and row["created_at"] >= since:
                created.append(entry)
            else:
                modified.append(entry)

        return {
            "since": since,
            "created": created,
            "modified": modified,
            "statistics": {
                "total_created": len(created),
                "total_modified": len(modified),
                "by_type": stats,
            },
        }

    # ------------------------------------------------------------------
    # 2. Evidence Assembly
    # ------------------------------------------------------------------

    async def assemble_evidence(self, research_question_id: str, fmt: str = "progress_report") -> str:
        """Assemble evidence under an RQ into a structured markdown draft."""
        rq = await self.db.fetchone(
            "SELECT id, question, rationale, status FROM decisions WHERE id = ? AND project_id = ?",
            [research_question_id, self.project_id],
        )
        if not rq:
            raise ValueError(f"Research question {research_question_id} not found")

        clusters = await self.db.fetchall(
            """SELECT id, label, synthesis, confidence, claim_count, gap_count
               FROM evidence_clusters
               WHERE research_question_id = ? AND project_id = ?
               ORDER BY claim_count DESC""",
            [research_question_id, self.project_id],
        )

        # Gather claims per cluster
        cluster_claims: dict[str, list[dict]] = {}
        for cl in clusters:
            claims = await self.db.fetchall(
                """SELECT c.id, c.claim_type, c.content, c.confidence, c.source_entry_id
                   FROM claims c
                   JOIN claim_edges ce ON ce.source_claim_id = c.id AND ce.relation = 'member_of'
                   WHERE ce.cluster_id = ? AND c.project_id = ?
                   ORDER BY c.confidence DESC""",
                [cl["id"], self.project_id],
            )
            cluster_claims[cl["id"]] = [dict(c) for c in claims]

        # Gather linked decisions
        decisions = await self.db.fetchall(
            """SELECT DISTINCT d.id, d.question, d.rationale, d.status
               FROM decisions d
               JOIN entity_links el ON el.target_id = d.id AND el.target_type = 'decision'
               WHERE el.source_id = ? AND el.source_type = 'decision' AND d.project_id = ?""",
            [research_question_id, self.project_id],
        )

        # Gather linked literature
        lit_ids: set[str] = set()
        for claims_list in cluster_claims.values():
            for claim in claims_list:
                if claim["source_entry_id"]:
                    lit_rows = await self.db.fetchall(
                        """SELECT DISTINCT l.id, l.title, l.authors, l.year
                           FROM literature l
                           JOIN entity_links el ON el.target_id = l.id AND el.target_type = 'literature'
                           WHERE el.source_id = ? AND el.source_type = 'journal' AND l.project_id = ?""",
                        [claim["source_entry_id"], self.project_id],
                    )
                    for lr in lit_rows:
                        lit_ids.add(lr["id"])

        literature = await self.db.fetchall(
            f"SELECT id, title, authors, year FROM literature WHERE project_id = ? AND id IN ({','.join('?' * len(lit_ids))})",
            [self.project_id] + list(lit_ids),
        ) if lit_ids else []

        if fmt == "lit_review":
            return self._format_lit_review(rq, clusters, cluster_claims, literature)
        elif fmt == "proposal_section":
            return self._format_proposal_section(rq, clusters, cluster_claims)
        else:
            return self._format_progress_report(rq, clusters, cluster_claims, decisions)

    def _format_progress_report(self, rq: dict, clusters: list, cluster_claims: dict, decisions: list) -> str:
        lines = [f"# Progress Report: {rq['question']}", ""]
        total_claims = sum(len(v) for v in cluster_claims.values())
        total_gaps = sum(c["gap_count"] or 0 for c in clusters)
        lines.append(f"**Status**: {len(clusters)} clusters, {total_claims} claims, {total_gaps} gaps")
        lines.append("")

        lines.append("## Key Findings")
        top_claims = sorted(
            [c for claims in cluster_claims.values() for c in claims],
            key=lambda x: x.get("confidence", 0),
            reverse=True,
        )[:10]
        for c in top_claims:
            lines.append(f"- [{c['claim_type']}] {c['content']} (confidence: {c.get('confidence', 0.5):.2f}, source: {c['source_entry_id']})")
        lines.append("")

        if decisions:
            lines.append("## Decisions Made")
            for d in decisions:
                lines.append(f"- **{d['question']}** ({d['status']})")
                if d.get("rationale"):
                    lines.append(f"  {d['rationale'][:200]}")
            lines.append("")

        gaps = [c for c in clusters if (c["gap_count"] or 0) > 0]
        if gaps:
            lines.append("## Current Gaps")
            for g in gaps:
                lines.append(f"- {g['label']}: {g['gap_count']} evidence gaps")
            lines.append("")

        lines.append("## Next Steps")
        emerging = [c for c in clusters if c["confidence"] == "emerging"]
        if emerging:
            lines.append(f"- {len(emerging)} emerging clusters need more evidence")
        contested = [c for c in clusters if c["confidence"] == "contested"]
        if contested:
            lines.append(f"- {len(contested)} contested clusters need contradiction resolution")

        return "\n".join(lines)

    def _format_lit_review(self, rq: dict, clusters: list, cluster_claims: dict, literature: list) -> str:
        lines = [f"# Literature Review: {rq['question']}", ""]
        lit_by_id = {l["id"]: l for l in literature}

        for cl in clusters:
            lines.append(f"## {cl['label']}")
            if cl.get("synthesis"):
                lines.append(cl["synthesis"])
                lines.append("")
            claims = cluster_claims.get(cl["id"], [])
            if claims:
                lines.append("**Key findings:**")
                for c in claims:
                    lines.append(f"- {c['content']} (confidence: {c.get('confidence', 0.5):.2f}, source: {c['source_entry_id']})")
                lines.append("")

        if literature:
            lines.append("## References")
            for lit in literature:
                authors = lit.get("authors") or ""
                if isinstance(authors, str):
                    try:
                        authors = ", ".join(json.loads(authors))
                    except (json.JSONDecodeError, TypeError):
                        pass
                lines.append(f"- {authors} ({lit.get('year', 'n.d.')}). {lit['title']}")

        return "\n".join(lines)

    def _format_proposal_section(self, rq: dict, clusters: list, cluster_claims: dict) -> str:
        lines = [f"# {rq['question']}", ""]
        if rq.get("rationale"):
            lines.append(rq["rationale"])
            lines.append("")

        lines.append("## Evidence Base")
        for cl in clusters:
            if cl.get("synthesis"):
                lines.append(f"### {cl['label']}")
                lines.append(cl["synthesis"])
                lines.append("")

        method_claims = [
            c for claims in cluster_claims.values() for c in claims if c["claim_type"] == "method"
        ]
        if method_claims:
            lines.append("## Methodology")
            for c in method_claims:
                lines.append(f"- {c['content']}")
            lines.append("")

        result_claims = [
            c for claims in cluster_claims.values() for c in claims
            if c["claim_type"] in ("result", "evidence")
        ]
        if result_claims:
            lines.append("## Preliminary Results")
            for c in result_claims[:15]:
                lines.append(f"- {c['content']} (confidence: {c.get('confidence', 0.5):.2f})")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 3. Split Cluster
    # ------------------------------------------------------------------

    async def split_cluster(self, source_id: str, new_clusters: list[dict]) -> dict:
        """Split a cluster by creating new ones and reassigning specified claims."""
        source = await self.db.fetchone(
            "SELECT * FROM evidence_clusters WHERE id = ? AND project_id = ?",
            [source_id, self.project_id],
        )
        if not source:
            raise ValueError(f"Source cluster {source_id} not found")

        created_clusters = []
        total_reassigned = 0

        for spec in new_clusters:
            cluster_id = generate_id("cluster")
            rq_id = spec.get("research_question_id") or source.get("research_question_id")
            await self.db.execute(
                """INSERT INTO evidence_clusters
                   (id, research_question_id, label, confidence, claim_count,
                    synthesized_by, project_id, created_at, updated_at)
                   VALUES (?, ?, ?, 'emerging', 0, 'llm', ?, ?, ?)""",
                [cluster_id, rq_id, spec["label"], self.project_id, _now(), _now()],
            )

            claim_ids = spec.get("claim_ids", [])
            for claim_id in claim_ids:
                # Remove old member_of edge
                await self.db.execute(
                    "DELETE FROM claim_edges WHERE source_claim_id = ? AND cluster_id = ? AND relation = 'member_of'",
                    [claim_id, source_id],
                )
                # Create new member_of edge
                edge_id = generate_id("claim_edge")
                await self.db.execute(
                    """INSERT INTO claim_edges
                       (id, source_claim_id, cluster_id, relation, confidence, project_id, created_at)
                       VALUES (?, ?, ?, 'member_of', 1.0, ?, ?)""",
                    [edge_id, claim_id, cluster_id, self.project_id, _now()],
                )

            # Update claim_count
            await self.db.execute(
                "UPDATE evidence_clusters SET claim_count = ? WHERE id = ?",
                [len(claim_ids), cluster_id],
            )
            total_reassigned += len(claim_ids)
            created_clusters.append({"id": cluster_id, "label": spec["label"], "claim_count": len(claim_ids)})

        # Update source cluster claim_count
        remaining = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM claim_edges WHERE cluster_id = ? AND relation = 'member_of'",
            [source_id],
        )
        await self.db.execute(
            "UPDATE evidence_clusters SET claim_count = ?, updated_at = ? WHERE id = ?",
            [remaining["cnt"] if remaining else 0, _now(), source_id],
        )

        await self.db.commit()

        return {
            "source_id": source_id,
            "source_remaining_claims": remaining["cnt"] if remaining else 0,
            "new_clusters": created_clusters,
            "total_reassigned": total_reassigned,
        }

    # ------------------------------------------------------------------
    # 4. Merge Clusters
    # ------------------------------------------------------------------

    async def merge_clusters(
        self,
        source_ids: list[str],
        target_label: str,
        target_synthesis: str | None = None,
        research_question_id: str | None = None,
    ) -> dict:
        """Merge multiple clusters into one new cluster."""
        # Resolve research_question_id from first source if not provided
        if not research_question_id:
            for sid in source_ids:
                src = await self.db.fetchone(
                    "SELECT research_question_id FROM evidence_clusters WHERE id = ? AND project_id = ?",
                    [sid, self.project_id],
                )
                if src and src.get("research_question_id"):
                    research_question_id = src["research_question_id"]
                    break

        target_id = generate_id("cluster")
        await self.db.execute(
            """INSERT INTO evidence_clusters
               (id, research_question_id, label, synthesis, confidence, claim_count,
                synthesized_by, project_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'emerging', 0, ?, ?, ?, ?)""",
            [target_id, research_question_id, target_label, target_synthesis,
             "brain" if target_synthesis else "llm", self.project_id, _now(), _now()],
        )

        total_moved = 0
        for sid in source_ids:
            # Get all claims in source
            edges = await self.db.fetchall(
                "SELECT source_claim_id FROM claim_edges WHERE cluster_id = ? AND relation = 'member_of'",
                [sid],
            )
            for edge in edges:
                claim_id = edge["source_claim_id"]
                await self.db.execute(
                    "DELETE FROM claim_edges WHERE source_claim_id = ? AND cluster_id = ? AND relation = 'member_of'",
                    [claim_id, sid],
                )
                edge_id = generate_id("claim_edge")
                await self.db.execute(
                    """INSERT OR IGNORE INTO claim_edges
                       (id, source_claim_id, cluster_id, relation, confidence, project_id, created_at)
                       VALUES (?, ?, ?, 'member_of', 1.0, ?, ?)""",
                    [edge_id, claim_id, target_id, self.project_id, _now()],
                )
                total_moved += 1

            # Zero out source cluster
            await self.db.execute(
                "UPDATE evidence_clusters SET claim_count = 0, updated_at = ? WHERE id = ?",
                [_now(), sid],
            )

        # Set target claim_count
        await self.db.execute(
            "UPDATE evidence_clusters SET claim_count = ? WHERE id = ?",
            [total_moved, target_id],
        )
        await self.db.commit()

        return {
            "target_id": target_id,
            "target_label": target_label,
            "total_claims_moved": total_moved,
            "source_ids": source_ids,
        }

    # ------------------------------------------------------------------
    # 5. Process Paper
    # ------------------------------------------------------------------

    async def process_paper(
        self,
        lit_id: str,
        annotations: list[dict],
        summary: str | None = None,
    ) -> dict:
        """Process reading annotations from a paper into structured claims."""
        # Verify literature exists
        lit = await self.db.fetchone(
            "SELECT id, title, status FROM literature WHERE id = ? AND project_id = ?",
            [lit_id, self.project_id],
        )
        if not lit:
            raise ValueError(f"Literature entry {lit_id} not found")

        # Build journal entry content from annotations
        content_parts = []
        if summary:
            content_parts.append(summary)
        for i, ann in enumerate(annotations, 1):
            content_parts.append(f"\n### Annotation {i}")
            content_parts.append(f"**Passage**: {ann['passage']}")
            if ann.get("note"):
                content_parts.append(f"**Note**: {ann['note']}")

        journal_content = "\n".join(content_parts) if content_parts else f"Reading notes for {lit['title']}"

        # Create journal entry
        journal_id = generate_id("journal")
        now = _now()
        related_lit = json.dumps([lit_id])
        await self.db.execute(
            """INSERT INTO journal
               (id, content, type, source, confidence, status,
                related_literature, project_id, created_at, updated_at)
               VALUES (?, ?, 'note', 'brain', 'tested', 'active',
                       ?, ?, ?, ?)""",
            [journal_id, journal_content, related_lit, self.project_id, now, now],
        )

        # Create entity link: journal -> literature
        link_id = generate_id("link")
        await self.db.execute(
            """INSERT OR IGNORE INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, created_at, created_by)
               VALUES (?, 'journal', ?, 'informed_by', 'literature', ?, ?, 'brain')""",
            [link_id, journal_id, lit_id, now],
        )

        # Extract claims from annotations
        created_claims = []
        assigned = 0
        for ann in annotations:
            claim_id = generate_id("claim")
            await self.db.execute(
                """INSERT INTO claims
                   (id, source_entry_id, claim_type, content, confidence, project_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [claim_id, journal_id, ann["claim_type"], ann["passage"],
                 ann.get("confidence", 0.5), self.project_id, now, now],
            )

            # derived_from link
            d_link_id = generate_id("link")
            await self.db.execute(
                """INSERT OR IGNORE INTO entity_links
                   (id, source_type, source_id, link_type, target_type, target_id, created_at, created_by)
                   VALUES (?, 'claim', ?, 'derived_from', 'journal', ?, ?, 'brain')""",
                [d_link_id, claim_id, journal_id, now],
            )

            # Inline cluster assignment
            cluster_id = ann.get("cluster_id")
            if cluster_id:
                edge_id = generate_id("claim_edge")
                await self.db.execute(
                    """INSERT OR IGNORE INTO claim_edges
                       (id, source_claim_id, cluster_id, relation, confidence, project_id, created_at)
                       VALUES (?, ?, ?, 'member_of', 1.0, ?, ?)""",
                    [edge_id, claim_id, cluster_id, self.project_id, now],
                )
                # Update cluster claim_count
                await self.db.execute(
                    """UPDATE evidence_clusters
                       SET claim_count = claim_count + 1, updated_at = ?
                       WHERE id = ?""",
                    [now, cluster_id],
                )
                assigned += 1

            created_claims.append({
                "id": claim_id,
                "claim_type": ann["claim_type"],
                "content": ann["passage"][:80],
                "cluster_id": cluster_id,
            })

        # Auto-advance literature status
        if lit["status"] == "to_read":
            await self.db.execute(
                "UPDATE literature SET status = 'reading', updated_at = ? WHERE id = ? AND project_id = ?",
                [now, lit_id, self.project_id],
            )

        await self.db.commit()

        return {
            "journal_entry_id": journal_id,
            "literature_id": lit_id,
            "claims_created": len(created_claims),
            "claims_assigned": assigned,
            "claims": created_claims,
            "literature_status": "reading" if lit["status"] == "to_read" else lit["status"],
        }

    # ------------------------------------------------------------------
    # 6. Advance RQ
    # ------------------------------------------------------------------

    async def advance_rq(
        self,
        rq_id: str,
        status: str,
        conclusion: str | None = None,
        evidence_cluster_ids: list[str] | None = None,
    ) -> dict:
        """Advance a research question's lifecycle status.

        The RQ lifecycle status is stored as a tag (rq:open, rq:answered, etc.)
        because the decisions.status column has a CHECK constraint for decision-level
        statuses (active, abandoned, superseded, merged, revisit).
        """
        valid_statuses = ("open", "partially_answered", "answered", "reframed", "closed")
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        rq = await self.db.fetchone(
            "SELECT id, question, kind, status FROM decisions WHERE id = ? AND project_id = ?",
            [rq_id, self.project_id],
        )
        if not rq:
            raise ValueError(f"Decision {rq_id} not found")
        if rq.get("kind") != "research_question":
            raise ValueError(f"Decision {rq_id} is not a research_question (kind={rq.get('kind')})")

        now = _now()

        # Read current tags, replace any existing rq:* tag with the new one
        existing_tags = await self.db.fetchall(
            "SELECT tag FROM tags WHERE entity_type = 'decision' AND entity_id = ?",
            [rq_id],
        )
        current_tags = [r["tag"] for r in existing_tags]
        previous_rq_status = "open"
        new_tags = []
        for t in current_tags:
            if t.startswith("rq:"):
                previous_rq_status = t[3:]
            else:
                new_tags.append(t)
        new_tags.append(f"rq:{status}")

        # Replace tags
        await self.db.execute(
            "DELETE FROM tags WHERE entity_type = 'decision' AND entity_id = ?", [rq_id],
        )
        for tag in new_tags:
            await self.db.execute(
                "INSERT INTO tags (entity_type, entity_id, tag) VALUES ('decision', ?, ?)",
                [rq_id, tag],
            )

        # Touch updated_at
        await self.db.execute(
            "UPDATE decisions SET updated_at = ? WHERE id = ? AND project_id = ?",
            [now, rq_id, self.project_id],
        )

        journal_id = None
        if conclusion:
            # Store conclusion as a linked journal entry
            journal_id = generate_id("journal")
            related_dec = json.dumps([rq_id])
            await self.db.execute(
                """INSERT INTO journal
                   (id, content, type, source, confidence, status,
                    related_decisions, project_id, created_at, updated_at)
                   VALUES (?, ?, 'note', 'brain', 'verified', 'active',
                           ?, ?, ?, ?)""",
                [journal_id, f"RQ Conclusion ({status}): {conclusion}",
                 related_dec, self.project_id, now, now],
            )
            # Link journal -> decision
            link_id = generate_id("link")
            await self.db.execute(
                """INSERT OR IGNORE INTO entity_links
                   (id, source_type, source_id, link_type, target_type, target_id, created_at, created_by)
                   VALUES (?, 'journal', ?, 'justified_by', 'decision', ?, ?, 'brain')""",
                [link_id, journal_id, rq_id, now],
            )

        # Create justified_by links from RQ to evidence clusters
        if evidence_cluster_ids:
            for ecl_id in evidence_cluster_ids:
                link_id = generate_id("link")
                await self.db.execute(
                    """INSERT OR IGNORE INTO entity_links
                       (id, source_type, source_id, link_type, target_type, target_id, created_at, created_by)
                       VALUES (?, 'decision', ?, 'justified_by', 'cluster', ?, ?, 'brain')""",
                    [link_id, rq_id, ecl_id, now],
                )

        await self.db.commit()

        return {
            "rq_id": rq_id,
            "question": rq["question"],
            "previous_status": previous_rq_status,
            "new_status": status,
            "conclusion_entry_id": journal_id,
            "evidence_clusters_linked": len(evidence_cluster_ids) if evidence_cluster_ids else 0,
        }

    # ------------------------------------------------------------------
    # 7. Flag Stale
    # ------------------------------------------------------------------

    async def flag_stale(
        self,
        entity_id: str,
        reason: str,
        staleness: str = "yellow",
        propagate: bool = True,
    ) -> dict:
        """Flag a claim, cluster, or decision as potentially stale."""
        if staleness not in ("yellow", "red"):
            raise ValueError("staleness must be 'yellow' or 'red'")

        now = _now()
        flagged = [{"id": entity_id, "staleness": staleness}]

        if entity_id.startswith("clm_"):
            await self.db.execute(
                "UPDATE claims SET staleness = ?, stale_reason = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                [staleness, reason, now, entity_id, self.project_id],
            )
            if propagate:
                flagged += await self._propagate_from_claim(entity_id, reason, now)
        elif entity_id.startswith("ecl_"):
            await self.db.execute(
                "UPDATE evidence_clusters SET staleness = ?, stale_reason = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                [staleness, reason, now, entity_id, self.project_id],
            )
            if propagate:
                flagged += await self._propagate_from_cluster(entity_id, reason, now)
        elif entity_id.startswith("dec_"):
            await self.db.execute(
                "UPDATE decisions SET assumptions = json_set(COALESCE(assumptions, '{}'), '$.staleness', ?), updated_at = ? WHERE id = ? AND project_id = ?",
                [staleness, now, entity_id, self.project_id],
            )
        else:
            raise ValueError(f"Unsupported entity type for {entity_id}")

        await self.db.commit()
        return {"flagged": flagged, "total_flagged": len(flagged)}

    async def _propagate_from_claim(self, claim_id: str, reason: str, now: str) -> list[dict]:
        """Propagate staleness from a claim to parent clusters and their decisions."""
        flagged = []
        # Find parent clusters via claim_edges
        clusters = await self.db.fetchall(
            "SELECT DISTINCT cluster_id FROM claim_edges WHERE source_claim_id = ? AND relation = 'member_of'",
            [claim_id],
        )
        for row in clusters:
            cid = row["cluster_id"]
            # Check if >50% of claims in this cluster are stale
            total = await self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM claim_edges WHERE cluster_id = ? AND relation = 'member_of'", [cid],
            )
            stale = await self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM claim_edges ce
                   JOIN claims c ON c.id = ce.source_claim_id
                   WHERE ce.cluster_id = ? AND ce.relation = 'member_of'
                     AND c.staleness IN ('yellow', 'red')""",
                [cid],
            )
            if total and stale and total["cnt"] > 0 and (stale["cnt"] / total["cnt"]) > 0.5:
                await self.db.execute(
                    "UPDATE evidence_clusters SET staleness = 'yellow', stale_reason = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                    [f">50% claims stale (includes {claim_id})", now, cid, self.project_id],
                )
                flagged.append({"id": cid, "staleness": "yellow"})
                flagged += await self._propagate_from_cluster(cid, reason, now)
        return flagged

    async def _propagate_from_cluster(self, cluster_id: str, reason: str, now: str) -> list[dict]:
        """Propagate staleness from a cluster to decisions citing it."""
        flagged = []
        decisions = await self.db.fetchall(
            """SELECT source_id FROM entity_links
               WHERE target_id = ? AND link_type = 'justified_by'
                 AND source_type = 'decision'""",
            [cluster_id],
        )
        for row in decisions:
            dec_id = row["source_id"]
            await self.db.execute(
                "UPDATE decisions SET updated_at = ? WHERE id = ? AND project_id = ?",
                [now, dec_id, self.project_id],
            )
            flagged.append({"id": dec_id, "staleness": "yellow"})
        return flagged

    # ------------------------------------------------------------------
    # 8. Check Freshness
    # ------------------------------------------------------------------

    async def check_freshness(self, days_threshold: int = 30) -> dict:
        """Scan for potentially stale knowledge items. Pure SQL — no LLM."""
        pid = self.project_id
        categories = {}

        # 1. Claims already flagged stale
        flagged_claims = await self.db.fetchall(
            """SELECT id, staleness, stale_reason FROM claims
               WHERE project_id = ? AND staleness IN ('yellow', 'red')
               ORDER BY updated_at DESC LIMIT 50""",
            [pid],
        )
        categories["stale_claims"] = {
            "count": len(flagged_claims),
            "ids": [r["id"] for r in flagged_claims],
            "description": "Claims flagged stale (yellow or red)",
            "fix_action": "Brain reviews and resolves via rka_flag_stale or updates",
        }

        # 2. Claims with superseded source entries
        superseded_source = await self.db.fetchall(
            """SELECT c.id FROM claims c
               JOIN journal j ON j.id = c.source_entry_id
               WHERE c.project_id = ? AND c.staleness = 'green'
                 AND j.superseded_by IS NOT NULL
               LIMIT 50""",
            [pid],
        )
        categories["superseded_source_claims"] = {
            "count": len(superseded_source),
            "ids": [r["id"] for r in superseded_source],
            "description": "Claims whose source journal entry was superseded",
            "fix_action": "rka_flag_stale(claim_id, reason='Source entry superseded')",
        }

        # 3. Claims older than threshold with no recent cluster activity
        old_claims = await self.db.fetchall(
            f"""SELECT c.id FROM claims c
               WHERE c.project_id = ? AND c.staleness = 'green'
                 AND c.valid_from < datetime('now', '-{days_threshold} days')
               ORDER BY c.valid_from ASC LIMIT 50""",
            [pid],
        )
        categories["aging_claims"] = {
            "count": len(old_claims),
            "ids": [r["id"] for r in old_claims],
            "description": f"Claims older than {days_threshold} days (may need review)",
            "fix_action": "Brain reviews claim currency and flags stale if needed",
        }

        # 4. Clusters with >50% stale claims
        stale_clusters = await self.db.fetchall(
            """SELECT ec.id FROM evidence_clusters ec
               WHERE ec.project_id = ? AND ec.staleness IN ('yellow', 'red')
               LIMIT 50""",
            [pid],
        )
        categories["stale_clusters"] = {
            "count": len(stale_clusters),
            "ids": [r["id"] for r in stale_clusters],
            "description": "Clusters flagged stale",
            "fix_action": "Brain re-synthesizes cluster with fresh evidence",
        }

        total = sum(c["count"] for c in categories.values())
        return {"total_items": total, "categories": categories}

    # ------------------------------------------------------------------
    # 9. Detect Contradictions (vector similarity)
    # ------------------------------------------------------------------

    async def detect_contradictions(
        self,
        entity_id: str,
        similarity_threshold: float = 0.7,
        max_results: int = 5,
    ) -> dict:
        """Find claims that may contradict a given claim or journal entry."""
        # Get the content to compare
        content = None
        if entity_id.startswith("clm_"):
            row = await self.db.fetchone(
                "SELECT content FROM claims WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                content = row["content"]
        elif entity_id.startswith("jrn_"):
            row = await self.db.fetchone(
                "SELECT content FROM journal WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                content = row["content"]

        if not content:
            raise ValueError(f"Entity {entity_id} not found or has no content")

        # Check if embeddings are available
        has_embeddings = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM embedding_metadata WHERE project_id = ?",
            [self.project_id],
        )
        if not has_embeddings or has_embeddings["cnt"] == 0:
            return {
                "entity_id": entity_id,
                "candidates": [],
                "message": "No embeddings available — enable RKA_EMBEDDINGS_ENABLED=true and reprocess entries to use vector similarity.",
            }

        # Try vector similarity search via sqlite-vec
        try:
            # Get embedding for the entity
            emb_row = await self.db.fetchone(
                "SELECT embedding FROM embeddings WHERE entity_id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if not emb_row:
                return {
                    "entity_id": entity_id,
                    "candidates": [],
                    "message": f"No embedding found for {entity_id}. Run enrichment first.",
                }

            # Find similar claims
            similar = await self.db.fetchall(
                """SELECT e.entity_id, e.distance, c.content, c.claim_type, c.confidence,
                          ce.cluster_id
                   FROM vec_embeddings v
                   JOIN embeddings e ON e.rowid = v.rowid
                   JOIN claims c ON c.id = e.entity_id AND c.project_id = e.project_id
                   LEFT JOIN claim_edges ce ON ce.source_claim_id = c.id AND ce.relation = 'member_of'
                   WHERE v.embedding MATCH ? AND e.project_id = ? AND e.entity_id != ?
                   ORDER BY v.distance ASC
                   LIMIT ?""",
                [emb_row["embedding"], self.project_id, entity_id, max_results],
            )
            candidates = [
                {
                    "claim_id": r["entity_id"],
                    "similarity": round(1 - (r.get("distance", 0) or 0), 3),
                    "content": r["content"][:120],
                    "claim_type": r["claim_type"],
                    "cluster_id": r.get("cluster_id"),
                }
                for r in similar
            ]
        except Exception:
            # Vector search not available — fall back to FTS
            candidates = await self._fts_contradiction_fallback(entity_id, content, max_results)

        return {
            "entity_id": entity_id,
            "candidates": candidates,
            "message": f"Found {len(candidates)} similar claims for review." if candidates else "No similar claims found.",
        }

    async def _fts_contradiction_fallback(self, entity_id: str, content: str, max_results: int) -> list[dict]:
        """Fallback: use FTS5 keyword matching when vector search unavailable."""
        # Extract key terms (first 5 significant words)
        words = [w for w in content.split() if len(w) > 3][:5]
        if not words:
            return []
        query = " OR ".join(words)
        try:
            rows = await self.db.fetchall(
                """SELECT c.id, c.content, c.claim_type, c.confidence
                   FROM fts_claims fc
                   JOIN claims c ON c.id = fc.id
                   WHERE fts_claims MATCH ? AND c.project_id = ? AND c.id != ?
                   LIMIT ?""",
                [query, self.project_id, entity_id, max_results],
            )
            return [
                {
                    "claim_id": r["id"],
                    "similarity": 0.5,  # FTS doesn't give similarity scores
                    "content": r["content"][:120],
                    "claim_type": r["claim_type"],
                    "cluster_id": None,
                }
                for r in rows
            ]
        except Exception:
            return []
