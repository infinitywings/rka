"""Core 3.0 compatibility for historical reference-validation jobs."""

from __future__ import annotations

import pytest

from rka.models.manuscript_native import ManuscriptCreate
from rka.services.jobs import JobQueue
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.reference_validation import ReferenceValidationService
from rka.services.worker import EnrichmentWorker


PROJECT_ID = "proj_default"


async def _manuscript(db, title: str):
    return await NativeManuscriptService(db, project_id=PROJECT_ID).create(
        ManuscriptCreate(title=title, venue="USENIX")
    )


async def _legacy_job(db, manuscript_id: str, *, requested_id: str | None = None):
    return await JobQueue(db).enqueue(
        "reference_validate",
        project_id=PROJECT_ID,
        entity_type="manuscript",
        entity_id=manuscript_id,
        payload={"requested_manuscript_id": requested_id or manuscript_id},
        max_attempts=3,
    )


@pytest.mark.asyncio
async def test_historical_job_status_remains_project_and_manuscript_scoped(db) -> None:
    first = await _manuscript(db, "First")
    second = await _manuscript(db, "Second")
    job_id = await _legacy_job(db, first.id)
    service = ReferenceValidationService(db, project_id=PROJECT_ID)

    status = await service.get_status(first.id, job_id)
    assert status is not None
    assert status["job_id"] == job_id
    assert status["status"] == "pending"
    assert status["canonical_manuscript_id"] == first.id
    assert status["requested_manuscript_id"] == first.id
    assert await service.get_status(second.id, job_id) is None
    assert await ReferenceValidationService(
        db, project_id="proj_other"
    ).get_status(first.id, job_id) is None


@pytest.mark.asyncio
async def test_worker_drains_pre_split_job_without_running_writer(db) -> None:
    manuscript = await _manuscript(db, "Drain")
    job_id = await _legacy_job(db, manuscript.id)

    worker = EnrichmentWorker(
        db=db,
        embeddings=None,
        worker_id="core-3-migration-worker",
    )
    assert await worker.run_once() is True

    status = await ReferenceValidationService(
        db, project_id=PROJECT_ID
    ).get_status(manuscript.id, job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert status["result"] == {
        "outcome": "skipped",
        "reason": "writer_runtime_moved",
    }
    assert await db.fetchone(
        "SELECT id FROM reference_validation_attestations WHERE validation_job_id = ?",
        [job_id],
    ) is None
