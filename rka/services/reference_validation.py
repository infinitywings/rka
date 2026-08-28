"""Read-only access to historical reference-validation jobs.

Reference-validation initiation and execution were removed from Core 3.0.
External Writer or client workflows may verify separately. Core keeps this
narrow reader so projects can inspect durable jobs created before the split.
"""

from __future__ import annotations

from typing import Any

from rka.services.base import BaseService
from rka.services.jobs import JobQueue
from rka.services.manuscript_native import NativeManuscriptService

REFERENCE_VALIDATE_JOB = "reference_validate"


class ReferenceValidationService(BaseService):
    """Expose project-scoped status for pre-split validation jobs."""

    async def get_status(
        self,
        manuscript_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        """Read one historical job after enforcing manuscript scope."""
        if (
            not isinstance(manuscript_id, str)
            or not manuscript_id
            or len(manuscript_id) > 128
            or not isinstance(job_id, str)
            or not job_id
            or len(job_id) > 128
        ):
            return None

        native = NativeManuscriptService(self.db, project_id=self.project_id)
        canonical_id = await native.resolve_id(manuscript_id)
        if canonical_id is None:
            return None

        job = await JobQueue(self.db).get(job_id, project_id=self.project_id)
        if (
            job is None
            or job["job_type"] != REFERENCE_VALIDATE_JOB
            or job.get("entity_type") != "manuscript"
            or job.get("entity_id") != canonical_id
        ):
            return None

        payload = job.get("payload") or {}
        response: dict[str, Any] = {
            "job_id": job["id"],
            "status": job["status"],
            "canonical_manuscript_id": canonical_id,
            "requested_manuscript_id": payload.get("requested_manuscript_id"),
            "attempts": int(job.get("attempts") or 0),
            "max_attempts": int(job.get("max_attempts") or 0),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "completed_at": job.get("completed_at"),
        }
        if job["status"] == "completed":
            response["result"] = job.get("result")
        elif job["status"] == "failed":
            response["error"] = job.get("last_error")
        return response
