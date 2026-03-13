"""Durable DB-backed job queue for asynchronous enrichment work."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from rka.infra.database import Database
from rka.infra.ids import generate_id
from rka.services.base import DEFAULT_PROJECT_ID, _now

logger = logging.getLogger(__name__)


def _after_seconds(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobQueue:
    """Simple durable queue stored in SQLite."""

    def __init__(
        self,
        db: Database,
        *,
        lease_seconds: int = 300,
        default_max_attempts: int = 5,
    ):
        self.db = db
        self.lease_seconds = lease_seconds
        self.default_max_attempts = default_max_attempts

    async def enqueue(
        self,
        job_type: str,
        *,
        project_id: str = DEFAULT_PROJECT_ID,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        priority: int = 100,
        max_attempts: int | None = None,
        run_after: str | None = None,
    ) -> str:
        """Enqueue a job and coalesce with an existing active job when dedupe_key matches."""
        job_id = generate_id("job")
        now = _now()
        await self.db.execute(
            """INSERT OR IGNORE INTO jobs
               (id, job_type, project_id, entity_type, entity_id, payload, status,
                attempts, max_attempts, priority, run_after, dedupe_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?, ?)""",
            [
                job_id,
                job_type,
                project_id,
                entity_type,
                entity_id,
                json.dumps(payload) if payload is not None else None,
                max_attempts or self.default_max_attempts,
                priority,
                run_after or now,
                dedupe_key,
                now,
                now,
            ],
        )
        await self.db.commit()

        if dedupe_key:
            row = await self.db.fetchone(
                """SELECT id
                   FROM jobs
                   WHERE dedupe_key = ? AND status IN ('pending', 'running')
                   ORDER BY created_at DESC
                   LIMIT 1""",
                [dedupe_key],
            )
            if row:
                return row["id"]

        return job_id

    async def claim_next(self, worker_id: str) -> dict[str, Any] | None:
        """Claim the next runnable job."""
        now = _now()
        lease_until = _after_seconds(self.lease_seconds)
        candidates = await self.db.fetchall(
            """SELECT id
               FROM jobs
               WHERE
                   (status = 'pending' AND run_after <= ?)
                   OR (status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?)
               ORDER BY priority ASC, created_at ASC
               LIMIT 10""",
            [now, now],
        )
        for candidate in candidates:
            cursor = await self.db.execute(
                """UPDATE jobs
                   SET status = 'running',
                       attempts = attempts + 1,
                       worker_id = ?,
                       lease_until = ?,
                       updated_at = ?,
                       last_error = NULL
                   WHERE id = ?
                     AND (
                        (status = 'pending' AND run_after <= ?)
                        OR (status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?)
                     )""",
                [worker_id, lease_until, now, candidate["id"], now, now],
            )
            await self.db.commit()
            if cursor.rowcount != 1:
                continue
            row = await self.db.fetchone("SELECT * FROM jobs WHERE id = ?", [candidate["id"]])
            if row:
                return self._decode_row(row)
        return None

    async def complete(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        now = _now()
        await self.db.execute(
            """UPDATE jobs
               SET status = 'completed',
                   lease_until = NULL,
                   worker_id = NULL,
                   result = ?,
                   updated_at = ?,
                   completed_at = ?
               WHERE id = ?""",
            [json.dumps(result) if result is not None else None, now, now, job_id],
        )
        await self.db.commit()

    async def fail(self, job: dict[str, Any], error: str) -> None:
        """Requeue with backoff, or mark failed after max_attempts."""
        attempts = int(job.get("attempts") or 0)
        max_attempts = int(job.get("max_attempts") or self.default_max_attempts)
        now = _now()
        terminal = attempts >= max_attempts
        status = "failed" if terminal else "pending"
        run_after = _after_seconds(self._backoff_seconds(attempts)) if not terminal else now
        await self.db.execute(
            """UPDATE jobs
               SET status = ?,
                   run_after = ?,
                   lease_until = NULL,
                   worker_id = NULL,
                   last_error = ?,
                   updated_at = ?,
                   completed_at = CASE WHEN ? = 'failed' THEN ? ELSE completed_at END
               WHERE id = ?""",
            [status, run_after, error[:1000], now, status, now, job["id"]],
        )
        await self.db.commit()

    @staticmethod
    def _backoff_seconds(attempt: int) -> int:
        return min(300, 15 * (2 ** max(0, attempt - 1)))

    @staticmethod
    def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload")
        result = row.get("result")
        row["payload"] = json.loads(payload) if payload else None
        row["result"] = json.loads(result) if result else None
        return row
