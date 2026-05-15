"""Embedding-backfill orchestration.

Phase 1 in v2.4.0: **synchronous foreground** job. "Synchronous" per the
Brain T2-gate clarification means: "no Redis/Celery — runs in the API
container process." It does NOT mean PUT blocks for 7-14 minutes — see
`rka/api/routes/config.py:PUT /api/config/embedding`, which kicks off
the backfill via FastAPI BackgroundTask and returns 202 + {job_id,
status_url}.

This module owns the **job-status registry** that T3's REST PUT/status
endpoints use. T5 fills in `BackfillService.run_backfill`.

Status snapshot shape (T3 status endpoint returns this verbatim):

    {
      "job_id":          str,
      "state":           Literal["pending", "running", "complete", "failed"],
      "processed":       int,
      "total":           int,
      "started_at":      ISO-8601 UTC,
      "elapsed_seconds": float,
      "error":           str | None,
    }
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)


JobState = Literal["pending", "running", "complete", "failed"]


def _now_iso_z() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class JobStatus:
    """Per-run snapshot read by the GET status endpoint.

    `started_at` is set when the job is registered; `elapsed_seconds` is
    computed from a monotonic clock so it remains correct across daylight-
    savings + system-clock adjustments.
    """

    job_id: str
    state: JobState
    processed: int = 0
    total: int = 0
    started_at: str = ""
    elapsed_seconds: float = 0.0
    error: str | None = None
    # monotonic timestamp at registration; used to compute elapsed_seconds
    _started_perf: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        """Public-facing dict (excludes the underscored bookkeeping field)."""
        out = asdict(self)
        out.pop("_started_perf", None)
        # Refresh elapsed_seconds at snapshot time so polling reflects reality.
        if self._started_perf > 0:
            out["elapsed_seconds"] = round(time.monotonic() - self._started_perf, 3)
        return out


# ---------------------------------------------------------------------------
# Job registry (module-level; one backfill at a time in v2.4.0)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, JobStatus] = {}


def register_job() -> JobStatus:
    """Create a new pending-state job; return its snapshot to the caller."""
    job_id = f"bf_{uuid.uuid4().hex[:12]}"
    status = JobStatus(
        job_id=job_id,
        state="pending",
        started_at=_now_iso_z(),
        _started_perf=time.monotonic(),
    )
    _REGISTRY[job_id] = status
    logger.info("registered backfill job %s", job_id)
    return status


def get_status(job_id: str) -> JobStatus | None:
    return _REGISTRY.get(job_id)


def latest_status() -> JobStatus | None:
    """Most recent job by insertion order (Python dict preserves it)."""
    if not _REGISTRY:
        return None
    return next(reversed(_REGISTRY.values()))


def clear_registry() -> None:
    """Test-only: wipe the in-memory registry between cases."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# BackfillService skeleton (T5 fills the loop)
# ---------------------------------------------------------------------------


ProgressCallback = Callable[[JobStatus], Awaitable[None] | None]


class BackfillService:
    """Iterates `claims WHERE embedding_pending=1` and re-embeds them.

      - `run_backfill(progress_callback=None)` is async.
      - Default batch_size = 32.
      - Per-claim failures get logged + the claim left with
        embedding_pending=1 so a later run retries.
      - Batch-level failures (embed_batch raised) abort the run with
        status.state = "failed"; remaining claims keep their flag for
        the next attempt.
      - On clean exit, status.state = "complete".
    """

    def __init__(self, *, db: Any, embeddings: Any, batch_size: int = 32) -> None:
        self._db = db
        self._embeddings = embeddings
        self._batch_size = batch_size

    async def run_backfill(
        self,
        status: JobStatus,
        progress_callback: ProgressCallback | None = None,
    ) -> JobStatus:
        """Embed every pending claim in batches.

        Cursor pattern: claims are iterated in `id`-ascending order with a
        `id > last_id` filter so persistent per-claim failures (which keep
        `embedding_pending=1`) don't trigger an infinite loop on re-fetch.

        Wall-clock target per mission spec: ~0.5–1s per claim with
        LM Studio qwen3-8b; 827 claims ≈ 7–14 min.
        """
        import struct

        status.state = "running"

        # Step 1: count pending claims (status.total snapshot for the polling UI).
        row = await self._db.fetchone(
            "SELECT COUNT(*) AS n FROM claims WHERE embedding_pending = 1"
        )
        status.total = int((row or {}).get("n") or 0)
        await _emit_progress(progress_callback, status)

        if status.total == 0:
            status.state = "complete"
            await _emit_progress(progress_callback, status)
            return status

        # Step 2: cursor-paginate through pending claims.
        last_id = ""
        vec_available = bool(getattr(self._db, "vec_available", False))

        while True:
            rows = await self._db.fetchall(
                "SELECT id, content FROM claims "
                "WHERE embedding_pending = 1 AND id > ? "
                "ORDER BY id LIMIT ?",
                [last_id, self._batch_size],
            )
            if not rows:
                break

            ids = [r["id"] for r in rows]
            texts = [r["content"] for r in rows]
            last_id = rows[-1]["id"]

            # Step 3: embed the batch. Batch-level failure → mark failed + exit.
            try:
                vectors = await self._embeddings.embed_batch(texts, is_query=False)
            except Exception as exc:  # noqa: BLE001
                status.state = "failed"
                status.error = f"batch embed failed (cursor at {last_id}): {exc!s}"
                logger.exception("backfill batch embed failed at cursor %s", last_id)
                await _emit_progress(progress_callback, status)
                return status

            # Step 4: write vec_claims rows + clear the per-claim flag.
            for claim_id, vec in zip(ids, vectors):
                try:
                    if vec_available:
                        vec_blob = struct.pack(f"{len(vec)}f", *vec)
                        await self._db.execute(
                            "INSERT OR REPLACE INTO vec_claims (id, embedding) VALUES (?, ?)",
                            [claim_id, vec_blob],
                        )
                    await self._db.execute(
                        "UPDATE claims SET embedding_pending = 0 WHERE id = ?",
                        [claim_id],
                    )
                    status.processed += 1
                except Exception as exc:  # noqa: BLE001
                    # Per-claim failure: leave the flag set, log, continue.
                    logger.warning(
                        "claim %s vec-write failed (flag stays set for retry): %s",
                        claim_id,
                        exc,
                    )

            await self._db.commit()
            await _emit_progress(progress_callback, status)

        status.state = "complete"
        await _emit_progress(progress_callback, status)
        return status


async def _emit_progress(
    cb: ProgressCallback | None, status: JobStatus
) -> None:
    """Fire the optional progress callback, awaiting if it returns a coroutine."""
    if cb is None:
        return
    await _maybe_await(cb(status))


async def _maybe_await(value: Any) -> None:
    """If `value` is awaitable, await it; otherwise no-op."""
    if hasattr(value, "__await__"):
        await value
