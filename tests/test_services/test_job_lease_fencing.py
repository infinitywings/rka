"""Attempt-level ownership tests for the durable worker queue."""

from __future__ import annotations

import pytest

from rka.services.jobs import JobLeaseLost, JobQueue


@pytest.mark.asyncio
async def test_dedupe_key_is_scoped_by_project_and_job_type(db) -> None:
    queue = JobQueue(db)
    first = await queue.enqueue(
        "mission_embed",
        dedupe_key="shared-logical-key",
    )
    second = await queue.enqueue(
        "note_embed",
        dedupe_key="shared-logical-key",
    )
    assert first != second


@pytest.mark.asyncio
async def test_stale_worker_cannot_complete_a_reclaimed_job(db) -> None:
    queue = JobQueue(db, lease_seconds=60)
    job_id = await queue.enqueue(
        "mission_embed",
        entity_type="mission",
        entity_id="mis_fenced",
    )

    first = await queue.claim_next("worker-a")
    assert first is not None
    assert first["id"] == job_id
    assert first["lease_token"]

    await db.execute(
        "UPDATE jobs SET lease_until = '1970-01-01T00:00:00Z' WHERE id = ?",
        [job_id],
    )
    await db.commit()
    with pytest.raises(JobLeaseLost, match="superseded"):
        await queue.complete(first, {"winner": "expired"})

    second = await queue.claim_next("worker-b")
    assert second is not None
    assert second["id"] == job_id
    assert second["lease_token"] != first["lease_token"]

    with pytest.raises(JobLeaseLost, match="superseded"):
        await queue.complete(first, {"winner": "stale"})

    running = await queue.get(job_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["worker_id"] == "worker-b"
    assert running["lease_token"] == second["lease_token"]

    await queue.complete(second, {"winner": "worker-b"})
    completed = await queue.get(job_id)
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["result"] == {"winner": "worker-b"}
    assert completed["lease_token"] is None


@pytest.mark.asyncio
async def test_stale_worker_cannot_requeue_a_reclaimed_job(db) -> None:
    queue = JobQueue(db, lease_seconds=60)
    job_id = await queue.enqueue("mission_embed")
    first = await queue.claim_next("worker-a")
    assert first is not None
    await db.execute(
        "UPDATE jobs SET lease_until = '1970-01-01T00:00:00Z' WHERE id = ?",
        [job_id],
    )
    await db.commit()
    second = await queue.claim_next("worker-b")
    assert second is not None

    with pytest.raises(JobLeaseLost, match="superseded"):
        await queue.fail(first, "stale failure")

    running = await queue.get(job_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["worker_id"] == "worker-b"
