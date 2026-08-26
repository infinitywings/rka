"""Transaction regressions for researcher-wide propagated mutations."""

from __future__ import annotations

import asyncio

import pytest

from rka.infra.database import Database
from rka.models.claim import ClaimEdgeCreate
from rka.services.claims import ClaimService
from rka.services.researcher_tools import ResearcherToolsService


async def _seed_cluster_graph(db) -> None:
    await db.execute(
        """INSERT INTO decisions
           (id, phase, question, chosen, rationale, decided_by, kind, project_id)
           VALUES ('dec_cluster_atomic_rq', 'core_hardening',
                   'Atomic RQ?', 'Investigate.',
                   'Test research question.', 'pi', 'research_question',
                   'proj_default')"""
    )
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, project_id)
           VALUES ('jrn_cluster_atomic', 'observation', 'source observation',
                   'executor', 'tested', 'normal', 'proj_default')"""
    )
    for suffix in ("one", "two"):
        await db.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence, project_id)
               VALUES (?, 'jrn_cluster_atomic', 'evidence', ?, 0.8,
                       'proj_default')""",
            [f"clm_cluster_atomic_{suffix}", f"atomic claim {suffix}"],
        )
        await db.execute(
            """INSERT INTO evidence_clusters
               (id, research_question_id, label, claim_count, project_id)
               VALUES (?, 'dec_cluster_atomic_rq', ?, 1, 'proj_default')""",
            [f"ecl_cluster_atomic_{suffix}", f"atomic cluster {suffix}"],
        )
        await db.execute(
            """INSERT INTO claim_edges
               (id, source_claim_id, cluster_id, relation, confidence,
                project_id)
               VALUES (?, ?, ?, 'member_of', 1.0, 'proj_default')""",
            [
                f"ced_cluster_atomic_{suffix}",
                f"clm_cluster_atomic_{suffix}",
                f"ecl_cluster_atomic_{suffix}",
            ],
        )
    await db.commit()


@pytest.mark.asyncio
async def test_flag_stale_propagation_failure_rolls_back_root_and_cluster(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, project_id)
           VALUES ('jnl_stale_atomic', 'observation', 'source observation',
                   'executor', 'tested', 'normal', 'proj_default')"""
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, project_id)
           VALUES ('clm_stale_atomic', 'jnl_stale_atomic', 'evidence',
                   'atomic staleness claim', 0.8, 'proj_default')"""
    )
    await db.execute(
        """INSERT INTO evidence_clusters
           (id, label, project_id)
           VALUES ('ecl_stale_atomic', 'atomic staleness cluster',
                   'proj_default')"""
    )
    await db.execute(
        """INSERT INTO claim_edges
           (id, source_claim_id, cluster_id, relation, confidence, project_id)
           VALUES ('ced_stale_atomic', 'clm_stale_atomic', 'ecl_stale_atomic',
                   'member_of', 1.0, 'proj_default')"""
    )
    await db.commit()

    svc = ResearcherToolsService(db, project_id="proj_default")

    async def fail_downstream(
        cluster_id: str,
        reason: str,
        now: str,
    ) -> list[dict]:
        raise RuntimeError("simulated downstream propagation failure")

    monkeypatch.setattr(svc, "_propagate_from_cluster", fail_downstream)

    with pytest.raises(
        RuntimeError,
        match="simulated downstream propagation failure",
    ):
        await svc.flag_stale(
            entity_id="clm_stale_atomic",
            reason="new contradictory evidence",
            staleness="red",
            propagate=True,
        )

    claim = await db.fetchone(
        """SELECT staleness, stale_reason FROM claims
           WHERE id = 'clm_stale_atomic'"""
    )
    cluster = await db.fetchone(
        """SELECT staleness, stale_reason FROM evidence_clusters
           WHERE id = 'ecl_stale_atomic'"""
    )
    assert claim == {"staleness": "green", "stale_reason": None}
    assert cluster == {"staleness": "green", "stale_reason": None}


