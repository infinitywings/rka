"""Tests for the v2.4 ContextEngine.

Per dec_01KQQPD6Y6B362T3K08368BDMP: temperature classifier and token budget
removed; ranking is SQL-time importance × entity_links centrality × recency.
This test file replaces the pre-v2.4 HOT/WARM/COLD assertions.
"""

from __future__ import annotations

import pytest
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
        """PI-sourced entries get a +0.125 normalized lift in the importance
        band — same magnitude as the pre-v2.5.3 +5/40 lift.

        Post-v2.5.3 (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ) the overview path is a
        weighted-sum, not a strict-band hierarchy, so jrn_critical is not
        guaranteed to be first when other entries have high centrality + high
        recency. This test now asserts the lift is APPLIED (PI > non-PI at
        equal importance / centrality / recency) by comparing scores from
        the engine's classmethod directly — a more precise check than relying
        on the fixture's ordering after centrality changes shift the leader.
        """
        pi_entry = {"importance": "normal", "source": "pi", "centrality_degree": 0, "created_at": "2026-05-17T00:00:00Z"}
        non_pi_entry = {"importance": "normal", "source": "executor", "centrality_degree": 0, "created_at": "2026-05-17T00:00:00Z"}
        pi_score = ContextEngine._overview_score(pi_entry)
        non_pi_score = ContextEngine._overview_score(non_pi_entry)
        assert pi_score > non_pi_score, (
            f"PI lift must produce a higher score at equal importance/centrality/"
            f"recency. Got pi={pi_score!r} vs non_pi={non_pi_score!r}."
        )
        # Lift magnitude is _PI_SOURCE_LIFT_NORMALIZED * _W_IMPORTANCE = 0.125 * 0.5 = 0.0625.
        assert pi_score - non_pi_score == pytest.approx(0.0625, abs=1e-9)


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
    async def test_high_centrality_with_age_can_beat_un_linked_critical(
        self, context_engine: ContextEngine
    ):
        """Pre-v2.5.3 this test asserted critical-strict-dominance-over-
        centrality. The fix-shape decision dec_01KRSMMCS8MD7KQDBS0E2DVKBQ
        explicitly identifies that invariant as the bug ("a 'critical' entry
        from 6 months ago beats a 'high' from yesterday" — the design intent
        was importance × centrality × recency, not strict-band hierarchy).

        Post-v2.5.3 the weighted-sum lets a heavily-linked high-band entry
        outrank an un-linked critical-band entry. The fixture's jrn_high_old
        has 5 entity_links and PI source; jrn_critical has 0 entity_links
        and PI source. Computed scores (w_imp=0.5, w_cent=0.3, w_recency=0.2):
          jrn_critical: 0.5*1.125 + 0 + 0.2*1.0 = 0.7625
          jrn_high_old: 0.5*0.875 + 0.3*log1p(5) + 0.2*(~0)  ≈ 0.98
        """
        pkg = await context_engine.get_context()
        ranked = pkg.sources

        crit_idx = ranked.index("jrn_critical")
        high_old_idx = ranked.index("jrn_high_old")
        low_recent_idx = ranked.index("jrn_low_recent")

        # Post-v2.5.3 invariant: heavily-linked high beats un-linked critical.
        assert high_old_idx < crit_idx, (
            "v2.5.3 weighted-sum: high-importance with high centrality should "
            "outrank un-linked critical (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ)."
        )
        # Importance still helps within similar centrality/recency cohorts:
        # high+centrality > low+recency+zero-centrality.
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


# ---------------------------------------------------------------------------
# v2.5.3 — sort-by-retrieval-path regression tests (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ)
# ---------------------------------------------------------------------------


