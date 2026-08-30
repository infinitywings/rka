"""Tests for queued note enrichment and the background worker."""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.infra.llm import SemanticLinks
from rka.models.journal import JournalEntryCreate
from rka.services.jobs import JobQueue
from rka.services.notes import NoteService
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
    def __init__(
        self,
        tags: list[str] | None = None,
        summary: str | None = "Auto-generated summary.",
        links: SemanticLinks | None = None,
        *,
        raises: bool = False,
    ):
        self.tags = tags or ["auto-tag", "note"]
        self.summary = summary
        self.links = links
        self.raises = raises
        self.calls: dict[str, int] = {"auto_tag": 0, "semantic_link": 0, "summarize": 0}

    async def auto_tag(self, content: str, project_tags: list[str]) -> list[str]:
        self.calls["auto_tag"] += 1
        if self.raises:
            raise RuntimeError("LLM unavailable")
        return self.tags

    async def semantic_link(self, *, content, current_type, decisions, literature, missions) -> SemanticLinks:
        self.calls["semantic_link"] += 1
        if self.raises:
            raise RuntimeError("LLM unavailable")
        if self.links:
            return self.links
        return SemanticLinks(reasoning="No links found.")

    async def summarize_entry(self, content: str) -> str:
        self.calls["summarize"] += 1
        if self.raises:
            raise RuntimeError("LLM unavailable")
        return self.summary


class DummyEmbeddings(EmbeddingService):
    def __init__(self, db: Database):
        super().__init__(model_name="dummy-embed", db=db)
        self.calls = 0
        self.texts: list[str] = []

    async def embed_document(self, text: str) -> list[float]:
        self.calls += 1
        self.texts.append(text)
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]


