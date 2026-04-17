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


class TestGuessType:
    def test_known_prefixes(self):
        assert GraphService._guess_type_from_id("jrn_001") == "journal"
        assert GraphService._guess_type_from_id("dec_abc") == "decision"
        assert GraphService._guess_type_from_id("lit_xyz") == "literature"
        assert GraphService._guess_type_from_id("mis_123") == "mission"
        assert GraphService._guess_type_from_id("chk_foo") == "checkpoint"

    def test_unknown_prefix(self):
        assert GraphService._guess_type_from_id("zzz_bar") == "unknown"
