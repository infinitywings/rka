"""Base service with shared DB access, audit logging, event emission, and FTS5/embedding sync."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rka.infra.database import Database
from rka.infra.ids import generate_id

if TYPE_CHECKING:
    from rka.infra.embeddings import EmbeddingService
    from rka.infra.llm import LLMClient

logger = logging.getLogger(__name__)
DEFAULT_PROJECT_ID = "proj_default"
VALID_ACTORS = frozenset({"brain", "executor", "pi", "llm", "web_ui", "system"})


def _now() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BaseService:
    """Base class for all services. Provides DB access, audit logging, event emission,
    and Phase 2 FTS5/embedding sync hooks."""

    def __init__(
        self,
        db: Database,
        llm: "LLMClient | None" = None,
        embeddings: "EmbeddingService | None" = None,
        project_id: str = DEFAULT_PROJECT_ID,
    ):
        self.db = db
        self.llm = llm
        self.embeddings = embeddings
        self.project_id = project_id

    def _resolve_project_id(self, project_id: str | None = None) -> str:
        return (project_id or self.project_id).strip()

    @staticmethod
    def _validate_actor(actor: str | None, *, allow_none: bool = False) -> str | None:
        if actor is None and allow_none:
            return None
        if actor not in VALID_ACTORS:
            allowed = ", ".join(sorted(VALID_ACTORS))
            raise ValueError(f"Invalid actor '{actor}'. Expected one of: {allowed}")
        return actor

    async def emit_event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        actor: str,
        summary: str,
        caused_by_event: str | None = None,
        caused_by_entity: str | None = None,
        phase: str | None = None,
        details: dict | None = None,
        project_id: str | None = None,
    ) -> str:
        """Record a cross-entity event for the exploration timeline."""
        actor = self._validate_actor(actor)
        event_id = generate_id("event")
        resolved_project_id = self._resolve_project_id(project_id)
        await self.db.execute(
            """INSERT INTO events
               (id, event_type, entity_type, entity_id, actor, summary,
                caused_by_event, caused_by_entity, phase, details, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id, event_type, entity_type, entity_id,
                actor, summary, caused_by_event, caused_by_entity,
                phase, json.dumps(details) if details else None, resolved_project_id,
            ],
        )
        await self.db.commit()
        return event_id

    async def audit(
        self,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor: str = "system",
        details: dict | None = None,
        project_id: str | None = None,
    ) -> None:
        """Record an audit log entry."""
        actor = self._validate_actor(actor, allow_none=True)
        resolved_project_id = self._resolve_project_id(project_id)
        await self.db.execute(
            """INSERT INTO audit_log (action, entity_type, entity_id, actor, details, project_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [action, entity_type, entity_id, actor, json.dumps(details) if details else None, resolved_project_id],
        )
        await self.db.commit()

    async def _get_tags(
        self,
        entity_type: str,
        entity_id: str,
        project_id: str | None = None,
    ) -> list[str]:
        """Get all tags for an entity."""
        resolved_project_id = self._resolve_project_id(project_id)
        rows = await self.db.fetchall(
            "SELECT tag FROM tags WHERE entity_type = ? AND entity_id = ? AND project_id = ?",
            [entity_type, entity_id, resolved_project_id],
        )
        return [row["tag"] for row in rows]

    async def _set_tags(
        self,
        entity_type: str,
        entity_id: str,
        tags: list[str],
        project_id: str | None = None,
    ) -> None:
        """Replace all tags for an entity."""
        resolved_project_id = self._resolve_project_id(project_id)
        await self.db.execute(
            "DELETE FROM tags WHERE entity_type = ? AND entity_id = ? AND project_id = ?",
            [entity_type, entity_id, resolved_project_id],
        )
        for tag in tags:
            await self.db.execute(
                "INSERT OR IGNORE INTO tags (tag, entity_type, entity_id, project_id) VALUES (?, ?, ?, ?)",
                [tag.lower().strip(), entity_type, entity_id, resolved_project_id],
            )
        await self.db.commit()

    # ---- FTS5 sync ----

    # Maps entity types to FTS5 table and columns
    _FTS_CONFIG: dict[str, dict] = {
        "journal": {"table": "fts_journal", "columns": ["id", "content", "summary"]},
        "decision": {"table": "fts_decisions", "columns": ["id", "question", "rationale"]},
        "literature": {"table": "fts_literature", "columns": ["id", "title", "abstract", "notes"]},
        "mission": {"table": "fts_missions", "columns": ["id", "objective", "context"]},
    }

    async def _sync_fts(self, entity_type: str, entity_id: str, data: dict) -> None:
        """Insert or update an entity's FTS5 index entry."""
        config = self._FTS_CONFIG.get(entity_type)
        if not config:
            return
        try:
            # Delete existing entry
            await self.db.execute(
                f"DELETE FROM {config['table']} WHERE id = ?", [entity_id]
            )
            # Insert new entry
            cols = config["columns"]
            values = [data.get(c, "") or "" for c in cols]
            values[0] = entity_id  # id column
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            await self.db.execute(
                f"INSERT INTO {config['table']} ({col_names}) VALUES ({placeholders})",
                values,
            )
            await self.db.commit()
        except Exception as exc:
            logger.debug("FTS5 sync failed for %s/%s: %s", entity_type, entity_id, exc)

    # ---- Embedding sync ----

    _EMBED_TEXT_MAP: dict[str, list[str]] = {
        "journal": ["content", "summary"],
        "decision": ["question", "rationale"],
        "literature": ["title", "abstract"],
        "mission": ["objective", "context"],
    }

    async def _sync_embedding(self, entity_type: str, entity_id: str, data: dict) -> None:
        """Generate and store embedding for an entity (if embedding service available)."""
        if not self.embeddings:
            return
        text_fields = self._EMBED_TEXT_MAP.get(entity_type, [])
        parts = [str(data.get(f) or "") for f in text_fields if data.get(f)]
        text = " ".join(parts).strip()
        if not text:
            return
        try:
            await self.embeddings.embed_and_store(
                entity_type,
                entity_id,
                text,
                project_id=self.project_id,
            )
        except Exception as exc:
            logger.debug("Embedding sync failed for %s/%s: %s", entity_type, entity_id, exc)

    async def _sync_indexes(self, entity_type: str, entity_id: str, data: dict) -> None:
        """Sync both FTS5 and embedding indexes for an entity."""
        await self._sync_fts(entity_type, entity_id, data)
        await self._sync_embedding(entity_type, entity_id, data)

    # ---- Auto-enrichment ----

    async def _auto_enrich_tags(
        self,
        content: str,
        existing_tags: list[str],
        project_id: str | None = None,
    ) -> list[str] | None:
        """Auto-generate tags via LLM. Returns None if LLM not configured on this service."""
        if not self.llm:
            return None
        resolved_project_id = self._resolve_project_id(project_id)
        # Get existing project tags for reuse hints
        rows = await self.db.fetchall(
            "SELECT DISTINCT tag FROM tags WHERE project_id = ? ORDER BY tag LIMIT 50",
            [resolved_project_id],
        )
        project_tags = [r["tag"] for r in rows]
        return await self.llm.auto_tag(content, project_tags)

    async def add_link(
        self,
        source_type: str,
        source_id: str,
        link_type: str,
        target_type: str,
        target_id: str,
        created_by: str = "system",
        project_id: str | None = None,
    ) -> None:
        """Record a typed edge in entity_links (idempotent — skips duplicates)."""
        link_id = generate_id("link")
        resolved_project_id = self._resolve_project_id(project_id)
        await self.db.execute(
            """INSERT OR IGNORE INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, created_by, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [link_id, source_type, source_id, link_type, target_type, target_id, created_by, resolved_project_id],
        )
        await self.db.commit()

    async def _auto_link(
        self,
        content: str,
        current_type: str,
        project_id: str | None = None,
    ):
        """Infer entity links for a new entry using the LLM.

        Fetches recent decisions, literature, and missions as candidates,
        then asks the LLM to identify which are related to this entry.
        Returns a SemanticLinks object or None if LLM not configured.
        """
        if not self.llm:
            return None
        resolved_project_id = self._resolve_project_id(project_id)
        decisions = await self.db.fetchall(
            "SELECT id, question FROM decisions WHERE project_id = ? AND status != 'superseded' ORDER BY created_at DESC LIMIT 30",
            [resolved_project_id],
        )
        literature = await self.db.fetchall(
            "SELECT id, title FROM literature WHERE project_id = ? ORDER BY created_at DESC LIMIT 30",
            [resolved_project_id],
        )
        missions = await self.db.fetchall(
            "SELECT id, objective FROM missions WHERE project_id = ? AND status != 'cancelled' ORDER BY created_at DESC LIMIT 20",
            [resolved_project_id],
        )
        return await self.llm.semantic_link(
            content=content,
            current_type=current_type,
            decisions=[dict(r) for r in decisions],
            literature=[dict(r) for r in literature],
            missions=[dict(r) for r in missions],
        )

    async def _auto_summarize(self, content: str) -> str | None:
        """Generate a one-line summary via LLM. Returns None if LLM not configured."""
        if not self.llm:
            return None
        return await self.llm.summarize_entry(content)

    # ---- JSON helpers ----

    @staticmethod
    def _json_dumps(obj) -> str | None:
        """Serialize to JSON string, or None if obj is None."""
        if obj is None:
            return None
        return json.dumps(obj, default=str)

    @staticmethod
    def _json_loads(s: str | None, default=None):
        """Parse JSON string, or return default if None/empty."""
        if not s:
            return default
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return default
