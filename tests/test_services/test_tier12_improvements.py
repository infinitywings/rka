"""Tests for the eval-v3 tier-1/tier-2 follow-ups (2026-06-11).

Covers: supersession graph edges (notes path + decision orphan guard),
knowledge-pack prose ID rewriting, multi-hop seed protection, FTS query
stopword stripping, tag-aware search, and overview-bundle pinning.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.models.decision import DecisionCreate, DecisionUpdate
from rka.models.journal import JournalEntryCreate as NoteCreate
from rka.services.context import ContextEngine
from rka.services.decisions import DecisionService
from rka.services.graph import GraphService
from rka.services.knowledge_pack import KnowledgePackService
from rka.services.notes import NoteService
from rka.services.search import SearchService


# ---------------------------------------------------------------------------
# Supersession edges
# ---------------------------------------------------------------------------


class TestJournalSupersedeEdge:
    @pytest.mark.asyncio
    async def test_note_supersede_writes_entity_link(self, db: Database):
        svc = NoteService(db=db, llm=None, embeddings=None)
        old = await svc.create(NoteCreate(content="old belief", phase="phase_1"))
        new = await svc.create(
            NoteCreate(content="corrected belief", phase="phase_1", supersedes=old.id)
        )
        row = await db.fetchone(
            """SELECT * FROM entity_links
               WHERE source_id = ? AND link_type = 'supersedes' AND target_id = ?""",
            [new.id, old.id],
        )
        assert row is not None, "supersession must be visible to graph traversal"


class TestDecisionOrphanSupersedeGuard:
    @pytest.mark.asyncio
    async def test_update_to_superseded_without_successor_raises(self, db: Database):
        svc = DecisionService(db, project_id="proj_default")
        dec = await svc.create(
            DecisionCreate(question="q", phase="design", decided_by="brain")
        )
        with pytest.raises(ValueError, match="supersede_decision"):
            await svc.update(dec.id, DecisionUpdate(status="superseded"))

    @pytest.mark.asyncio
    async def test_update_with_existing_pointer_is_allowed(self, db: Database):
        svc = DecisionService(db, project_id="proj_default")
        old = await svc.create(
            DecisionCreate(question="old", phase="design", decided_by="brain")
        )
        await svc.supersede_decision(
            old.id,
            DecisionCreate(question="new", phase="design", decided_by="brain"),
        )
        # Pointer exists now; a redundant status update must not raise.
        updated = await svc.update(old.id, DecisionUpdate(status="superseded"))
        assert updated.status == "superseded"


# ---------------------------------------------------------------------------
# Knowledge-pack prose ID rewriting
# ---------------------------------------------------------------------------


class TestPackProseRewriting:
    def _svc(self, db: Database) -> KnowledgePackService:
        return KnowledgePackService(db)

    @pytest.mark.asyncio
    async def test_embedded_ids_in_prose_are_rekeyed(self, db: Database):
        svc = self._svc(db)
        old_dec = "dec_01AAAAAAAAAAAAAAAAAAAAAAAA"
        new_dec = "dec_01BBBBBBBBBBBBBBBBBBBBBBBB"
        row = {
            "id": "jrn_01CCCCCCCCCCCCCCCCCCCCCCCC",
            "project_id": "prj_src",
            "content": f"This supersedes {old_dec} per the review.",
        }
        out = svc._remap_row(
            "journal",
            row,
            id_map={old_dec: new_dec, row["id"]: "jrn_01DDDDDDDDDDDDDDDDDDDDDDDD"},
            source_project_id="prj_src",
            target_project_id="prj_tgt",
        )
        assert new_dec in out["content"]
        assert old_dec not in out["content"]

    @pytest.mark.asyncio
    async def test_unknown_ids_in_prose_pass_through(self, db: Database):
        svc = self._svc(db)
        foreign = "dec_01ZZZZZZZZZZZZZZZZZZZZZZZZ"
        row = {"id": "jrn_01CCCCCCCCCCCCCCCCCCCCCCCC", "project_id": "prj_src",
               "content": f"references {foreign} from another project"}
        out = svc._remap_row(
            "journal", row,
            id_map={row["id"]: "jrn_01DDDDDDDDDDDDDDDDDDDDDDDD"},
            source_project_id="prj_src", target_project_id="prj_tgt",
        )
        assert foreign in out["content"]


# ---------------------------------------------------------------------------
# Multi-hop seed protection
# ---------------------------------------------------------------------------


class TestMultiHopSeedProtection:
    @pytest_asyncio.fixture
    async def graph_with_contradiction(self, db: Database) -> GraphService:
        # Seed claim A; B contradicts A (claim_edges weight 1.1 > seed 1.0),
        # so a plain top-N cut at max_nodes=1 would evict the seed.
        await db.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
            "VALUES ('jrn_src', 'note', 'source entry', 'brain', 'hypothesis', "
            "'phase_1', 'proj_default')"
        )
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, project_id) "
            "VALUES ('clm_A', 'jrn_src', 'evidence', 'claim A', 'proj_default')"
        )
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, project_id) "
            "VALUES ('clm_B', 'jrn_src', 'evidence', 'claim B', 'proj_default')"
        )
        await db.execute(
            "INSERT INTO claim_edges (id, source_claim_id, target_claim_id, relation, project_id) "
            "VALUES ('ce_1', 'clm_B', 'clm_A', 'contradicts', 'proj_default')"
        )
        await db.commit()
        return GraphService(db)

    @pytest.mark.asyncio
    async def test_seed_survives_cap(self, graph_with_contradiction: GraphService):
        result = await graph_with_contradiction.multi_hop_retrieval(
            "", seeds=["clm_A"], max_depth=2, max_nodes=1,
        )
        ids = {n["id"] for n in result["nodes"]}
        assert "clm_A" in ids, "seed must never be displaced by expansion"


# ---------------------------------------------------------------------------
# FTS query stopword stripping
# ---------------------------------------------------------------------------


class TestQueryStopwords:
    def test_framing_words_stripped(self, monkeypatch):
        monkeypatch.delenv("RKA_FTS_QUERY_MODE", raising=False)
        q = SearchService._sanitize_fts_query(
            "I want to write a report about embedding backends"
        )
        assert '"embedding" OR "backends"' == q

    def test_all_stopword_query_falls_through_unstripped(self, monkeypatch):
        monkeypatch.delenv("RKA_FTS_QUERY_MODE", raising=False)
        # Nothing but framing words: keep the words rather than emit an
        # empty (match-nothing) FTS expression.
        assert SearchService._sanitize_fts_query("what is this") == \
            '"what" OR "is" OR "this"'

    def test_domain_terms_survive(self, monkeypatch):
        monkeypatch.delenv("RKA_FTS_QUERY_MODE", raising=False)
        q = SearchService._sanitize_fts_query("how does the worker lease jobs")
        assert '"worker"' in q and '"lease"' in q and '"jobs"' in q
        assert '"how"' not in q and '"the"' not in q


# ---------------------------------------------------------------------------
# Tag-aware search
# ---------------------------------------------------------------------------


class TestTagSearch:
    @pytest_asyncio.fixture
    async def svc_with_tagged_entity(self, db: Database) -> SearchService:
        await db.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
            "VALUES ('jrn_tagged', 'note', 'weekly sync outcomes', 'brain', "
            "'hypothesis', 'phase_1', 'proj_default')"
        )
        await db.execute(
            "INSERT INTO tags (tag, entity_type, entity_id) "
            "VALUES ('eval-harness', 'journal', 'jrn_tagged')"
        )
        await db.commit()
        return SearchService(db=db, embeddings=None)

    @pytest.mark.asyncio
    async def test_tag_segment_match_surfaces_entity(self, svc_with_tagged_entity):
        # 'harness' matches the second hyphen segment of 'eval-harness';
        # the journal CONTENT contains neither token, so FTS/LIKE cannot
        # find it — only the tag source can.
        hits = await svc_with_tagged_entity._tag_search(
            "harness", ["journal"], limit=10
        )
        assert any(h.entity_id == "jrn_tagged" for h in hits)
        assert "eval-harness" in hits[0].snippet

    @pytest.mark.asyncio
    async def test_tag_hits_merge_into_search(self, svc_with_tagged_entity):
        results = await svc_with_tagged_entity.search("harness", limit=10)
        assert any(h.entity_id == "jrn_tagged" for h in results)

    @pytest.mark.asyncio
    async def test_other_project_entities_filtered(self, db: Database):
        await db.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
            "VALUES ('jrn_foreign', 'note', 'other project', 'brain', "
            "'hypothesis', 'phase_1', 'proj_other')"
        )
        await db.execute(
            "INSERT INTO tags (tag, entity_type, entity_id) "
            "VALUES ('eval-harness', 'journal', 'jrn_foreign')"
        )
        await db.commit()
        svc = SearchService(db=db, embeddings=None)  # proj_default scope
        hits = await svc._tag_search("harness", ["journal"], limit=10)
        assert not any(h.entity_id == "jrn_foreign" for h in hits)


# ---------------------------------------------------------------------------
# Overview-bundle pinning
# ---------------------------------------------------------------------------


class TestOverviewPinning:
    @pytest_asyncio.fixture
    async def engine_with_buried_critical(self, db_with_project: Database) -> ContextEngine:
        db = db_with_project
        NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        OLD = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-90 days')"
        # An OLD critical PI directive (no recency, no centrality) ...
        await db.execute(
            f"""INSERT INTO journal (id, type, content, source, confidence, importance,
                phase, project_id, created_at, updated_at)
               VALUES ('jrn_pin_me', 'directive', 'never push to main without ratification',
                       'pi', 'verified', 'critical', 'phase_1', 'proj_default', {OLD}, {OLD})"""
        )
        # ... buried under many recent high-importance entries.
        for i in range(8):
            await db.execute(
                f"""INSERT INTO journal (id, type, content, source, confidence, importance,
                    phase, project_id, created_at, updated_at)
                   VALUES ('jrn_recent_{i}', 'note', 'recent finding {i}', 'pi',
                           'verified', 'high', 'phase_1', 'proj_default', {NOW}, {NOW})"""
            )
        await db.commit()
        search = SearchService(db=db, embeddings=None)
        return ContextEngine(db=db, search=search, llm=None)

    @pytest.mark.asyncio
    async def test_critical_directive_pinned_first_and_survives_cap(
        self, engine_with_buried_critical: ContextEngine, monkeypatch
    ):
        monkeypatch.setenv("RKA_CTX_BUNDLE_K", "3")
        pkg = await engine_with_buried_critical.get_context(project_id="proj_default")
        assert "jrn_pin_me" in pkg.sources, "pinned entry must survive the K cap"
        assert pkg.sources[0] == "jrn_pin_me", "pinned tier must lead the bundle"