@pytest.mark.asyncio
async def test_split_cluster_failure_rolls_back_new_cluster_and_membership(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_cluster_graph(db)
    svc = ResearcherToolsService(db, project_id="proj_default")
    real_execute = db.execute

    async def fail_new_membership(sql, params=None):
        if "INSERT INTO claim_edges" in sql:
            raise RuntimeError("simulated split membership failure")
        return await real_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_new_membership)
    with pytest.raises(RuntimeError, match="split membership failure"):
        await svc.split_cluster(
            "ecl_cluster_atomic_one",
            [{
                "label": "new split",
                "claim_ids": ["clm_cluster_atomic_one"],
            }],
        )
    monkeypatch.setattr(db, "execute", real_execute)

    clusters = await db.fetchall(
        """SELECT id, claim_count FROM evidence_clusters
           WHERE project_id = 'proj_default'
           ORDER BY id"""
    )
    assert clusters == [
        {"id": "ecl_cluster_atomic_one", "claim_count": 1},
        {"id": "ecl_cluster_atomic_two", "claim_count": 1},
    ]
    membership = await db.fetchone(
        """SELECT cluster_id FROM claim_edges
           WHERE source_claim_id = 'clm_cluster_atomic_one'
             AND project_id = 'proj_default'"""
    )
    assert membership == {"cluster_id": "ecl_cluster_atomic_one"}
    assert await db.fetchall(
        """SELECT source_id FROM entity_links
           WHERE project_id = 'proj_default' AND link_type = 'answers'"""
    ) == []


@pytest.mark.asyncio
async def test_merge_cluster_failure_rolls_back_target_and_source_edges(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_cluster_graph(db)
    svc = ResearcherToolsService(db, project_id="proj_default")
    real_execute = db.execute

    async def fail_new_membership(sql, params=None):
        if "INSERT OR IGNORE INTO claim_edges" in sql:
            raise RuntimeError("simulated merge membership failure")
        return await real_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_new_membership)
    with pytest.raises(RuntimeError, match="merge membership failure"):
        await svc.merge_clusters(
            ["ecl_cluster_atomic_one", "ecl_cluster_atomic_two"],
            "merged target",
        )
    monkeypatch.setattr(db, "execute", real_execute)

    clusters = await db.fetchall(
        """SELECT id, claim_count FROM evidence_clusters
           WHERE project_id = 'proj_default'
           ORDER BY id"""
    )
    assert clusters == [
        {"id": "ecl_cluster_atomic_one", "claim_count": 1},
        {"id": "ecl_cluster_atomic_two", "claim_count": 1},
    ]
    memberships = await db.fetchall(
        """SELECT source_claim_id, cluster_id FROM claim_edges
           WHERE project_id = 'proj_default'
           ORDER BY source_claim_id"""
    )
    assert memberships == [
        {
            "source_claim_id": "clm_cluster_atomic_one",
            "cluster_id": "ecl_cluster_atomic_one",
        },
        {
            "source_claim_id": "clm_cluster_atomic_two",
            "cluster_id": "ecl_cluster_atomic_two",
        },
    ]
    assert await db.fetchall(
        """SELECT source_id FROM entity_links
           WHERE project_id = 'proj_default' AND link_type = 'answers'"""
    ) == []


@pytest.mark.asyncio
async def test_member_of_edge_creation_is_idempotent_and_count_is_distinct(db) -> None:
    await _seed_cluster_graph(db)
    service = ClaimService(db, project_id="proj_default")
    membership = ClaimEdgeCreate(
        source_claim_id="clm_cluster_atomic_one",
        cluster_id="ecl_cluster_atomic_one",
        relation="member_of",
        confidence=1.0,
    )

    events_before = await db.fetchone(
        """SELECT COUNT(*) AS count FROM change_events
           WHERE project_id = 'proj_default'"""
    )
    cluster_before = await db.fetchone(
        """SELECT updated_at FROM evidence_clusters
           WHERE id = 'ecl_cluster_atomic_one'
             AND project_id = 'proj_default'"""
    )
    first = await service.create_edge(membership)
    second = await service.create_edge(membership)
    events_after = await db.fetchone(
        """SELECT COUNT(*) AS count FROM change_events
           WHERE project_id = 'proj_default'"""
    )
    cluster_after = await db.fetchone(
        """SELECT updated_at FROM evidence_clusters
           WHERE id = 'ecl_cluster_atomic_one'
             AND project_id = 'proj_default'"""
    )

    assert first.id == second.id
    assert events_after == events_before
    assert cluster_after == cluster_before
    assert await db.fetchone(
        """SELECT COUNT(DISTINCT source_claim_id) AS distinct_claims,
                  COUNT(*) AS edges
           FROM claim_edges
           WHERE project_id = 'proj_default'
             AND cluster_id = 'ecl_cluster_atomic_one'
             AND relation = 'member_of'"""
    ) == {"distinct_claims": 1, "edges": 1}
    assert await db.fetchone(
        """SELECT claim_count FROM evidence_clusters
           WHERE id = 'ecl_cluster_atomic_one'
             AND project_id = 'proj_default'"""
    ) == {"claim_count": 1}


