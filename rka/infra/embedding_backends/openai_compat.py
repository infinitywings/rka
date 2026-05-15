"""OpenAI-compatible HTTP embedding backend.

Talks to any service that implements OpenAI's `/v1/embeddings` shape:

  - OpenAI API itself (api.openai.com)
  - LM Studio (`host.docker.internal:1234`)
  - vLLM with `--api-key` option
  - Together AI (`api.together.xyz`)
  - Anthropic-via-OpenAI-shim deployments
  - Custom OpenAI-compat proxies

Request shape:
  POST {base_url}/v1/embeddings
  {"input": ["text1", "text2", ...], "model": "<model>"}

Response shape:
  {"data": [{"embedding": [...], "index": 0}, ...], "model": "...", ...}

`api_key` is optional — LM Studio + several proxies don't require one.
When set, it's sent as `Authorization: Bearer <api_key>`.

Retry policy: per rehearsal observation #5, exponential backoff on 429
and 5xx (3 attempts; 0.5s, 1s, 2s). 4xx other than 429 surfaces as a
hard error (likely a config mistake).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from rka.infra.embedding_backends.base import (
    ConnectionTestResult,
    EmbeddingConfigError,
    reconcile_dim,
)

logger = logging.getLogger(__name__)

_RETRY_SLEEPS_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)


class OpenAICompatBackend:
    """OpenAI `/v1/embeddings` HTTP client."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        dim: int | None = None,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("openai_compat backend requires base_url")
        if not model:
            raise ValueError("openai_compat backend requires model")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key or None  # treat empty string as missing
        # dim is "expected" — the backend trusts the config until the
        # first real call detects a different length.
        self._dim: int = dim or 0
        self._timeout = timeout_seconds
        self._http = http_client

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def _post_embeddings(self, inputs: list[str]) -> list[list[float]]:
        body = {"input": inputs, "model": self._model}
        url = f"{self._base_url}/v1/embeddings"
        client = self._client()
        last_exc: Exception | None = None
        for attempt, sleep_s in enumerate(_RETRY_SLEEPS_SECONDS, start=1):
            try:
                resp = await client.post(url, json=body, headers=self._headers())
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "openai_compat embed attempt %d/%d failed: %s",
                    attempt,
                    len(_RETRY_SLEEPS_SECONDS),
                    exc,
                )
                if attempt == len(_RETRY_SLEEPS_SECONDS):
                    raise
                await asyncio.sleep(sleep_s)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "openai_compat embed HTTP %d on attempt %d/%d",
                    resp.status_code,
                    attempt,
                    len(_RETRY_SLEEPS_SECONDS),
                )
                if attempt == len(_RETRY_SLEEPS_SECONDS):
                    resp.raise_for_status()
                await asyncio.sleep(sleep_s)
                continue
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data") or []
            vecs = [item["embedding"] for item in data]
            if vecs:
                # T2.5 calibration: drift-check rather than silent mutate.
                # `reconcile_dim` returns the new self._dim (or raises on
                # drift when self._dim was already non-zero).
                self._dim = reconcile_dim(self._dim, len(vecs[0]))
            return vecs
        # unreachable — every loop branch either returns or raises
        if last_exc:
            raise last_exc
        raise RuntimeError("openai_compat embed: exhausted retries")

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:  # noqa: ARG002
        out = await self._post_embeddings([text])
        return out[0]

    async def embed_batch(
        self, texts: list[str], *, is_query: bool = False  # noqa: ARG002
    ) -> list[list[float]]:
        if not texts:
            return []
        return await self._post_embeddings(list(texts))

    async def test_connection(self) -> ConnectionTestResult:
        t0 = time.perf_counter()
        try:
            vec = await self.embed("rka test", is_query=True)
        except httpx.ConnectError as exc:
            return ConnectionTestResult(
                ok=False, detail=f"connection refused to {self._base_url}: {exc!s}"
            )
        except httpx.HTTPStatusError as exc:
            return ConnectionTestResult(
                ok=False,
                detail=(
                    f"HTTP {exc.response.status_code} from {self._base_url}: "
                    f"{exc.response.text[:200]}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(ok=False, detail=f"unexpected error: {exc!s}")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ConnectionTestResult(
            ok=True,
            detail=f"reached {self._base_url}; model={self._model}; dim={len(vec)}",
            detected_dim=len(vec),
            latency_ms=elapsed_ms,
        )
