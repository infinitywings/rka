"""Background worker for asynchronous enrichment jobs."""

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
    """Polls the durable queue and processes enrichment jobs."""

    def __init__(
        self,
        *,
        db: Database,
        llm=None,
        embeddings=None,
        poll_interval: float = 1.0,
        lease_seconds: int = 300,
        max_attempts: int = 5,
        worker_id: str | None = None,
    ):
        self.db = db
        self.llm = llm
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

        if job_type.startswith("mission_"):
            from rka.services.missions import MissionService

            svc = MissionService(
                self.db,
                llm=self.llm,
                embeddings=self.embeddings,
                project_id=project_id,
            )
            if job_type == "mission_auto_tag":
                return await svc.process_auto_tag_job(entity_id)
            if job_type == "mission_embed":
                return await svc.process_embedding_job(entity_id)

        if job_type.startswith("note_"):
            from rka.services.notes import NoteService

            svc = NoteService(
                self.db,
                llm=self.llm,
                embeddings=self.embeddings,
                project_id=project_id,
            )
            if job_type == "note_auto_tag":
                return await svc.process_auto_tag_job(entity_id)
            if job_type == "note_auto_link":
                return await svc.process_auto_link_job(entity_id)
            if job_type == "note_auto_summarize":
                return await svc.process_auto_summarize_job(entity_id)
            if job_type == "note_embed":
                return await svc.process_embedding_job(entity_id)
            if job_type == "note_extract_claims":
                from rka.services.claims import ClaimService
                claim_svc = ClaimService(
                    self.db, llm=self.llm, embeddings=self.embeddings,
                    project_id=project_id,
                )
                return await claim_svc.process_extract_claims_job(entity_id)

        if job_type.startswith("claim_"):
            from rka.services.claims import ClaimService

            svc = ClaimService(
                self.db, llm=self.llm, embeddings=self.embeddings,
                project_id=project_id,
            )
            if job_type == "claim_verify":
                return await svc.process_verify_claim_job(entity_id)
            if job_type == "claim_embed":
                return await svc.process_embedding_job(entity_id)

        if job_type.startswith("cluster_") or job_type in ("theme_synthesize", "contradiction_check"):
            from rka.services.clusters import ClusterService

            svc = ClusterService(
                self.db, llm=self.llm, embeddings=self.embeddings,
                project_id=project_id,
            )
            if job_type == "cluster_update":
                return await svc.process_cluster_update_job(entity_id)
            if job_type == "theme_synthesize":
                return await svc.process_theme_synthesize_job(entity_id)
            if job_type == "contradiction_check":
                payload = None
                if job.get("payload"):
                    import json
                    try:
                        payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                return await svc.process_contradiction_check_job(entity_id, payload)

        if job_type == "re_distill":
            from rka.services.claims import ClaimService
            claim_svc = ClaimService(
                self.db, llm=self.llm, embeddings=self.embeddings,
                project_id=project_id,
            )
            # Mark existing claims as stale, then re-extract
            await claim_svc.mark_stale_by_entry(entity_id)
            return await claim_svc.process_extract_claims_job(entity_id)

        if job_type.startswith("decision_"):
            from rka.services.decisions import DecisionService

            svc = DecisionService(
                self.db,
                llm=self.llm,
                embeddings=self.embeddings,
                project_id=project_id,
            )
            if job_type == "decision_auto_tag":
                return await svc.process_auto_tag_job(entity_id)
            if job_type == "decision_embed":
                return await svc.process_embedding_job(entity_id)

        if job_type.startswith("literature_"):
            from rka.services.literature import LiteratureService

            svc = LiteratureService(
                self.db,
                llm=self.llm,
                embeddings=self.embeddings,
                project_id=project_id,
            )
            if job_type == "literature_auto_tag":
                return await svc.process_auto_tag_job(entity_id)
            if job_type == "literature_embed":
                return await svc.process_embedding_job(entity_id)

        raise ValueError(f"Unsupported job_type '{job_type}'")
