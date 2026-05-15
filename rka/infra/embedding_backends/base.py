"""Embedding-backend Protocol + shared result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ConnectionTestResult:
    """Result of `EmbeddingBackend.test_connection()`.

    `ok` is the headline; `detail` is a one-line human-readable summary.
    `detected_dim` and `latency_ms` are populated when the backend can
    measure them (a successful test embed call returns both).
    """

    ok: bool
    detail: str
    detected_dim: int | None = None
    latency_ms: float | None = None


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Protocol every embedding backend implements.

    Async because all three concrete backends either do I/O (HTTP) or
    blocking work that we wrap with `asyncio.to_thread` (FastEmbed). The
    `is_query` flag lets backends that distinguish query- vs document-
    encoding (Nomic does via the `search_query:` / `search_document:`
    prefix) honor that; HTTP backends typically ignore it.
    """

    @property
    def dim(self) -> int:
        """Embedding dimensionality. Stable for the lifetime of the instance."""
        ...

    @property
    def model_name(self) -> str:
        """Backend-specific model identifier (for logging + provenance)."""
        ...

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        """Embed a single string. Returns a `dim`-length float list."""
        ...

    async def embed_batch(
        self, texts: list[str], *, is_query: bool = False
    ) -> list[list[float]]:
        """Embed many strings. Length-N input → length-N output."""
        ...

    async def test_connection(self) -> ConnectionTestResult:
        """Cheap reachability + dim-detection probe; never persists state."""
        ...
