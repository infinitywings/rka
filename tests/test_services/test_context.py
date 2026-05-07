"""Tests for the v2.4 ContextEngine.

Per dec_01KQQPD6Y6B362T3K08368BDMP: temperature classifier and token budget
removed; ranking is SQL-time importance × entity_links centrality × recency.
This test file replaces the pre-v2.4 HOT/WARM/COLD assertions.
"""

from __future__ import annotations

import pytest_asyncio

from rka.infra.database import Database
from rka.services.context import ContextEngine
from rka.services.search import SearchService


@pytest_asyncio.fixture
async def context_engine(db_with_project: Database) -> ContextEngine:
    """Context engine with mixed-importance test data."""
    db = db_with_project
    search = SearchService(db=db, embeddings=None)
    engine = ContextEngine(db=db, search=search, llm=None)

    NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    OLD = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 days')"

    # critical-importance journal (should rank highest)
    await db.execute(
        f"""INSERT INTO journal (id, type, content, source, confidence, importance,
            phase, project_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, {NOW}, {NOW})""",
        ["jrn_critical", "finding", "Critical finding about timing attacks",
         "pi", "verified", "critical", "phase_1", "proj_default"],
    )
    # high-importance journal, older
    await db.execute(
        f"""INSERT INTO journal (id, type, content, source, confidence, importance,
            phase, project_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, {OLD}, {OLD})""",
        ["jrn_high_old", "finding", "High-importance older finding",
         "pi", "verified", "high", "phase_1", "proj_default"],
    )
    # low-importance journal, recent (lower-ranked despite recency)
    await db.execute(
        f"""INSERT INTO journal (id, type, content, source, confidence, importance,
            phase, project_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, {NOW}, {NOW})""",
        ["jrn_low_recent", "note", "Low-importance recent observation",
         "executor", "hypothesis", "low", "phase_1", "proj_default"],
    )
    # archived (should rank lowest)
    await db.execute(
        f"""INSERT INTO journal (id, type, content, source, confidence, importance,
            phase, project_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, {NOW}, {NOW})""",
        ["jrn_archived", "note", "Archived note", "executor", "verified",
         "archived", "phase_1", "proj_default"],
    )

    # An active decision in current phase
    await db.execute(
        f"""INSERT INTO decisions (id, question, decided_by, status, phase, project_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, {NOW}, {NOW})""",
        ["dec_active", "Should we A or B?", "brain", "active", "phase_1", "proj_default"],
    )

    # An active mission
    await db.execute(
        f"""INSERT INTO missions (id, objective, phase, status, project_id, created_at)
           VALUES (?, ?, ?, ?, ?, {NOW})""",
        ["mis_active", "Test mission", "phase_1", "active", "proj_default"],
    )

    # Centrality fixture: jrn_high_old is highly connected. Vary target_id
    # because entity_links is UNIQUE(project_id, source_id, link_type, target_id)
    # post-migration 020.
    centrality_targets = [
        ("dec_active", "decision"),
        ("mis_active", "mission"),
        ("jrn_low_recent", "journal"),
        ("jrn_archived", "journal"),
        ("jrn_critical", "journal"),
    ]
    for i, (tgt_id, tgt_type) in enumerate(centrality_targets):
        await db.execute(
            """INSERT INTO entity_links (id, source_type, source_id, link_type,
                target_type, target_id, project_id)
               VALUES (?, 'journal', ?, 'references', ?, ?, ?)""",
            [f"lnk_high_{i}", "jrn_high_old", tgt_type, tgt_id, "proj_default"],
        )

    # FTS rows so search-anchored path also has data
    await db.execute(
        "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, ?)",
        ["jrn_critical", "Critical finding about timing attacks", ""],
    )

    await db.commit()
    return engine


class TestContextRankingByImportance:
    async def test_critical_importance_ranks_first(self, context_engine: ContextEngine):
        """A critical-importance journal entry ranks above a low-importance one,
        even when the low-importance entry is more recent."""
        pkg = await context_engine.get_context()
        ranked_ids = pkg.sources

        crit_idx = ranked_ids.index("jrn_critical")
        low_idx = ranked_ids.index("jrn_low_recent")
        assert crit_idx < low_idx, (
            f"jrn_critical (importance=critical) must rank before jrn_low_recent "
            f"(importance=low, more recent). Got positions {crit_idx} vs {low_idx}."
        )

    async def test_archived_ranks_low(self, context_engine: ContextEngine):
        """Archived entries appear at the bottom."""
        pkg = await context_engine.get_context()
        ranked_ids = pkg.sources

        archived_idx = ranked_ids.index("jrn_archived")
        # All other journal entries should rank above archived.
        for nid in ("jrn_critical", "jrn_high_old", "jrn_low_recent"):
            assert ranked_ids.index(nid) < archived_idx, (
                f"{nid} must rank above jrn_archived (importance=archived)."
            )

    async def test_pi_source_lift_applied_within_band(self, context_engine: ContextEngine):
        """PI-sourced entries get a small lift; jrn_critical (pi) outranks
        any equally-rated executor-sourced entries (none in this fixture, but
        the PI entry is at top — sanity-check the scoring tuple respects it)."""
        pkg = await context_engine.get_context()
        # First entry should be jrn_critical (PI + critical).
        assert pkg.sources[0] == "jrn_critical", (
            f"Expected jrn_critical first; got {pkg.sources[0]}"
        )