class TestNoteQueue:
    @pytest.mark.asyncio
    async def test_create_note_returns_immediately(self, db: Database):
        """Note creation should not call LLM inline; only embed enrichment is queued."""
        await _ensure_project(db, "proj_notes", "Notes")
        llm = DummyLLM()
        embeddings = DummyEmbeddings(db)
        svc = NoteService(db, llm=llm, embeddings=embeddings, project_id="proj_notes")

        note = await svc.create(
            JournalEntryCreate(
                content="We observed a 15% improvement in precision after fine-tuning.",
                type="finding",
                source="executor",
            ),
            actor="executor",
        )

        # No LLM calls during create (auto_tag/auto_link/auto_summarize were removed
        # when local-LLM enrichment was deprecated — those moved to the Brain).
        assert llm.calls == {"auto_tag": 0, "semantic_link": 0, "summarize": 0}
        assert embeddings.calls == 0

        # Embed is queued, note reports pending until the worker processes it.
        assert note.enrichment_status == "pending"
        assert note.tags == []
        assert note.summary is None

        # FTS was synced synchronously
        fts_rows = await db.fetchall("SELECT * FROM fts_journal WHERE id = ?", [note.id])
        assert len(fts_rows) == 1

        # Only note_embed is enqueued.
        jobs = await db.fetchall(
            """SELECT job_type, status, priority
               FROM jobs
               WHERE project_id = ? AND entity_type = 'journal' AND entity_id = ?
               ORDER BY job_type""",
            ["proj_notes", note.id],
        )
        assert [j["job_type"] for j in jobs] == ["note_embed"]

    @pytest.mark.asyncio
    async def test_worker_processes_note_jobs(self, db: Database):
        """Worker processes note_embed; no LLM-dependent jobs enqueued post-deprecation."""
        await _ensure_project(db, "proj_notes", "Notes")
        llm = DummyLLM()  # unused by worker; kept for NoteService construction parity
        embeddings = DummyEmbeddings(db)
        svc = NoteService(db, llm=llm, embeddings=embeddings, project_id="proj_notes")

        note = await svc.create(
            JournalEntryCreate(
                content="We observed a 15% improvement in precision after fine-tuning.",
                type="finding",
                source="executor",
            ),
            actor="executor",
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

        assert handled == 1

        refreshed = await svc.get(note.id)
        assert refreshed is not None
        assert refreshed.enrichment_status == "ready"
        assert refreshed.tags == []
        assert refreshed.summary is None
        assert llm.calls == {"auto_tag": 0, "semantic_link": 0, "summarize": 0}
        assert embeddings.calls == 1

    @pytest.mark.asyncio
    async def test_note_embed_runs_after_summarize(self, db: Database):
        """Embed job has higher priority number (lower priority) so it runs after summarize."""
        await _ensure_project(db, "proj_notes", "Notes")
        llm = DummyLLM()
        embeddings = DummyEmbeddings(db)
        svc = NoteService(db, llm=llm, embeddings=embeddings, project_id="proj_notes")

        note = await svc.create(
            JournalEntryCreate(
                content="Test priority ordering.",
                type="finding",
                source="executor",
            ),
        )

        jobs = await db.fetchall(
            "SELECT job_type, priority FROM jobs WHERE entity_id = ? ORDER BY priority, job_type",
            [note.id],
        )
        # LLM jobs at priority 100, embed at 110
        for j in jobs:
            if j["job_type"] == "note_embed":
                assert j["priority"] == 110
            else:
                assert j["priority"] == 100

    @pytest.mark.asyncio
    async def test_worker_handles_note_job_failure(self, db: Database):
        """Exceptions during embed processing mark the job failed after max attempts."""
        await _ensure_project(db, "proj_notes", "Notes")

        class FailingEmbeddings(DummyEmbeddings):
            async def embed_document(self, text: str) -> list[float]:
                raise RuntimeError("Embedding service unavailable")

        svc_no_llm = NoteService(db, llm=None, embeddings=None, project_id="proj_notes")
        note = await svc_no_llm.create(
            JournalEntryCreate(
                content="This will fail enrichment.",
                type="finding",
                source="executor",
            ),
        )

        queue = JobQueue(db, default_max_attempts=1)
        await queue.enqueue(
            "note_embed",
            project_id="proj_notes",
            entity_type="journal",
            entity_id=note.id,
            max_attempts=1,
            dedupe_key=f"proj_notes:journal:{note.id}:embed",
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
            [note.id],
        )
        assert row is not None
        assert row["status"] == "failed"
        assert row["attempts"] == 1
        assert "Embedding service unavailable" in row["last_error"]

        # Note should show failed enrichment status
        refreshed = await svc_no_llm.get(note.id)
        assert refreshed.enrichment_status == "failed"

    @pytest.mark.asyncio
    async def test_generation_change_rejects_inflight_worker_write(
        self, db: Database
    ):
        from rka.services.embedding_index import (
            embedding_space_signature,
            reconcile_embedding_index,
        )

        class BlockingBackend:
            model_name = "model-a"
            dim = 768

            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def embed(self, _text: str, *, is_query: bool = False):
                self.started.set()
                await self.release.wait()
                return [0.0] * self.dim

            async def embed_batch(self, texts, *, is_query: bool = False):
                return [await self.embed(text, is_query=is_query) for text in texts]

        await _ensure_project(db, "proj_generation", "Generation")
        cfg_a = {
            "backend": "openai_compat",
            "config": {"model": "model-a", "dim": 768},
        }
        initial = await reconcile_embedding_index(
            db,
            space_signature=embedding_space_signature(cfg_a),
            model_name="model-a",
            dim=768,
        )
        backend = BlockingBackend()
        embeddings = EmbeddingService(db=db, backend=backend)
        embeddings.space_signature = initial.state.space_signature
        embeddings.bind_index_generation(initial.state.generation)
        note_svc = NoteService(
            db,
            embeddings=embeddings,
            project_id="proj_generation",
        )
        note = await note_svc.create(
            JournalEntryCreate(content="generation fence", source="executor")
        )
        await db.execute(
            "UPDATE jobs SET max_attempts = 1 WHERE entity_id = ?",
            [note.id],
        )
        worker = EnrichmentWorker(
            db=db,
            embeddings=embeddings,
            max_attempts=1,
        )

        task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(backend.started.wait(), timeout=2)
        cfg_b = {
            "backend": "openai_compat",
            "config": {"model": "model-b", "dim": 768},
        }
        await reconcile_embedding_index(
            db,
            space_signature=embedding_space_signature(cfg_b),
            model_name="model-b",
            dim=768,
        )
        backend.release.set()
        assert await task is True

        job = await db.fetchone(
            "SELECT status, last_error FROM jobs WHERE entity_id = ?",
            [note.id],
        )
        assert job is not None
        assert job["status"] == "failed"
        assert "generation changed" in job["last_error"]
        assert await db.fetchone(
            "SELECT id FROM vec_journal WHERE id = ?", [note.id]
        ) is None
        assert await db.fetchone(
            """SELECT entity_id FROM embedding_metadata
               WHERE entity_type = 'journal' AND entity_id = ?""",
            [note.id],
        ) is None

    @pytest.mark.asyncio
    async def test_generation_change_reloads_config_and_repairs_inflight_note(
        self, db: Database, tmp_path
    ):
        from unittest.mock import patch

        from rka.services.embedding_config import EmbeddingConfig, EmbeddingConfigService
        from rka.services.embedding_index import (
            embedding_space_signature,
            reconcile_embedding_index,
        )

        class BlockingBackend:
            model_name = "model-a"
            dim = 768

            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def embed(self, _text: str, *, is_query: bool = False):
                self.started.set()
                await self.release.wait()
                return [0.0] * self.dim

            async def embed_batch(self, texts, *, is_query: bool = False):
                return [await self.embed(text, is_query=is_query) for text in texts]

        class ReadyBackend:
            model_name = "model-b"
            dim = 768

            async def embed(self, _text: str, *, is_query: bool = False):
                return [1.0] * self.dim

            async def embed_batch(self, texts, *, is_query: bool = False):
                return [[1.0] * self.dim for _text in texts]

        def config(model: str) -> EmbeddingConfig:
            return EmbeddingConfig(
                backend="openai_compat",
                config={
                    "base_url": "http://127.0.0.1:1",
                    "model": model,
                    "dim": 768,
                },
            )

        await _ensure_project(db, "proj_generation_retry", "Generation Retry")
        cfg_svc = EmbeddingConfigService(config_dir=tmp_path)
        saved_a = cfg_svc.save_config(config("model-a"), actor="test")
        state_a = await reconcile_embedding_index(
            db,
            space_signature=embedding_space_signature(saved_a),
            model_name="model-a",
            dim=768,
        )
        blocking = BlockingBackend()
        service_a = EmbeddingService(db=db, backend=blocking)
        service_a.space_signature = state_a.state.space_signature
        service_a.bind_index_generation(state_a.state.generation)
        service_b = EmbeddingService(db=db, backend=ReadyBackend())

        note_svc = NoteService(
            db,
            embeddings=service_a,
            project_id="proj_generation_retry",
        )
        note = await note_svc.create(
            JournalEntryCreate(content="repair this generation race", source="executor")
        )
        await db.execute(
            "UPDATE jobs SET max_attempts = 1 WHERE entity_id = ?",
            [note.id],
        )

        def build(payload, db=None):  # noqa: ARG001
            model = payload["config"].get("model")
            return service_a if model == "model-a" else service_b

        worker = EnrichmentWorker(
            db=db,
            embeddings=service_a,
            data_dir=tmp_path,
            max_attempts=1,
        )
        with patch(
            "rka.infra.embeddings.EmbeddingService.from_config",
            side_effect=build,
        ):
            task = asyncio.create_task(worker.run_once())
            await asyncio.wait_for(blocking.started.wait(), timeout=2)
            saved_b = cfg_svc.save_config(config("model-b"), actor="test")
            state_b = await reconcile_embedding_index(
                db,
                space_signature=embedding_space_signature(saved_b),
                model_name="model-b",
                dim=768,
            )
            blocking.release.set()
            assert await task is True

        job = await db.fetchone(
            "SELECT status, attempts, last_error FROM jobs WHERE entity_id = ?",
            [note.id],
        )
        metadata = await db.fetchone(
            """SELECT model_name, dimensions FROM embedding_metadata
               WHERE project_id = ? AND entity_type = 'journal' AND entity_id = ?""",
            ["proj_generation_retry", note.id],
        )
        assert job == {"status": "completed", "attempts": 1, "last_error": None}
        assert worker.embeddings is service_b
        assert service_b.index_generation == state_b.state.generation
        assert metadata == {"model_name": "model-b", "dimensions": 768}
        assert await db.fetchone(
            "SELECT id FROM vec_journal WHERE id = ?", [note.id]
        ) == {"id": note.id}

    @pytest.mark.asyncio
    async def test_create_note_without_llm_no_jobs(self, db: Database):
        """When LLM and embeddings are disabled, no enrichment jobs are enqueued."""
        await _ensure_project(db, "proj_notes", "Notes")
        svc = NoteService(db, llm=None, embeddings=None, project_id="proj_notes")

        note = await svc.create(
            JournalEntryCreate(
                content="Simple note, no enrichment.",
                type="observation",
                source="pi",
            ),
        )

        assert note.enrichment_status == "ready"
        jobs = await db.fetchall(
            "SELECT job_type FROM jobs WHERE entity_id = ?", [note.id],
        )
        assert jobs == []

    @pytest.mark.asyncio
    async def test_worker_embeds_large_note_content_without_truncation(self, db: Database):
        """Embedding jobs should handle multi-thousand-word journal entries intact."""
        await _ensure_project(db, "proj_notes", "Notes")
        embeddings = DummyEmbeddings(db)
        svc = NoteService(db, llm=None, embeddings=embeddings, project_id="proj_notes")
        large_content = " ".join(f"token_{i}" for i in range(2500))

        note = await svc.create(
            JournalEntryCreate(
                content=large_content,
                type="note",
                source="executor",
            ),
            actor="executor",
        )

        worker = EnrichmentWorker(
            db=db,
            embeddings=embeddings,
            poll_interval=0.01,
            lease_seconds=60,
            max_attempts=3,
        )

        assert await worker.run_once() is True
        assert embeddings.calls == 1
        assert embeddings.texts == [large_content]

        metadata = await db.fetchone(
            """SELECT content_hash
               FROM embedding_metadata
               WHERE project_id = ? AND entity_type = 'journal' AND entity_id = ?""",
            ["proj_notes", note.id],
        )
        assert metadata is not None