@pytest.mark.asyncio
async def test_concurrent_member_of_creation_converges_without_duplicate_events(db) -> None:
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, project_id)
           VALUES ('jrn_cluster_concurrent', 'observation', 'source observation',
                   'executor', 'tested', 'normal', 'proj_default')"""
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, project_id)
           VALUES ('clm_cluster_concurrent', 'jrn_cluster_concurrent',
                   'evidence', 'concurrent claim', 0.8, 'proj_default')"""
    )
    await db.execute(
        """INSERT INTO evidence_clusters
           (id, label, claim_count, project_id)
           VALUES ('ecl_cluster_concurrent', 'concurrent cluster', 0,
                   'proj_default')"""
    )
    await db.commit()

    second_db = Database(db.db_path)
    await second_db.connect()
    try:
        first_service = ClaimService(db, project_id="proj_default")
        second_service = ClaimService(second_db, project_id="proj_default")
        membership = ClaimEdgeCreate(
            source_claim_id="clm_cluster_concurrent",
            cluster_id="ecl_cluster_concurrent",
            relation="member_of",
            confidence=1.0,
        )
        events_before = await db.fetchone(
            """SELECT COUNT(*) AS count FROM change_events
               WHERE project_id = 'proj_default'"""
        )

        first, second = await asyncio.gather(
            first_service.create_edge(membership),
            second_service.create_edge(membership),
        )

        assert first.id == second.id
        assert await db.fetchone(
            """SELECT COUNT(*) AS edges FROM claim_edges
               WHERE source_claim_id = 'clm_cluster_concurrent'
                 AND cluster_id = 'ecl_cluster_concurrent'
                 AND relation = 'member_of'
                 AND project_id = 'proj_default'"""
        ) == {"edges": 1}
        assert await db.fetchone(
            """SELECT claim_count FROM evidence_clusters
               WHERE id = 'ecl_cluster_concurrent'
                 AND project_id = 'proj_default'"""
        ) == {"claim_count": 1}
        events_after = await db.fetchone(
            """SELECT COUNT(*) AS count FROM change_events
               WHERE project_id = 'proj_default'"""
        )
        # One claim-edge insert and one real cluster-count update. The losing
        # retry observes both and appends no additional semantic event.
        assert events_after["count"] - events_before["count"] == 2
    finally:
        await second_db.close()


@pytest.mark.asyncio
async def test_merge_clusters_counts_unique_union_and_links_target_to_rq(db) -> None:
    await _seed_cluster_graph(db)
    await db.execute(
        """INSERT INTO claim_edges
           (id, source_claim_id, cluster_id, relation, confidence, project_id)
           VALUES ('ced_cluster_overlap', 'clm_cluster_atomic_one',
                   'ecl_cluster_atomic_two', 'member_of', 1.0,
                   'proj_default')"""
    )
    await db.execute(
        """UPDATE evidence_clusters SET claim_count = 2
           WHERE id = 'ecl_cluster_atomic_two'"""
    )
    await db.commit()
    service = ResearcherToolsService(db, project_id="proj_default")

    result = await service.merge_clusters(
        ["ecl_cluster_atomic_one", "ecl_cluster_atomic_two"],
        "merged target",
    )

    assert result["total_claims_moved"] == 2
    assert await db.fetchone(
        """SELECT claim_count, research_question_id
           FROM evidence_clusters WHERE id = ?""",
        [result["target_id"]],
    ) == {
        "claim_count": 2,
        "research_question_id": "dec_cluster_atomic_rq",
    }
    assert await db.fetchone(
        """SELECT COUNT(*) AS edges,
                  COUNT(DISTINCT source_claim_id) AS distinct_claims
           FROM claim_edges
           WHERE project_id = 'proj_default' AND cluster_id = ?
             AND relation = 'member_of'""",
        [result["target_id"]],
    ) == {"edges": 2, "distinct_claims": 2}
    assert await db.fetchone(
        """SELECT target_id FROM entity_links
           WHERE project_id = 'proj_default'
             AND source_type = 'cluster' AND source_id = ?
             AND link_type = 'answers' AND target_type = 'decision'""",
        [result["target_id"]],
    ) == {"target_id": "dec_cluster_atomic_rq"}