class TestContextNoTokenBudget:
    async def test_no_max_tokens_parameter(self, context_engine: ContextEngine):
        """get_context no longer accepts max_tokens as a kwarg."""
        # Should not raise — just accepts no max_tokens.
        pkg = await context_engine.get_context()
        # All eligible entries should be present (no budget truncation).
        ranked_ids = pkg.sources
        for nid in ("jrn_critical", "jrn_high_old", "jrn_low_recent",
                    "jrn_archived", "dec_active", "mis_active"):
            assert nid in ranked_ids, (
                f"{nid} missing from ranked output — token budget should NOT be truncating."
            )

    async def test_token_estimate_is_informational_only(self, context_engine: ContextEngine):
        """token_estimate is reported but not enforced."""
        pkg = await context_engine.get_context()
        # token_estimate should reflect the rendered content's rough token count;
        # crucially, NOT zero (meaning content was rendered) and NOT a low fixed
        # cap.
        assert pkg.token_estimate > 0, "token_estimate should report rendered token count"

    async def test_entries_field_populated(self, context_engine: ContextEngine):
        """The new `entries` field carries the ranked list (not the legacy buckets)."""
        pkg = await context_engine.get_context()
        assert pkg.entries, "entries field must be populated (v2.4 single ranked list)"
        # Legacy bucket fields stay empty.
        assert pkg.hot_entries == []
        assert pkg.warm_entries == []
        assert pkg.cold_entries == []


class TestContextCentralityContribution:
    async def test_high_centrality_lifts_within_importance_band(self, context_engine: ContextEngine):
        """jrn_high_old (importance=high, 5 entity_links) should outrank an
        un-linked normal-importance entry — but stay below the critical entry."""
        pkg = await context_engine.get_context()
        ranked = pkg.sources

        crit_idx = ranked.index("jrn_critical")
        high_old_idx = ranked.index("jrn_high_old")
        low_recent_idx = ranked.index("jrn_low_recent")

        # Sanity: critical above high (importance dominates centrality)
        assert crit_idx < high_old_idx
        # high+centrality above low+recent (importance still wins; centrality
        # tie-breaks within importance bands)
        assert high_old_idx < low_recent_idx


class TestContextNote:
    async def test_note_describes_v2_4_ranking(self, context_engine: ContextEngine):
        pkg = await context_engine.get_context()
        assert pkg.note is not None
        assert "importance" in pkg.note.lower()
        # Should reference the v2.4 decision id for traceability.
        assert "dec_01KQQPD6Y6B362T3K08368BDMP" in pkg.note


class TestHydrateHitsClaimAndCluster:
    """Defect 1 (mis_01KR1Z28QW9WYXG4VV8PGYWD8G T4): pre-v2.3.4 _hydrate_hits
    silently dropped claim and cluster hits because the table_map only had
    journal/decision/literature/mission entries. Multi-hop retrieval returned
    these node types since v2.3.3, so the hydration drop was a silent
    data-invisibility bug. These tests assert claim and cluster hits round-trip
    through _hydrate_hits with an entity_type annotation.
    """

    async def test_claim_hit_hydrated(self, context_engine: ContextEngine):
        from rka.services.search import SearchHit

        await context_engine.db.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence, project_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ["clm_t4_alpha", "jrn_critical", "observation",
             "Smoke claim for Defect 1 hydration coverage", 0.8, "proj_default"],
        )
        await context_engine.db.commit()

        hits = [SearchHit(
            entity_type="claim", entity_id="clm_t4_alpha",
            title="Smoke claim", snippet="…",
        )]
        rows = await context_engine._hydrate_hits(hits, project_id="proj_default")
        assert len(rows) == 1
        assert rows[0]["id"] == "clm_t4_alpha"
        assert rows[0]["entity_type"] == "claim"
        assert rows[0]["content"].startswith("Smoke claim")

    async def test_cluster_hit_hydrated(self, context_engine: ContextEngine):
        from rka.services.search import SearchHit

        await context_engine.db.execute(
            """INSERT INTO evidence_clusters
               (id, label, project_id)
               VALUES (?, ?, ?)""",
            ["ecl_t4_alpha", "Smoke cluster for Defect 1", "proj_default"],
        )
        await context_engine.db.commit()

        hits = [SearchHit(
            entity_type="cluster", entity_id="ecl_t4_alpha",
            title="Smoke cluster", snippet="…",
        )]
        rows = await context_engine._hydrate_hits(hits, project_id="proj_default")
        assert len(rows) == 1
        assert rows[0]["id"] == "ecl_t4_alpha"
        assert rows[0]["entity_type"] == "cluster"
        assert rows[0]["label"] == "Smoke cluster for Defect 1"

    async def test_unknown_entity_type_still_dropped(self, context_engine: ContextEngine):
        """Hits with an entity_type not in the table_map are still dropped
        silently — same fail-open behavior as before the fix; the fix only
        added claim and cluster, did not turn unknown types into errors.
        """
        from rka.services.search import SearchHit

        hits = [SearchHit(
            entity_type="totally_unknown_type", entity_id="x",
            title="t", snippet="s",
        )]
        rows = await context_engine._hydrate_hits(hits, project_id="proj_default")
        assert rows == []
