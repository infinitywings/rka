"""Tests for Phase 2 BaseService methods (FTS5 sync, embedding sync, auto-enrichment)."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.base import BaseService


@pytest_asyncio.fixture
async def base_svc(db: Database) -> BaseService:
    """BaseService with no LLM or embeddings (testing sync-only)."""
    return BaseService(db=db, llm=None, embeddings=None)


class TestFTS5Sync:
    """Test FTS5 index synchronization."""

    @pytest.mark.asyncio
    async def test_sync_fts_journal(self, base_svc: BaseService, db: Database):
        data = {"content": "Test journal content", "summary": "Test summary"}
        await base_svc._sync_fts("journal", "jrn_test", data)

        rows = await db.fetchall("SELECT * FROM fts_journal WHERE id = ?", ["jrn_test"])
        assert len(rows) == 1
        assert rows[0]["content"] == "Test journal content"
        assert rows[0]["summary"] == "Test summary"

    @pytest.mark.asyncio
    async def test_sync_fts_decision(self, base_svc: BaseService, db: Database):
        data = {"question": "Which approach?", "rationale": "Because reasons"}
        await base_svc._sync_fts("decision", "dec_test", data)

        rows = await db.fetchall("SELECT * FROM fts_decisions WHERE id = ?", ["dec_test"])
        assert len(rows) == 1
        assert rows[0]["question"] == "Which approach?"

    @pytest.mark.asyncio
    async def test_sync_fts_literature(self, base_svc: BaseService, db: Database):
        data = {"title": "My Paper", "abstract": "We show that...", "notes": "Good paper"}
        await base_svc._sync_fts("literature", "lit_test", data)

        rows = await db.fetchall("SELECT * FROM fts_literature WHERE id = ?", ["lit_test"])
        assert len(rows) == 1
        assert rows[0]["title"] == "My Paper"

    @pytest.mark.asyncio
    async def test_sync_fts_mission(self, base_svc: BaseService, db: Database):
        data = {"objective": "Survey papers", "context": "Phase 1"}
        await base_svc._sync_fts("mission", "mis_test", data)

        rows = await db.fetchall("SELECT * FROM fts_missions WHERE id = ?", ["mis_test"])
        assert len(rows) == 1
        assert rows[0]["objective"] == "Survey papers"

    @pytest.mark.asyncio
    async def test_sync_fts_replaces_existing(self, base_svc: BaseService, db: Database):
        """Updating FTS should delete old and insert new."""
        await base_svc._sync_fts("journal", "jrn_dup", {"content": "Original", "summary": ""})
        await base_svc._sync_fts("journal", "jrn_dup", {"content": "Updated", "summary": ""})

        rows = await db.fetchall("SELECT * FROM fts_journal WHERE id = ?", ["jrn_dup"])
        assert len(rows) == 1
        assert rows[0]["content"] == "Updated"

    @pytest.mark.asyncio
    async def test_sync_fts_unknown_entity_type(self, base_svc: BaseService, db: Database):
        """Unknown entity type should be silently ignored."""
        await base_svc._sync_fts("unknown_type", "x_1", {"content": "test"})
        # Should not raise

    @pytest.mark.asyncio
    async def test_sync_fts_with_none_values(self, base_svc: BaseService, db: Database):
        """None values should be stored as empty strings."""
        await base_svc._sync_fts("journal", "jrn_none", {"content": None, "summary": None})
        rows = await db.fetchall("SELECT * FROM fts_journal WHERE id = ?", ["jrn_none"])
        assert len(rows) == 1
        assert rows[0]["content"] == ""


class TestEmbeddingSync:
    """Test embedding sync behavior without embeddings service."""

    @pytest.mark.asyncio
    async def test_sync_embedding_skips_when_no_service(self, base_svc: BaseService):
        """Should silently skip when embeddings is None."""
        await base_svc._sync_embedding("journal", "jrn_1", {"content": "test"})
        # Should not raise


class TestAutoEnrichment:
    """Test auto-enrichment methods without LLM."""

    @pytest.mark.asyncio
    async def test_auto_tag_returns_none_without_llm(self, base_svc: BaseService):
        result = await base_svc._auto_enrich_tags("some content", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_summarize_returns_none_without_llm(self, base_svc: BaseService):
        result = await base_svc._auto_summarize("some content")
        assert result is None


class TestSyncIndexes:
    """Test combined FTS5 + embedding sync."""

    @pytest.mark.asyncio
    async def test_sync_indexes_creates_fts(self, base_svc: BaseService, db: Database):
        """_sync_indexes should create FTS5 entries even without embeddings."""
        await base_svc._sync_indexes("journal", "jrn_idx", {"content": "Indexed content", "summary": "Summary"})

        rows = await db.fetchall("SELECT * FROM fts_journal WHERE id = ?", ["jrn_idx"])
        assert len(rows) == 1
        assert rows[0]["content"] == "Indexed content"
