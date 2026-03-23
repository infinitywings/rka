"""Background worker for asynchronous enrichment jobs.

Only processes embedding jobs. LLM-dependent enrichment (auto-tag, auto-link,
auto-summarize, claim extraction, verification, theme synthesis, contradiction
checks) has been removed — those tasks are now handled by the Brain during
maintenance sessions.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any

from rka.infra.database import Database
from rka.services.jobs import JobQueue

logger = logging.getLogger(__name__)


class EnrichmentWorker:
    """Polls the durable queue and processes embedding jobs."""

    def __init__(
        self,
        *,
        db: Database,
        embeddings=None,
        poll_interval: float = 1.0,
        lease_seconds: int = 300,
        max_attempts: int = 5,
        worker_id: str | None = None,
    ):
        self.db = db
        self.embeddings = embeddings
        self.poll_interval = poll_interval
        self.queue = JobQueue(db, lease_seconds=lease_seconds, default_max_attempts=max_attempts)
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"

    async def run_once(self) -> bool:
        """Process one job if available."""
        job = await self.queue.claim_next(self.worker_id)
        if job is None:
            return False

        try:
            result = await self._process_job(job)
        except Exception as exc:  # pragma: no cover - failure path tested via queue state
            logger.exception("Worker job %s failed", job["id"])
            await self.queue.fail(job, str(exc))
            return True

        await self.queue.complete(job["id"], result=result)
        return True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """Process jobs until cancelled or stop_event is set."""
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            handled = await self.run_once()
            if handled:
                continue
            await asyncio.sleep(self.poll_interval)

    async def _process_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_type = job["job_type"]
        project_id = job["project_id"]
        entity_id = job.get("entity_id")

        # ── Embedding-only jobs ──────────────────────────────────

        if job_type == "mission_embed":
            from rka.services.missions import MissionService
            svc = MissionService(self.db, embeddings=self.embeddings, project_id=project_id)
            return await svc.process_embedding_job(entity_id)

        if job_type == "note_embed":
            from rka.services.notes import NoteService
            svc = NoteService(self.db, embeddings=self.embeddings, project_id=project_id)
            return await svc.process_embedding_job(entity_id)

        if job_type == "claim_embed":
            from rka.services.claims import ClaimService
            svc = ClaimService(self.db, embeddings=self.embeddings, project_id=project_id)
            return await svc.process_embedding_job(entity_id)

        if job_type == "decision_embed":
            from rka.services.decisions import DecisionService
            svc = DecisionService(self.db, embeddings=self.embeddings, project_id=project_id)
            return await svc.process_embedding_job(entity_id)

        if job_type == "literature_embed":
            from rka.services.literature import LiteratureService
            svc = LiteratureService(self.db, embeddings=self.embeddings, project_id=project_id)
            return await svc.process_embedding_job(entity_id)

        # ── Legacy LLM jobs — skip gracefully ────────────────────
        # These job types may still exist in the queue from before the migration.
        # Complete them as no-ops instead of failing.

        _LEGACY_LLM_JOBS = {
            "note_auto_tag", "note_auto_link", "note_auto_summarize", "note_extract_claims",
            "claim_verify", "cluster_update", "theme_synthesize", "contradiction_check",
            "decision_auto_tag", "literature_auto_tag", "mission_auto_tag", "re_distill",
        }
        if job_type in _LEGACY_LLM_JOBS:
            logger.info("Skipping legacy LLM job %s (%s) — no longer processed by worker", job_type, job["id"])
            return {"outcome": "skipped", "reason": "legacy_llm_job"}

        raise ValueError(f"Unsupported job_type '{job_type}'")
