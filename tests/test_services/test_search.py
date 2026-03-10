"""Tests for the hybrid SearchService."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.search import SearchService


@pytest_asyncio.fixture
async def search_svc(db: Database) -> SearchService:
    """Search service with FTS5 data populated."""
    svc = SearchService(db=db, embeddings=None)

    # Populate FTS5 indexes directly
    await db.execute(
        "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, ?)",
        ["jrn_001", "Timing side-channel attacks on IoT protocols", "Side-channel observation"],
    )
    await db.execute(
        "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, ?)",
        ["jrn_002", "Multi-hop amplification factor is sqrt(n)", "Amplification insight"],
    )
    await db.execute(
        "INSERT INTO fts_literature (id, title, abstract, notes) VALUES (?, ?, ?, ?)",
        ["lit_001", "Remote Timing Attacks on IoT Devices", "AES key recovery via timing", ""],
    )
    await db.execute(
        "INSERT INTO fts_decisions (id, question, rationale) VALUES (?, ?, ?)",
        ["dec_001", "Statistical vs ML approach for timing analysis", "Balance accuracy and interpretability"],
    )
    await db.execute(
        "INSERT INTO fts_missions (id, objective, context) VALUES (?, ?, ?)",
        ["mis_001", "Survey timing side-channel attack methodologies", "Literature review phase"],
    )

    # Also insert source rows so SearchService can fetch full data
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence) VALUES (?, ?, ?, ?, ?)",
        ["jrn_001", "finding", "Timing side-channel attacks on IoT protocols", "pi", "hypothesis"],
    )
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence) VALUES (?, ?, ?, ?, ?)",
        ["jrn_002", "insight", "Multi-hop amplification factor is sqrt(n)", "pi", "tested"],
    )
    await db.execute(
        "INSERT INTO literature (id, title, abstract, status) VALUES (?, ?, ?, ?)",
        ["lit_001", "Remote Timing Attacks on IoT Devices", "AES key recovery via timing", "reading"],
    )
    await db.execute(
        "INSERT INTO decisions (id, question, rationale, decided_by, status, phase) VALUES (?, ?, ?, ?, ?, ?)",
        ["dec_001", "Statistical vs ML approach for timing analysis", "Balance accuracy and interpretability", "brain", "active", "phase_1"],
    )
    await db.execute(
        "INSERT INTO missions (id, objective, phase, status) VALUES (?, ?, ?, ?)",
        ["mis_001", "Survey timing side-channel attack methodologies", "phase_1", "active"],
    )
    await db.commit()

    return svc


class TestFTS5Search:
    """FTS5 keyword search tests."""

    @pytest.mark.asyncio
    async def test_search_finds_matching_journal(self, search_svc: SearchService):
        results = await search_svc.search("timing attacks", limit=10)
        ids = [r.entity_id for r in results]
        assert "jrn_001" in ids

    @pytest.mark.asyncio
    async def test_search_finds_matching_literature(self, search_svc: SearchService):
        results = await search_svc.search("Remote Timing Attacks", limit=10)
        ids = [r.entity_id for r in results]
        assert "lit_001" in ids

    @pytest.mark.asyncio
    async def test_search_finds_matching_decision(self, search_svc: SearchService):
        results = await search_svc.search("statistical ML", limit=10)
        ids = [r.entity_id for r in results]
        assert "dec_001" in ids

    @pytest.mark.asyncio
    async def test_search_finds_matching_mission(self, search_svc: SearchService):
        results = await search_svc.search("survey timing methodologies", limit=10)
        ids = [r.entity_id for r in results]
        assert "mis_001" in ids

    @pytest.mark.asyncio
    async def test_search_respects_entity_type_filter(self, search_svc: SearchService):
        results = await search_svc.search("timing", entity_types=["journal"], limit=10)
        types = {r.entity_type for r in results}
        assert types == {"journal"}

    @pytest.mark.asyncio
    async def test_search_handles_special_chars(self, search_svc: SearchService):
        """Hyphens and other special chars shouldn't crash FTS5."""
        results = await search_svc.search("side-channel", limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_returns_empty_for_no_match(self, search_svc: SearchService):
        results = await search_svc.search("quantum entanglement photonics", limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_cross_entity(self, search_svc: SearchService):
        """Broad query should find results across multiple entity types."""
        results = await search_svc.search("timing", limit=20)
        types = {r.entity_type for r in results}
        assert len(types) >= 2  # Should find journal + literature + mission + decision


class TestQuerySanitization:
    """Test FTS5 query sanitization."""

    def test_sanitize_removes_hyphens(self):
        q = SearchService._sanitize_fts_query("side-channel")
        assert '"side"' in q
        assert '"channel"' in q

    def test_sanitize_handles_empty(self):
        q = SearchService._sanitize_fts_query("")
        assert q == ""

    def test_sanitize_quotes_words(self):
        q = SearchService._sanitize_fts_query("foo bar")
        assert '"foo"' in q
        assert '"bar"' in q


class TestRRFMerge:
    """Test Reciprocal Rank Fusion merging."""

    def test_rrf_combines_results(self):
        from rka.services.search import SearchHit
        svc = SearchService.__new__(SearchService)

        fts = [
            SearchHit("journal", "j1", "T1", "S1", fts_rank=0),
            SearchHit("journal", "j2", "T2", "S2", fts_rank=1),
        ]
        vec = [
            SearchHit("journal", "j2", "T2", "S2", vec_rank=0),
            SearchHit("journal", "j3", "T3", "S3", vec_rank=1),
        ]

        merged = svc._rrf_merge(fts, vec, keyword_weight=0.3, semantic_weight=0.7)

        ids = [h.entity_id for h in merged]
        # j2 appears in both lists so should rank highest
        assert ids[0] == "j2"
        assert len(merged) == 3  # j1, j2, j3

    def test_rrf_empty_lists(self):
        svc = SearchService.__new__(SearchService)
        merged = svc._rrf_merge([], [], 0.3, 0.7)
        assert merged == []
