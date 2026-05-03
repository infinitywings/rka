"""Test for v2.4 Improvement 2 — multi_hop_retrieval primitive.

Per dec_01KQQPDHCKHS4YMD6QP7J7K2GW, default edge weights from
dec_01KQQRZ0CJHB68P2F6233AHEJ5 (mis_01KQQS3DYQ2EVJV288PNHX0CMY).

Fixture: ~10 entities with mixed entity_links + claim_edges. Query the
primitive with explicit seeds (so we don't depend on FTS/vec being seeded
in tests) and assert ranking, max_nodes cap, and edge-weight propagation.
"""

from __future__ import annotations

import pytest_asyncio

from rka.infra.database import Database
from rka.models.project import ProjectCreate
from rka.services.graph import GraphService
from rka.services.project import ProjectService

PROJECT_ID = "proj_test_multi_hop"


@pytest_asyncio.fixture
async def small_graph(db: Database):
    """Mini graph for multi-hop testing.

    Topology (entity_links unless noted):
        seed_dec --motivated--> mis_a --produced--> jrn_a
        seed_dec --justified_by--> jrn_b
        jrn_b --references--> lit_x
        jrn_a --derived_from--> lit_x
        seed_dec --supersedes--> dec_old   (low-weight edge, deprioritized)
        unrelated_dec is isolated
    """
    project_svc = ProjectService(db)
    await project_svc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Multi-hop Test", description="test"),
        actor="system",
    )

    # Insert minimal entity rows so the BFS/hydration paths don't choke.
    # We're not testing the full row hydration; just enough so the primitive
    # can return node IDs ranked by edge-weight propagation.
    nodes = [
        ("dec_seed", "decisions"),
        ("dec_old", "decisions"),
        ("dec_unrel", "decisions"),
        ("mis_a", "missions"),
        ("jrn_a", "journal"),
        ("jrn_b", "journal"),
        ("lit_x", "literature"),
    ]
    # Insert minimal stub rows in the appropriate tables so guess_type_from_id
    # and _fill_missing_nodes find something. We use only the columns these
    # tables require to be NOT NULL.
    for nid, tbl in nodes:
        if tbl == "decisions":
            await db.execute(
                "INSERT INTO decisions (id, phase, question, decided_by, project_id) "
                "VALUES (?, 'design', ?, 'pi', ?)",
                [nid, f"Q for {nid}", PROJECT_ID],
            )
        elif tbl == "missions":
            await db.execute(
                "INSERT INTO missions (id, phase, objective, project_id) "
                "VALUES (?, 'design', ?, ?)",
                [nid, f"objective for {nid}", PROJECT_ID],
            )
        elif tbl == "journal":
            await db.execute(
                "INSERT INTO journal (id, type, content, source, project_id) "
                "VALUES (?, 'note', ?, 'executor', ?)",
                [nid, f"content for {nid}", PROJECT_ID],
            )
        elif tbl == "literature":
            await db.execute(
                "INSERT INTO literature (id, title, project_id) VALUES (?, ?, ?)",
                [nid, f"Title for {nid}", PROJECT_ID],
            )

    # Edges
    edges = [
        ("decision", "dec_seed", "motivated", "mission", "mis_a"),       # 1.0
        ("mission", "mis_a", "produced", "journal", "jrn_a"),             # 0.5
        ("decision", "dec_seed", "justified_by", "journal", "jrn_b"),     # 1.0
        ("journal", "jrn_b", "references", "literature", "lit_x"),        # 0.7
        ("journal", "jrn_a", "derived_from", "literature", "lit_x"),      # 1.0
        ("decision", "dec_seed", "supersedes", "decision", "dec_old"),    # 0.3
    ]
    for src_t, src_id, link, tgt_t, tgt_id in edges:
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [f"lnk_{src_id}_{tgt_id}", src_t, src_id, link, tgt_t, tgt_id, PROJECT_ID],
        )
    await db.commit()
    return db


class TestMultiHopRetrieval:
    async def test_seeds_appear_first_with_max_score(self, small_graph):
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored — seeds provided",
            seeds=["dec_seed"],
            max_depth=3,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        assert result["seeds"] == ["dec_seed"]
        assert result["nodes"], "must return at least the seed plus reachable neighbors"
        # Seed has score=1.0 by construction; should rank first.
        first = result["nodes"][0]
        assert first["id"] == "dec_seed"
        assert first["score"] == 1.0
        assert first["depth"] == 0

    async def test_high_weight_neighbor_outranks_low_weight(self, small_graph):
        """mis_a (motivated, w=1.0) must outrank dec_old (supersedes, w=0.3)."""
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=1,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        scores = {n["id"]: n["score"] for n in result["nodes"]}
        assert "mis_a" in scores
        assert "dec_old" in scores
        assert scores["mis_a"] > scores["dec_old"], (
            f"motivated (w=1.0) should outrank supersedes (w=0.3); got mis_a={scores['mis_a']}, "
            f"dec_old={scores['dec_old']}"
        )

    async def test_max_nodes_cap_truncates_result(self, small_graph):
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=3,
            max_nodes=3,
            project_id=PROJECT_ID,
        )
        assert len(result["nodes"]) <= 3, f"max_nodes=3 cap violated: got {len(result['nodes'])}"

    async def test_unrelated_nodes_not_returned(self, small_graph):
        """dec_unrel has no edges; must not appear in the subgraph."""
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=3,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        ids = {n["id"] for n in result["nodes"]}
        assert "dec_unrel" not in ids, "Disconnected nodes must not appear in subgraph."

    async def test_edge_weights_override_works(self, small_graph):
        """Caller-supplied weights override defaults — cranking supersedes to
        2.0 should make dec_old outrank mis_a."""
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=1,
            max_nodes=20,
            edge_weights={"supersedes": 2.0},  # >1.0 — boosted
            project_id=PROJECT_ID,
        )
        scores = {n["id"]: n["score"] for n in result["nodes"]}
        assert scores["dec_old"] > scores["mis_a"], (
            f"With supersedes=2.0 weight, dec_old must outrank mis_a; got "
            f"dec_old={scores['dec_old']}, mis_a={scores['mis_a']}"
        )

    async def test_returns_edges_within_ranked_set(self, small_graph):
        """Result edges must connect two nodes that are in the ranked output."""
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=3,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        node_ids = {n["id"] for n in result["nodes"]}
        for edge in result["edges"]:
            assert edge["source"] in node_ids and edge["target"] in node_ids, (
                f"Edge {edge['source']} -> {edge['target']} references nodes outside ranked set."
            )
