"""Tests for the GraphService."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.graph import GraphService


@pytest_asyncio.fixture
async def graph_svc(db: Database) -> GraphService:
    """GraphService with seed data: journal, decision, mission, literature, entity_links."""
    # Seed entities
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["jrn_001", "finding", "Side-channel observation on IoT", "pi", "hypothesis", "phase_1", "proj_default"],
    )
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["jrn_002", "insight", "Amplification factor is sqrt(n)", "brain", "tested", "phase_1", "proj_default"],
    )
    await db.execute(
        "INSERT INTO decisions (id, question, rationale, decided_by, status, phase, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["dec_001", "Statistical vs ML approach", "Balance accuracy", "brain", "active", "phase_1", "proj_default"],
    )
    await db.execute(
        "INSERT INTO missions (id, objective, phase, status, project_id) VALUES (?, ?, ?, ?, ?)",
        ["mis_001", "Survey timing methodologies", "phase_1", "active", "proj_default"],
    )
    await db.execute(
        "INSERT INTO literature (id, title, status, project_id) VALUES (?, ?, ?, ?)",
        ["lit_001", "Remote Timing Attacks", "reading", "proj_default"],
    )

    # Seed entity_links
    await db.execute(
        "INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, target_id, created_by, project_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["lnk_001", "journal", "jrn_001", "references", "decision", "dec_001", "brain", "proj_default"],
    )
    await db.execute(
        "INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, target_id, created_by, project_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["lnk_002", "journal", "jrn_001", "cites", "literature", "lit_001", "brain", "proj_default"],
    )
    await db.execute(
        "INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, target_id, created_by, project_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["lnk_003", "decision", "dec_001", "triggered", "mission", "mis_001", "brain", "proj_default"],
    )

    # Different project data for isolation checks
    await db.execute(
        "INSERT INTO decisions (id, question, rationale, decided_by, status, phase, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["dec_999", "Other project only", "N/A", "brain", "active", "phase_x", "proj_other"],
    )
    await db.commit()

    return GraphService(db=db)


class TestFullGraph:
    @pytest.mark.asyncio
    async def test_returns_all_nodes_and_edges(self, graph_svc: GraphService):
        result = await graph_svc.get_full_graph()
        node_ids = {n["id"] for n in result["nodes"]}
        assert "jrn_001" in node_ids
        assert "dec_001" in node_ids
        assert "mis_001" in node_ids
        assert "lit_001" in node_ids
        assert len(result["edges"]) == 3

    @pytest.mark.asyncio
    async def test_includes_orphan_nodes(self, graph_svc: GraphService):
        """jrn_002 has no links but should still appear."""
        result = await graph_svc.get_full_graph()
        node_ids = {n["id"] for n in result["nodes"]}
        assert "jrn_002" in node_ids

    @pytest.mark.asyncio
    async def test_filter_by_type(self, graph_svc: GraphService):
        result = await graph_svc.get_full_graph(include_types=["journal"])
        types = {n["type"] for n in result["nodes"]}
        assert types == {"journal"}
        # Edges between non-journal nodes should be excluded
        for e in result["edges"]:
            assert e["source"].startswith("jrn") or e["target"].startswith("jrn")

    @pytest.mark.asyncio
    async def test_edge_has_link_type(self, graph_svc: GraphService):
        result = await graph_svc.get_full_graph()
        link_types = {e["link_type"] for e in result["edges"]}
        assert "references" in link_types
        assert "cites" in link_types
        assert "triggered" in link_types

    @pytest.mark.asyncio
    async def test_scopes_rows_by_project_id(self, graph_svc: GraphService):
        result = await graph_svc.get_full_graph(project_id="proj_default")
        node_ids = {n["id"] for n in result["nodes"]}
        assert "dec_999" not in node_ids


class TestEgoGraph:
    @pytest.mark.asyncio
    async def test_ego_returns_neighbors(self, graph_svc: GraphService):
        result = await graph_svc.get_ego_graph("jrn_001", depth=1)
        node_ids = {n["id"] for n in result["nodes"]}
        assert "jrn_001" in node_ids
        assert "dec_001" in node_ids  # linked via references
        assert "lit_001" in node_ids  # linked via cites
        assert len(result["edges"]) >= 2

    @pytest.mark.asyncio
    async def test_ego_depth_2(self, graph_svc: GraphService):
        result = await graph_svc.get_ego_graph("jrn_001", depth=2)
        node_ids = {n["id"] for n in result["nodes"]}
        # depth 2 should reach mis_001 via dec_001
        assert "mis_001" in node_ids

    @pytest.mark.asyncio
    async def test_ego_no_links(self, graph_svc: GraphService):
        result = await graph_svc.get_ego_graph("jrn_002", depth=1)
        # jrn_002 has no links, should return just itself
        node_ids = {n["id"] for n in result["nodes"]}
        assert "jrn_002" in node_ids
        assert len(result["edges"]) == 0


class TestEgoGraphClaimEdges:
    @pytest_asyncio.fixture
    async def cluster_svc(self, db: Database) -> GraphService:
        """GraphService seeded with a cluster and two member claims via claim_edges."""
        await db.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["jrn_src", "finding", "Source entry for test claims", "brain", "hypothesis", "phase_1", "proj_default"],
        )
        await db.execute(
            "INSERT INTO evidence_clusters (id, label, project_id) VALUES (?, ?, ?)",
            ["ecl_test", "Test cluster", "proj_default"],
        )
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, project_id) VALUES (?, ?, ?, ?, ?)",
            ["clm_a", "jrn_src", "evidence", "Claim A", "proj_default"],
        )
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, project_id) VALUES (?, ?, ?, ?, ?)",
            ["clm_b", "jrn_src", "evidence", "Claim B", "proj_default"],
        )
        await db.execute(
            "INSERT INTO claim_edges (id, source_claim_id, cluster_id, relation, project_id) VALUES (?, ?, ?, ?, ?)",
            ["ced_a", "clm_a", "ecl_test", "member_of", "proj_default"],
        )
        await db.execute(
            "INSERT INTO claim_edges (id, source_claim_id, cluster_id, relation, project_id) VALUES (?, ?, ?, ?, ?)",
            ["ced_b", "clm_b", "ecl_test", "member_of", "proj_default"],
        )
        await db.commit()
        return GraphService(db=db)

    @pytest.mark.asyncio
    async def test_cluster_ego_includes_member_claims(self, cluster_svc: GraphService):
        result = await cluster_svc.get_ego_graph("ecl_test", depth=1)
        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == {"ecl_test", "clm_a", "clm_b"}
        edge_types = [e["link_type"] for e in result["edges"]]
        assert edge_types.count("member_of") == 2
        for edge in result["edges"]:
            assert edge["target"] == "ecl_test"
            assert edge["source"] in {"clm_a", "clm_b"}


class TestDecisionTree:
    @pytest.mark.asyncio
    async def test_returns_decision_with_linked_entities(self, graph_svc: GraphService):
        tree = await graph_svc.get_decision_tree()
        assert len(tree) >= 1
        dec = tree[0]
        assert dec["id"] == "dec_001"
        # Should have linked entities from entity_links
        linked_ids = {le["id"] for le in dec["linked_entities"]}
        assert "jrn_001" in linked_ids or "mis_001" in linked_ids


class TestStats:
    @pytest.mark.asyncio
    async def test_returns_counts(self, graph_svc: GraphService):
        stats = await graph_svc.get_stats()
        assert stats["total_nodes"] == 5  # 2 journal + 1 dec + 1 mis + 1 lit
        assert stats["total_edges"] == 3
        assert stats["node_counts"]["journal"] == 2
        assert stats["edge_counts_by_type"]["cites"] == 1


class TestCondensedView:
    @pytest.mark.asyncio
    async def test_refresh_condensed_view_materializes_keynodes(self, graph_svc: GraphService, db: Database):
        payload = await graph_svc.refresh_condensed_view(top_per_kind=3, min_importance=0.4)

        assert payload["view"] == "condensed"
        assert payload["nodes"]

        rows = await db.fetchall("SELECT id, kind, node_refs FROM keynodes")
        assert rows
        assert any(r["kind"] == "decision" for r in rows)

    @pytest.mark.asyncio
    async def test_get_condensed_view_uses_cached_graph_view(self, graph_svc: GraphService):
        await graph_svc.refresh_condensed_view(top_per_kind=3, min_importance=0.4)
        payload = await graph_svc.get_graph_view(view="condensed")

        assert payload["view"] == "condensed"
        assert isinstance(payload["nodes"], list)
        assert isinstance(payload["edges"], list)

    @pytest.mark.asyncio
    async def test_refresh_failure_restores_previous_materialization(
        self,
        graph_svc: GraphService,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await graph_svc.refresh_condensed_view(
            top_per_kind=3,
            min_importance=0.4,
        )
        previous_keynodes = await db.fetchall(
            "SELECT id FROM keynodes WHERE blessed = 0 ORDER BY id"
        )
        previous_views = await db.fetchall(
            "SELECT id FROM graph_views ORDER BY id"
        )

        real_execute = db.execute

        async def fail_view_insert(sql, params=None):
            if "INSERT INTO graph_views" in sql:
                raise RuntimeError("injected graph-view insert failure")
            return await real_execute(sql, params)

        monkeypatch.setattr(db, "execute", fail_view_insert)
        with pytest.raises(
            RuntimeError,
            match="injected graph-view insert failure",
        ):
            await graph_svc.refresh_condensed_view(
                top_per_kind=3,
                min_importance=0.4,
            )

        assert await db.fetchall(
            "SELECT id FROM keynodes WHERE blessed = 0 ORDER BY id"
        ) == previous_keynodes
        assert await db.fetchall(
            "SELECT id FROM graph_views ORDER BY id"
        ) == previous_views


class TestGuessType:
    def test_known_prefixes(self):
        assert GraphService._guess_type_from_id("jrn_001") == "journal"
        assert GraphService._guess_type_from_id("dec_abc") == "decision"
        assert GraphService._guess_type_from_id("lit_xyz") == "literature"
        assert GraphService._guess_type_from_id("mis_123") == "mission"
        assert GraphService._guess_type_from_id("chk_foo") == "checkpoint"

    def test_unknown_prefix(self):
        assert GraphService._guess_type_from_id("zzz_bar") == "unknown"


# ---------------------------------------------------------------------------
# v2.5.2 — cluster→parent-RQ traversal (migration 023 + 'answers' link_type)
# ---------------------------------------------------------------------------


class TestClusterAnswersTraversal:
    """Cluster anchors must surface the parent research-question via the
    new 'answers' edge type. Pre-v2.5.2 these tests would fail because
    no 'answers' edges existed in entity_links (FK column was invisible
    to graph traversal). Anchor IDs are Eval-v2 S7's anchor pair so the
    regression-lock matches the surfaced finding's anchors verbatim.

    Provenance: mission mis_01KRS1D8C0E2FP52D0P6JNB3SX (D3); decision
    dec_01KRS1ADPD4W6AW2X54MKVXMCR.
    """

    # Eval-v2 S7's anchor pair (eval-harness/v2/corpus/scenarios.jsonl →
    # brain-contradiction-staleness-vs-validation).
    S7_CLUSTER_ID = "ecl_01KP4PK7VPN8YFR50PSFXPGTQ0"
    S7_RQ_ID = "dec_01KP4P4QSSNZCTEHVT6QR7ZRYD"

    @pytest_asyncio.fixture
    async def graph_svc_with_s7_cluster(self, db: Database) -> GraphService:
        """Seed the S7 cluster + parent-RQ + the 'answers' entity_link.

        This is the minimal fixture that exercises the post-migration-023
        state. The cluster has a non-null FK and a parallel entity_link
        — matching what migration 023 produces in production.
        """
        await db.execute(
            "INSERT INTO decisions (id, question, decided_by, status, phase, project_id) VALUES (?, ?, ?, ?, ?, ?)",
            [self.S7_RQ_ID, "S7 research question", "brain", "active", "phase_1", "proj_default"],
        )
        await db.execute(
            "INSERT INTO evidence_clusters (id, research_question_id, label, project_id) VALUES (?, ?, ?, ?)",
            [self.S7_CLUSTER_ID, self.S7_RQ_ID, "S7 cluster", "proj_default"],
        )
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id,
                link_weight, created_by, project_id)
               VALUES (?, 'cluster', ?, 'answers', 'decision', ?, 1.0, 'migration_023', 'proj_default')""",
            ["lnk_test_s7_answers", self.S7_CLUSTER_ID, self.S7_RQ_ID],
        )
        await db.commit()
        return GraphService(db=db)

    @pytest.mark.asyncio
    async def test_ego_graph_from_cluster_anchor_includes_parent_rq(
        self, graph_svc_with_s7_cluster: GraphService
    ):
        """T4 (a): get_ego_graph anchored at the S7 cluster MUST return
        the parent-RQ decision in nodes. Pre-v2.5.2 this returned only
        the cluster itself (cluster's `answers` edge didn't exist)."""
        result = await graph_svc_with_s7_cluster.get_ego_graph(
            entity_id=self.S7_CLUSTER_ID, depth=1
        )
        node_ids = {n["id"] for n in result["nodes"]}
        assert self.S7_RQ_ID in node_ids, (
            f"ego_graph from cluster anchor must include parent RQ "
            f"{self.S7_RQ_ID}; got nodes {sorted(node_ids)}"
        )

    @pytest.mark.asyncio
    async def test_multi_hop_seeds_only_cluster_traversal_returns_parent_rq(
        self, graph_svc_with_s7_cluster: GraphService
    ):
        """T4 (b): multi_hop_retrieval with seeds=[cluster_id] (the
        v2.5.1 seeds-only invocation surface) MUST surface the parent-RQ
        decision. Combined regression-lock: v2.5.1 schema relaxation +
        v2.5.2 'answers' edge."""
        result = await graph_svc_with_s7_cluster.multi_hop_retrieval(
            query="",
            seeds=[self.S7_CLUSTER_ID],
            max_depth=2,
            max_nodes=50,
            project_id="proj_default",
        )
        node_ids = {n["id"] for n in result["nodes"]}
        assert self.S7_RQ_ID in node_ids, (
            f"multi_hop from cluster seed must include parent RQ "
            f"{self.S7_RQ_ID}; got nodes {sorted(node_ids)}"
        )


