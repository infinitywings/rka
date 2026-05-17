"""Regression tests for migration 023 (cluster → parent-RQ entity_links backfill).

The migration does two things:

  1. Extends the entity_links.link_type CHECK enum (from migration 021)
     to include the new 'answers' value.
  2. Backfills one entity_link per evidence_clusters row with a non-null
     research_question_id — source=cluster, target=decision, link_type=
     'answers', link_weight=1.0.

Provenance: mis_01KRS1D8C0E2FP52D0P6JNB3SX (v2.5.2 patch). Fix-shape decision
dec_01KRS1ADPD4W6AW2X54MKVXMCR. Phase-3 sequencing dec_01KRRM5WKSSX7C3ZXZME0BMVQ9.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from rka.infra.database import Database


PROJECT_A = "proj_test_migration_023_a"
PROJECT_B = "proj_test_migration_023_b"


_MIGRATION_023_PATH = (
    Path(__file__).resolve().parents[2]
    / "rka"
    / "db"
    / "migrations"
    / "023_cluster_answers_links.sql"
)


async def _make_rq(db: Database, decision_id: str, project_id: str) -> None:
    """Insert a research-question decision the cluster's FK can reference."""
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status)
           VALUES (?, 'design', 'Test RQ', 'brain', 'active')""",
        [decision_id],
    )
    # project_id column added in a later migration; set it if present.
    await db.execute(
        "UPDATE decisions SET project_id = ? WHERE id = ?",
        [project_id, decision_id],
    )


async def _make_cluster(
    db: Database,
    cluster_id: str,
    rq_id: str | None,
    project_id: str,
) -> None:
    """Insert an evidence_clusters row pointing at the given RQ (or NULL)."""
    await db.execute(
        """INSERT INTO evidence_clusters
           (id, research_question_id, label, project_id)
           VALUES (?, ?, 'test cluster', ?)""",
        [cluster_id, rq_id, project_id],
    )


# ---------------------------------------------------------------------------
# (a) Migration runs cleanly on a fresh DB; CHECK extension landed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_023_check_extension_accepts_answers_link_type(db: Database):
    """Post-023, an INSERT with link_type='answers' must succeed; same
    INSERT pre-021's CHECK enum would have failed because 'answers' was
    not in the enumeration. This proves the CHECK extension landed."""
    await db.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        [PROJECT_A, "Test"],
    )
    await db.execute(
        """INSERT INTO entity_links
           (id, source_type, source_id, link_type, target_type, target_id,
            link_weight, project_id)
           VALUES ('lnk_test_answers_ok', 'cluster', 'ecl_X', 'answers',
                   'decision', 'dec_Y', 1.0, ?)""",
        [PROJECT_A],
    )
    await db.commit()
    row = await db.fetchone(
        "SELECT link_type FROM entity_links WHERE id = 'lnk_test_answers_ok'"
    )
    assert row is not None
    assert row["link_type"] == "answers"


@pytest.mark.asyncio
async def test_migration_023_check_still_rejects_unknown_link_type(db: Database):
    """The extended CHECK still rejects values outside the new enum —
    the extension is additive, not a removal of the constraint."""
    await db.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        [PROJECT_A, "Test"],
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id,
                project_id)
               VALUES ('lnk_test_bogus', 'cluster', 'ecl_X',
                       'totally_not_a_real_link_type', 'decision', 'dec_Y', ?)""",
            [PROJECT_A],
        )


# ---------------------------------------------------------------------------
# (b) Idempotency: re-running the backfill yields the same row count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_023_backfill_is_idempotent(db: Database):
    """Re-running the migration SQL's backfill step on populated data
    must not duplicate rows. Enforced by INSERT OR IGNORE against the
    project-scoped UNIQUE triple from migration 020."""
    await db.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        [PROJECT_A, "Test"],
    )
    # Insert 3 clusters each pointing at a distinct RQ.
    n = 3
    for i in range(n):
        rq_id = f"dec_test_023_rq_{i}"
        cl_id = f"ecl_test_023_cl_{i}"
        await _make_rq(db, rq_id, PROJECT_A)
        await _make_cluster(db, cl_id, rq_id, PROJECT_A)
    await db.commit()

    migration_sql = _MIGRATION_023_PATH.read_text()
    # The migration was already run by the test fixture (Database.run_migrations).
    # Re-execute just the backfill INSERT step to assert idempotency on the
    # populated data — the CHECK-extension step is one-shot (table-swap)
    # and isn't relevant to backfill idempotency.
    backfill_sql = migration_sql[migration_sql.index("INSERT OR IGNORE INTO entity_links"):]
    # Strip trailing PRAGMA which we don't need to re-execute.
    backfill_sql = backfill_sql.split("PRAGMA")[0]
    await db._conn.executescript(backfill_sql)
    await db.commit()

    first_count = await db.fetchone(
        "SELECT COUNT(*) AS c FROM entity_links WHERE link_type = 'answers'"
    )
    assert first_count["c"] == n, f"first run: expected {n}, got {first_count['c']}"

    # Run the backfill a second time.
    await db._conn.executescript(backfill_sql)
    await db.commit()
    second_count = await db.fetchone(
        "SELECT COUNT(*) AS c FROM entity_links WHERE link_type = 'answers'"
    )
    assert second_count["c"] == n, (
        f"second run created duplicates: expected {n}, got {second_count['c']}"
    )