@pytest.mark.asyncio
async def test_split_cluster_links_each_new_cluster_to_its_rq(db) -> None:
    await _seed_cluster_graph(db)
    service = ResearcherToolsService(db, project_id="proj_default")

    result = await service.split_cluster(
        "ecl_cluster_atomic_one",
        [{
            "label": "new split",
            "claim_ids": ["clm_cluster_atomic_one"],
        }],
    )
    new_cluster_id = result["new_clusters"][0]["id"]

    assert await db.fetchone(
        """SELECT target_id FROM entity_links
           WHERE project_id = 'proj_default'
             AND source_type = 'cluster' AND source_id = ?
             AND link_type = 'answers' AND target_type = 'decision'""",
        [new_cluster_id],
    ) == {"target_id": "dec_cluster_atomic_rq"}


@pytest.mark.asyncio
async def test_split_cluster_rejects_non_rq_parent(db) -> None:
    await _seed_cluster_graph(db)
    await db.execute(
        """INSERT INTO decisions
           (id, phase, question, decided_by, kind, project_id)
           VALUES ('dec_cluster_design', 'core_hardening', 'Design choice?',
                   'pi', 'design_choice', 'proj_default')"""
    )
    await db.commit()
    service = ResearcherToolsService(db, project_id="proj_default")

    with pytest.raises(ValueError, match="is not a research_question"):
        await service.split_cluster(
            "ecl_cluster_atomic_one",
            [{
                "label": "invalid split",
                "research_question_id": "dec_cluster_design",
                "claim_ids": ["clm_cluster_atomic_one"],
            }],
        )

    assert await db.fetchone(
        """SELECT COUNT(*) AS count FROM evidence_clusters
           WHERE project_id = 'proj_default'"""
    ) == {"count": 2}


@pytest.mark.asyncio
async def test_merge_clusters_rejects_non_rq_parent(db) -> None:
    await _seed_cluster_graph(db)
    await db.execute(
        """INSERT INTO decisions
           (id, phase, question, decided_by, kind, project_id)
           VALUES ('dec_cluster_design', 'core_hardening', 'Design choice?',
                   'pi', 'design_choice', 'proj_default')"""
    )
    await db.commit()
    service = ResearcherToolsService(db, project_id="proj_default")

    with pytest.raises(ValueError, match="is not a research_question"):
        await service.merge_clusters(
            ["ecl_cluster_atomic_one", "ecl_cluster_atomic_two"],
            "invalid merge",
            research_question_id="dec_cluster_design",
        )

    assert await db.fetchone(
        """SELECT COUNT(*) AS count FROM evidence_clusters
           WHERE project_id = 'proj_default'"""
    ) == {"count": 2}


@pytest.mark.asyncio
async def test_merge_clusters_requires_explicit_parent_for_mixed_rqs(db) -> None:
    await _seed_cluster_graph(db)
    await db.execute(
        """INSERT INTO decisions
           (id, phase, question, decided_by, kind, project_id)
           VALUES ('dec_cluster_second_rq', 'core_hardening', 'Second RQ?',
                   'pi', 'research_question', 'proj_default')"""
    )
    await db.execute(
        """UPDATE evidence_clusters
           SET research_question_id = 'dec_cluster_second_rq'
           WHERE id = 'ecl_cluster_atomic_two'
             AND project_id = 'proj_default'"""
    )
    await db.commit()
    service = ResearcherToolsService(db, project_id="proj_default")

    with pytest.raises(ValueError, match="span multiple research questions"):
        await service.merge_clusters(
            ["ecl_cluster_atomic_one", "ecl_cluster_atomic_two"],
            "ambiguous merge",
        )

    result = await service.merge_clusters(
        ["ecl_cluster_atomic_one", "ecl_cluster_atomic_two"],
        "explicit merge",
        research_question_id="dec_cluster_second_rq",
    )
    assert await db.fetchone(
        """SELECT research_question_id FROM evidence_clusters
           WHERE id = ? AND project_id = 'proj_default'""",
        [result["target_id"]],
    ) == {"research_question_id": "dec_cluster_second_rq"}