class TestV2_5_3SortByRetrievalPath:
    """Regression-lock the v2.5.3 sort semantics:

    - Topic path preserves search-relevance order (regardless of importance
      tags).
    - Overview path uses weighted-sum with recency as multiplicative term
      (today's normal entry beats 30-day-old normal entry).
    - PI-source lift applies on BOTH paths (topic and overview).
    """

    @pytest_asyncio.fixture
    async def engine_with_known_search_hits(self, db_with_project: Database):
        """ContextEngine wired to a stub SearchService that yields a fixed
        relevance-ordered hit list. Lets us test that the topic path
        preserves search order without depending on FTS/vector content."""
        from rka.services.search import SearchHit

        db = db_with_project

        # 4 decisions with deliberately inverted importance order vs. the
        # search-rank order, so importance-based re-sort would scramble them.
        NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        for did, q in (
            ("dec_topic_A", "topic anchor A"),
            ("dec_topic_B", "topic anchor B"),
            ("dec_topic_C", "topic anchor C"),
            ("dec_topic_D", "topic anchor D"),
        ):
            await db.execute(
                f"""INSERT INTO decisions (id, question, decided_by, status, phase,
                    project_id, created_at, updated_at)
                   VALUES (?, ?, 'brain', 'active', 'phase_1', 'proj_default',
                           {NOW}, {NOW})""",
                [did, q],
            )
        await db.commit()

        class _StubSearch:
            def __init__(self, hits):
                self._hits = hits

            def with_project(self, project_id):
                return self

            async def search(self, topic, limit=50):
                return list(self._hits)

        # Order: A (best), B, C, D (worst). Re-sort by importance would
        # scramble — they're all default 'normal' decisions with no
        # importance tag, so importance is tied; centrality and created_at
        # tie too (all NOW). The topic path must preserve [A,B,C,D].
        hits = [
            SearchHit(entity_type="decision", entity_id=did, title=did, snippet="")
            for did in ("dec_topic_A", "dec_topic_B", "dec_topic_C", "dec_topic_D")
        ]
        engine = ContextEngine(db=db, search=_StubSearch(hits), llm=None)
        return engine

    async def test_topic_query_preserves_search_rank(
        self, engine_with_known_search_hits: ContextEngine
    ):
        """Topic path must return entries in search-hit order, NOT importance
        order. Pre-v2.5.3 the relevance ranking was discarded by the
        importance-only re-sort."""
        pkg = await engine_with_known_search_hits.get_context(topic="anchor")
        assert pkg.sources == [
            "dec_topic_A",
            "dec_topic_B",
            "dec_topic_C",
            "dec_topic_D",
        ], (
            f"Topic path lost search-rank order; got {pkg.sources}. "
            "v2.5.3 must preserve BM25/vector ranking from SearchService."
        )

    async def test_overview_uses_weighted_sum_recency(
        self, db_with_project: Database
    ):
        """Overview path: two entries with the same importance band; the
        more recent one ranks higher because recency is now a first-class
        multiplicative term (pre-v2.5.3 it was tuple tie-break only)."""
        db = db_with_project
        NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        # 30 days back, so days_since_created ≈ 30; recency_score ≈ 1/31.
        OLD = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-30 days')"
        # Identical importance + source so the only differentiator is recency.
        await db.execute(
            f"""INSERT INTO journal (id, type, content, source, confidence,
                importance, phase, project_id, created_at, updated_at)
               VALUES ('jrn_recency_today', 'finding', 'recent content',
                       'executor', 'verified', 'normal', 'phase_1',
                       'proj_default', {NOW}, {NOW})"""
        )
        await db.execute(
            f"""INSERT INTO journal (id, type, content, source, confidence,
                importance, phase, project_id, created_at, updated_at)
               VALUES ('jrn_recency_old', 'finding', 'old content',
                       'executor', 'verified', 'normal', 'phase_1',
                       'proj_default', {OLD}, {OLD})"""
        )
        await db.commit()

        from rka.services.search import SearchService

        search = SearchService(db=db, embeddings=None)
        engine = ContextEngine(db=db, search=search, llm=None)

        pkg = await engine.get_context()  # overview path
        ranked = pkg.sources
        today_idx = ranked.index("jrn_recency_today")
        old_idx = ranked.index("jrn_recency_old")
        assert today_idx < old_idx, (
            "Overview path with weighted-sum: recent entry of same importance "
            "MUST rank above 30-day-old entry. v2.5.3 lifts recency to a "
            "multiplicative term (dec_01KRSMMCS8MD7KQDBS0E2DVKBQ)."
        )

    async def test_pi_source_lift_applied_on_both_paths(
        self, db_with_project: Database
    ):
        """PI-source lift must apply on BOTH the topic and overview paths.

        Overview path is exercised by scoring two same-importance same-recency
        entries with different sources via ContextEngine._overview_score
        directly (deterministic). Topic path uses the same scoring logic for
        tie-breaks within identical search_rank — also verified via
        _topic_sort_key.
        """
        pi_entry = {
            "_search_rank": 0,
            "importance": "high",
            "source": "pi",
            "centrality_degree": 0,
            "created_at": "2026-05-17T00:00:00Z",
        }
        non_pi_entry = {
            "_search_rank": 0,
            "importance": "high",
            "source": "executor",
            "centrality_degree": 0,
            "created_at": "2026-05-17T00:00:00Z",
        }
        # Overview: PI score > non-PI score.
        assert ContextEngine._overview_score(pi_entry) > ContextEngine._overview_score(
            non_pi_entry
        )
        # Topic-path tie-break (same search_rank=0): -importance term is more
        # negative for PI → PI tuple sorts first.
        assert ContextEngine._topic_sort_key(pi_entry) < ContextEngine._topic_sort_key(
            non_pi_entry
        )