class TestClusterServiceAnswersLinkHook:
    """T3 hook (ClusterService.create/.update writing 'answers' entity_link).

    T4 (c) per spec: isolated unit test that exercises the hook in
    create — assert one entity_link with link_type='answers' lands when
    a cluster is created with a non-null research_question_id.
    """

    @pytest.mark.asyncio
    async def test_cluster_service_creates_entity_link_alongside_fk(
        self, db: Database
    ):
        from rka.models import EvidenceClusterCreate
        from rka.services.clusters import ClusterService

        # Seed a parent-RQ decision the cluster can point at.
        rq_id = "dec_test_t3_hook_rq"
        await db.execute(
            """INSERT INTO decisions
               (id, question, kind, decided_by, status, phase, project_id)
               VALUES (?, ?, 'research_question', ?, ?, ?, ?)""",
            [
                rq_id,
                "T3 hook RQ",
                "brain",
                "active",
                "phase_1",
                "proj_default",
            ],
        )
        await db.commit()

        svc = ClusterService(db=db)
        cluster = await svc.create(
            EvidenceClusterCreate(
                research_question_id=rq_id,
                label="T3 hook test cluster",
                synthesis="seed",
                confidence="emerging",
            )
        )

        rows = await db.fetchall(
            """SELECT source_id, target_id, link_type
               FROM entity_links
               WHERE link_type = 'answers' AND source_id = ?""",
            [cluster.id],
        )
        assert len(rows) == 1, (
            f"ClusterService.create should write exactly one 'answers' "
            f"entity_link when FK is set; got {len(rows)} rows"
        )
        assert rows[0]["target_id"] == rq_id

    @pytest.mark.asyncio
    async def test_cluster_service_skips_link_when_fk_is_null(self, db: Database):
        """The hook is gated on a non-null FK; a cluster created without
        an RQ should not emit a link (no orphan link target)."""
        from rka.models import EvidenceClusterCreate
        from rka.services.clusters import ClusterService

        svc = ClusterService(db=db)
        cluster = await svc.create(
            EvidenceClusterCreate(
                research_question_id=None,
                label="Cluster without RQ",
                synthesis="seed",
                confidence="emerging",
            )
        )
        rows = await db.fetchall(
            "SELECT 1 FROM entity_links WHERE link_type = 'answers' AND source_id = ?",
            [cluster.id],
        )
        assert rows == [], "no link should be emitted when FK is NULL"

    @pytest.mark.asyncio
    async def test_cluster_create_rejects_foreign_project_rq(
        self,
        db: Database,
    ):
        from rka.models import EvidenceClusterCreate
        from rka.services.clusters import ClusterService

        rq_id = "dec_cluster_foreign_create_rq"
        await db.execute(
            """INSERT INTO decisions
               (id, question, kind, decided_by, status, phase, project_id)
               VALUES (?, ?, 'research_question', 'brain', 'active',
                       'phase_1', 'proj_foreign')""",
            [rq_id, "A foreign project's research question"],
        )
        await db.commit()

        svc = ClusterService(db=db, project_id="proj_default")
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.create(
                EvidenceClusterCreate(
                    research_question_id=rq_id,
                    label="Foreign-RQ cluster must not persist",
                )
            )

        assert await db.fetchone(
            "SELECT id FROM evidence_clusters WHERE label = ?",
            ["Foreign-RQ cluster must not persist"],
        ) is None
        assert await db.fetchone(
            """SELECT id FROM entity_links
               WHERE source_type = 'cluster' AND target_id = ?""",
            [rq_id],
        ) is None

    @pytest.mark.asyncio
    async def test_cluster_update_replaces_then_clears_answers_projection(
        self,
        db: Database,
    ):
        from rka.models import EvidenceClusterCreate, EvidenceClusterUpdate
        from rka.services.clusters import ClusterService

        old_rq_id = "dec_cluster_exact_old_rq"
        new_rq_id = "dec_cluster_exact_new_rq"
        for rq_id, question in (
            (old_rq_id, "Original exact-projection question"),
            (new_rq_id, "Replacement exact-projection question"),
        ):
            await db.execute(
                """INSERT INTO decisions
                   (id, question, kind, decided_by, status, phase, project_id)
                   VALUES (?, ?, 'research_question', 'brain', 'active',
                           'phase_1', 'proj_default')""",
                [rq_id, question],
            )
        await db.commit()

        svc = ClusterService(db=db)
        cluster = await svc.create(
            EvidenceClusterCreate(
                research_question_id=old_rq_id,
                label="Exact answers projection",
            )
        )
        updated = await svc.update(
            cluster.id,
            EvidenceClusterUpdate(research_question_id=new_rq_id),
        )
        assert updated.research_question_id == new_rq_id
        assert await db.fetchall(
            """SELECT target_id FROM entity_links
               WHERE project_id = 'proj_default'
                 AND source_type = 'cluster' AND source_id = ?
                 AND link_type = 'answers' AND target_type = 'decision'
               ORDER BY target_id""",
            [cluster.id],
        ) == [{"target_id": new_rq_id}]

        cleared = await svc.update(
            cluster.id,
            EvidenceClusterUpdate(research_question_id=None),
        )
        assert cleared.research_question_id is None
        assert await db.fetchall(
            """SELECT target_id FROM entity_links
               WHERE project_id = 'proj_default'
                 AND source_type = 'cluster' AND source_id = ?
                 AND link_type = 'answers' AND target_type = 'decision'""",
            [cluster.id],
        ) == []

    @pytest.mark.asyncio
    async def test_cluster_update_rejects_foreign_cluster(
        self,
        db: Database,
    ):
        from rka.models import EvidenceClusterUpdate
        from rka.services.clusters import ClusterNotFoundError, ClusterService

        cluster_id = "ecl_foreign_update_scope"
        await db.execute(
            """INSERT INTO evidence_clusters
               (id, label, synthesis, project_id)
               VALUES (?, 'Foreign cluster', 'must remain unchanged',
                       'proj_foreign')""",
            [cluster_id],
        )
        await db.commit()

        svc = ClusterService(db=db, project_id="proj_default")
        with pytest.raises(ClusterNotFoundError, match="proj_default"):
            await svc.update(
                "ecl_missing_update_scope",
                EvidenceClusterUpdate(),
            )
        with pytest.raises(ClusterNotFoundError, match="proj_default"):
            await svc.update(
                cluster_id,
                EvidenceClusterUpdate(label="Cross-project overwrite"),
            )

        assert await db.fetchone(
            """SELECT label, synthesis, project_id FROM evidence_clusters
               WHERE id = ?""",
            [cluster_id],
        ) == {
            "label": "Foreign cluster",
            "synthesis": "must remain unchanged",
            "project_id": "proj_foreign",
        }
        assert await db.fetchone(
            """SELECT id FROM audit_log
               WHERE entity_type = 'cluster' AND entity_id = ?""",
            [cluster_id],
        ) is None

    @pytest.mark.asyncio
    async def test_cluster_update_rowcount_zero_prevents_side_effects(
        self,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from rka.models import EvidenceClusterCreate, EvidenceClusterUpdate
        from rka.services.clusters import ClusterNotFoundError, ClusterService

        rq_id = "dec_cluster_zero_row_rq"
        await db.execute(
            """INSERT INTO decisions
               (id, question, kind, decided_by, status, phase, project_id)
               VALUES (?, ?, 'research_question', 'brain', 'active',
                       'phase_1', 'proj_default')""",
            [rq_id, "Should zero-row updates project side effects?"],
        )
        await db.commit()

        svc = ClusterService(db=db)
        cluster = await svc.create(
            EvidenceClusterCreate(label="Zero-row original")
        )
        audit_count = await db.fetchone(
            """SELECT COUNT(*) AS count FROM audit_log
               WHERE entity_type = 'cluster' AND entity_id = ?""",
            [cluster.id],
        )
        real_execute = db.execute

        class ZeroRowCursor:
            rowcount = 0

        async def zero_row_update(sql, params=None):
            if sql.startswith("UPDATE evidence_clusters SET"):
                return ZeroRowCursor()
            return await real_execute(sql, params)

        monkeypatch.setattr(db, "execute", zero_row_update)
        with pytest.raises(ClusterNotFoundError, match="not found in project"):
            await svc.update(
                cluster.id,
                EvidenceClusterUpdate(
                    label="Zero-row replacement",
                    research_question_id=rq_id,
                ),
            )

        assert await db.fetchone(
            """SELECT label, research_question_id FROM evidence_clusters
               WHERE id = ?""",
            [cluster.id],
        ) == {
            "label": "Zero-row original",
            "research_question_id": None,
        }
        assert await db.fetchall(
            """SELECT target_id FROM entity_links
               WHERE source_type = 'cluster' AND source_id = ?
                 AND link_type = 'answers'""",
            [cluster.id],
        ) == []
        final_audit_count = await db.fetchone(
            """SELECT COUNT(*) AS count FROM audit_log
               WHERE entity_type = 'cluster' AND entity_id = ?""",
            [cluster.id],
        )
        assert final_audit_count == audit_count

    @pytest.mark.asyncio
    async def test_cluster_create_rolls_back_row_indexes_link_and_audit(
        self,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from rka.models import EvidenceClusterCreate
        from rka.services.clusters import ClusterService

        rq_id = "dec_cluster_create_atomic_rq"
        await db.execute(
            """INSERT INTO decisions
               (id, question, kind, decided_by, status, phase, project_id)
               VALUES (?, ?, 'research_question', 'brain', 'active',
                       'phase_1', 'proj_default')""",
            [rq_id, "Can cluster creation remain atomic?"],
        )
        await db.commit()

        svc = ClusterService(db=db)
        original_audit = svc.audit

        async def audit_then_fail(*args, **kwargs):
            await original_audit(*args, **kwargs)
            raise RuntimeError("injected cluster create audit failure")

        monkeypatch.setattr(svc, "audit", audit_then_fail)
        with pytest.raises(
            RuntimeError,
            match="injected cluster create audit failure",
        ):
            await svc.create(
                EvidenceClusterCreate(
                    research_question_id=rq_id,
                    label="Atomic create cluster",
                    synthesis="This projection must roll back with its cluster.",
                    confidence="emerging",
                )
            )

        assert await db.fetchone(
            "SELECT id FROM evidence_clusters WHERE label = ?",
            ["Atomic create cluster"],
        ) is None
        assert await db.fetchone(
            "SELECT id FROM fts_clusters WHERE label = ?",
            ["Atomic create cluster"],
        ) is None
        assert await db.fetchone(
            """SELECT id FROM entity_links
               WHERE source_type = 'cluster' AND link_type = 'answers'
                 AND target_id = ?""",
            [rq_id],
        ) is None
        assert await db.fetchone(
            """SELECT id FROM audit_log
               WHERE entity_type = 'cluster' AND action = 'create'"""
        ) is None

    @pytest.mark.asyncio
    async def test_cluster_update_rolls_back_row_indexes_link_and_audit(
        self,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from rka.models import EvidenceClusterCreate, EvidenceClusterUpdate
        from rka.services.clusters import ClusterService

        old_rq_id = "dec_cluster_update_old_rq"
        new_rq_id = "dec_cluster_update_new_rq"
        for rq_id, question in (
            (old_rq_id, "What was the original cluster question?"),
            (new_rq_id, "What is the replacement cluster question?"),
        ):
            await db.execute(
                """INSERT INTO decisions
                   (id, question, kind, decided_by, status, phase, project_id)
                   VALUES (?, ?, 'research_question', 'brain', 'active',
                           'phase_1', 'proj_default')""",
                [rq_id, question],
            )
        await db.commit()

        svc = ClusterService(db=db)
        cluster = await svc.create(
            EvidenceClusterCreate(
                research_question_id=old_rq_id,
                label="Atomic update original",
                synthesis="Original searchable synthesis.",
                confidence="emerging",
            )
        )
        audit_count = await db.fetchone(
            """SELECT COUNT(*) AS count FROM audit_log
               WHERE entity_type = 'cluster' AND entity_id = ?""",
            [cluster.id],
        )
        original_audit = svc.audit

        async def audit_then_fail(*args, **kwargs):
            await original_audit(*args, **kwargs)
            raise RuntimeError("injected cluster update audit failure")

        monkeypatch.setattr(svc, "audit", audit_then_fail)
        with pytest.raises(
            RuntimeError,
            match="injected cluster update audit failure",
        ):
            await svc.update(
                cluster.id,
                EvidenceClusterUpdate(
                    research_question_id=new_rq_id,
                    label="Atomic update replacement",
                    synthesis="Replacement searchable synthesis.",
                ),
            )

        row = await db.fetchone(
            """SELECT research_question_id, label, synthesis
               FROM evidence_clusters WHERE id = ?""",
            [cluster.id],
        )
        assert row == {
            "research_question_id": old_rq_id,
            "label": "Atomic update original",
            "synthesis": "Original searchable synthesis.",
        }
        fts_row = await db.fetchone(
            "SELECT label, synthesis FROM fts_clusters WHERE id = ?",
            [cluster.id],
        )
        assert fts_row == {
            "label": "Atomic update original",
            "synthesis": "Original searchable synthesis.",
        }
        links = await db.fetchall(
            """SELECT target_id FROM entity_links
               WHERE source_type = 'cluster' AND source_id = ?
                 AND link_type = 'answers' ORDER BY target_id""",
            [cluster.id],
        )
        assert links == [{"target_id": old_rq_id}]
        final_audit_count = await db.fetchone(
            """SELECT COUNT(*) AS count FROM audit_log
               WHERE entity_type = 'cluster' AND entity_id = ?""",
            [cluster.id],
        )
        assert final_audit_count == audit_count

    @pytest.mark.asyncio
    async def test_cluster_update_job_rolls_back_post_llm_mutation_unit(
        self,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from rka.infra.llm import ClusterAssignment, ClaimRelation
        from rka.services.clusters import ClusterService

        await db.execute(
            """INSERT INTO journal
               (id, type, content, source, confidence, phase, project_id)
               VALUES ('jrn_cluster_job_atomic', 'finding', 'source evidence',
                       'executor', 'tested', 'phase_1', 'proj_default')"""
        )
        for claim_id, content in (
            ("clm_cluster_job_source", "new result for atomic clustering"),
            ("clm_cluster_job_target", "earlier result contradicted by the new result"),
        ):
            await db.execute(
                """INSERT INTO claims
                   (id, source_entry_id, claim_type, content, verified, project_id)
                   VALUES (?, 'jrn_cluster_job_atomic', 'result', ?, 1,
                           'proj_default')""",
                [claim_id, content],
            )
        await db.commit()

        class LLM:
            async def assign_to_cluster(self, **_kwargs):
                return ClusterAssignment(
                    cluster_id=None,
                    cluster_label="Atomic job-created cluster",
                    relations=[
                        ClaimRelation(
                            target_claim_id="clm_cluster_job_target",
                            relation="contradicts",
                            confidence=0.9,
                        )
                    ],
                )

        service = ClusterService(db, llm=LLM())
        real_execute = db.execute

        async def fail_final_count(sql, params=None):
            if "SET claim_count = ?, updated_at = ?" in sql:
                raise RuntimeError("injected cluster count failure")
            return await real_execute(sql, params)

        monkeypatch.setattr(db, "execute", fail_final_count)
        with pytest.raises(
            RuntimeError,
            match="injected cluster count failure",
        ):
            await service.process_cluster_update_job("clm_cluster_job_source")

        assert await db.fetchone(
            "SELECT id FROM evidence_clusters WHERE label = ?",
            ["Atomic job-created cluster"],
        ) is None
        assert await db.fetchall(
            """SELECT id FROM claim_edges
               WHERE source_claim_id = 'clm_cluster_job_source'"""
        ) == []
        assert await db.fetchone(
            "SELECT id FROM fts_clusters WHERE label = ?",
            ["Atomic job-created cluster"],
        ) is None
        assert await db.fetchone(
            """SELECT id FROM audit_log
               WHERE entity_type = 'cluster' AND action = 'create'"""
        ) is None


class TestCollectReportContext:
    """Tests for GraphService.collect_report_context (report-scoped retrieval)."""

    @pytest_asyncio.fixture
    async def search_svc(self, db: Database):
        from rka.services.search import SearchService

        await db.execute(
            "INSERT INTO fts_journal (id, content, summary) VALUES (?, ?, ?)",
            ["jrn_001", "Side-channel observation on IoT", "Side-channel observation"],
        )
        await db.commit()
        return SearchService(db=db, embeddings=None)

    async def test_seeds_carry_search_provenance(self, graph_svc, search_svc):
        result = await graph_svc.collect_report_context(
            "Report on the side-channel timing observations",
            angle_queries=["side-channel"],
            search_service=search_svc,
        )
        by_id = {n["id"]: n for n in result["nodes"]}
        assert "jrn_001" in by_id
        seed = by_id["jrn_001"]
        assert seed["included_via"]["via"] == "search"
        assert seed["depth"] == 0
        assert result["seed_count"] >= 1

    async def test_expansion_carries_link_provenance(self, graph_svc, search_svc):
        result = await graph_svc.collect_report_context(
            "Report on the side-channel timing observations",
            angle_queries=["side-channel"],
            max_depth=2,
            search_service=search_svc,
        )
        by_id = {n["id"]: n for n in result["nodes"]}
        # jrn_001 --references--> dec_001 and --cites--> lit_001 (fixture links)
        assert "dec_001" in by_id and "lit_001" in by_id
        assert by_id["dec_001"]["included_via"]["via"] == "link"
        assert by_id["dec_001"]["included_via"]["from"] == "jrn_001"
        assert by_id["dec_001"]["depth"] >= 1

    async def test_seed_protection_under_tiny_cap(self, graph_svc, search_svc):
        result = await graph_svc.collect_report_context(
            "Report on the side-channel timing observations",
            angle_queries=["side-channel"],
            max_nodes=1,
            search_service=search_svc,
        )
        ids = {n["id"] for n in result["nodes"]}
        # Seeds survive even when the cap is smaller than the seed count.
        assert "jrn_001" in ids

    async def test_fallback_query_preserves_single_digit_counts(self, graph_svc, search_svc):
        result = await graph_svc.collect_report_context(
            "Why map 9 journal types to 3 record types?",
            search_service=search_svc,
        )
        assert result["queries"] == ["why map 9 journal types 3 record types"]

    async def test_requires_search_service(self, graph_svc):
        with pytest.raises(ValueError):
            await graph_svc.collect_report_context("anything", search_service=None)
