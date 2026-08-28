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
from rka.services.search import SearchHit

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
    await db.execute(
        "UPDATE decisions SET status = 'superseded', superseded_by = ? WHERE id = ?",
        ["dec_seed", "dec_old"],
    )
    await db.commit()
    return db


class TestMultiHopRetrieval:
    async def test_local_stamped_cross_project_edge_is_pruned(self, small_graph):
        await small_graph.execute(
            "INSERT INTO projects (id, name, created_by) VALUES (?, ?, ?)",
            ["proj_foreign_edge", "Foreign Edge", "system"],
        )
        await small_graph.execute(
            "INSERT INTO decisions (id, phase, question, decided_by, project_id) "
            "VALUES (?, 'design', ?, 'pi', ?)",
            ["dec_foreign_endpoint", "Foreign endpoint", "proj_foreign_edge"],
        )
        await small_graph.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id,
                project_id)
               VALUES (?, 'decision', 'dec_seed', 'references', 'decision', ?, ?)""",
            ["lnk_dirty_cross_project", "dec_foreign_endpoint", PROJECT_ID],
        )

        svc = GraphService(small_graph)
        multi = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=2,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        ego = await svc.get_ego_graph("dec_seed", depth=2, project_id=PROJECT_ID)

        for result in (multi, ego):
            assert "dec_foreign_endpoint" not in {
                node["id"] for node in result["nodes"]
            }
            assert all(
                "dec_foreign_endpoint" not in {edge["source"], edge["target"]}
                for edge in result["edges"]
            )

    async def test_valid_interpretation_and_observation_anchors_survive(
        self, small_graph
    ):
        await small_graph.execute(
            """INSERT INTO interpretation_candidates
               (id, project_id, source_type, source_id, locator_kind,
                locator_value, statement, epistemic_kind, created_by,
                extraction_tool)
               VALUES ('icd_graph_anchor', ?, 'journal', 'jrn_a', 'record',
                       'full_record', 'Candidate graph anchor', 'inference',
                       'brain', 'test')""",
            [PROJECT_ID],
        )
        await small_graph.execute(
            """INSERT INTO experiments
               (id, project_id, title, created_by)
               VALUES ('exp_graph_anchor', ?, 'Graph anchor experiment', 'pi')""",
            [PROJECT_ID],
        )
        await small_graph.execute(
            """INSERT INTO experiment_plan_versions
               (id, experiment_id, project_id, version, objective, protocol,
                created_by, reason)
               VALUES ('epv_graph_anchor', 'exp_graph_anchor', ?, 1,
                       'Test graph anchors', 'Run once', 'pi', 'test')""",
            [PROJECT_ID],
        )
        await small_graph.execute(
            """INSERT INTO experiment_runs
               (id, experiment_id, project_id, plan_version, label, runner,
                created_by)
               VALUES ('run_graph_anchor', 'exp_graph_anchor', ?, 1,
                       'Graph anchor run', 'manual', 'executor')""",
            [PROJECT_ID],
        )
        await small_graph.execute(
            """INSERT INTO experiment_observations
               (id, run_id, project_id, name, kind, direction, summary,
                value_real, observed_at, recorded_by)
               VALUES ('obs_graph_anchor', 'run_graph_anchor', ?, 'Anchor metric',
                       'metric', 'positive', 'Observation graph anchor', 1.0,
                       '2026-08-28T00:00:00Z', 'executor')""",
            [PROJECT_ID],
        )

        svc = GraphService(small_graph)
        for entity_id in ("icd_graph_anchor", "obs_graph_anchor"):
            result = await svc.multi_hop_retrieval(
                query="ignored",
                seeds=[entity_id],
                max_depth=0,
                max_nodes=5,
                project_id=PROJECT_ID,
            )
            assert [node["id"] for node in result["nodes"]] == [entity_id]

    async def test_report_context_does_not_attach_a_foreign_tag(self, small_graph):
        await small_graph.execute(
            "INSERT INTO projects (id, name, created_by) VALUES (?, ?, ?)",
            ["proj_foreign_context_tag", "Foreign Context Tag", "system"],
        )
        await small_graph.execute(
            "INSERT INTO tags (project_id, tag, entity_type, entity_id) "
            "VALUES (?, ?, ?, ?)",
            ["proj_foreign_context_tag", "foreign-only", "decision", "dec_seed"],
        )

        class _SeedSearch:
            def with_project(self, _project_id: str):
                return self

            async def search(self, _query: str, limit: int = 20):
                return [SearchHit("decision", "dec_seed", "seed", "seed")][:limit]

        result = await GraphService(small_graph).collect_report_context(
            "seed",
            angle_queries=["seed"],
            max_depth=0,
            max_nodes=10,
            project_id=PROJECT_ID,
            search_service=_SeedSearch(),
        )

        node = next(node for node in result["nodes"] if node["id"] == "dec_seed")
        assert "foreign-only" not in node["tags"]

    async def test_foreign_or_missing_explicit_seed_is_not_a_placeholder(
        self, small_graph
    ):
        await small_graph.execute(
            "INSERT INTO projects (id, name, created_by) VALUES (?, ?, ?)",
            ["proj_foreign_graph", "Foreign Graph", "system"],
        )
        await small_graph.execute(
            "INSERT INTO decisions (id, phase, question, decided_by, project_id) "
            "VALUES (?, 'design', ?, 'pi', ?)",
            ["dec_foreign_seed", "Foreign seed", "proj_foreign_graph"],
        )
        svc = GraphService(small_graph)

        foreign = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_foreign_seed"],
            max_depth=2,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        missing = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_missing_seed"],
            max_depth=2,
            max_nodes=20,
            project_id=PROJECT_ID,
        )

        assert foreign["nodes"] == []
        assert foreign["seeds"] == []
        assert missing["nodes"] == []
        assert missing["seeds"] == []

    async def test_foreign_ego_root_returns_an_empty_graph(self, small_graph):
        await small_graph.execute(
            "INSERT INTO projects (id, name, created_by) VALUES (?, ?, ?)",
            ["proj_foreign_ego", "Foreign Ego", "system"],
        )
        await small_graph.execute(
            "INSERT INTO decisions (id, phase, question, decided_by, project_id) "
            "VALUES (?, 'design', ?, 'pi', ?)",
            ["dec_foreign_ego", "Foreign ego", "proj_foreign_ego"],
        )
        svc = GraphService(small_graph)

        result = await svc.get_ego_graph(
            "dec_foreign_ego", depth=2, project_id=PROJECT_ID
        )

        assert result == {"nodes": [], "edges": []}

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

    async def test_nodes_expose_canonical_currentness(self, small_graph):
        svc = GraphService(small_graph)
        result = await svc.multi_hop_retrieval(
            query="ignored",
            seeds=["dec_seed"],
            max_depth=1,
            max_nodes=20,
            project_id=PROJECT_ID,
        )
        nodes = {node["id"]: node for node in result["nodes"]}

        assert nodes["dec_seed"]["currentness"]["is_current"] is True
        assert nodes["dec_old"]["currentness"]["is_current"] is False
        assert nodes["dec_old"]["superseded_by"] == "dec_seed"
        assert "status:superseded" in nodes["dec_old"]["currentness"]["reasons"]

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
