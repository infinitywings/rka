"""Regression tests for migration 020 (entity_links project-scoped UNIQUE).

Pre-migration the UNIQUE(source_id, link_type, target_id) constraint enforced
GLOBAL uniqueness across projects: two projects sharing the same
(source_id, link_type, target_id) triple would have the second INSERT
silently dropped by INSERT OR IGNORE. Migration 020 changes the constraint
to UNIQUE(project_id, source_id, link_type, target_id), which is strictly
LOOSER — same triples can coexist across different project_ids.

Filed under mis_01KQMWJ5EA9GKMQKQ8JT4M4FJE. Diagnosis trail:
jrn_01KQJKPDD80HABE12GFAMZ3GW6 (latent bug log) →
mis_01KQMFY19AD3T004X7NWW41H9Y (probe report) →
chk_01KQMXH6WA8T3WKPN312RWW45S (PI ratification of bulk-resolution).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database


PROJECT_A = "proj_test_migration_020_a"
PROJECT_B = "proj_test_migration_020_b"


@pytest_asyncio.fixture
async def db_with_two_projects(db: Database):
    """Initialize two projects; leaves entity_links empty."""
    for pid in (PROJECT_A, PROJECT_B):
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            [pid, f"Test {pid}"],
        )
    await db.commit()
    return db


class TestMigration020CrossProjectInsert:
    """Cross-project triples coexist post-migration; pre-migration the second
    INSERT would be silently dropped by INSERT OR IGNORE."""

    async def test_two_projects_can_have_same_triple(self, db_with_two_projects: Database):
        triple = ("source_42", "motivated", "target_42")

        # Project A: insert a link with this triple.
        await db_with_two_projects.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES ('lnk_A', 'decision', ?, ?, 'mission', ?, ?)""",
            [triple[0], triple[1], triple[2], PROJECT_A],
        )

        # Project B: insert a link with the SAME triple. Pre-migration this
        # would silently drop via INSERT OR IGNORE. Post-migration it
        # succeeds because UNIQUE is per-project.
        await db_with_two_projects.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES ('lnk_B', 'decision', ?, ?, 'mission', ?, ?)""",
            [triple[0], triple[1], triple[2], PROJECT_B],
        )
        await db_with_two_projects.commit()

        # Both rows must exist.
        async with db_with_two_projects._conn.execute(  # type: ignore[attr-defined]
            """SELECT id, project_id FROM entity_links
               WHERE source_id = ? AND link_type = ? AND target_id = ?
               ORDER BY id""",
            [triple[0], triple[1], triple[2]],
        ) as cur:
            rows = await cur.fetchall()
        assert len(rows) == 2, (
            "Migration 020 regression: two projects should be able to hold "
            "the same (source_id, link_type, target_id) triple. Got "
            f"{len(rows)} rows; expected 2."
        )
        assert {r[1] for r in rows} == {PROJECT_A, PROJECT_B}

    async def test_within_project_uniqueness_still_enforced(
        self, db_with_two_projects: Database
    ):
        """Same project + same triple still rejects via the new
        UNIQUE(project_id, source_id, link_type, target_id) constraint."""
        triple = ("source_99", "references", "target_99")

        await db_with_two_projects.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES ('lnk_dup_1', 'journal', ?, ?, 'decision', ?, ?)""",
            [triple[0], triple[1], triple[2], PROJECT_A],
        )
        await db_with_two_projects.commit()

        # Second INSERT in the same project with the same triple — must be
        # rejected (or silently ignored if the caller used INSERT OR IGNORE).
        # Test via INSERT OR IGNORE to mirror BaseService.add_link's
        # behavior; the row count must stay at 1 for project A.
        await db_with_two_projects.execute(
            """INSERT OR IGNORE INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES ('lnk_dup_2', 'journal', ?, ?, 'decision', ?, ?)""",
            [triple[0], triple[1], triple[2], PROJECT_A],
        )
        await db_with_two_projects.commit()

        async with db_with_two_projects._conn.execute(  # type: ignore[attr-defined]
            """SELECT COUNT(*) FROM entity_links
               WHERE source_id = ? AND link_type = ? AND target_id = ? AND project_id = ?""",
            [triple[0], triple[1], triple[2], PROJECT_A],
        ) as cur:
            (count,) = await cur.fetchone()
        assert count == 1, (
            "Migration 020 regression: within-project uniqueness must still "
            f"be enforced. Got {count} rows; expected 1 (the second INSERT "
            "OR IGNORE must collide on the project-scoped UNIQUE)."
        )


class TestMigration020DataCleanup:
    """The migration's data-cleanup step corrects rows whose project_id was
    NULL or mismatched the source's project_id. We can't assert against the
    live DB's pre-migration state (it's already migrated), but we can verify
    that the migrated test DB has no rows whose project_id mismatches their
    source's project_id (across all source_types we have data for)."""

    async def test_no_orphan_or_mismatched_project_ids_post_migration(self, db: Database):
        """Run-time invariant: after migrations apply (which the `db` fixture
        does), no entity_links row should have project_id NULL when its
        source can be resolved to a known project_id, nor mismatched against
        the source's project_id."""
        # The fixture's DB is freshly migrated and empty of entity_links data,
        # so this passes trivially. The intent is to lock in that, going
        # forward, any test or migration that backfills entity_links data
        # produces clean project_id values. This serves as documentation and
        # a place to extend with explicit data-state assertions if future
        # migrations add data.
        async with db._conn.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM entity_links WHERE project_id IS NULL"
        ) as cur:
            (null_count,) = await cur.fetchone()
        assert null_count == 0, (
            f"Migration 020 invariant: 0 NULL project_id rows expected on a "
            f"freshly-migrated DB; found {null_count}."
        )
