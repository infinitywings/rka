"""Literature service."""

from __future__ import annotations

import json

from rka.infra.ids import generate_id
from rka.models.literature import Literature, LiteratureCreate, LiteratureUpdate
from rka.services.base import BaseService, _now


class LiteratureService(BaseService):
    """Manages literature entries."""

    async def create(self, data: LiteratureCreate, actor: str | None = None) -> Literature:
        """Create a new literature entry."""
        lit_id = generate_id("literature")
        source = actor or data.added_by

        await self.db.execute(
            """INSERT INTO literature
               (id, title, authors, year, venue, doi, url, bibtex, pdf_path, abstract,
                status, key_findings, methodology_notes, relevance, relevance_score,
                related_decisions, added_by, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                lit_id, data.title, self._json_dumps(data.authors),
                data.year, data.venue, data.doi, data.url, data.bibtex,
                data.pdf_path, data.abstract, data.status,
                self._json_dumps(data.key_findings), data.methodology_notes,
                data.relevance, data.relevance_score,
                self._json_dumps(data.related_decisions),
                data.added_by, data.notes,
            ],
        )
        await self.db.commit()

        # Save tags (user-provided or auto-generated)
        tags = data.tags
        if not tags:
            text_for_tags = f"{data.title}. {data.abstract or ''}"
            auto_tags = await self._auto_enrich_tags(text_for_tags, [])
            if auto_tags:
                tags = auto_tags
        if tags:
            await self._set_tags("literature", lit_id, tags)

        # Sync FTS5 + embedding indexes
        await self._sync_indexes("literature", lit_id, {
            "title": data.title, "abstract": data.abstract, "notes": data.notes,
        })

        await self.emit_event(
            event_type="literature_added",
            entity_type="literature",
            entity_id=lit_id,
            actor=source,
            summary=f"Added: {data.title[:100]}",
        )
        await self.audit("create", "literature", lit_id, source)
        return await self.get(lit_id)

    async def get(self, lit_id: str) -> Literature | None:
        """Get a single literature entry by ID."""
        row = await self.db.fetchone("SELECT * FROM literature WHERE id = ?", [lit_id])
        if row is None:
            return None
        return await self._row_to_model(row)

    async def list(
        self,
        status: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        venue: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Literature]:
        """List literature with filters."""
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if year_min:
            conditions.append("year >= ?")
            params.append(year_min)
        if year_max:
            conditions.append("year <= ?")
            params.append(year_max)
        if venue:
            conditions.append("venue LIKE ?")
            params.append(f"%{venue}%")
        if query:
            conditions.append("(title LIKE ? OR abstract LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM literature WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [await self._row_to_model(row) for row in rows]

    async def update(self, lit_id: str, data: LiteratureUpdate, actor: str = "system") -> Literature:
        """Update a literature entry."""
        dump = data.model_dump(exclude_none=True)
        tags = dump.pop("tags", None)

        updates = {}
        for field, value in dump.items():
            if field in ("authors", "key_findings", "related_decisions"):
                updates[field] = self._json_dumps(value)
            else:
                updates[field] = value

        if tags is not None:
            await self._set_tags("literature", lit_id, tags)

        if not updates:
            return await self.get(lit_id)

        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [lit_id]

        await self.db.execute(f"UPDATE literature SET {set_clause} WHERE id = ?", values)
        await self.db.commit()

        # Emit event if status changed to cited
        if data.status == "cited":
            await self.emit_event(
                event_type="literature_cited",
                entity_type="literature",
                entity_id=lit_id,
                actor=actor,
                summary=f"Literature cited",
            )

        # Re-sync FTS5 + embedding on content changes
        if any(f in updates for f in ("title", "abstract", "notes")):
            row = await self.db.fetchone("SELECT title, abstract, notes FROM literature WHERE id = ?", [lit_id])
            if row:
                await self._sync_indexes("literature", lit_id, dict(row))

        await self.audit("update", "literature", lit_id, actor, {"fields": list(updates.keys())})
        return await self.get(lit_id)

    async def _row_to_model(self, row: dict) -> Literature:
        tags = await self._get_tags("literature", row["id"])
        return Literature(
            id=row["id"],
            title=row["title"],
            authors=self._json_loads(row.get("authors")),
            year=row.get("year"),
            venue=row.get("venue"),
            doi=row.get("doi"),
            url=row.get("url"),
            bibtex=row.get("bibtex"),
            pdf_path=row.get("pdf_path"),
            abstract=row.get("abstract"),
            status=row["status"],
            key_findings=self._json_loads(row.get("key_findings")),
            methodology_notes=row.get("methodology_notes"),
            relevance=row.get("relevance"),
            relevance_score=row.get("relevance_score"),
            related_decisions=self._json_loads(row.get("related_decisions")),
            added_by=row.get("added_by"),
            notes=row.get("notes"),
            tags=tags,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
