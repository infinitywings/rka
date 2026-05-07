"""Context engine — prepares importance-ranked context packages for Brain and Executor.

v2.4 (Improvement 1, dec_01KQQPD6Y6B362T3K08368BDMP): the temperature classifier
(HOT/WARM/COLD bucketing on day-thresholds) and the token-budget arithmetic were
removed. Rationale per the probe report (mis_01KQQPHC2649SXJG30JMCR0WFK):

- Day-threshold buckets systematically excluded older relevant content.
- Frontier model context windows make a bookkeeper-imposed token budget
  unnecessary; the bookkeeper invariant says compute at SQL time, not at
  retrieval time.
- The `journal.importance` column already exists with an index; pairing it
  with `entity_links` centrality gives a deterministic SQL-time ranking that
  doesn't drift with wall-clock time.
"""

from __future__ import annotations

import logging
from typing import Literal

from rka.infra.database import Database
from rka.infra.llm import LLMClient
from rka.models.context import ContextPackage
from rka.services.search import SearchService

logger = logging.getLogger(__name__)

# Importance text → numeric rank for ORDER BY. Mirrors the journal.importance
# CHECK constraint in schema.sql.
_IMPORTANCE_CASE = """CASE j.importance
    WHEN 'critical' THEN 4
    WHEN 'high' THEN 3
    WHEN 'normal' THEN 2
    WHEN 'low' THEN 1
    WHEN 'archived' THEN 0
    ELSE 2
END"""


