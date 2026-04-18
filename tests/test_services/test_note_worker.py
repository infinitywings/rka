"""Tests for queued note enrichment and the background worker."""

from __future__ import annotations

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
