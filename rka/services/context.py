"""Context engine — prepares focused context packages for Brain and Executor."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from rka.infra.database import Database
from rka.infra.llm import LLMClient
from rka.models.context import ContextPackage
from rka.services.search import SearchService

logger = logging.getLogger(__name__)


class ContextEngine:
    """Prepares focused context packages with temperature classification.

    Temperature model:
      HOT  — active + current phase + recently updated (< hot_days)
      WARM — everything else that's active/recent
      COLD — abandoned / superseded / old completed
    """

    def __init__(
        self,
        db: Database,
        search: SearchService,
        llm: LLMClient | None = None,
        hot_days: int = 3,
        warm_days: int = 14,
    ):
        self.db = db
        self.search = search
        self.llm = llm
        self.hot_days = hot_days
        self.warm_days = warm_days

    @property
    def _default_max_tokens(self) -> int:
        """Default context budget, scaled to LLM context window."""
        if self.llm:
            # Use ~25% of context window for context packages
            return max(2000, self.llm.ctx // 4)
        return 2000

    async def get_context(
        self,
        topic: str | None = None,
        phase: str | None = None,
        depth: Literal["summary", "detailed"] = "summary",
        max_tokens: int | None = None,
        project_id: str = "proj_default",
    ) -> ContextPackage:
        """Build a context package within token budget."""
        if max_tokens is None:
            max_tokens = self._default_max_tokens
        # 1. Gather candidates
        if topic:
            hits = await self.search.with_project(project_id).search(topic, limit=50)
            candidates = await self._hydrate_hits(hits, project_id=project_id)
        else:
            candidates = await self._get_overview_candidates(phase, project_id=project_id)

        # 2. Classify by temperature
        current_phase = phase or await self._get_current_phase(project_id=project_id)
        hot, warm, cold = self._classify_temperature(candidates, current_phase)

        # 3. Build context within token budget
        package = ContextPackage(topic=topic, phase=current_phase)
        budget = max_tokens

        # HOT entries: always included verbatim
        for entry in hot:
            text = self._render_entry(entry)
            cost = self._estimate_tokens(text)
            if budget - cost < 0 and package.hot_entries:
                break
            budget -= cost
            package.hot_entries.append(text)

        if budget <= 0:
            package.note = "Context truncated: too many active items"
            package.sources = [e["id"] for e in hot + warm + cold]
            package.token_estimate = max_tokens - budget
            return package

        # WARM entries: include verbatim if fits, else summarize
        warm_texts = [self._render_entry(e) for e in warm]
        warm_total = sum(self._estimate_tokens(t) for t in warm_texts)

        if warm_total <= budget * 0.6:
            package.warm_entries = warm_texts
            budget -= warm_total
        elif warm and self.llm:
            try:
                warm_summary = await self.llm.summarize_entries(
                    warm, max_tokens=int(budget * 0.5),
                )
                if warm_summary:
                    package.warm_entries = [warm_summary]
                    budget -= self._estimate_tokens(warm_summary)
            except Exception:
                # Fall back to truncated verbatim
                for text in warm_texts:
                    cost = self._estimate_tokens(text)
                    if budget - cost < 200:
                        break
                    budget -= cost
                    package.warm_entries.append(text)
        else:
            for text in warm_texts:
                cost = self._estimate_tokens(text)
                if budget - cost < 200:
                    break
                budget -= cost
                package.warm_entries.append(text)

        # COLD entries: always summarized
        if budget > 200 and cold:
            if self.llm:
                try:
                    cold_summary = await self.llm.summarize_entries(
                        cold, max_tokens=min(budget, 300),
                    )
                    if cold_summary:
                        package.cold_entries = [cold_summary]
                        budget -= self._estimate_tokens(cold_summary)
                except Exception:
                    pass
            if not package.cold_entries:
                # Fallback: one-liners
                for entry in cold[:5]:
                    line = f"[{entry.get('entity_type', '?')}] {entry.get('title', entry.get('content', ''))[:80]}"
                    package.cold_entries.append(line)
                    budget -= self._estimate_tokens(line)
                    if budget < 100:
                        break

        # 4. Source references
        package.sources = [e["id"] for e in hot + warm + cold]

        # 5. Optional narrative
        if depth == "detailed" and self.llm:
            try:
                narrative = await self.llm.produce_narrative(package.model_dump())
                if narrative:
                    package.narrative = narrative
            except Exception:
                pass

        package.token_estimate = max_tokens - budget
        return package

    def _classify_temperature(
        self, candidates: list[dict], current_phase: str | None,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Assign temperature based on status, recency, phase, and cross-refs."""
        hot, warm, cold = [], [], []
        now = datetime.now(timezone.utc)

        for entry in candidates:
            etype = entry.get("entity_type", "")
            # Normalize "status" across entity types
            # journal uses 'confidence' instead of 'status'
            if etype == "journal":
                status = entry.get("confidence", "hypothesis")
            else:
                status = entry.get("status", "")

            phase = entry.get("phase")
            updated_str = entry.get("updated_at") or entry.get("created_at")
            days_old = 999
            if updated_str:
                try:
                    updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    days_old = (now - updated).days
                except (ValueError, TypeError):
                    pass

            # HOT: active/in-progress + current phase + recent
            hot_statuses = {"active", "open", "pending", "to_read", "reading", "hypothesis", "tested"}
            cold_statuses = {"abandoned", "superseded", "retracted", "excluded", "cancelled"}
            done_statuses = {"complete", "read", "cited", "verified"}

            if (
                status in hot_statuses
                and (phase == current_phase or phase is None)
                and days_old < self.hot_days
            ):
                hot.append(entry)
            # COLD: abandoned/superseded/old completed
            elif (
                status in cold_statuses
                or (status in done_statuses and days_old > self.warm_days)
            ):
                cold.append(entry)
            # WARM: everything else
            else:
                warm.append(entry)

        # Boost items with many cross-references to HOT items
        hot_ids = {e["id"] for e in hot}
        for entry in warm[:]:
            refs = set(entry.get("related_decisions") or []) | set(entry.get("related_literature") or [])
            if len(refs & hot_ids) >= 2:
                warm.remove(entry)
                hot.append(entry)

        return hot, warm, cold

    async def _hydrate_hits(self, hits, project_id: str = "proj_default") -> list[dict]:
        """Convert search hits to full entity dicts."""
        table_map = {
            "journal": "journal",
            "decision": "decisions",
            "literature": "literature",
            "mission": "missions",
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
        """Get general overview candidates when no topic is specified."""
        candidates = []
        phase_filter = "AND phase = ?" if phase else ""
        phase_params = [project_id]
        if phase:
            phase_params.append(phase)

        # Scale limits based on LLM context window
        entries_limit = self.llm._entries_limit if self.llm else 20
        dec_limit = max(10, entries_limit * 3 // 4)
        lit_limit = max(5, entries_limit // 2)
        msn_limit = max(3, entries_limit // 4)

        # Recent journal entries
        rows = await self.db.fetchall(
            f"SELECT *, 'journal' as entity_type FROM journal WHERE project_id = ? AND confidence != 'superseded' {phase_filter} ORDER BY created_at DESC LIMIT ?",
            phase_params + [entries_limit],
        )
        candidates.extend(rows)

        # Active decisions
        rows = await self.db.fetchall(
            f"SELECT *, 'decision' as entity_type FROM decisions WHERE project_id = ? AND status = 'active' {phase_filter} ORDER BY created_at DESC LIMIT ?",
            phase_params + [dec_limit],
        )
        candidates.extend(rows)

        # Recent literature
        rows = await self.db.fetchall(
            "SELECT *, 'literature' as entity_type FROM literature WHERE project_id = ? AND status IN ('to_read', 'reading', 'read') ORDER BY created_at DESC LIMIT ?",
            [project_id, lit_limit],
        )
        candidates.extend(rows)

        # Active missions
        rows = await self.db.fetchall(
            f"SELECT *, 'mission' as entity_type FROM missions WHERE project_id = ? AND status IN ('active', 'pending') {phase_filter} ORDER BY created_at DESC LIMIT ?",
            phase_params + [msn_limit],
        )
        candidates.extend(rows)

        return candidates

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
        """Render an entry as a concise text block."""
        if max_len is None:
            max_len = self.llm._evidence_block_limit if self.llm else 400
        etype = entry.get("entity_type", "unknown")
        eid = entry.get("id", "?")

        if etype == "journal":
            return f"[{entry.get('type', 'note')}|{entry.get('confidence', '?')}] {eid}: {(entry.get('content') or '')[:max_len]}"
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
        """Rough token estimation: ~4 chars per token."""
        return max(1, len(text) // 4)