class ContextEngine:
    """Prepares importance-ranked context packages.

    Ranking signal (deterministic, SQL-time):
      1. journal.importance (critical=4 → archived=0); other entity types
         do not have an importance column and use a baseline of 2 ('normal').
      2. entity_links centrality — sum of inbound + outbound edge degree
         for the entity. High-centrality nodes surface first within a band.
      3. created_at DESC as a tie-breaker; newer entries win ties.
    """

    def __init__(
        self,
        db: Database,
        search: SearchService,
        llm: LLMClient | None = None,
    ):
        self.db = db
        self.search = search
        self.llm = llm

    async def get_context(
        self,
        topic: str | None = None,
        phase: str | None = None,
        depth: Literal["summary", "detailed"] = "summary",
        project_id: str = "proj_default",
    ) -> ContextPackage:
        """Build a ranked context package.

        Args:
            topic: Optional search query. If provided, candidates are seeded by
                hybrid search and then re-ranked by importance + centrality.
            phase: Optional phase filter for the overview path. If both `topic`
                and `phase` are None, falls through to the recent-with-importance
                overview.
            depth: 'summary' returns the ranked list as-is. 'detailed' adds an
                LLM-generated narrative if an LLM is configured.
            project_id: Project scope. Defaults to 'proj_default'; callers
                normally inject from the API request.

        Returns a ContextPackage with `entries` populated (legacy bucket fields
        left empty).
        """
        if topic:
            hits = await self.search.with_project(project_id).search(topic, limit=50)
            candidates = await self._hydrate_hits(hits, project_id=project_id)
            candidates = await self._rerank_by_importance_and_centrality(
                candidates, project_id=project_id
            )
        else:
            candidates = await self._get_overview_candidates(phase, project_id=project_id)

        current_phase = phase or await self._get_current_phase(project_id=project_id)

        package = ContextPackage(topic=topic, phase=current_phase)

        # Render the ranked list. PI-sourced entries get a small lift within
        # their importance band — they're the human-anchored signal.
        candidates.sort(key=self._sort_key, reverse=True)
        rendered = [self._render_entry(entry) for entry in candidates]
        package.entries = rendered
        package.sources = [e["id"] for e in candidates]

        # Optional narrative for callers that ask for `detailed`.
        if depth == "detailed" and self.llm and candidates:
            try:
                narrative = await self.llm.produce_narrative(
                    {"topic": topic, "phase": current_phase, "entries": rendered}
                )
                if narrative:
                    package.narrative = narrative
            except Exception as exc:
                logger.debug("Narrative generation failed: %s", exc)

        package.note = (
            "Importance-ranked context: ordered by journal.importance, then "
            "entity_links centrality, then created_at. No token-budget truncation "
            "(v2.4 / dec_01KQQPD6Y6B362T3K08368BDMP)."
        )
        # Informational; no longer drives truncation.
        package.token_estimate = sum(self._estimate_tokens(t) for t in rendered)
        return package

    @staticmethod
    def _sort_key(entry: dict) -> tuple[int, int, str]:
        """Sort key: (importance_rank, centrality_degree, created_at). Higher first."""
        imp_map = {
            "critical": 4,
            "high": 3,
            "normal": 2,
            "low": 1,
            "archived": 0,
        }
        imp = imp_map.get(entry.get("importance") or "normal", 2)
        # PI-sourced entries get +0.5 lift within their importance band.
        if entry.get("source") == "pi":
            imp = imp * 10 + 5  # widen scale to allow non-integer-equivalent lift
        else:
            imp = imp * 10
        centrality = int(entry.get("centrality_degree") or 0)
        # Tuple of negatives gets DESC ordering when reverse=True is used.
        return (imp, centrality, entry.get("created_at") or "")

    async def _rerank_by_importance_and_centrality(
        self, candidates: list[dict], project_id: str
    ) -> list[dict]:
        """Annotate candidates with centrality_degree from entity_links."""
        if not candidates:
            return candidates
        ids = [c["id"] for c in candidates]
        placeholders = ",".join("?" for _ in ids)
        rows = await self.db.fetchall(
            f"""SELECT id, SUM(degree) AS centrality_degree FROM (
                    SELECT source_id AS id, COUNT(*) AS degree FROM entity_links
                    WHERE project_id = ? AND source_id IN ({placeholders})
                    GROUP BY source_id
                  UNION ALL
                    SELECT target_id AS id, COUNT(*) AS degree FROM entity_links
                    WHERE project_id = ? AND target_id IN ({placeholders})
                    GROUP BY target_id
                ) GROUP BY id""",
            [project_id, *ids, project_id, *ids],
        )
        degree_map = {r["id"]: int(r["centrality_degree"]) for r in rows}
        for c in candidates:
            c["centrality_degree"] = degree_map.get(c["id"], 0)
        return candidates

    async def _hydrate_hits(self, hits, project_id: str = "proj_default") -> list[dict]:
        """Convert search hits to full entity dicts.

        Defect 1 (mis_01KR1Z28QW9WYXG4VV8PGYWD8G T4): pre-v2.3.4 the table_map
        omitted claim and cluster, so v2.3.3's multi-hop retrieval primitive
        returned claim/cluster nodes that ContextEngine then silently dropped.
        Extension is symmetric with the existing render path: SELECT * gated
        on (id, project_id) plus an entity_type annotation.
        """
        table_map = {
            "journal": "journal",
            "decision": "decisions",
            "literature": "literature",
            "mission": "missions",
            "claim": "claims",
            "cluster": "evidence_clusters",
        }
        results = []
        for hit in hits:
            table = table_map.get(hit.entity_type)
            if not table:
                continue
            row = await self.db.fetchone(
                f"SELECT * FROM {table} WHERE id = ? AND project_id = ?",
                [hit.entity_id, project_id],
            )
            if row:
                row["entity_type"] = hit.entity_type
                results.append(row)
        return results

    async def _get_overview_candidates(
        self,
        phase: str | None = None,
        project_id: str = "proj_default",
    ) -> list[dict]:
        """Get importance-ranked overview candidates when no topic is specified.

        Pulls from journal (importance-aware ORDER BY), decisions (active),
        literature (in-progress states), and missions (active/pending). The
        per-entity-type LIMITs are upper bounds; the final ranker re-orders
        across types so the top of the result list is the highest-importance
        regardless of source table.
        """
        candidates: list[dict] = []
        phase_filter = "AND phase = ?" if phase else ""

        # Journal: ORDER BY importance, then created_at — uses idx_journal_importance.
        params: list = [project_id]
        if phase:
            params.append(phase)
        params.append(50)
        rows = await self.db.fetchall(
            f"""SELECT *, 'journal' AS entity_type, {_IMPORTANCE_CASE} AS imp_rank
                FROM journal j
                WHERE project_id = ? AND confidence != 'superseded' {phase_filter}
                ORDER BY imp_rank DESC, created_at DESC LIMIT ?""",
            params,
        )
        candidates.extend(rows)

        # Decisions: active, ranked by recency.
        params2: list = [project_id]
        if phase:
            params2.append(phase)
        params2.append(30)
        rows = await self.db.fetchall(
            f"""SELECT *, 'decision' AS entity_type FROM decisions
                WHERE project_id = ? AND status = 'active' {phase_filter}
                ORDER BY created_at DESC LIMIT ?""",
            params2,
        )
        candidates.extend(rows)

        # Literature: status filter, recency.
        rows = await self.db.fetchall(
            """SELECT *, 'literature' AS entity_type FROM literature
                WHERE project_id = ? AND status IN ('to_read', 'reading', 'read')
                ORDER BY created_at DESC LIMIT ?""",
            [project_id, 20],
        )
        candidates.extend(rows)

        # Missions: active/pending, recency.
        params3: list = [project_id]
        if phase:
            params3.append(phase)
        params3.append(15)
        rows = await self.db.fetchall(
            f"""SELECT *, 'mission' AS entity_type FROM missions
                WHERE project_id = ? AND status IN ('active', 'pending') {phase_filter}
                ORDER BY created_at DESC LIMIT ?""",
            params3,
        )
        candidates.extend(rows)

        # Annotate with centrality so the cross-type ranker can use it.
        return await self._rerank_by_importance_and_centrality(candidates, project_id=project_id)

    async def _get_current_phase(self, project_id: str = "proj_default") -> str | None:
        """Get the current project phase."""
        row = await self.db.fetchone(
            "SELECT current_phase FROM project_states WHERE project_id = ?",
            [project_id],
        )
        if row is None and project_id == "proj_default":
            row = await self.db.fetchone("SELECT current_phase FROM project_state LIMIT 1")
        return row["current_phase"] if row else None

    def _render_entry(self, entry: dict, max_len: int | None = None) -> str:
        """Render an entry as a concise text block.

        `max_len` defaults to the LLM's per-evidence-block hint when an LLM is
        configured (~400 chars), else 400. This is a per-entry display cap, not
        a context-engine token budget.
        """
        if max_len is None:
            max_len = self.llm._evidence_block_limit if self.llm else 400
        etype = entry.get("entity_type", "unknown")
        eid = entry.get("id", "?")

        if etype == "journal":
            pi_tag = " [PI]" if entry.get("source") == "pi" else ""
            verbatim = entry.get("verbatim_input")
            verbatim_line = f"\n  PI said: \"{verbatim[:200]}\"" if verbatim else ""
            return (
                f"[{entry.get('type', 'note')}|{entry.get('confidence', '?')}|"
                f"{entry.get('importance', 'normal')}]{pi_tag} {eid}: "
                f"{(entry.get('content') or '')[:max_len]}{verbatim_line}"
            )
        elif etype == "decision":
            chosen = f" → {entry['chosen']}" if entry.get("chosen") else ""
            return f"[decision|{entry.get('status', '?')}] {eid}: {(entry.get('question') or '')[:max_len]}{chosen}"
        elif etype == "literature":
            return f"[lit|{entry.get('status', '?')}] {eid}: {(entry.get('title') or '')[:max_len]}"
        elif etype == "mission":
            return f"[mission|{entry.get('status', '?')}] {eid}: {(entry.get('objective') or '')[:max_len]}"
        else:
            return f"[{etype}] {eid}: {str(entry)[:max_len]}"

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 chars per token. Used only for the
        informational `token_estimate` field on ContextPackage; no longer
        drives truncation."""
        return max(1, len(text) // 4)
