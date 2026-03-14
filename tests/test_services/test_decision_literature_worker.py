"""Tests for queued decision and literature enrichment via the background worker."""

from __future__ import annotations

import hashlib

import pytest

from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.models.decision import DecisionCreate
from rka.models.literature import LiteratureCreate
from rka.services.decisions import DecisionService
from rka.services.literature import LiteratureService
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
        self.tags = tags or ["auto-tag"]
        self.raises = raises
        self.calls = 0

    async def auto_tag(self, content: str, project_tags: list[str]) -> list[str]:
        self.calls += 1
        if self.raises:
            raise RuntimeError("LLM unavailable")
        return self.tags


class DummyEmbeddings(EmbeddingService):
    def __init__(self, db: Database):
        super().__init__(model_name="dummy-embed", db=db)
        self.calls = 0

    async def embed_document(self, text: str) -> list[float]:
        self.calls += 1
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]


class TestDecisionQueue:
    @pytest.mark.asyncio
    async def test_create_decision_enqueues_background_enrichment(self, db: Database):
        await _ensure_project(db, "proj_dec", "Decisions")
        llm = DummyLLM()
        embeddings = DummyEmbeddings(db)
        svc = DecisionService(db, llm=llm, embeddings=embeddings, project_id="proj_dec")

        dec = await svc.create(
            DecisionCreate(
                question="Should we use PostgreSQL or SQLite?",
                phase="setup",
                decided_by="brain",
            ),
        )

        # No LLM calls during create
        assert llm.calls == 0
        assert embeddings.calls == 0
        assert dec.enrichment_status == "pending"
        assert dec.tags == []

        # FTS synced
        fts_rows = await db.fetchall("SELECT * FROM fts_decisions WHERE id = ?", [dec.id])
        assert len(fts_rows) == 1

        # 2 jobs enqueued
        jobs = await db.fetchall(
            "SELECT job_type, status FROM jobs WHERE entity_type = 'decision' AND entity_id = ? ORDER BY job_type",
            [dec.id],
        )
        assert jobs == [
            {"job_type": "decision_auto_tag", "status": "pending"},
            {"job_type": "decision_embed", "status": "pending"},
        ]

    @pytest.mark.asyncio
    async def test_create_decision_with_user_tags_skips_auto_tag(self, db: Database):
        await _ensure_project(db, "proj_dec", "Decisions")
        llm = DummyLLM()
        svc = DecisionService(db, llm=llm, embeddings=None, project_id="proj_dec")

        dec = await svc.create(
            DecisionCreate(
                question="Framework choice?",
                phase="setup",
                decided_by="pi",
                tags=["architecture"],
            ),
        )

        assert dec.tags == ["architecture"]
        jobs = await db.fetchall(
            "SELECT job_type FROM jobs WHERE entity_id = ?", [dec.id],
        )
        assert [j["job_type"] for j in jobs] == []  # no LLM, no embeddings

    @pytest.mark.asyncio
    async def test_worker_processes_decision_jobs(self, db: Database):
        await _ensure_project(db, "proj_dec", "Decisions")
        llm = DummyLLM(tags=["database", "architecture"])
        embeddings = DummyEmbeddings(db)
        svc = DecisionService(db, llm=llm, embeddings=embeddings, project_id="proj_dec")

        dec = await svc.create(
            DecisionCreate(
                question="Should we use PostgreSQL or SQLite?",
                rationale="SQLite is simpler for local-first.",
                phase="setup",
                decided_by="brain",
            ),
        )

        worker = EnrichmentWorker(
            db=db, llm=llm, embeddings=embeddings,
            poll_interval=0.01, lease_seconds=60, max_attempts=3,
        )

        handled = 0
        while await worker.run_once():
            handled += 1

        assert handled == 2
        refreshed = await svc.get(dec.id)
        assert refreshed.enrichment_status == "ready"
        assert sorted(refreshed.tags) == ["architecture", "database"]
        assert llm.calls == 1
        assert embeddings.calls == 1


class TestLiteratureQueue:
    @pytest.mark.asyncio
    async def test_create_literature_enqueues_background_enrichment(self, db: Database):
        await _ensure_project(db, "proj_lit", "Literature")
        llm = DummyLLM()
        embeddings = DummyEmbeddings(db)
        svc = LiteratureService(db, llm=llm, embeddings=embeddings, project_id="proj_lit")

        lit = await svc.create(
            LiteratureCreate(
                title="Attention Is All You Need",
                abstract="We propose the Transformer architecture.",
                added_by="pi",
            ),
        )

        assert llm.calls == 0
        assert embeddings.calls == 0
        assert lit.enrichment_status == "pending"
        assert lit.tags == []

        fts_rows = await db.fetchall("SELECT * FROM fts_literature WHERE id = ?", [lit.id])
        assert len(fts_rows) == 1

        jobs = await db.fetchall(
            "SELECT job_type, status FROM jobs WHERE entity_type = 'literature' AND entity_id = ? ORDER BY job_type",
            [lit.id],
        )
        assert jobs == [
            {"job_type": "literature_auto_tag", "status": "pending"},
            {"job_type": "literature_embed", "status": "pending"},
        ]

    @pytest.mark.asyncio
    async def test_create_literature_with_user_tags_skips_auto_tag(self, db: Database):
        await _ensure_project(db, "proj_lit", "Literature")
        llm = DummyLLM()
        svc = LiteratureService(db, llm=llm, embeddings=None, project_id="proj_lit")

        lit = await svc.create(
            LiteratureCreate(
                title="BERT: Pre-training",
                added_by="pi",
                tags=["nlp", "transformers"],
            ),
        )

        assert sorted(lit.tags) == ["nlp", "transformers"]
        jobs = await db.fetchall(
            "SELECT job_type FROM jobs WHERE entity_id = ?", [lit.id],
        )
        assert jobs == []

    @pytest.mark.asyncio
    async def test_worker_processes_literature_jobs(self, db: Database):
        await _ensure_project(db, "proj_lit", "Literature")
        llm = DummyLLM(tags=["transformers", "attention"])
        embeddings = DummyEmbeddings(db)
        svc = LiteratureService(db, llm=llm, embeddings=embeddings, project_id="proj_lit")

        lit = await svc.create(
            LiteratureCreate(
                title="Attention Is All You Need",
                abstract="We propose the Transformer architecture.",
                added_by="pi",
            ),
        )

        worker = EnrichmentWorker(
            db=db, llm=llm, embeddings=embeddings,
            poll_interval=0.01, lease_seconds=60, max_attempts=3,
        )

        handled = 0
        while await worker.run_once():
            handled += 1

        assert handled == 2
        refreshed = await svc.get(lit.id)
        assert refreshed.enrichment_status == "ready"
        assert sorted(refreshed.tags) == ["attention", "transformers"]
        assert llm.calls == 1
        assert embeddings.calls == 1

    @pytest.mark.asyncio
    async def test_create_without_llm_no_jobs(self, db: Database):
        await _ensure_project(db, "proj_lit", "Literature")
        svc = LiteratureService(db, llm=None, embeddings=None, project_id="proj_lit")

        lit = await svc.create(
            LiteratureCreate(title="Simple paper", added_by="pi"),
        )

        assert lit.enrichment_status == "ready"
        jobs = await db.fetchall("SELECT job_type FROM jobs WHERE entity_id = ?", [lit.id])
        assert jobs == []
