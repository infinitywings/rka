"""qwen3-embedding-8b-dwq client via LM Studio's OpenAI-compatible API.

Mission `mis_01KRKJ9G20EM5XMA147JTKQCFF` Option C (ratified per
`jrn_01KRKQHGS9G3ZRA8Z1ZWG6RGXQ`): eval-harness-direct integration —
the hybrid configurations call qwen3 LM Studio endpoint directly,
bypassing RKA's EmbeddingService. This file is the local client.

LM Studio exposes an OpenAI-compatible `/v1/embeddings` endpoint at
`http://192.168.86.24:1234` (PI's reachable URL) — or
`http://host.docker.internal:1234` when run from inside the RKA
Docker container.

The reachability probe at T3 pre-flight (observation #2,
reachability-first) verifies the endpoint responds BEFORE the
backfill kicks off. Failure → immediate checkpoint, no retry-loop.

API design:

  - `EmbeddingClient(base_url, model)` — config + state
  - `client.probe()` — pre-flight reachability check returning a small
    diagnostic dict (status, latency_ms, model echo, vector_dim)
  - `client.embed(text)` — single embedding, returns list[float]
  - `client.embed_batch(texts)` — batch embedding, returns list[list[float]]

Bounded retry on transient errors (observation #5): up to 3 attempts
with 10s/30s/90s backoff. Persistent failures raise
`EmbeddingError` for the caller to surface as a checkpoint per the
retry-then-checkpoint discipline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import httpx


DEFAULT_BASE_URL = "http://192.168.86.24:1234"
DEFAULT_MODEL = "qwen3-embedding-8b-dwq"
DEFAULT_TIMEOUT = 30.0
RETRY_BACKOFFS = (10.0, 30.0, 90.0)


class EmbeddingError(RuntimeError):
    """Raised when LM Studio cannot fulfill a request after bounded retries.

    Callers should surface this as a checkpoint per observation #5
    (retry-then-checkpoint discipline), NOT retry-loop further.
    """


@dataclass
class ProbeResult:
    """Lightweight diagnostic from `EmbeddingClient.probe()`."""

    reachable: bool
    base_url: str
    model: str
    latency_ms: float | None
    vector_dim: int | None
    error: str | None = None

    def __str__(self) -> str:
        if self.reachable:
            return (
                f"✓ LM Studio reachable at {self.base_url} · "
                f"model={self.model} · dim={self.vector_dim} · "
                f"latency={self.latency_ms:.0f} ms"
            )
        return f"✗ LM Studio unreachable at {self.base_url}: {self.error}"


class EmbeddingClient:
    """Synchronous OpenAI-compat embeddings client for LM Studio."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EmbeddingClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def probe(self) -> ProbeResult:
        """Reachability check used at T3 pre-flight (observation #2).

        Performs one short embedding request and reports outcome. NEVER
        retries — infra failures must be visible immediately per the
        retry-then-checkpoint discipline.
        """
        start = time.perf_counter()
        try:
            vector = self._embed_once("ping")
            latency_ms = (time.perf_counter() - start) * 1000.0
            return ProbeResult(
                reachable=True,
                base_url=self.base_url,
                model=self.model,
                latency_ms=latency_ms,
                vector_dim=len(vector),
            )
        except Exception as e:
            return ProbeResult(
                reachable=False,
                base_url=self.base_url,
                model=self.model,
                latency_ms=None,
                vector_dim=None,
                error=str(e),
            )

    def embed(self, text: str) -> list[float]:
        """Embed a single string with bounded retry."""
        return self._with_retry(lambda: self._embed_once(text))

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of strings with bounded retry.

        LM Studio's `/v1/embeddings` accepts a list `input` — single
        round-trip per batch. Empty input returns []."""
        if not texts:
            return []
        return self._with_retry(lambda: self._embed_batch_once(list(texts)))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _embed_once(self, text: str) -> list[float]:
        response = self._client.post(
            "/v1/embeddings",
            json={"model": self.model, "input": text},
        )
        response.raise_for_status()
        payload = response.json()
        return _extract_first_vector(payload)

    def _embed_batch_once(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            "/v1/embeddings",
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()
        return _extract_vectors(payload, expected_count=len(texts))

    def _with_retry(self, fn):
        """Up to 3 attempts with 10s/30s/90s backoff per observation #5."""
        last_error: Exception | None = None
        for attempt, backoff in enumerate(RETRY_BACKOFFS, start=1):
            try:
                return fn()
            except (httpx.HTTPError, ValueError) as e:
                last_error = e
                if attempt < len(RETRY_BACKOFFS):
                    time.sleep(backoff)
                    continue
                raise EmbeddingError(
                    f"qwen3 embedding failed after {len(RETRY_BACKOFFS)} attempts: {e}"
                ) from e
        raise EmbeddingError(f"unreachable retry-loop exit: {last_error}")


# ---------------------------------------------------------------------------
# Response parsing — separated for testability against fixture payloads
# ---------------------------------------------------------------------------


def _extract_first_vector(payload: dict) -> list[float]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError(f"unexpected embeddings payload shape: {payload}")
    first = data[0]
    vector = first.get("embedding") if isinstance(first, dict) else None
    if not isinstance(vector, list) or not vector:
        raise ValueError(f"missing embedding in payload[0]: {first}")
    return [float(x) for x in vector]


def _extract_vectors(payload: dict, expected_count: int) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError(f"unexpected embeddings payload shape: {payload}")
    if len(data) != expected_count:
        raise ValueError(
            f"expected {expected_count} embeddings, got {len(data)} in {payload}"
        )
    out: list[list[float]] = []
    for i, item in enumerate(sorted(data, key=lambda d: d.get("index", 0))):
        vector = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(vector, list) or not vector:
            raise ValueError(f"missing embedding in payload[{i}]: {item}")
        out.append([float(x) for x in vector])
    return out


# ---------------------------------------------------------------------------
# CLI — pre-flight probe used at T3 (`python -m eval_harness.embedder probe`)
# ---------------------------------------------------------------------------


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="qwen3 LM Studio embedding client (eval-harness Option C).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    probe = sub.add_parser("probe", help="Reachability probe (T3 pre-flight)")
    probe.add_argument("--base-url", default=DEFAULT_BASE_URL)
    probe.add_argument("--model", default=DEFAULT_MODEL)
    probe.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)

    embed = sub.add_parser("embed", help="One-off single-string embed")
    embed.add_argument("--base-url", default=DEFAULT_BASE_URL)
    embed.add_argument("--model", default=DEFAULT_MODEL)
    embed.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    embed.add_argument("text", help="The string to embed")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    client = EmbeddingClient(
        base_url=args.base_url, model=args.model, timeout=args.timeout
    )
    try:
        if args.cmd == "probe":
            result = client.probe()
            print(result)
            return 0 if result.reachable else 2
        if args.cmd == "embed":
            vector = client.embed(args.text)
            print(f"dim={len(vector)} · head={vector[:8]}")
            return 0
    finally:
        client.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
