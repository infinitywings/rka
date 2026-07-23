"""Background worker for asynchronous embedding and validation jobs.

Processes local embedding jobs and worker-owned manuscript reference
validation. LLM-dependent enrichment (auto-tag, auto-link, auto-summarize,
claim extraction, claim verification, theme synthesis, contradiction checks)
has been removed — those tasks are handled by the Brain during maintenance
sessions.

Worker boot reads the persisted embedding config from
`/data/embedding_config.json` via `EmbeddingConfigService.load_config()`
(see `EnrichmentWorker.boot()`). This matches the api-server boot path
established in v2.4.0 (rka/api/app.py) and was added in v2.5.8 per
dec_01KS3E1FGSK530N8HM04BNMCEW (Bug 2 fix; pre-existing bug surfaced by
corpus refresh mis_01KS0QEW21N2NG4EJTKJ3JTWTE).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from pathlib import Path
from typing import Any

from rka.infra.database import Database
from rka.services.jobs import JobLeaseLost, JobQueue

logger = logging.getLogger(__name__)


class EnrichmentWorker:
    """Poll the durable queue for embeddings and reference validation."""

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

    # ------------------------------------------------------------------
    # v2.5.8 boot path (Bug 2 fix per dec_01KS3E1FGSK530N8HM04BNMCEW)
    # ------------------------------------------------------------------

    @classmethod
    def boot(
        cls,
        *,
        db: Database,
        data_dir: Path | str = Path("/data"),
        embeddings_enabled: bool = True,
        env_fallback_model: str = "nomic-ai/nomic-embed-text-v1.5",
        poll_interval: float = 1.0,
        lease_seconds: int = 300,
        max_attempts: int = 5,
        worker_id: str | None = None,
    ) -> "EnrichmentWorker":
        """Construct a worker with embeddings loaded from persisted config.

        Resolution order matches the api-server boot path (rka/api/app.py
        v2.4.0+):

        1. If embeddings_enabled is False: worker has embeddings=None.
        2. Otherwise, attempt to read `<data_dir>/embedding_config.json`
           via `EmbeddingConfigService.load_config()` and construct an
           `EmbeddingService.from_config(...)`.
        3. On any failure (file missing, corrupt, EmbeddingService
           construction error), fall back to the legacy env-driven
           constructor (`EmbeddingService(model_name=env_fallback_model)`)
           and log WARNING.

        Log lines explicitly indicate which path was taken so operators
        can correlate worker boot logs with config-changed-via-webui events.
        """
        embeddings = cls._resolve_embeddings(
            db=db,
            data_dir=data_dir,
            embeddings_enabled=embeddings_enabled,
            env_fallback_model=env_fallback_model,
        )
        return cls(
            db=db,
            embeddings=embeddings,
            poll_interval=poll_interval,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            worker_id=worker_id,
        )

    @staticmethod
    def _resolve_embeddings(
        *,
        db: Database,
        data_dir: Path | str,
        embeddings_enabled: bool,
        env_fallback_model: str,
    ):
        """Load EmbeddingService from persisted config or fall back to env.

        Isolated as a staticmethod so unit tests can exercise the resolution
        logic without instantiating a full worker. Logs are informative-only
        (no exceptions raised on fallback).
        """
        if not embeddings_enabled:
            logger.info(
                "worker boot: embeddings_enabled=False; running without EmbeddingService"
            )
            return None

        # Lazy imports keep the worker.py top-level import surface small
        # (embedding_config + embedding_backends pull in optional deps).
        try:
            from rka.infra.embeddings import EmbeddingService
            from rka.services.embedding_config import EmbeddingConfigService

            cfg_svc = EmbeddingConfigService(config_dir=data_dir)
            if not cfg_svc.config_path.exists():
                logger.info(
                    "worker boot: falling back to env defaults; persisted config "
                    "not found at %s",
                    cfg_svc.config_path,
                )
                return EmbeddingService(model_name=env_fallback_model, db=db)

            embedding_cfg = cfg_svc.load_config()
            embeddings = EmbeddingService.from_config(
                embedding_cfg.model_dump(), db=db
            )
            logger.info(
                "worker boot: reading config from %s (backend=%s, dim=%d)",
                cfg_svc.config_path,
                embedding_cfg.backend,
                embeddings.dim,
            )
            return embeddings
        except Exception as exc:
            logger.warning(
                "worker boot: failed to load persisted config (%s); falling back "
                "to env defaults (model=%s)",
                exc,
                env_fallback_model,
            )
            try:
                from rka.infra.embeddings import EmbeddingService
                return EmbeddingService(model_name=env_fallback_model, db=db)
            except Exception as inner_exc:
                logger.error(
                    "worker boot: env-fallback EmbeddingService construction also "
                    "failed (%s); running without embeddings",
                    inner_exc,
                )
                return None

    async def run_once(self) -> bool:
        """Process one job if available."""
        job = await self.queue.claim_next(self.worker_id)
        if job is None:
            return False

        try:
            result = await self._process_job(job)
        except Exception as exc:  # pragma: no cover - failure path tested via queue state
            logger.exception("Worker job %s failed", job["id"])
            durable_error = (
                f"{type(exc).__name__}: reference validation failed"
                if job.get("job_type") == "reference_validate"
                else str(exc)
            )
            try:
                await self.queue.fail(job, durable_error)
            except JobLeaseLost:
                logger.info(
                    "Worker job %s failure ignored after lease supersession",
                    job["id"],
                )
            return True

        try:
            await self.queue.complete(job, result=result)
        except JobLeaseLost:
            logger.info(
                "Worker job %s completion ignored after lease supersession",
                job["id"],
            )
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

        # ── Slow, externally resolved reference validation ───────

        if job_type == "reference_validate":
            from rka.services.reference_validation import ReferenceValidationRunner

            return await ReferenceValidationRunner(
                self.db,
                project_id=project_id,
            ).run_job(job)

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
