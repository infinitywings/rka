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
        "INSERT INTO journal (id, type, content, source, confidence, project_id) VALUES (?, ?, ?, ?, ?, ?)",
        ["jrn_001", "finding", "Timing side-channel attacks on IoT protocols", "pi", "hypothesis", "proj_default"],
    )
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence, project_id) VALUES (?, ?, ?, ?, ?, ?)",
        ["jrn_002", "insight", "Multi-hop amplification factor is sqrt(n)", "pi", "tested", "proj_default"],
    )
    await db.execute(
        "INSERT INTO literature (id, title, abstract, status, project_id) VALUES (?, ?, ?, ?, ?)",
        ["lit_001", "Remote Timing Attacks on IoT Devices", "AES key recovery via timing", "reading", "proj_default"],
    )
    await db.execute(
        "INSERT INTO decisions (id, question, rationale, decided_by, status, phase, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["dec_001", "Statistical vs ML approach for timing analysis", "Balance accuracy and interpretability", "brain", "active", "phase_1", "proj_default"],
    )
    await db.execute(
        "INSERT INTO missions (id, objective, phase, status, project_id) VALUES (?, ?, ?, ?, ?)",
        ["mis_001", "Survey timing side-channel attack methodologies", "phase_1", "active", "proj_default"],
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

    def test_best_fts_hit_survives_semantic_eviction(self):
        from rka.services.search import SearchHit

        svc = SearchService.__new__(SearchService)
        needle = SearchHit("decision", "needle", "needle", "needle", fts_rank=0)
        vector_only = [
            SearchHit("journal", f"noise-{index}", "noise", "noise", vec_rank=index)
            for index in range(60)
        ]
        ranked = svc._rrf_merge([needle], vector_only, 0.3, 0.7)

        assert "needle" not in [hit.entity_id for hit in ranked[:30]]
        final = svc._truncate_with_lexical_floor(
            ranked,
            [needle],
            30,
            keyword_weight=0.3,
        )

        assert [hit.entity_id for hit in final[:-1]] == [
            hit.entity_id for hit in ranked[:29]
        ]
        assert final[-1].entity_id == "needle"
        assert len(final) == 30

    def test_lexical_floor_preserves_an_existing_hit(self):
        from rka.services.search import SearchHit

        svc = SearchService.__new__(SearchService)
        needle = SearchHit("decision", "needle", "needle", "needle", fts_rank=0)
        vector = [needle] + [
            SearchHit("journal", f"noise-{index}", "noise", "noise", vec_rank=index + 1)
            for index in range(5)
        ]
        ranked = svc._rrf_merge([needle], vector, 0.3, 0.7)
        expected = ranked[:3]

        final = svc._truncate_with_lexical_floor(
            ranked,
            [needle],
            3,
            keyword_weight=0.3,
        )

        assert final == expected
        assert sum(hit.entity_id == "needle" for hit in final) == 1

    def test_zero_keyword_weight_disables_lexical_floor(self):
        from rka.services.search import SearchHit

        svc = SearchService.__new__(SearchService)
        needle = SearchHit("decision", "needle", "needle", "needle", fts_rank=0)
        vector_only = [
            SearchHit("journal", f"noise-{index}", "noise", "noise", vec_rank=index)
            for index in range(60)
        ]
        ranked = svc._rrf_merge([needle], vector_only, 0.0, 0.7)

        final = svc._truncate_with_lexical_floor(
            ranked,
            [needle],
            30,
            keyword_weight=0.0,
        )

        assert final == ranked[:30]
        assert "needle" not in [hit.entity_id for hit in final]


# ------------------------------------------------- currency signals on hits


@pytest_asyncio.fixture
async def superseded_svc(db: Database) -> SearchService:
    """A superseded decision and its replacement, both FTS-indexed."""
    svc = SearchService(db=db, embeddings=None)
    for did, q in (
        ("dec_old", "What is the headline evaluation metric"),
        ("dec_new", "What is the headline evaluation metric"),
    ):
        await db.execute(
            "INSERT INTO fts_decisions (id, question, rationale) VALUES (?, ?, ?)",
            [did, q, "rationale text"],
        )
    # successor first: decisions.superseded_by is a self-referencing FK
    await db.execute(
        "INSERT INTO decisions (id, question, chosen, rationale, decided_by, phase,"
        " status, project_id)"
        " VALUES (?, ?, ?, ?, 'pi', 'p1', 'active', 'proj_default')",
        ["dec_new", "What is the headline evaluation metric", "new choice", "r"],
    )
    await db.execute(
        "INSERT INTO decisions (id, question, chosen, rationale, decided_by, phase,"
        " status, superseded_by, project_id)"
        " VALUES (?, ?, ?, ?, 'pi', 'p1', 'superseded', 'dec_new', 'proj_default')",
        ["dec_old", "What is the headline evaluation metric", "old choice", "r"],
    )
    return svc


async def test_search_hits_expose_supersession(superseded_svc: SearchService) -> None:
    """A superseded decision must be distinguishable from a current one.

    Regression: search returned only entity_type/entity_id/title/snippet/score,
    so an agent could not tell an overturned decision from one still in force
    and would act on stale knowledge. Every other read surface (ego_graph,
    multi_hop, operation="entity") already carried status.
    """
    hits = {h.entity_id: h for h in await superseded_svc.search("headline evaluation metric")}
    assert {"dec_old", "dec_new"} <= set(hits)

    assert hits["dec_old"].status == "superseded"
    assert hits["dec_old"].superseded_by == "dec_new"
    assert hits["dec_new"].status == "active"
    assert hits["dec_new"].superseded_by is None


async def test_currency_absent_for_types_without_lifecycle(
    search_svc: SearchService,
) -> None:
    """Types whose table carries no lifecycle column stay None, not crash."""
    hits = await search_svc.search("timing")
    assert hits, "fixture should produce hits"
    for hit in hits:
        assert hit.status is None or isinstance(hit.status, str)
        assert hit.stale is None or isinstance(hit.stale, bool)
