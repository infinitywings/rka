"""Tests for NoteService Phase 2 features (FTS5 sync, auto-enrichment)."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.notes import NoteService
from rka.models.journal import JournalEntryCreate as NoteCreate, JournalEntryUpdate as NoteUpdate


@pytest_asyncio.fixture
async def note_svc(db: Database) -> NoteService:
    """NoteService without LLM/embeddings (testing FTS5 sync only)."""
    return NoteService(db=db, llm=None, embeddings=None)


class TestNoteCreation:
    """Test note creation with Phase 2 index sync."""

    @pytest.mark.asyncio
    async def test_create_note_syncs_fts(self, note_svc: NoteService, db: Database):
        """Creating a note should populate the FTS5 index."""
        data = NoteCreate(
            content="Timing side-channel attack via network jitter",
            type="observation",
            confidence="hypothesis",
            phase="phase_1",
            tags=["timing", "side-channel"],
        )
        note = await note_svc.create(data, actor="pi")
        assert note is not None
        assert note.id.startswith("jrn_")

        # Verify FTS5 entry was created
        rows = await db.fetchall(
            "SELECT * FROM fts_journal WHERE id = ?", [note.id]
        )
        assert len(rows) == 1
        assert "Timing side-channel" in rows[0]["content"]

    @pytest.mark.asyncio
    async def test_create_note_with_tags(self, note_svc: NoteService, db: Database):
        """Tags should be persisted."""
        data = NoteCreate(
            content="Test content",
            type="finding",
            tags=["alpha", "beta"],
        )
        note = await note_svc.create(data, actor="pi")
        assert set(note.tags) == {"alpha", "beta"}


class TestNoteUpdate:
    """Test note update with Phase 2 re-sync."""

    @pytest.mark.asyncio
    async def test_update_note_resyncs_fts(self, note_svc: NoteService, db: Database):
        """Updating content should re-sync the FTS5 index."""
        data = NoteCreate(content="Original content", type="finding")
        note = await note_svc.create(data, actor="pi")

        # Update the content
        updated = await note_svc.update(
            note.id,
            NoteUpdate(content="Updated content about quantum effects"),
        )
        assert "Updated content" in updated.content

        # FTS5 should reflect the update
        rows = await db.fetchall(
            "SELECT * FROM fts_journal WHERE fts_journal MATCH ?", ["quantum"]
        )
        assert len(rows) >= 1
        assert rows[0]["id"] == note.id


class TestNoteSearch:
    """Test searching notes via FTS5."""

    @pytest.mark.asyncio
    async def test_fts_search_finds_note(self, note_svc: NoteService, db: Database):
        """FTS5 should find notes by content keywords."""
        data = NoteCreate(
            content="Reciprocal rank fusion combines keyword and semantic search results",
            type="finding",
        )
        note = await note_svc.create(data, actor="pi")

        # Search via FTS5
        rows = await db.fetchall(
            "SELECT * FROM fts_journal WHERE fts_journal MATCH ?", ["reciprocal rank fusion"]
        )
        assert len(rows) >= 1
        ids = [r["id"] for r in rows]
        assert note.id in ids
