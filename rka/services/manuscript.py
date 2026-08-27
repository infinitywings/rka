"""Legacy manuscript-manifest compatibility service.

Canonical manuscript identity and argument-spine state live in the native
``man_`` aggregate.  This adapter preserves the historical ``jrn_`` manifest
surface for one compatibility window.  Slow reference validation is owned by
Reference-validation initiation and execution are not part of Core 3.0.
"""

from __future__ import annotations

from typing import Any

from rka.infra.database import Database
from rka.models.journal import JournalEntry, JournalEntryCreate
from rka.models.manuscript_native import ManuscriptCreate
from rka.services.base import BaseService
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.notes import NoteService


class ManuscriptService(BaseService):
    """Legacy ``jrn_`` manifest CRUD with canonical dual-write registration."""

    def __init__(
        self,
        db: Database,
        *,
        notes: NoteService | None = None,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(db=db, project_id=project_id, **kwargs)
        self._notes = notes or NoteService(db, project_id=project_id)

    async def register(
        self,
        venue: str,
        title: str,
        *,
        abstract: str | None = None,
        sections: list[str] | None = None,
        actor: str = "executor",
    ) -> JournalEntry:
        """Create legacy and canonical manuscript identities atomically."""
        content_lines = [f"# Manuscript: {title}", "", "## Section index"]
        for section in sections or []:
            content_lines.append(f"- {section}: outlined")
        content = "\n".join(content_lines)
        verbatim = title if not abstract else f"{title}\n\n{abstract}"
        entry_data = JournalEntryCreate(
            content=content,
            type="note",
            source="executor",
            verbatim_input=verbatim,
            tags=["manuscript", f"venue:{venue}", "phase:draft"],
        )
        async with self.db.transaction():
            entry = await self._notes.create(entry_data, actor=actor)
            await NativeManuscriptService(
                self.db,
                project_id=self.project_id,
            ).create(
                ManuscriptCreate(
                    title=title,
                    abstract=abstract,
                    venue=venue,
                    phase="planning",
                    legacy_journal_id=entry.id,
                ),
                actor=actor,
            )
            return entry

    async def get(self, manuscript_id: str) -> dict[str, Any] | None:
        """Read a legacy manifest only when it is explicitly tagged."""
        entry = await self._notes.get(manuscript_id)
        if entry is None:
            return None
        tags = getattr(entry, "tags", None) or []
        if "manuscript" not in tags:
            return None

        title = ""
        abstract = ""
        if entry.verbatim_input:
            parts = entry.verbatim_input.split("\n\n", 1)
            title = parts[0].strip()
            if len(parts) == 2:
                abstract = parts[1].strip()

        venue = None
        phase = None
        for tag in tags:
            if tag.startswith("venue:"):
                venue = tag.split(":", 1)[1]
            elif tag.startswith("phase:"):
                phase = tag.split(":", 1)[1]

        return {
            "id": entry.id,
            "project_id": entry.project_id,
            "title": title,
            "abstract": abstract,
            "venue": venue,
            "phase": phase,
            "content": entry.content,
            "tags": tags,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }
