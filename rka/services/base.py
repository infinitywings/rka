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
    ):
        self.db = db
        self.llm = llm
        self.embeddings = embeddings

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
    ) -> str:
        """Record a cross-entity event for the exploration timeline."""
        event_id = generate_id("event")
        await self.db.execute(
            """INSERT INTO events
               (id, event_type, entity_type, entity_id, actor, summary,
                caused_by_event, caused_by_entity, phase, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id, event_type, entity_type, entity_id,
                actor, summary, caused_by_event, caused_by_entity,
                phase, json.dumps(details) if details else None,
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
    ) -> None:
        """Record an audit log entry."""
        await self.db.execute(
            """INSERT INTO audit_log (action, entity_type, entity_id, actor, details)
               VALUES (?, ?, ?, ?, ?)""",
            [action, entity_type, entity_id, actor, json.dumps(details) if details else None],
        )
        await self.db.commit()

    async def _get_tags(self, entity_type: str, entity_id: str) -> list[str]:
        """Get all tags for an entity."""
        rows = await self.db.fetchall(
            "SELECT tag FROM tags WHERE entity_type = ? AND entity_id = ?",
            [entity_type, entity_id],
        )
        return [row["tag"] for row in rows]

    async def _set_tags(self, entity_type: str, entity_id: str, tags: list[str]) -> None:
        """Replace all tags for an entity."""
        await self.db.execute(
            "DELETE FROM tags WHERE entity_type = ? AND entity_id = ?",
            [entity_type, entity_id],
        )
        for tag in tags:
            await self.db.execute(
                "INSERT OR IGNORE INTO tags (tag, entity_type, entity_id) VALUES (?, ?, ?)",
                [tag.lower().strip(), entity_type, entity_id],
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
            await self.embeddings.embed_and_store(entity_type, entity_id, text)
        except Exception as exc:
            logger.debug("Embedding sync failed for %s/%s: %s", entity_type, entity_id, exc)

    async def _sync_indexes(self, entity_type: str, entity_id: str, data: dict) -> None:
        """Sync both FTS5 and embedding indexes for an entity."""
        await self._sync_fts(entity_type, entity_id, data)
        await self._sync_embedding(entity_type, entity_id, data)

    # ---- Auto-enrichment ----

    async def _auto_enrich_tags(self, content: str, existing_tags: list[str]) -> list[str] | None:
        """Auto-generate tags via LLM. Returns None if LLM not configured on this service."""
        if not self.llm:
            return None
        # Get existing project tags for reuse hints
        rows = await self.db.fetchall(
            "SELECT DISTINCT tag FROM tags ORDER BY tag LIMIT 50"
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
    ) -> None:
        """Record a typed edge in entity_links (idempotent — skips duplicates)."""
        link_id = generate_id("link")
        await self.db.execute(
            """INSERT OR IGNORE INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [link_id, source_type, source_id, link_type, target_type, target_id, created_by],
        )
        await self.db.commit()

    async def _auto_link(self, content: str, current_type: str):
        """Infer entity links for a new entry using the LLM.

        Fetches recent decisions, literature, and missions as candidates,
        then asks the LLM to identify which are related to this entry.
        Returns a SemanticLinks object or None if LLM not configured.
        """
        if not self.llm:
            return None
        decisions = await self.db.fetchall(
            "SELECT id, question FROM decisions WHERE status != 'superseded' ORDER BY created_at DESC LIMIT 30"
        )
        literature = await self.db.fetchall(
            "SELECT id, title FROM literature ORDER BY created_at DESC LIMIT 30"
        )
        missions = await self.db.fetchall(
            "SELECT id, objective FROM missions WHERE status != 'cancelled' ORDER BY created_at DESC LIMIT 20"
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
