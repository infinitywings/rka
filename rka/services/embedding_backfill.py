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

    T5 contract:
      - `run_backfill(progress_callback=None)` is async.
      - Default batch_size = 32.
      - Per-claim failures get logged + the claim left with
        embedding_pending=1 so a later run retries.
      - On clean exit, status.state = "complete".
      - On any unhandled exception, status.state = "failed" and
        status.error carries the exception text.
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
        """Skeleton — T5 implements. Marks the job complete-with-zero-work
        so T3's tests can exercise the registry path independently of T5."""
        status.state = "running"
        if progress_callback:
            await _maybe_await(progress_callback(status))
        # T5 fills in the actual claim iteration here.
        status.state = "complete"
        if progress_callback:
            await _maybe_await(progress_callback(status))
        return status


async def _maybe_await(value: Any) -> None:
    """If `value` is awaitable, await it; otherwise no-op."""
    if hasattr(value, "__await__"):
        await value
