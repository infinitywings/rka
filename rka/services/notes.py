"""Journal (notes) service."""

from __future__ import annotations

import json

from rka.infra.ids import generate_id
from rka.models.journal import JournalEntry, JournalEntryCreate, JournalEntryUpdate
from rka.services.base import BaseService, _now


class NoteService(BaseService):
    """Manages research journal entries."""

    async def create(self, data: JournalEntryCreate, actor: str | None = None) -> JournalEntry:
        """Create a new journal entry."""
        entry_id = generate_id("journal")
        source = actor or data.source

        await self.db.execute(
            """INSERT INTO journal
               (id, type, content, source, phase, related_decisions, related_literature,
                related_mission, supersedes, confidence, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                entry_id, data.type, data.content, source, data.phase,
                self._json_dumps(data.related_decisions),
                self._json_dumps(data.related_literature),
                data.related_mission, data.supersedes,
                data.confidence, data.importance,
            ],
        )

        # If superseding another entry, update the back-reference
        if data.supersedes:
            await self.db.execute(
                "UPDATE journal SET superseded_by = ?, confidence = 'superseded', updated_at = ? WHERE id = ?",
                [entry_id, _now(), data.supersedes],
            )

        await self.db.commit()

        # Save tags (user-provided or auto-generated)
        tags = data.tags
        if not tags:
            auto_tags = await self._auto_enrich_tags(data.content, [])
            if auto_tags:
                tags = auto_tags
        if tags:
            await self._set_tags("journal", entry_id, tags)

        # Auto-link to related entities via LLM (only when caller didn't specify links)
        no_links_provided = (
            not data.related_decisions
            and not data.related_literature
            and not data.related_mission
        )
        if no_links_provided:
            links = await self._auto_link(data.content, data.type)
            if links:
                link_updates: dict = {}
                if links.related_decision_ids:
                    link_updates["related_decisions"] = self._json_dumps(links.related_decision_ids)
                if links.related_literature_ids:
                    link_updates["related_literature"] = self._json_dumps(links.related_literature_ids)
                if links.related_mission_id:
                    link_updates["related_mission"] = links.related_mission_id
                # Correct type if LLM suggests a better one
                if links.suggested_type and links.suggested_type != data.type:
                    link_updates["type"] = links.suggested_type
                if link_updates:
                    set_clause = ", ".join(f"{k} = ?" for k in link_updates)
                    await self.db.execute(
                        f"UPDATE journal SET {set_clause} WHERE id = ?",
                        list(link_updates.values()) + [entry_id],
                    )
                    await self.db.commit()

        # Write entity_links for whatever related_* fields ended up on the entry
        # (includes both caller-provided and auto-linked values)
        final_row = await self.db.fetchone(
            "SELECT related_decisions, related_literature, related_mission FROM journal WHERE id = ?",
            [entry_id],
        )
        if final_row:
            for dec_id in self._json_loads(final_row.get("related_decisions"), []):
                await self.add_link("journal", entry_id, "references", "decision", dec_id, created_by=source or "system")
            for lit_id in self._json_loads(final_row.get("related_literature"), []):
                await self.add_link("journal", entry_id, "cites", "literature", lit_id, created_by=source or "system")
            if final_row.get("related_mission"):
                await self.add_link("mission", final_row["related_mission"], "produced", "journal", entry_id, created_by=source or "system")

        # Auto-generate summary via LLM
        summary = await self._auto_summarize(data.content)
        if summary:
            await self.db.execute("UPDATE journal SET summary = ? WHERE id = ?", [summary, entry_id])
            await self.db.commit()

        # Sync FTS5 + embedding indexes
        await self._sync_indexes("journal", entry_id, {
            "content": data.content, "summary": summary,
        })

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
        row = await self.db.fetchone("SELECT * FROM journal WHERE id = ?", [entry_id])
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
        params = []

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
            f"UPDATE journal SET {set_clause} WHERE id = ?",
            values,
        )
        await self.db.commit()

        # Re-sync FTS5 + embedding on content changes
        if "content" in updates or "summary" in updates:
            row = await self.db.fetchone("SELECT content, summary FROM journal WHERE id = ?", [entry_id])
            if row:
                await self._sync_indexes("journal", entry_id, dict(row))

        await self.audit("update", "journal", entry_id, "system", {"fields": list(updates.keys())})
        return await self.get(entry_id)

    async def _row_to_model(self, row: dict) -> JournalEntry:
        tags = await self._get_tags("journal", row["id"])
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
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