# ---------------------------------------------------------------------------
# (c) Row-count invariant: 1 link per cluster with non-null FK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_023_creates_one_link_per_cluster_with_non_null_fk(
    db: Database,
):
    """Invariant: after the backfill runs against populated data,
    `COUNT(entity_links WHERE link_type='answers') == COUNT(evidence_clusters
    WHERE research_question_id IS NOT NULL)`.

    Production state at the time of mission spec authoring (2026-05-16):
    101 clusters across 9 projects, all with non-null FK → 101 answers
    links expected. We exercise the invariant with a smaller fixture
    here — exact production numbers are verified at T5 live re-run.
    Also covers a mix across two projects to confirm project_id
    propagates correctly.
    """
    for pid in (PROJECT_A, PROJECT_B):
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            [pid, f"Test {pid}"],
        )

    # Project A: 4 clusters all linked.
    for i in range(4):
        rq_id = f"dec_A_023_{i}"
        cl_id = f"ecl_A_023_{i}"
        await _make_rq(db, rq_id, PROJECT_A)
        await _make_cluster(db, cl_id, rq_id, PROJECT_A)
    # Project B: 2 clusters linked, 1 cluster with NULL FK (should NOT
    # produce an entity_link).
    for i in range(2):
        rq_id = f"dec_B_023_{i}"
        cl_id = f"ecl_B_023_{i}"
        await _make_rq(db, rq_id, PROJECT_B)
        await _make_cluster(db, cl_id, rq_id, PROJECT_B)
    await _make_cluster(db, "ecl_B_023_orphan", None, PROJECT_B)
    await db.commit()

    migration_sql = _MIGRATION_023_PATH.read_text()
    backfill_sql = migration_sql[migration_sql.index("INSERT OR IGNORE INTO entity_links"):]
    backfill_sql = backfill_sql.split("PRAGMA")[0]
    await db._conn.executescript(backfill_sql)
    await db.commit()

    # Total answers links == total clusters with non-null FK == 6.
    answers_total = await db.fetchone(
        "SELECT COUNT(*) AS c FROM entity_links WHERE link_type = 'answers'"
    )
    clusters_with_fk = await db.fetchone(
        """SELECT COUNT(*) AS c FROM evidence_clusters
           WHERE research_question_id IS NOT NULL"""
    )
    assert answers_total["c"] == clusters_with_fk["c"], (
        "invariant broken: count of answers links must equal count of "
        f"clusters with non-null FK ({answers_total['c']} vs {clusters_with_fk['c']})"
    )

    # Per-project breakdown propagates project_id correctly.
    per_project = {
        row["project_id"]: row["c"]
        for row in await db.fetchall(
            """SELECT project_id, COUNT(*) AS c FROM entity_links
               WHERE link_type = 'answers' GROUP BY project_id"""
        )
    }
    assert per_project.get(PROJECT_A) == 4
    assert per_project.get(PROJECT_B) == 2

    # Orphan cluster (NULL FK) produced no link.
    orphan = await db.fetchone(
        """SELECT COUNT(*) AS c FROM entity_links
           WHERE link_type = 'answers' AND source_id = 'ecl_B_023_orphan'"""
    )
    assert orphan["c"] == 0

    # Provenance columns set as the migration documents.
    sample = await db.fetchone(
        """SELECT created_by, link_weight, link_reason, source_type, target_type
           FROM entity_links WHERE link_type = 'answers' LIMIT 1"""
    )
    assert sample["created_by"] == "migration_023"
    assert sample["link_weight"] == 1.0
    assert "migration 023" in (sample["link_reason"] or "").lower()
    assert sample["source_type"] == "cluster"
    assert sample["target_type"] == "decision"
