"""Transaction regressions for researcher-wide propagated mutations."""

from __future__ import annotations

import pytest

from rka.services.researcher_tools import ResearcherToolsService


async def _seed_cluster_graph(db) -> None:
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
               (id, label, claim_count, project_id)
               VALUES (?, ?, 1, 'proj_default')""",
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
