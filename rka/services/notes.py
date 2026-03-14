"""Journal (notes) service."""

from __future__ import annotations

from rka.infra.ids import generate_id
from rka.models.journal import JournalEntry, JournalEntryCreate, JournalEntryUpdate
from rka.services.base import BaseService, _now
from rka.services.jobs import JobQueue


class NoteService(BaseService):
    """Manages research journal entries."""

    def _job_dedupe_key(self, entry_id: str, operation: str) -> str:
        return f"{self.project_id}:journal:{entry_id}:{operation}"

    async def _enqueue_enrichment_jobs(
        self,
        entry_id: str,
        *,
        include_auto_tags: bool,
        include_auto_link: bool,
        include_auto_summarize: bool,
        include_embedding: bool,
    ) -> None:
        queue = JobQueue(self.db)
        if include_auto_tags:
            await queue.enqueue(
                "note_auto_tag",
                project_id=self.project_id,
                entity_type="journal",
                entity_id=entry_id,
                dedupe_key=self._job_dedupe_key(entry_id, "auto_tag"),
            )
        if include_auto_link:
            await queue.enqueue(
                "note_auto_link",
                project_id=self.project_id,
                entity_type="journal",
                entity_id=entry_id,
                dedupe_key=self._job_dedupe_key(entry_id, "auto_link"),
            )
        if include_auto_summarize:
            await queue.enqueue(
                "note_auto_summarize",
                project_id=self.project_id,
                entity_type="journal",
                entity_id=entry_id,
                dedupe_key=self._job_dedupe_key(entry_id, "auto_summarize"),
            )
        if include_embedding:
            await queue.enqueue(
                "note_embed",
                project_id=self.project_id,
                entity_type="journal",
                entity_id=entry_id,
                dedupe_key=self._job_dedupe_key(entry_id, "embed"),
                priority=110,  # run after summarize so embedding includes summary
            )

    async def create(self, data: JournalEntryCreate, actor: str | None = None) -> JournalEntry:
        """Create a new journal entry."""
        entry_id = generate_id("journal")
        source = actor or data.source

        await self.db.execute(
            """INSERT INTO journal
               (id, type, content, source, phase, related_decisions, related_literature,
                related_mission, supersedes, confidence, importance, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                entry_id, data.type, data.content, source, data.phase,
                self._json_dumps(data.related_decisions),
                self._json_dumps(data.related_literature),
                data.related_mission, data.supersedes,
                data.confidence, data.importance, self.project_id,
            ],
        )

        # If superseding another entry, update the back-reference
        if data.supersedes:
            await self.db.execute(
                "UPDATE journal SET superseded_by = ?, confidence = 'superseded', updated_at = ? WHERE id = ? AND project_id = ?",
                [entry_id, _now(), data.supersedes, self.project_id],
            )

        await self.db.commit()

        # Save user-provided tags immediately; auto-tags are deferred to job queue
        has_user_tags = bool(data.tags)
        if has_user_tags:
            await self._set_tags("journal", entry_id, data.tags)

        # Write entity_links for caller-provided related_* fields
        has_user_links = bool(data.related_decisions or data.related_literature or data.related_mission)
        if has_user_links:
            for dec_id in (data.related_decisions or []):
                await self.add_link("journal", entry_id, "references", "decision", dec_id, created_by=source or "system")
            for lit_id in (data.related_literature or []):
                await self.add_link("journal", entry_id, "cites", "literature", lit_id, created_by=source or "system")
            if data.related_mission:
                await self.add_link("mission", data.related_mission, "produced", "journal", entry_id, created_by=source or "system")

        # Sync cheap deterministic FTS now; LLM enrichment + embedding are queued
        await self._sync_fts("journal", entry_id, {
            "content": data.content, "summary": "",
        })

        # Enqueue background enrichment jobs
        await self._enqueue_enrichment_jobs(
            entry_id,
            include_auto_tags=bool(self.llm) and not has_user_tags,
            include_auto_link=bool(self.llm) and not has_user_links,
            include_auto_summarize=bool(self.llm),
            include_embedding=bool(self.embeddings),
        )

        # Determine event type based on journal type
        event_type_map = {
            "finding": "finding_recorded",
            "insight": "insight_recorded",
            "pi_instruction": "pi_instruction",
        }
        event_type = event_type_map.get(data.type, "finding_recorded")

        await self.emit_event(
            event_type=event_type,
            entity_type="journal",
            entity_id=entry_id,
            actor=source,
            summary=f"{data.type}: {data.content[:100]}",
            phase=data.phase,
        )
        await self.audit("create", "journal", entry_id, source)
        return await self.get(entry_id)

    async def get(self, entry_id: str) -> JournalEntry | None:
        """Get a single journal entry by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if row is None:
            return None
        return await self._row_to_model(row)

    async def list(
        self,
        type: str | None = None,
        phase: str | None = None,
        confidence: str | None = None,
        importance: str | None = None,
        source: str | None = None,
        since: str | None = None,
        hide_superseded: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JournalEntry]:
        """List journal entries with filters."""
        conditions = []
        params = [self.project_id]

        conditions.append("project_id = ?")

        if type:
            conditions.append("type = ?")
            params.append(type)
        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        if confidence:
            conditions.append("confidence = ?")
            params.append(confidence)
        if importance:
            conditions.append("importance = ?")
            params.append(importance)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if since:
            conditions.append("created_at >= ?")
            params.append(since)
        if hide_superseded:
            conditions.append("confidence != 'superseded'")

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM journal WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [await self._row_to_model(row) for row in rows]

    async def update(self, entry_id: str, data: JournalEntryUpdate) -> JournalEntry:
        """Update a journal entry."""
        dump = data.model_dump(exclude_none=True)
        tags = dump.pop("tags", None)

        updates = {}
        for field, value in dump.items():
            if field in ("related_decisions", "related_literature"):
                updates[field] = self._json_dumps(value)
            else:
                updates[field] = value

        if tags is not None:
            await self._set_tags("journal", entry_id, tags)

        if not updates:
            return await self.get(entry_id)

        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [entry_id]

        await self.db.execute(
            f"UPDATE journal SET {set_clause} WHERE id = ? AND project_id = ?",
            values + [self.project_id],
        )
        await self.db.commit()

        # Re-sync FTS on content changes; defer embedding to job queue
        if "content" in updates or "summary" in updates:
            row = await self.db.fetchone(
                "SELECT content, summary FROM journal WHERE id = ? AND project_id = ?",
                [entry_id, self.project_id],
            )
            if row:
                await self._sync_fts("journal", entry_id, dict(row))
                if self.embeddings:
                    queue = JobQueue(self.db)
                    await queue.enqueue(
                        "note_embed",
                        project_id=self.project_id,
                        entity_type="journal",
                        entity_id=entry_id,
                        dedupe_key=self._job_dedupe_key(entry_id, "embed"),
                        priority=110,
                    )

        await self.audit("update", "journal", entry_id, "system", {"fields": list(updates.keys())})
        return await self.get(entry_id)

    async def _row_to_model(self, row: dict) -> JournalEntry:
        tags = await self._get_tags("journal", row["id"])
        enrichment_status = await self._get_enrichment_status("journal", row["id"])
        return JournalEntry(
            id=row["id"],
            type=row["type"],
            content=row["content"],
            summary=row.get("summary"),
            source=row["source"],
            phase=row.get("phase"),
            related_decisions=self._json_loads(row.get("related_decisions")),
            related_literature=self._json_loads(row.get("related_literature")),
            related_mission=row.get("related_mission"),
            supersedes=row.get("supersedes"),
            superseded_by=row.get("superseded_by"),
            confidence=row["confidence"],
            importance=row["importance"],
            tags=tags,
            enrichment_status=enrichment_status,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    # ---- Background job handlers ----

    async def process_auto_tag_job(self, entry_id: str) -> dict[str, str | int]:
        """Generate tags for a journal entry when none are present."""
        row = await self.db.fetchone(
            "SELECT content FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        existing_tags = await self._get_tags("journal", entry_id)
        if existing_tags:
            return {"outcome": "skipped", "reason": "tags_present"}

        auto_tags = await self._auto_enrich_tags(row["content"], existing_tags)
        if not auto_tags:
            return {"outcome": "noop"}

        await self._set_tags("journal", entry_id, auto_tags)
        return {"outcome": "updated", "tag_count": len(auto_tags)}

    async def process_auto_link_job(self, entry_id: str) -> dict[str, str | int]:
        """Infer entity links for a journal entry via LLM."""
        row = await self.db.fetchone(
            "SELECT content, type, source, related_decisions, related_literature, related_mission "
            "FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        links = await self._auto_link(row["content"], row["type"])
        if not links:
            return {"outcome": "noop"}

        link_updates: dict = {}
        if links.related_decision_ids:
            link_updates["related_decisions"] = self._json_dumps(links.related_decision_ids)
        if links.related_literature_ids:
            link_updates["related_literature"] = self._json_dumps(links.related_literature_ids)
        if links.related_mission_id:
            link_updates["related_mission"] = links.related_mission_id
        if links.suggested_type and links.suggested_type != row["type"]:
            link_updates["type"] = links.suggested_type

        if link_updates:
            set_clause = ", ".join(f"{k} = ?" for k in link_updates)
            await self.db.execute(
                f"UPDATE journal SET {set_clause} WHERE id = ? AND project_id = ?",
                list(link_updates.values()) + [entry_id, self.project_id],
            )
            await self.db.commit()

        # Write entity_links rows
        source = row.get("source") or "system"
        final_row = await self.db.fetchone(
            "SELECT related_decisions, related_literature, related_mission FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if final_row:
            for dec_id in self._json_loads(final_row.get("related_decisions"), []):
                await self.add_link("journal", entry_id, "references", "decision", dec_id, created_by=source)
            for lit_id in self._json_loads(final_row.get("related_literature"), []):
                await self.add_link("journal", entry_id, "cites", "literature", lit_id, created_by=source)
            if final_row.get("related_mission"):
                await self.add_link("mission", final_row["related_mission"], "produced", "journal", entry_id, created_by=source)

        link_count = len(link_updates)
        return {"outcome": "updated" if link_count else "noop", "link_count": link_count}

    async def process_auto_summarize_job(self, entry_id: str) -> dict[str, str | int]:
        """Generate a one-line summary for a journal entry via LLM."""
        row = await self.db.fetchone(
            "SELECT content FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        summary = await self._auto_summarize(row["content"])
        if not summary:
            return {"outcome": "noop"}

        await self.db.execute(
            "UPDATE journal SET summary = ? WHERE id = ? AND project_id = ?",
            [summary, entry_id, self.project_id],
        )
        await self.db.commit()

        # Re-sync FTS so the summary is searchable
        await self._sync_fts("journal", entry_id, {
            "content": row["content"], "summary": summary,
        })

        return {"outcome": "updated", "summary_len": len(summary)}

    async def process_embedding_job(self, entry_id: str) -> dict[str, str | int]:
        """Generate or refresh the journal entry embedding."""
        row = await self.db.fetchone(
            "SELECT content, summary FROM journal WHERE id = ? AND project_id = ?",
            [entry_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.embeddings:
            return {"outcome": "skipped", "reason": "embeddings_disabled"}

        parts = [str(row.get("content") or "").strip(), str(row.get("summary") or "").strip()]
        text = " ".join(part for part in parts if part).strip()
        if not text:
            return {"outcome": "skipped", "reason": "empty"}

        await self.embeddings.embed_and_store("journal", entry_id, text, project_id=self.project_id)
        return {"outcome": "updated", "char_count": len(text)}
