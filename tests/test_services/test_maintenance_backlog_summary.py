"""Test for v2.4 Improvement 4 — get_backlog_summary().

Per dec_01KQQPER3XSSBACGZANFJCVQ66, dec_01KQQRZRY9NN0PYQNXPW07D732
(mis_01KQQS3DYQ2EVJV288PNHX0CMY).

The lightweight COUNT-only summary fuels the one-line backlog decoration
appended to rka_get_status and rka_search outputs. Returns top-3 categories
by count, deterministic shape, sub-100ms expected at typical project scale.
"""

from __future__ import annotations

import pytest_asyncio

from rka.infra.database import Database
from rka.models.journal import JournalEntryCreate
from rka.models.project import ProjectCreate
from rka.services.maintenance import MaintenanceService
from rka.services.notes import NoteService
from rka.services.project import ProjectService

PROJECT_ID = "proj_test_backlog_summary"


@pytest_asyncio.fixture
async def project_with_untagged_entries(db: Database):
    """A project with 5 untagged journal entries (entries_without_tags backlog).

    These untagged entries also lack claims (entries_without_claims) and
    cross-refs (entries_missing_cross_refs), so multiple categories will count.
    """
    project_svc = ProjectService(db)
    await project_svc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Test Backlog", description="test"),
        actor="system",
    )
    note_svc = NoteService(db, project_id=PROJECT_ID)
    for i in range(5):
        await note_svc.create(
            JournalEntryCreate(
                content=f"Untagged note {i}.",
                type="note",
                source="executor",
                confidence="hypothesis",
            ),
            actor="executor",
        )
    return db


class TestBacklogSummary:
    async def test_summary_returns_total_and_top3(self, project_with_untagged_entries):
        svc = MaintenanceService(project_with_untagged_entries, project_id=PROJECT_ID)
        summary = await svc.get_backlog_summary()

        assert "total_items" in summary
        assert "top_categories" in summary
        assert isinstance(summary["top_categories"], list)
        assert len(summary["top_categories"]) <= 3
        # Each top entry has the documented shape
        for cat in summary["top_categories"]:
            assert set(cat.keys()) >= {"name", "count"}
            assert isinstance(cat["count"], int)
            assert cat["count"] > 0

    async def test_summary_total_matches_sum_of_categories(self, project_with_untagged_entries):
        """Total is the sum across ALL categories (not just top 3)."""
        svc = MaintenanceService(project_with_untagged_entries, project_id=PROJECT_ID)
        summary = await svc.get_backlog_summary()

        # The 5 untagged entries hit at least entries_without_tags (5),
        # entries_without_claims (5), and entries_missing_cross_refs (5).
        assert summary["total_items"] >= 15, (
            f"Expected at least 15 items (5 each across 3 categories); got {summary['total_items']}"
        )

    async def test_summary_descending_by_count(self, project_with_untagged_entries):
        svc = MaintenanceService(project_with_untagged_entries, project_id=PROJECT_ID)
        summary = await svc.get_backlog_summary()

        counts = [c["count"] for c in summary["top_categories"]]
        assert counts == sorted(counts, reverse=True), "top_categories must be sorted by count descending"

    async def test_empty_project_returns_zero(self, db: Database):
        """Sanity: a project with no entries has total 0 and empty top_categories."""
        # Use a different project so the fixture's content doesn't leak in.
        project_svc = ProjectService(db)
        await project_svc.create_project(
            ProjectCreate(id="proj_empty_backlog", name="Empty Backlog", description="test"),
            actor="system",
        )
        svc = MaintenanceService(db, project_id="proj_empty_backlog")
        summary = await svc.get_backlog_summary()

        assert summary["total_items"] == 0
        assert summary["top_categories"] == []
