"""Local FastEmbed backend (extracted from the historical
`rka/infra/embeddings.py:EmbeddingService`).

Preserves the prior production semantics exactly:

  - `nomic-ai/nomic-embed-text-v1.5` default model (768-dim)
  - `search_query: ` / `search_document: ` prefixes on Nomic-family models
  - first-use download (~130 MB) is performed lazily inside the model
    accessor; the FastEmbed library handles caching
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from rka.infra.embedding_backends.base import ConnectionTestResult

logger = logging.getLogger(__name__)


_NOMIC_PREFIX_MODELS = ("nomic-ai/nomic-embed-text",)


def _needs_nomic_prefix(model_name: str) -> bool:
    return any(model_name.startswith(p) for p in _NOMIC_PREFIX_MODELS)


class FastEmbedBackend:
    """In-process ONNX inference via the `fastembed` package."""

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5") -> None:
        self._model_name = model_name
        self._model: Any = None
        # nomic-768 is the default; backend-detected dim overrides on first embed.
        self._dim: int = 768
        self._uses_prefix = _needs_nomic_prefix(model_name)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            logger.info(
                "Loading FastEmbed model: %s (first load downloads ~130MB)",
                self._model_name,
            )
            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def _prefix(self, text: str, *, is_query: bool) -> str:
        if not self._uses_prefix:
            return text
        marker = "search_query: " if is_query else "search_document: "
        return f"{marker}{text}"

    def _sync_embed(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        model = self._get_model()
        prefixed = [self._prefix(t, is_query=is_query) for t in texts]
        result = [v.tolist() for v in model.embed(prefixed)]
        if result and len(result[0]) != self._dim:
            # Detected dimensionality differs from default (e.g. user
            # picked a different nomic variant). Sync the field so the
            # config layer can see it via `dim`.
            self._dim = len(result[0])
        return result

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        out = await asyncio.to_thread(self._sync_embed, [text], is_query=is_query)
        return out[0]

    async def embed_batch(
        self, texts: list[str], *, is_query: bool = False
    ) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._sync_embed, list(texts), is_query=is_query)

    async def test_connection(self) -> ConnectionTestResult:
        # FastEmbed runs in-process; "test" means: can we load the model
        # + run a single embed?
        t0 = time.perf_counter()
        try:
            vec = await self.embed("rka test", is_query=True)
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(
                ok=False,
                detail=f"fastembed load/inference failed: {exc!s}",
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ConnectionTestResult(
            ok=True,
            detail=f"fastembed model {self._model_name} ready (dim={len(vec)})",
            detected_dim=len(vec),
            latency_ms=elapsed_ms,
        )
