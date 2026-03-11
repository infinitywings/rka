"""Summary and QA services — NotebookLM-style research assistance.

Both services REQUIRE a working LLM. They raise LLMUnavailableError
if the LLM is not configured or unreachable.
"""

from __future__ import annotations

import json

from rka.infra.database import Database
from rka.infra.ids import generate_id
from rka.infra.llm import LLMUnavailableError
from rka.services.base import BaseService, _now


class SummaryService(BaseService):
    """Generates and manages multi-granularity exploration summaries."""

    async def generate(
        self,
        scope_type: str,
        scope_id: str | None = None,
        granularity: str = "paragraph",
        produced_by: str = "llm",
    ) -> dict | None:
        """Generate a summary for a given scope (phase, mission, project, tag, etc.).

        Gathers evidence from relevant entities, calls LLM, stores result.
        Returns the stored summary row or None if LLM unavailable.
        """
        if not self.llm:
            raise LLMUnavailableError("SummaryService requires a configured LLM.")

        evidence = await self._gather_evidence(scope_type, scope_id)
        if not evidence:
            return None

        scope_label = f"{scope_type}:{scope_id}" if scope_id else scope_type
        result = await self.llm.generate_summary(
            evidence_blocks=evidence,
            scope_label=scope_label,
            granularity=granularity,
        )

        # Pick the right content field based on granularity
        if granularity == "narrative" and result.narrative:
            content = result.narrative
        elif granularity == "one_line":
            content = result.one_line
        else:
            content = result.paragraph

        summary_id = generate_id("summary")
        source_refs = json.dumps([s.model_dump() for s in result.sources]) if result.sources else None

        await self.db.execute(
            """INSERT INTO exploration_summaries
               (id, scope_type, scope_id, granularity, content, produced_by,
                confidence, source_refs)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [summary_id, scope_type, scope_id, granularity, content,
             produced_by, result.confidence, source_refs],
        )
        await self.db.commit()

        await self.audit("create", "summary", summary_id, produced_by)

        return {
            "id": summary_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "granularity": granularity,
            "one_line": result.one_line,
            "paragraph": result.paragraph,
            "narrative": result.narrative,
            "key_questions": result.key_questions,
            "sources": [s.model_dump() for s in result.sources],
            "confidence": result.confidence,
        }

    async def get(self, summary_id: str) -> dict | None:
        """Get a single summary by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM exploration_summaries WHERE id = ?", [summary_id]
        )
        if not row:
            return None
        return dict(row)

    async def list_summaries(
        self,
        scope_type: str | None = None,
        scope_id: str | None = None,
        blessed_only: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        """List summaries with optional filters."""
        conditions: list[str] = []
        params: list = []
        if scope_type:
            conditions.append("scope_type = ?")
            params.append(scope_type)
        if scope_id:
            conditions.append("scope_id = ?")
            params.append(scope_id)
        if blessed_only:
            conditions.append("blessed = 1")
        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        rows = await self.db.fetchall(
            f"SELECT * FROM exploration_summaries WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in rows]

    async def bless(self, summary_id: str, actor: str = "pi") -> dict | None:
        """Mark a summary as blessed (human-approved)."""
        await self.db.execute(
            "UPDATE exploration_summaries SET blessed = 1, updated_at = ? WHERE id = ?",
            [_now(), summary_id],
        )
        await self.db.commit()
        await self.audit("update", "summary", summary_id, actor, {"action": "bless"})
        return await self.get(summary_id)

    async def _gather_evidence(
        self, scope_type: str, scope_id: str | None
    ) -> list[dict]:
        """Gather evidence blocks for the given scope."""
        evidence: list[dict] = []

        if scope_type == "phase":
            # All journal entries + decisions in this phase
            rows = await self.db.fetchall(
                "SELECT id, content, summary FROM journal WHERE phase = ? ORDER BY created_at DESC LIMIT 30",
                [scope_id],
            )
            for r in rows:
                evidence.append({"entity_type": "journal", "entity_id": r["id"], "text": r["content"] or r.get("summary", "")})
            dec_rows = await self.db.fetchall(
                "SELECT id, question, rationale FROM decisions WHERE phase = ? ORDER BY created_at DESC LIMIT 20",
                [scope_id],
            )
            for r in dec_rows:
                evidence.append({"entity_type": "decision", "entity_id": r["id"], "text": f"{r['question']} — {r.get('rationale', '')}"})

        elif scope_type == "mission":
            # Mission + its journal entries
            msn = await self.db.fetchone("SELECT id, objective, context, report FROM missions WHERE id = ?", [scope_id])
            if msn:
                evidence.append({"entity_type": "mission", "entity_id": msn["id"], "text": f"{msn['objective']}\n{msn.get('context', '')}"})
                if msn.get("report"):
                    evidence.append({"entity_type": "mission", "entity_id": msn["id"], "text": msn["report"][:2000], "loc": "report"})
            journal_rows = await self.db.fetchall(
                "SELECT id, content FROM journal WHERE related_mission = ? ORDER BY created_at LIMIT 20",
                [scope_id],
            )
            for r in journal_rows:
                evidence.append({"entity_type": "journal", "entity_id": r["id"], "text": r["content"]})

        elif scope_type == "tag":
            # All entities with this tag
            tag_rows = await self.db.fetchall(
                "SELECT entity_type, entity_id FROM tags WHERE tag = ? LIMIT 30",
                [scope_id],
            )
            for tr in tag_rows:
                text = await self._fetch_entity_text(tr["entity_type"], tr["entity_id"])
                if text:
                    evidence.append({"entity_type": tr["entity_type"], "entity_id": tr["entity_id"], "text": text})

        else:
            # Project-wide: recent entries across all types
            for table, etype, text_col in [
                ("journal", "journal", "content"),
                ("decisions", "decision", "question"),
                ("literature", "literature", "title"),
            ]:
                rows = await self.db.fetchall(
                    f"SELECT id, {text_col} FROM {table} ORDER BY created_at DESC LIMIT 15",
                )
                for r in rows:
                    evidence.append({"entity_type": etype, "entity_id": r["id"], "text": r[text_col] or ""})

        return evidence

    async def _fetch_entity_text(self, entity_type: str, entity_id: str) -> str | None:
        """Fetch the primary text of an entity."""
        table_map = {
            "journal": ("journal", "content"),
            "decision": ("decisions", "question"),
            "literature": ("literature", "title"),
            "mission": ("missions", "objective"),
        }
        info = table_map.get(entity_type)
        if not info:
            return None
        table, col = info
        row = await self.db.fetchone(f"SELECT {col} FROM {table} WHERE id = ?", [entity_id])
        return row[col] if row else None


class QAService(BaseService):
    """NotebookLM-style Q&A over the knowledge base."""

    async def ask(
        self,
        question: str,
        session_id: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        actor: str = "pi",
    ) -> dict | None:
        """Answer a research question grounded in knowledge base evidence.

        Returns structured answer with sources, or None if LLM unavailable.
        """
        if not self.llm:
            raise LLMUnavailableError("QAService requires a configured LLM.")

        # Create or reuse session
        if not session_id:
            session_id = generate_id("qa_session")
            await self.db.execute(
                "INSERT INTO qa_sessions (id, created_by, title) VALUES (?, ?, ?)",
                [session_id, actor, question[:100]],
            )
            await self.db.commit()

        # Gather evidence
        evidence = await self._gather_qa_evidence(question, scope_type, scope_id)
        if not evidence:
            return {"error": "No evidence found for this question."}

        # Get session context (previous Q&A in this session)
        session_context = await self._get_session_context(session_id)

        result = await self.llm.answer_qa(
            question=question,
            evidence_blocks=evidence,
            session_context=session_context,
        )

        # Store the Q&A log
        log_id = generate_id("qa_log")
        await self.db.execute(
            """INSERT INTO qa_logs
               (id, session_id, question, answer, answer_structured, sources, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                log_id, session_id, question, result.answer,
                json.dumps(result.model_dump()),
                json.dumps([s.model_dump() for s in result.sources]),
                result.confidence,
            ],
        )
        await self.db.commit()

        await self.audit("create", "qa_log", log_id, actor)

        return {
            "session_id": session_id,
            "log_id": log_id,
            "answer": result.answer,
            "answer_type": result.answer_type,
            "sources": [s.model_dump() for s in result.sources],
            "confidence": result.confidence,
            "followups": result.followups,
        }

    async def get_session(self, session_id: str) -> dict | None:
        """Get a QA session with all its logs."""
        session = await self.db.fetchone(
            "SELECT * FROM qa_sessions WHERE id = ?", [session_id]
        )
        if not session:
            return None
        logs = await self.db.fetchall(
            "SELECT * FROM qa_logs WHERE session_id = ? ORDER BY created_at",
            [session_id],
        )
        return {
            **dict(session),
            "logs": [dict(l) for l in logs],
        }

    async def list_sessions(self, limit: int = 20) -> list[dict]:
        """List QA sessions."""
        rows = await self.db.fetchall(
            "SELECT * FROM qa_sessions ORDER BY created_at DESC LIMIT ?",
            [limit],
        )
        return [dict(r) for r in rows]

    async def verify_source(
        self, qa_log_id: str, source_index: int, actor: str = "pi"
    ) -> dict:
        """Verify a cited source in a QA answer against actual stored data."""
        row = await self.db.fetchone(
            "SELECT sources FROM qa_logs WHERE id = ?", [qa_log_id]
        )
        if not row or not row["sources"]:
            return {"verified": False, "reason": "QA log not found"}

        sources = json.loads(row["sources"])
        if source_index >= len(sources):
            return {"verified": False, "reason": "Source index out of range"}

        source = sources[source_index]
        entity_type = source.get("entity_type")
        entity_id = source.get("entity_id")
        excerpt = source.get("excerpt", "")

        # Look up the actual entity text
        table_map = {
            "journal": ("journal", "content"),
            "decision": ("decisions", "question"),
            "literature": ("literature", "abstract"),
            "mission": ("missions", "objective"),
        }
        info = table_map.get(entity_type)
        if not info:
            return {"verified": False, "reason": f"Unknown entity type: {entity_type}"}

        table, col = info
        entity_row = await self.db.fetchone(f"SELECT {col} FROM {table} WHERE id = ?", [entity_id])
        if not entity_row:
            return {"verified": False, "reason": f"Entity {entity_id} not found"}

        actual_text = entity_row[col] or ""
        # Simple substring check
        verified = excerpt.lower().strip() in actual_text.lower()

        return {
            "verified": verified,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "excerpt": excerpt,
            "matched_text": excerpt if verified else None,
            "reason": None if verified else "Excerpt not found in source text",
        }

    async def _gather_qa_evidence(
        self, question: str, scope_type: str | None, scope_id: str | None
    ) -> list[dict]:
        """Gather evidence relevant to a question.

        Uses FTS5 search if available, falls back to recent entries.
        """
        evidence: list[dict] = []

        # Try FTS5 search first
        try:
            for table, etype, fts_table in [
                ("journal", "journal", "fts_journal"),
                ("decisions", "decision", "fts_decisions"),
                ("literature", "literature", "fts_literature"),
            ]:
                # Simple keyword search using first few words of question
                search_terms = " OR ".join(question.split()[:5])
                rows = await self.db.fetchall(
                    f"SELECT j.id, j.* FROM {table} j "
                    f"JOIN {fts_table} f ON j.id = f.id "
                    f"WHERE {fts_table} MATCH ? LIMIT 10",
                    [search_terms],
                )
                text_col = {"journal": "content", "decision": "question", "literature": "title"}.get(etype, "id")
                for r in rows:
                    evidence.append({
                        "entity_type": etype,
                        "entity_id": r["id"],
                        "text": (r.get(text_col) or "")[:500],
                    })
        except Exception:
            # FTS5 not available or query failed, fall back to recent entries
            pass

        # If not enough evidence from FTS, add recent entries
        if len(evidence) < 5:
            if scope_type == "phase" and scope_id:
                rows = await self.db.fetchall(
                    "SELECT id, content FROM journal WHERE phase = ? ORDER BY created_at DESC LIMIT 15",
                    [scope_id],
                )
            else:
                rows = await self.db.fetchall(
                    "SELECT id, content FROM journal ORDER BY created_at DESC LIMIT 15",
                )
            for r in rows:
                if not any(e["entity_id"] == r["id"] for e in evidence):
                    evidence.append({"entity_type": "journal", "entity_id": r["id"], "text": (r["content"] or "")[:500]})

        return evidence[:30]

    async def _get_session_context(self, session_id: str) -> str | None:
        """Get previous Q&A in this session as context."""
        rows = await self.db.fetchall(
            "SELECT question, answer FROM qa_logs WHERE session_id = ? ORDER BY created_at DESC LIMIT 5",
            [session_id],
        )
        if not rows:
            return None
        parts = []
        for r in reversed(rows):
            parts.append(f"Q: {r['question']}\nA: {r['answer'][:200]}")
        return "\n\n".join(parts)