# ---------------------------------------------------------------------------
# v2.5.4 — env-var-configurable coefficients (mis_01KRSP44W7BDZH11PZRGXH1WM4)
# ---------------------------------------------------------------------------


class TestV2_5_4EnvVarConfigurableCoefficients:
    """Coefficients are read from RKA_CTX_W_IMP / W_CENT / W_RECENCY /
    PI_LIFT at module-import time. Tests use monkeypatch.setenv plus
    _reload_coefficients_from_env() to swap values mid-process."""

    def test_defaults_match_phase_3_1_cfg11_winner_when_no_env_set(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """With no env vars set, the module constants must equal the
        Phase-3.1 T5 cfg11 winner defaults: w_imp=0.5, w_cent=0.3,
        w_recency=0.15, pi_lift=0.125, recency_shape_n=1.

        v2.5.3 hypothesis Config 1 had w_recency=0.2 (retained through
        v2.5.4 sweep). Phase-3.1 64-config sweep (mis_01KS3EB2671CDD4V9RZCMYCEH1
        T4; cfg11 winner per Brain ratification of
        chk_01KS3K40N6JRHV118969RMBNF0) drops w_recency to 0.15.
        The 0.125 PI lift preserves the pre-v2.5.3 +5/40 magnitude
        unchanged across all sweeps."""
        import rka.services.context as ctx

        for var in (
            "RKA_CTX_W_IMP",
            "RKA_CTX_W_CENT",
            "RKA_CTX_W_RECENCY",
            "RKA_CTX_PI_LIFT",
            "RKA_CTX_RECENCY_SHAPE_N",
        ):
            monkeypatch.delenv(var, raising=False)
        ctx._reload_coefficients_from_env()
        assert ctx._W_IMPORTANCE == 0.5
        assert ctx._W_CENTRALITY == 0.3
        assert ctx._W_RECENCY == 0.15  # Phase-3.1 cfg11 winner (was 0.2)
        assert ctx._PI_SOURCE_LIFT_NORMALIZED == 0.125
        # Phase-3.1: N=1 retained as cfg11 winner — shape_N effect was
        # within noise across the {1, 30, 90, 365} sweep so the simplest
        # shape wins by tie-break.
        assert ctx._RECENCY_SHAPE_N == 1.0

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch):
        """Setting the five RKA_CTX_* env vars overrides the module-level
        constants when _reload_coefficients_from_env() runs. This is the
        production swap pattern: docker restart with env → fresh import
        → fresh constants."""
        import rka.services.context as ctx

        monkeypatch.setenv("RKA_CTX_W_IMP", "0.7")
        monkeypatch.setenv("RKA_CTX_W_CENT", "0.2")
        monkeypatch.setenv("RKA_CTX_W_RECENCY", "0.1")
        monkeypatch.setenv("RKA_CTX_PI_LIFT", "0.3")
        monkeypatch.setenv("RKA_CTX_RECENCY_SHAPE_N", "90")
        ctx._reload_coefficients_from_env()
        assert ctx._W_IMPORTANCE == 0.7
        assert ctx._W_CENTRALITY == 0.2
        assert ctx._W_RECENCY == 0.1
        assert ctx._PI_SOURCE_LIFT_NORMALIZED == 0.3
        assert ctx._RECENCY_SHAPE_N == 90.0

        # Restore defaults so subsequent tests in the same module aren't
        # affected by env-var bleed.
        for var in (
            "RKA_CTX_W_IMP",
            "RKA_CTX_W_CENT",
            "RKA_CTX_W_RECENCY",
            "RKA_CTX_PI_LIFT",
            "RKA_CTX_RECENCY_SHAPE_N",
        ):
            monkeypatch.delenv(var, raising=False)
        ctx._reload_coefficients_from_env()

    def test_invalid_float_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Operator typo in env var (non-numeric) must not crash the
        engine; falls back to the documented default."""
        import rka.services.context as ctx

        monkeypatch.setenv("RKA_CTX_W_IMP", "not-a-float")
        ctx._reload_coefficients_from_env()
        assert ctx._W_IMPORTANCE == 0.5  # default preserved
        monkeypatch.delenv("RKA_CTX_W_IMP", raising=False)
        ctx._reload_coefficients_from_env()


# ---------------------------------------------------------------------------
# Phase-3.1 T1 — recency_score env-var-configurable shape
# (mis_01KS3EB2671CDD4V9RZCMYCEH1 T1; per dec_01KS3E6ZJXXV7542QPWZ9W8BQS)
# ---------------------------------------------------------------------------


class TestPhase3_1RecencyShape:
    """Phase-3.1 generalizes ``recency_score`` from hardcoded
    ``1/(1+days)`` to env-var-configurable ``1/(1+days/N)``. Default N=1
    is bit-identical to the pre-refactor formula (backward-compat). Larger
    N produces slower decay; the v2.5.4-D4 / corpus-refresh diagnosis
    identified the steep N=1 shape as the source of recency
    over-amplification (jrn_01KS0RM9VXT2HHXDN76VXKTFTS Brain sketch).

    Pure-function tests of ``_compute_recency_score(days, shape_n)`` —
    no DB fixtures, no clock dependence."""

    def test_shape_n1_matches_pre_phase_3_1_formula(self):
        """N=1 reproduces ``1/(1+days)`` bit-for-bit. This is the
        backward-compat default. Tested at the boundary values that
        appear in the Brain sketch's mechanism table
        (jrn_01KS0RM9VXT2HHXDN76VXKTFTS):

        ┌─────┬────────────────┐
        │ days│  1/(1+days)    │
        ├─────┼────────────────┤
        │   0 │ 1.000          │
        │   1 │ 0.500          │
        │   3 │ 0.250          │
        │   7 │ 0.125          │
        │  30 │ 0.032258...    │
        │  90 │ 0.010989...    │
        │ 365 │ 0.002732...    │
        └─────┴────────────────┘
        """
        from rka.services.context import _compute_recency_score

        cases = [
            (0.0, 1.0),
            (1.0, 0.5),
            (3.0, 0.25),
            (7.0, 0.125),
            (30.0, 1.0 / 31.0),
            (90.0, 1.0 / 91.0),
            (365.0, 1.0 / 366.0),
        ]
        for days, expected in cases:
            got = _compute_recency_score(days, 1.0)
            assert got == pytest.approx(expected, rel=1e-12), (
                f"N=1 must reproduce 1/(1+days) bit-for-bit; days={days}: "
                f"got {got!r}, expected {expected!r}."
            )

    def test_shape_n30_thirty_day_half_life(self):
        """N=30 produces a 30-day half-life: an entry that is 30 days old
        scores exactly 0.5 (versus 0.0323 at N=1). 90-day entries score
        0.25 (versus 0.011 at N=1). The Brain sketch table confirms these
        targets as the "smoother decay" lever for Phase-3.1's A/B sweep."""
        from rka.services.context import _compute_recency_score

        # 30-day half-life shape:
        assert _compute_recency_score(0.0, 30.0) == pytest.approx(1.0)
        assert _compute_recency_score(30.0, 30.0) == pytest.approx(0.5)
        assert _compute_recency_score(60.0, 30.0) == pytest.approx(1.0 / 3.0)
        assert _compute_recency_score(90.0, 30.0) == pytest.approx(0.25)
        # Compare against N=1 to confirm the shape difference is in the
        # expected direction (slower decay at higher N).
        assert _compute_recency_score(30.0, 30.0) > _compute_recency_score(
            30.0, 1.0
        ), "N=30 must produce a LARGER recency_score at 30 days than N=1."

    def test_shape_n365_year_half_life(self):
        """N=365 produces a year half-life: a 365-day-old entry scores
        exactly 0.5 (versus 0.0027 at N=1). This is the "most stable
        against DB drift" extreme of the sweep matrix."""
        from rka.services.context import _compute_recency_score

        assert _compute_recency_score(0.0, 365.0) == pytest.approx(1.0)
        assert _compute_recency_score(365.0, 365.0) == pytest.approx(0.5)
        # 730 days = 2 years = 1/3 at year-half-life shape.
        assert _compute_recency_score(730.0, 365.0) == pytest.approx(1.0 / 3.0)
        # Confirm the shape is monotonically slower-decaying than N=1.
        for days in [30.0, 90.0, 180.0, 365.0]:
            assert _compute_recency_score(days, 365.0) > _compute_recency_score(
                days, 1.0
            ), f"N=365 must produce a larger score than N=1 at {days} days."

    def test_env_var_recency_shape_n_loads_and_drives_score(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """``RKA_CTX_RECENCY_SHAPE_N`` env var feeds through
        ``_reload_coefficients_from_env`` into ``_RECENCY_SHAPE_N``, which
        the staticmethod ``ContextEngine._recency_score`` consults. End-
        to-end: set env, reload, score an entry, verify the shape changed.

        This is the production swap pattern the T4 sweep harness will use
        (set RKA_CTX_RECENCY_SHAPE_N=30 / 90 / 365 between configs).
        """
        import rka.services.context as ctx

        # Baseline: no env var → default N=1.
        monkeypatch.delenv("RKA_CTX_RECENCY_SHAPE_N", raising=False)
        ctx._reload_coefficients_from_env()
        assert ctx._RECENCY_SHAPE_N == 1.0, "default must be N=1.0"

        # Set N=30, reload, verify the constant changes.
        monkeypatch.setenv("RKA_CTX_RECENCY_SHAPE_N", "30")
        ctx._reload_coefficients_from_env()
        assert ctx._RECENCY_SHAPE_N == 30.0

        # A 30-day-old entry now scores 0.5 (not 0.0323 from N=1).
        from datetime import datetime, timedelta, timezone

        thirty_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = {"created_at": thirty_days_ago}
        score = ctx.ContextEngine._recency_score(entry)
        # Allow a small tolerance for the sub-second clock between
        # the fixture timestamp and `now` inside _recency_score.
        assert score == pytest.approx(0.5, abs=0.005), (
            f"At N=30, a 30-day-old entry should score ~0.5; got {score!r}."
        )

        # Cleanup: restore default for subsequent tests in the suite.
        monkeypatch.delenv("RKA_CTX_RECENCY_SHAPE_N", raising=False)
        ctx._reload_coefficients_from_env()

    def test_invalid_shape_n_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Operator typo (non-numeric or non-positive value) must not
        crash the engine. Non-numeric → ``_read_coeff`` logs a warning
        and returns the default. Zero/negative → ``_compute_recency_score``
        defensively reproduces the backward-compat N=1 shape."""
        import rka.services.context as ctx
        from rka.services.context import _compute_recency_score

        # Non-numeric env value → default preserved.
        monkeypatch.setenv("RKA_CTX_RECENCY_SHAPE_N", "not-a-float")
        ctx._reload_coefficients_from_env()
        assert ctx._RECENCY_SHAPE_N == 1.0

        # Zero / negative N → defensive fallback to N=1 inside the pure helper.
        assert _compute_recency_score(30.0, 0.0) == pytest.approx(1.0 / 31.0)
        assert _compute_recency_score(30.0, -1.0) == pytest.approx(1.0 / 31.0)

        # Cleanup.
        monkeypatch.delenv("RKA_CTX_RECENCY_SHAPE_N", raising=False)
        ctx._reload_coefficients_from_env()


# ---------------------------------------------------------------------------
# Phase-3.1 T2 — post-rank-merge bundle_K truncation (always-on)
# (mis_01KS3EB2671CDD4V9RZCMYCEH1 T2; per dec_01KS3E6ZJXXV7542QPWZ9W8BQS)
#
# Replaces the v2.5.4-D4 conditional truncation (gated by
# anchor_aware_present). Brain ratification of chk_01KS3FZDX78FD89CVR4K6VYJFK
# moved the policy to unconditional post-rank-merge cap with anchor-aware
# UNION protection. Default K=30 → 50.
# ---------------------------------------------------------------------------


class TestPhase3_1T2BundleTruncation:
    """Bundle-truncation policy. Always-on post-rank-merge cap at top-K
    (default 50, `RKA_CTX_BUNDLE_K` env override). The v2.5.4-D4
    `anchor_aware_present` gating has been removed — the policy is
    unconditional because the un-anchored backward-compat path left the
    efficiency floor structurally unreachable (corpus-refresh diagnosis
    + chk_01KS3FZDX78FD89CVR4K6VYJFK Brain ratification).

    Anchor-aware UNION is preserved: when `anchor_aware_ids` is provided,
    those entities pass through the cap regardless of weighted-sum
    rank."""

    @pytest_asyncio.fixture
    async def engine_with_many_entries(
        self, db_with_project: Database
    ) -> ContextEngine:
        """Database fixture with 70 journal entries — enough to exceed the
        new default K=50 cap by a margin large enough to test UNION
        protection of entities ranked >50."""
        db = db_with_project
        NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        # 70 normal-importance journal entries — exceeds default K=50.
        for i in range(70):
            await db.execute(
                f"""INSERT INTO journal (id, type, content, source, confidence,
                    importance, phase, project_id, created_at, updated_at)
                   VALUES (?, 'note', ?, 'executor', 'verified', 'normal',
                           'phase_1', 'proj_default', {NOW}, {NOW})""",
                [f"jrn_d4_{i:03d}", f"Truncation test entry {i}"],
            )
        await db.commit()
        search = SearchService(db=db, embeddings=None)
        return ContextEngine(db=db, search=search, llm=None)

    async def test_default_bundle_k_is_80_cfg11_winner(self):
        """Phase-3.1 evolution of the bundle_K default:
        - v2.5.4 D4: K=30 (conditional on anchor_aware_present)
        - Phase-3.1 T2: K=50 (always-on truncation)
        - Phase-3.1 T5 cfg11 winner: K=80 (Pareto-best on recall ×
          efficiency frontier per chk_01KS3K40N6JRHV118969RMBNF0
          Brain ratification)

        K=80 hits the structural recall ceiling 0.822 (vs K=30/K=50
        which produce 0.713/0.783); ordering ranks well above floor
        (0.403 vs 0.363 floor); efficiency at 0.034 (still below 0.13
        floor — structural; deferred to Phase-3.2)."""
        from rka.services.context import _DEFAULT_BUNDLE_K, _read_bundle_k

        assert _DEFAULT_BUNDLE_K == 80, (
            "Phase-3.1 T5 default bundle_K is 80 (cfg11 sweep winner)."
        )
        # No env var set → read returns the default.
        import os

        os.environ.pop("RKA_CTX_BUNDLE_K", None)
        assert _read_bundle_k() == 80

    async def test_truncation_always_applied_after_phase_3_1_t2(
        self, engine_with_many_entries: ContextEngine
    ):
        """Phase-3.1 T2: truncation is unconditional. Both the un-anchored
        path (anchor_aware_present omitted/False, the v2.5.4-D4
        backward-compat case) and the anchor-aware-present path MUST cap
        at K=50. The fixture has 70 entries → bundle size 50 in both
        cases."""
        # Un-anchored path (v2.5.4-D4 used to skip truncation here):
        pkg_unanchored = await engine_with_many_entries.get_context()
        assert len(pkg_unanchored.sources) == 50, (
            f"Phase-3.1 T2: un-anchored path MUST also cap at K=50 (was "
            f"un-truncated under v2.5.4 D4); got "
            f"{len(pkg_unanchored.sources)} entries."
        )

        # Anchor-aware-present=True (same K=50 since the gating was removed):
        pkg_anchored = await engine_with_many_entries.get_context(
            anchor_aware_present=True
        )
        assert len(pkg_anchored.sources) == 50, (
            f"Phase-3.1 T2: anchor_aware_present=True path also caps at "
            f"K=50; got {len(pkg_anchored.sources)} entries."
        )

    async def test_env_var_overrides_default_k(
        self,
        engine_with_many_entries: ContextEngine,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """`RKA_CTX_BUNDLE_K` env override drives the cap. Sweep harness
        uses this for the bundle_K dimension of the 64-config matrix
        (K ∈ {30, 50, 80, 150} per Brain ratification)."""
        monkeypatch.setenv("RKA_CTX_BUNDLE_K", "30")
        pkg = await engine_with_many_entries.get_context()
        assert len(pkg.sources) == 30, (
            f"Phase-3.1 T2 RKA_CTX_BUNDLE_K=30 override: expected 30 "
            f"entries; got {len(pkg.sources)}. Fixture has 70 entries so "
            "K=30 truncates."
        )

    async def test_anchor_aware_outputs_pass_through_above_k(
        self,
        engine_with_many_entries: ContextEngine,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Anchor-aware-tool outputs UNION through the top-K cap regardless
        of weighted-sum rank. With K=30 and the SQL-LIMITed 50 candidates,
        IDs at rank [30..49] are normally truncated; passing them via
        anchor_aware_ids restores them.

        (Note: the journal SQL has LIMIT 50, so candidates max out at 50
        even when the fixture has 70 entries. Testing UNION with K=30
        keeps the candidate count above K while leaving room for protected
        entries that would otherwise be truncated.)"""
        monkeypatch.setenv("RKA_CTX_BUNDLE_K", "30")

        # The fixture inserts i=0..69; SQL LIMIT 50 + ORDER BY created_at
        # DESC + ROWID-tiebreak → candidates ≈ jrn_d4_000..049 (the first
        # 50 inserted, sharing the same created_at). jrn_d4_049 is at
        # rank ~49, well outside K=30.
        outside_top_k_id = "jrn_d4_049"

        pkg = await engine_with_many_entries.get_context(
            anchor_aware_ids=[outside_top_k_id],
        )
        assert outside_top_k_id in pkg.sources, (
            f"Anchor-aware UNION: id {outside_top_k_id!r} (rank ~49, "
            f"below K=30) MUST pass through truncation when passed via "
            f"anchor_aware_ids. Got sources={pkg.sources[:3]}..."
            f"{pkg.sources[-3:]}"
        )
        # Bundle size = K (30) + 1 extra anchor-aware UNION = 31.
        assert len(pkg.sources) == 31, (
            f"Bundle size: top-K=30 + 1 UNION extra = 31; got "
            f"{len(pkg.sources)}."
        )

    async def test_anchor_aware_present_no_longer_gates_truncation(
        self, engine_with_many_entries: ContextEngine
    ):
        """The v2.5.4-D4 `anchor_aware_present` parameter is retained for
        API backward-compat (Pydantic models, REST callers, the eval-v2
        runner's `_call_get_context`) but is now a no-op for the truncation
        decision. Truncation behavior MUST be identical whether the param
        is True, False, or omitted."""
        pkg_omitted = await engine_with_many_entries.get_context()
        pkg_false = await engine_with_many_entries.get_context(
            anchor_aware_present=False
        )
        pkg_true = await engine_with_many_entries.get_context(
            anchor_aware_present=True
        )
        # All three produce identical bundle sizes — anchor_aware_present
        # no longer changes the truncation path.
        assert (
            len(pkg_omitted.sources)
            == len(pkg_false.sources)
            == len(pkg_true.sources)
            == 50
        ), (
            "Phase-3.1 T2: anchor_aware_present is no-op for truncation; "
            f"omitted={len(pkg_omitted.sources)}, "
            f"False={len(pkg_false.sources)}, "
            f"True={len(pkg_true.sources)} — all must equal 50."
        )
