"""Embedding generation via FastEmbed (local ONNX inference)."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rka.infra.database import Database

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Local embedding generation via FastEmbed.

    Uses nomic-ai/nomic-embed-text-v1.5 (768-dim) by default.
    The model is downloaded on first use (~130 MB).
    """

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5", db: "Database | None" = None):
        self.model_name = model_name
        self.db = db
        self._model = None
        self._dim: int = 768  # nomic-embed-text-v1.5

    @property
    def dim(self) -> int:
        return self._dim

    def _get_model(self):
        """Lazy-load the embedding model."""
        if self._model is None:
            from fastembed import TextEmbedding
            logger.info("Loading embedding model: %s (first load downloads ~130MB)", self.model_name)
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    async def embed(self, text: str) -> list[float]:
        """Embed a query string. Uses 'search_query:' prefix for nomic."""
        model = self._get_model()
        prefixed = f"search_query: {text}"
        embeddings = list(model.embed([prefixed]))
        return embeddings[0].tolist()

    async def embed_document(self, text: str) -> list[float]:
        """Embed a document for storage. Uses 'search_document:' prefix for nomic."""
        model = self._get_model()
        prefixed = f"search_document: {text}"
        embeddings = list(model.embed([prefixed]))
        return embeddings[0].tolist()

    async def embed_batch(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """Batch embed multiple texts."""
        model = self._get_model()
        prefix = "search_query: " if is_query else "search_document: "
        prefixed = [f"{prefix}{t}" for t in texts]
        embeddings = list(model.embed(prefixed))
        return [e.tolist() for e in embeddings]

    @staticmethod
    def content_hash(text: str) -> str:
        """Hash content to detect changes for re-embedding."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def needs_reembed(self, entity_type: str, entity_id: str, text: str) -> bool:
        """Check if stored embedding is stale (content changed)."""
        if self.db is None:
            return True
        meta = await self.db.fetchone(
            "SELECT content_hash FROM embedding_metadata WHERE entity_type = ? AND entity_id = ?",
            [entity_type, entity_id],
        )
        if meta is None:
            return True
        return meta["content_hash"] != self.content_hash(text)

    async def store_embedding(
        self, entity_type: str, entity_id: str, text: str, embedding: list[float],
    ) -> None:
        """Store embedding in sqlite-vec virtual table and update metadata."""
        if self.db is None:
            return

        table_map = {
            "decision": "vec_decisions",
            "literature": "vec_literature",
            "journal": "vec_journal",
            "mission": "vec_missions",
        }
        table = table_map.get(entity_type)
        if not table:
            return

        # Upsert into vec table (only if sqlite-vec is loaded)
        if self.db.vec_available:
            import struct
            vec_blob = struct.pack(f"{len(embedding)}f", *embedding)
            await self.db.execute(
                f"INSERT OR REPLACE INTO {table} (id, embedding) VALUES (?, ?)",
                [entity_id, vec_blob],
            )

        # Always upsert metadata (tracks what needs embedding, useful for batch re-embed)
        await self.db.execute(
            """INSERT OR REPLACE INTO embedding_metadata
               (entity_type, entity_id, content_hash, model_name, dimensions)
               VALUES (?, ?, ?, ?, ?)""",
            [entity_type, entity_id, self.content_hash(text), self.model_name, self._dim],
        )
        await self.db.commit()

    async def embed_and_store(self, entity_type: str, entity_id: str, text: str) -> None:
        """Convenience: embed text and store result if content changed."""
        if not text.strip():
            return
        if not await self.needs_reembed(entity_type, entity_id, text):
            return
        embedding = await self.embed_document(text)
        await self.store_embedding(entity_type, entity_id, text, embedding)
        logger.debug("Embedded %s/%s (%d chars)", entity_type, entity_id, len(text))
