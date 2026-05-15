"""Embedding generation — pluggable backends via `embedding_backends/`.

Public surface (`EmbeddingService`) is preserved for every existing
caller. Internally, the work is delegated to a swappable
`EmbeddingBackend` (FastEmbed local, OpenAI-compat HTTP, or Ollama HTTP)
selected at construction time. Mission D (`feat/v2.4-pluggable-embeddings`)
introduces this seam; the factory lives in `embedding_backends/__init__.py`.

Construction modes:

  - `EmbeddingService(model_name="...")` — legacy FastEmbed-only path,
    preserved for tests + boot code that haven't been migrated yet.
  - `EmbeddingService.from_config({"backend": "...", "config": {...}})` —
    new path used by application startup once T2's
    `EmbeddingConfigService` lands.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from rka.infra.embedding_backends import EmbeddingBackend, make_backend

if TYPE_CHECKING:
    from rka.infra.database import Database

logger = logging.getLogger(__name__)


class EmbeddingService:
    """High-level embedding facade.

    The actual embed calls are dispatched to a backend that satisfies the
    `EmbeddingBackend` Protocol. The legacy positional / keyword arg
    construction defaults to FastEmbed to preserve historical behavior;
    new callers should prefer `EmbeddingService.from_config(...)`.
    """

    def __init__(
        self,
        model_name: str = "nomic-ai/nomic-embed-text-v1.5",
        db: "Database | None" = None,
        *,
        backend: EmbeddingBackend | None = None,
    ) -> None:
        self.db = db
        if backend is not None:
            self._backend: EmbeddingBackend = backend
            self.model_name = backend.model_name
        else:
            self._backend = make_backend(
                {"backend": "fastembed", "config": {"model_name": model_name}}
            )
            self.model_name = model_name

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls, config: dict[str, Any], db: "Database | None" = None
    ) -> "EmbeddingService":
        """Build a service from a `/data/embedding_config.json`-shaped dict."""
        backend = make_backend(config)
        return cls(model_name=backend.model_name, db=db, backend=backend)

    # ------------------------------------------------------------------
    # Public surface — preserved from the pre-T1 EmbeddingService
    # ------------------------------------------------------------------

    @property
    def dim(self) -> int:
        return self._backend.dim

    @property
    def backend(self) -> EmbeddingBackend:
        return self._backend

    async def embed(self, text: str) -> list[float]:
        """Embed a query string."""
        return await self._backend.embed(text, is_query=True)

    async def embed_document(self, text: str) -> list[float]:
        """Embed a document for storage."""
        return await self._backend.embed(text, is_query=False)

    async def embed_batch(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        """Batch embed multiple texts."""
        return await self._backend.embed_batch(texts, is_query=is_query)

    @staticmethod
    def content_hash(content: str | bytes) -> str:
        """Hash content to detect changes for re-embedding."""
        if isinstance(content, bytes):
            raw = content
        else:
            raw = content.encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    async def needs_reembed(
        self,
        entity_type: str,
        entity_id: str,
        text: str,
        project_id: str = "proj_default",
    ) -> bool:
        """Check if stored embedding is stale (content changed)."""
        if self.db is None:
            return True
        meta = await self.db.fetchone(
            """SELECT content_hash
               FROM embedding_metadata
               WHERE project_id = ? AND entity_type = ? AND entity_id = ?""",
            [project_id, entity_type, entity_id],
        )
        if meta is None:
            return True
        return meta["content_hash"] != self.content_hash(text)

    async def store_embedding(
        self,
        entity_type: str,
        entity_id: str,
        text: str,
        embedding: list[float] | None = None,
        project_id: str = "proj_default",
    ) -> None:
        """Store embedding in sqlite-vec virtual table and update metadata."""
        if self.db is None:
            return

        table_map = {
            "decision": "vec_decisions",
            "literature": "vec_literature",
            "journal": "vec_journal",
            "mission": "vec_missions",
            "claim": "vec_claims",
            "artifact": "vec_artifacts",
            "figure": "vec_artifacts",
        }
        table = table_map.get(entity_type)
        if embedding is None:
            embedding = await self.embed_document(text)

        if self.db.vec_available and table:
            import struct

            vec_blob = struct.pack(f"{len(embedding)}f", *embedding)
            await self.db.execute(
                f"INSERT OR REPLACE INTO {table} (id, embedding) VALUES (?, ?)",
                [entity_id, vec_blob],
            )

        await self.db.execute(
            """INSERT OR REPLACE INTO embedding_metadata
               (project_id, entity_type, entity_id, content_hash, model_name, dimensions)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                project_id,
                entity_type,
                entity_id,
                self.content_hash(text),
                self.model_name,
                self._backend.dim,
            ],
        )
        await self.db.commit()

    async def embed_and_store(
        self,
        entity_type: str,
        entity_id: str,
        text: str,
        project_id: str = "proj_default",
    ) -> None:
        """Convenience: embed text and store result if content changed."""
        if not text.strip():
            return
        if not await self.needs_reembed(entity_type, entity_id, text, project_id=project_id):
            return
        await self.store_embedding(entity_type, entity_id, text, project_id=project_id)
        logger.debug("Embedded %s/%s (%d chars)", entity_type, entity_id, len(text))
