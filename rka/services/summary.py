"""Summary and QA services — NotebookLM-style research assistance.

Both services REQUIRE a working LLM. They raise LLMUnavailableError
if the LLM is not configured or unreachable.
"""

from __future__ import annotations

import json

from rka.infra.ids import generate_id
from rka.infra.llm import LLMUnavailableError
from rka.services.artifacts import build_figure_text
from rka.services.base import BaseService, _now
from rka.services.search import SearchService


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
                confidence, source_refs, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [summary_id, scope_type, scope_id, granularity, content,
             produced_by, result.confidence, source_refs, self.project_id],
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
            "SELECT * FROM exploration_summaries WHERE id = ? AND project_id = ?",
            [summary_id, self.project_id],
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
        conditions: list[str] = ["project_id = ?"]
        params: list = [self.project_id]
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
            "UPDATE exploration_summaries SET blessed = 1, updated_at = ? WHERE id = ? AND project_id = ?",
            [_now(), summary_id, self.project_id],
        )
        await self.db.commit()
        await self.audit("update", "summary", summary_id, actor, {"action": "bless"})
        return await self.get(summary_id)

    def _evidence_limit(self) -> int:
        """Max evidence entries to gather, scaled to LLM context window."""
        if self.llm:
            return self.llm._max_evidence_blocks
        return 30

    async def _gather_evidence(
        self, scope_type: str, scope_id: str | None
    ) -> list[dict]:
        """Gather evidence blocks for the given scope."""
        evidence: list[dict] = []
        limit = self._evidence_limit()
        figure_limit = max(3, limit // 5)

        if scope_type == "phase":
            # All journal entries + decisions in this phase
            rows = await self.db.fetchall(
                "SELECT id, content, summary FROM journal WHERE project_id = ? AND phase = ? ORDER BY created_at DESC LIMIT ?",
                [self.project_id, scope_id, limit],
            )
            for r in rows:
                evidence.append({"entity_type": "journal", "entity_id": r["id"], "text": r["content"] or r.get("summary", "")})
            dec_rows = await self.db.fetchall(
                "SELECT id, question, rationale FROM decisions WHERE project_id = ? AND phase = ? ORDER BY created_at DESC LIMIT ?",
                [self.project_id, scope_id, limit * 2 // 3],
            )
            for r in dec_rows:
                evidence.append({"entity_type": "decision", "entity_id": r["id"], "text": f"{r['question']} — {r.get('rationale', '')}"})
            evidence.extend(await self._gather_recent_figure_evidence(figure_limit))

        elif scope_type == "mission":
            # Mission + its journal entries
            content_limit = self.llm._content_limit if self.llm else 2000
            msn = await self.db.fetchone(
                "SELECT id, objective, context, report FROM missions WHERE id = ? AND project_id = ?",
                [scope_id, self.project_id],
            )
            if msn:
                evidence.append({"entity_type": "mission", "entity_id": msn["id"], "text": f"{msn['objective']}\n{msn.get('context', '')}"})
                if msn.get("report"):
                    evidence.append({"entity_type": "mission", "entity_id": msn["id"], "text": msn["report"][:content_limit], "loc": "report"})
            journal_rows = await self.db.fetchall(
                "SELECT id, content FROM journal WHERE related_mission = ? AND project_id = ? ORDER BY created_at LIMIT ?",
                [scope_id, self.project_id, limit * 2 // 3],
            )
            for r in journal_rows:
                evidence.append({"entity_type": "journal", "entity_id": r["id"], "text": r["content"]})
            evidence.extend(await self._gather_recent_figure_evidence(figure_limit))

        elif scope_type == "tag":
            # All entities with this tag
            tag_rows = await self.db.fetchall(
                "SELECT entity_type, entity_id FROM tags WHERE tag = ? AND project_id = ? LIMIT ?",
                [scope_id, self.project_id, limit],
            )
            for tr in tag_rows:
                block = await self._fetch_entity_block(tr["entity_type"], tr["entity_id"])
                if block:
                    evidence.append(block)

        else:
            # Project-wide: recent entries across all types
            per_type_limit = limit // 2
            for table, etype, text_col in [
                ("journal", "journal", "content"),
                ("decisions", "decision", "question"),
                ("literature", "literature", "title"),
            ]:
                rows = await self.db.fetchall(
                    f"SELECT id, {text_col} FROM {table} WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    [self.project_id, per_type_limit],
                )
                for r in rows:
                    evidence.append({"entity_type": etype, "entity_id": r["id"], "text": r[text_col] or ""})
            evidence.extend(await self._gather_recent_figure_evidence(figure_limit))

        return evidence[:limit]

    async def _fetch_entity_text(self, entity_type: str, entity_id: str) -> str | None:
        """Fetch the primary text of an entity."""
        block = await self._fetch_entity_block(entity_type, entity_id)
        return block["text"] if block else None

    async def _fetch_entity_block(self, entity_type: str, entity_id: str) -> dict | None:
        """Fetch an evidence block for a supported entity type."""
        if entity_type == "journal":
            row = await self.db.fetchone(
                "SELECT id, content, summary FROM journal WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "journal",
                    "entity_id": row["id"],
                    "text": row.get("content") or row.get("summary") or "",
                }
            return None

        if entity_type == "decision":
            row = await self.db.fetchone(
                "SELECT id, question, rationale FROM decisions WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "decision",
                    "entity_id": row["id"],
                    "text": f"{row.get('question') or ''} — {row.get('rationale') or ''}".strip(" —"),
                }
            return None

        if entity_type == "literature":
            row = await self.db.fetchone(
                "SELECT id, title, abstract FROM literature WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "literature",
                    "entity_id": row["id"],
                    "text": "\n".join(
                        part for part in [row.get("title"), row.get("abstract")] if part
                    ),
                }
            return None

        if entity_type == "mission":
            row = await self.db.fetchone(
                "SELECT id, objective, context FROM missions WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "mission",
                    "entity_id": row["id"],
                    "text": "\n".join(
                        part for part in [row.get("objective"), row.get("context")] if part
                    ),
                }
            return None

        if entity_type == "figure":
            row = await self.db.fetchone(
                """SELECT id, artifact_id, page, caption, summary, claims
                   FROM figures WHERE id = ? AND project_id = ?""",
                [entity_id, self.project_id],
            )
            if row:
                loc = f"artifact:{row['artifact_id']}"
                if row.get("page") is not None:
                    loc += f"|page:{row['page']}"
                return {
                    "entity_type": "figure",
                    "entity_id": row["id"],
                    "text": build_figure_text(
                        caption=row.get("caption"),
                        summary=row.get("summary"),
                        claims=row.get("claims"),
                    ),
                    "loc": loc,
                }
            return None

        return None

    async def _gather_recent_figure_evidence(self, limit: int) -> list[dict]:
        """Gather recent figures as additional evidence blocks."""
        rows = await self.db.fetchall(
            """SELECT id
               FROM figures
               WHERE project_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            [self.project_id, limit],
        )
        blocks: list[dict] = []
        for row in rows:
            block = await self._fetch_entity_block("figure", row["id"])
            if block and block.get("text"):
                blocks.append(block)
        return blocks


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
                "INSERT INTO qa_sessions (id, project_id, created_by, title) VALUES (?, ?, ?, ?)",
                [session_id, self.project_id, actor, question[:100]],
            )
            await self.db.commit()
        else:
            existing_session = await self.db.fetchone(
                "SELECT id FROM qa_sessions WHERE id = ? AND project_id = ?",
                [session_id, self.project_id],
            )
            if not existing_session:
                return {"error": f"QA session {session_id} not found for this project."}

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
            "SELECT * FROM qa_sessions WHERE id = ? AND project_id = ?",
            [session_id, self.project_id],
        )
        if not session:
            return None
        logs = await self.db.fetchall(
            "SELECT * FROM qa_logs WHERE session_id = ? ORDER BY created_at",
            [session_id],
        )
        return {
            **dict(session),
            "logs": [dict(log_row) for log_row in logs],
        }

    async def list_sessions(self, limit: int = 20) -> list[dict]:
        """List QA sessions."""
        rows = await self.db.fetchall(
            "SELECT * FROM qa_sessions WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            [self.project_id, limit],
        )
        return [dict(r) for r in rows]

    async def verify_source(
        self, qa_log_id: str, source_index: int, actor: str = "pi"
    ) -> dict:
        """Verify a cited source in a QA answer against actual stored data."""
        row = await self.db.fetchone(
            """SELECT l.sources
               FROM qa_logs l
               JOIN qa_sessions s ON s.id = l.session_id
               WHERE l.id = ? AND s.project_id = ?""",
            [qa_log_id, self.project_id],
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

        block = await self._fetch_entity_block(entity_type, entity_id)
        if not block:
            return {"verified": False, "reason": f"Unknown entity type: {entity_type}"}
        actual_text = block["text"] or ""
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

        Uses hybrid search where available, falls back to recent entries.
        """
        evidence: list[dict] = []
        block_limit = self.llm._evidence_block_limit if self.llm else 500
        max_blocks = self.llm._max_evidence_blocks if self.llm else 30
        fallback_limit = max(15, max_blocks // 2)
        search_service = SearchService(
            db=self.db,
            embeddings=self.embeddings,
            project_id=self.project_id,
        )

        try:
            hits = await search_service.search(
                question,
                entity_types=["journal", "decision", "literature", "figure", "artifact"],
                limit=max_blocks,
            )
            for hit in hits:
                block = await self._fetch_entity_block(hit.entity_type, hit.entity_id)
                if not block:
                    continue
                block["text"] = (block.get("text") or "")[:block_limit]
                if not block["text"]:
                    continue
                evidence.append(block)
        except Exception:
            # Search backend unavailable, fall back to recent entries
            pass

        # If not enough evidence from FTS, add recent entries
        if len(evidence) < 5:
            if scope_type == "phase" and scope_id:
                rows = await self.db.fetchall(
                    "SELECT id, content FROM journal WHERE project_id = ? AND phase = ? ORDER BY created_at DESC LIMIT ?",
                    [self.project_id, scope_id, fallback_limit],
                )
            else:
                rows = await self.db.fetchall(
                    "SELECT id, content FROM journal WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    [self.project_id, fallback_limit],
                )
            for r in rows:
                if not any(e["entity_id"] == r["id"] for e in evidence):
                    evidence.append({"entity_type": "journal", "entity_id": r["id"], "text": (r["content"] or "")[:block_limit]})

            figure_rows = await self.db.fetchall(
                """SELECT id
                   FROM figures
                   WHERE project_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [self.project_id, max(5, fallback_limit // 3)],
            )
            for row in figure_rows:
                if any(e["entity_type"] == "figure" and e["entity_id"] == row["id"] for e in evidence):
                    continue
                block = await self._fetch_entity_block("figure", row["id"])
                if not block:
                    continue
                block["text"] = (block.get("text") or "")[:block_limit]
                if block["text"]:
                    evidence.append(block)

        return evidence[:max_blocks]

    async def _fetch_entity_block(self, entity_type: str, entity_id: str) -> dict | None:
        """Fetch a grounded evidence block for QA and verification."""
        if entity_type == "journal":
            row = await self.db.fetchone(
                "SELECT id, content, summary FROM journal WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "journal",
                    "entity_id": row["id"],
                    "text": row.get("content") or row.get("summary") or "",
                }
            return None

        if entity_type == "decision":
            row = await self.db.fetchone(
                "SELECT id, question, rationale FROM decisions WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "decision",
                    "entity_id": row["id"],
                    "text": f"{row.get('question') or ''} — {row.get('rationale') or ''}".strip(" —"),
                }
            return None

        if entity_type == "literature":
            row = await self.db.fetchone(
                "SELECT id, title, abstract FROM literature WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "literature",
                    "entity_id": row["id"],
                    "text": "\n".join(
                        part for part in [row.get("title"), row.get("abstract")] if part
                    ),
                }
            return None

        if entity_type == "mission":
            row = await self.db.fetchone(
                "SELECT id, objective, context FROM missions WHERE id = ? AND project_id = ?",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "mission",
                    "entity_id": row["id"],
                    "text": "\n".join(
                        part for part in [row.get("objective"), row.get("context")] if part
                    ),
                }
            return None

        if entity_type == "artifact":
            row = await self.db.fetchone(
                """SELECT id, filename, filetype, mime, metadata
                   FROM artifacts WHERE id = ? AND project_id = ?""",
                [entity_id, self.project_id],
            )
            if row:
                return {
                    "entity_type": "artifact",
                    "entity_id": row["id"],
                    "text": "\n".join(
                        part
                        for part in [
                            row.get("filename"),
                            row.get("filetype"),
                            row.get("mime"),
                            row.get("metadata"),
                        ]
                        if part
                    ),
                }
            return None

        if entity_type == "figure":
            row = await self.db.fetchone(
                """SELECT id, artifact_id, page, caption, summary, claims
                   FROM figures WHERE id = ? AND project_id = ?""",
                [entity_id, self.project_id],
            )
            if row:
                loc = f"artifact:{row['artifact_id']}"
                if row.get("page") is not None:
                    loc += f"|page:{row['page']}"
                return {
                    "entity_type": "figure",
                    "entity_id": row["id"],
                    "text": build_figure_text(
                        caption=row.get("caption"),
                        summary=row.get("summary"),
                        claims=row.get("claims"),
                    ),
                    "loc": loc,
                }
            return None

        return None

    async def _get_session_context(self, session_id: str) -> str | None:
        """Get previous Q&A in this session as context."""
        rows = await self.db.fetchall(
            """SELECT l.question, l.answer
               FROM qa_logs l
               JOIN qa_sessions s ON s.id = l.session_id
               WHERE l.session_id = ? AND s.project_id = ?
               ORDER BY l.created_at DESC LIMIT 5""",
            [session_id, self.project_id],
        )
        if not rows:
            return None
        parts = []
        for r in reversed(rows):
            answer_limit = self.llm._evidence_block_limit if self.llm else 200
            parts.append(f"Q: {r['question']}\nA: {r['answer'][:answer_limit]}")
        return "\n\n".join(parts)
