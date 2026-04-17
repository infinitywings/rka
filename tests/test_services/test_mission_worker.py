"""Tests for queued mission enrichment and the background worker."""

from __future__ import annotations

import hashlib

import pytest

from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.models.mission import MissionCreate
from rka.services.jobs import JobQueue
from rka.services.missions import MissionService
from rka.services.worker import EnrichmentWorker


async def _ensure_project(db: Database, project_id: str, name: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        [project_id, name, f"{name} description", "system"],
    )
    await db.execute(
        """INSERT OR IGNORE INTO project_states
           (project_id, project_name, project_description, phases_config, created_at, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
        [project_id, name, f"{name} description", "[]"],
    )
    await db.commit()


class DummyLLM:
    def __init__(self, tags: list[str] | None = None, *, raises: bool = False):
        self.tags = tags or ["mission", "queued"]
        self.raises = raises
        self.calls = 0

    async def auto_tag(self, content: str, project_tags: list[str]) -> list[str]:
        self.calls += 1
        if self.raises:
            raise RuntimeError("LLM unavailable")
        assert content
        return self.tags


class DummyEmbeddings(EmbeddingService):
    def __init__(self, db: Database):
        super().__init__(model_name="dummy-embed", db=db)
        self.calls = 0

    async def embed_document(self, text: str) -> list[float]:
        self.calls += 1
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]


class TestMissionQueue:
    @pytest.mark.asyncio
    async def test_create_mission_enqueues_background_enrichment(
        self,
        db: Database,
    ):
        await _ensure_project(db, "proj_alpha", "Alpha")
        llm = DummyLLM()
        embeddings = DummyEmbeddings(db)
        svc = MissionService(db, llm=llm, embeddings=embeddings, project_id="proj_alpha")

        mission = await svc.create(
            MissionCreate(
                phase="setup",
                objective="Benchmark the baseline",
                context="Compare the current pipeline before any changes.",
            ),
            actor="brain",
        )

        assert mission.enrichment_status == "pending"
        assert mission.tags == []
        assert llm.calls == 0
        assert embeddings.calls == 0

        fts_rows = await db.fetchall("SELECT * FROM fts_missions WHERE id = ?", [mission.id])
        assert len(fts_rows) == 1
        assert fts_rows[0]["objective"] == "Benchmark the baseline"

        jobs = await db.fetchall(
            """SELECT job_type, status
               FROM jobs
               WHERE project_id = ? AND entity_type = 'mission' AND entity_id = ?
               ORDER BY job_type""",
            ["proj_alpha", mission.id],
        )
        # LLM-dependent mission_auto_tag is no longer enqueued — only embed.
        assert jobs == [
            {"job_type": "mission_embed", "status": "pending"},
        ]

        metadata = await db.fetchall(
            """SELECT entity_type, entity_id
               FROM embedding_metadata
               WHERE project_id = ? AND entity_id = ?""",
            ["proj_alpha", mission.id],
        )
        assert metadata == []

    @pytest.mark.asyncio
    async def test_worker_processes_mission_jobs(self, db: Database):
        await _ensure_project(db, "proj_alpha", "Alpha")
        llm = DummyLLM(tags=["evaluation", "baseline"])
        embeddings = DummyEmbeddings(db)
        svc = MissionService(db, llm=llm, embeddings=embeddings, project_id="proj_alpha")

        mission = await svc.create(
            MissionCreate(
                phase="analysis",
                objective="Measure false positives",
                context="Use the held-out validation split.",
            ),
            actor="brain",
        )

        worker = EnrichmentWorker(
            db=db,
            embeddings=embeddings,
            poll_interval=0.01,
            lease_seconds=60,
            max_attempts=3,
        )

        handled = 0
        while await worker.run_once():
            handled += 1

        refreshed = await svc.get(mission.id)
        assert handled == 1
        assert refreshed is not None
        assert refreshed.enrichment_status == "ready"
        assert refreshed.tags == []
        assert llm.calls == 0
        assert embeddings.calls == 1

        metadata = await db.fetchall(
            """SELECT entity_type, entity_id
               FROM embedding_metadata
               WHERE project_id = ? AND entity_id = ?""",
            ["proj_alpha", mission.id],
        )
        assert metadata == [{"entity_type": "mission", "entity_id": mission.id}]

        jobs = await db.fetchall(
            "SELECT status FROM jobs WHERE entity_id = ? ORDER BY job_type",
            [mission.id],
        )
        assert [job["status"] for job in jobs] == ["completed"]

    @pytest.mark.asyncio
    async def test_job_queue_dedupes_pending_jobs(self, db: Database):
        queue = JobQueue(db)
        first = await queue.enqueue(
            "mission_embed",
            project_id="proj_alpha",
            entity_type="mission",
            entity_id="mis_001",
            dedupe_key="proj_alpha:mission:mis_001:embed",
        )
        second = await queue.enqueue(
            "mission_embed",
            project_id="proj_alpha",
            entity_type="mission",
            entity_id="mis_001",
            dedupe_key="proj_alpha:mission:mis_001:embed",
        )

        assert first == second
        rows = await db.fetchall(
            "SELECT id, status FROM jobs WHERE dedupe_key = ?",
            ["proj_alpha:mission:mis_001:embed"],
        )
        assert rows == [{"id": first, "status": "pending"}]

    @pytest.mark.asyncio
    async def test_worker_marks_job_failed_after_max_attempts(self, db: Database):
        """Exceptions raised during job processing mark the job failed after max_attempts."""
        await _ensure_project(db, "proj_alpha", "Alpha")
        await db.execute(
            "INSERT INTO missions (id, phase, objective, status, project_id) VALUES (?, ?, ?, ?, ?)",
            ["mis_fail", "setup", "Will fail", "pending", "proj_alpha"],
        )
        await db.commit()

        class FailingEmbeddings(DummyEmbeddings):
            async def embed_document(self, text: str) -> list[float]:
                raise RuntimeError("Embedding service unavailable")

        queue = JobQueue(db, default_max_attempts=1)
        await queue.enqueue(
            "mission_embed",
            project_id="proj_alpha",
            entity_type="mission",
            entity_id="mis_fail",
            max_attempts=1,
            dedupe_key="proj_alpha:mission:mis_fail:embed",
        )

        worker = EnrichmentWorker(
            db=db,
            embeddings=FailingEmbeddings(db),
            poll_interval=0.01,
            lease_seconds=60,
            max_attempts=1,
        )

        assert await worker.run_once() is True
        row = await db.fetchone(
            "SELECT status, attempts, last_error FROM jobs WHERE entity_id = ?",
            ["mis_fail"],
        )
        assert row is not None
        assert row["status"] == "failed"
        assert row["attempts"] == 1
        assert "Embedding service unavailable" in row["last_error"]
