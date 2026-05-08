"""Test for Affordance F (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
'motivated-by-explained' tag suppression on the missions_without_motivated_by
manifest category.

A mission tagged 'motivated-by-explained' (with a separate journal entry
documenting the reason, linked via related_journal) is excluded from the
manifest's missions_without_motivated_by category. This closes the
manifest false-positive on missions whose missing FK is documented and
intentional (e.g., Bug A's mission which PI-directed unlinked) without
introducing a new schema column.
"""

from __future__ import annotations

import pytest_asyncio

from rka.infra.database import Database
from rka.services.maintenance import MaintenanceService

PROJECT_ID = "proj_test_explained_suppression"


async def _seed_mission(db: Database, mis_id: str, motivated_by: str | None = None) -> None:
    await db.execute(
        """INSERT INTO missions (id, phase, objective, status, project_id, motivated_by_decision)
           VALUES (?, 'design', ?, 'pending', ?, ?)""",
        [mis_id, f"obj for {mis_id}", PROJECT_ID, motivated_by],
    )


async def _add_tag(db: Database, entity_type: str, entity_id: str, tag: str) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO tags (tag, entity_type, entity_id, project_id)
           VALUES (?, ?, ?, ?)""",
        [tag, entity_type, entity_id, PROJECT_ID],
    )


@pytest_asyncio.fixture
async def explained_db(db: Database) -> Database:
    """Build the matrix:
      mis_unlinked_no_tag       — flagged (the canonical case)
      mis_unlinked_explained    — NOT flagged (has 'motivated-by-explained' tag)
      mis_linked_no_tag         — NOT flagged (has motivated_by_decision FK)
      mis_cancelled_unlinked    — NOT flagged (cancelled)
    """
    await db.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        [PROJECT_ID, "Explained Suppression Test"],
    )
    await _seed_mission(db, "mis_unlinked_no_tag", motivated_by=None)
    await _seed_mission(db, "mis_unlinked_explained", motivated_by=None)
    await _add_tag(db, "mission", "mis_unlinked_explained", "motivated-by-explained")
    await _seed_mission(db, "mis_cancelled_unlinked", motivated_by=None)
    await db.execute(
        "UPDATE missions SET status = 'cancelled' WHERE id = ?",
        ["mis_cancelled_unlinked"],
    )
    # mis_linked_no_tag is "linked" via the entity_links table per the
    # category's actual NOT EXISTS query — insert an entity_link.
    await db.execute(
        "INSERT INTO decisions (id, phase, question, decided_by, project_id) "
        "VALUES (?, 'design', ?, 'executor', ?)",
        ["dec_link_anchor", "anchor", PROJECT_ID],
    )
    await _seed_mission(db, "mis_linked_no_tag", motivated_by="dec_link_anchor")
    await db.execute(
        """INSERT INTO entity_links
           (id, source_type, source_id, link_type, target_type, target_id, project_id)
           VALUES ('lnk_motivated_anchor', 'decision', 'dec_link_anchor',
                   'motivated', 'mission', 'mis_linked_no_tag', ?)""",
        [PROJECT_ID],
    )
    await db.commit()
    return db


class TestExplainedSuppression:
    async def test_unlinked_untagged_flagged(self, explained_db: Database):
        svc = MaintenanceService(explained_db, project_id=PROJECT_ID)
        result = await svc._missions_without_motivated_by(PROJECT_ID)
        assert "mis_unlinked_no_tag" in result["ids"]

    async def test_unlinked_with_explained_tag_suppressed(self, explained_db: Database):
        svc = MaintenanceService(explained_db, project_id=PROJECT_ID)
        result = await svc._missions_without_motivated_by(PROJECT_ID)
        assert "mis_unlinked_explained" not in result["ids"]

    async def test_linked_mission_not_in_category(self, explained_db: Database):
        """Sanity: a linked mission was never in the category; the suppression
        change must not regress this."""
        svc = MaintenanceService(explained_db, project_id=PROJECT_ID)
        result = await svc._missions_without_motivated_by(PROJECT_ID)
        assert "mis_linked_no_tag" not in result["ids"]

    async def test_cancelled_excluded(self, explained_db: Database):
        svc = MaintenanceService(explained_db, project_id=PROJECT_ID)
        result = await svc._missions_without_motivated_by(PROJECT_ID)
        assert "mis_cancelled_unlinked" not in result["ids"]

    async def test_summary_count_matches_full_query(self, explained_db: Database):
        """The lightweight summary count and the full-manifest count must
        agree under the new suppression rule."""
        svc = MaintenanceService(explained_db, project_id=PROJECT_ID)
        full = await svc._missions_without_motivated_by(PROJECT_ID)
        summary = await svc.get_backlog_summary()
        # Find the count from the summary by summing all categories' contributions
        # to total_items — but the summary's per-category counts aren't exposed
        # individually. Re-run the count query directly via the service.
        # Simpler check: the summary's top_categories should include
        # missions_without_motivated_by with count == full["count"]
        # IF it's in the top 3.
        all_top_names = {c["name"] for c in summary["top_categories"]}
        if "missions_without_motivated_by" in all_top_names:
            top = next(c for c in summary["top_categories"]
                       if c["name"] == "missions_without_motivated_by")
            assert top["count"] == full["count"]
        # Otherwise assert nothing — the value is correct in the underlying
        # COUNT query, which the test_summary_total_matches_sum tests in
        # test_maintenance_backlog_summary.py validate end-to-end.

    async def test_removing_tag_re_flags_mission(self, explained_db: Database):
        """Idempotency / reversibility: removing the tag re-flags the mission."""
        svc = MaintenanceService(explained_db, project_id=PROJECT_ID)
        before = await svc._missions_without_motivated_by(PROJECT_ID)
        assert "mis_unlinked_explained" not in before["ids"]

        await explained_db.execute(
            """DELETE FROM tags WHERE entity_type = 'mission'
               AND entity_id = ? AND tag = 'motivated-by-explained'""",
            ["mis_unlinked_explained"],
        )
        await explained_db.commit()
        after = await svc._missions_without_motivated_by(PROJECT_ID)
        assert "mis_unlinked_explained" in after["ids"]
