"""A decision must never be recorded as superseding itself.

Every other pre-flight check in `_validate_pair` waves a self-link through:
both rows exist (they are the same row), the status is `superseded`, and
`superseded_by` is empty. Applying it would set `superseded_by` to the row's
own id and write a `supersedes` self-loop, leaving the decision permanently its
own replacement — it reads as stale forever, which is exactly the currency
signal this repair exists to restore.
"""

from __future__ import annotations

import pytest

from rka.services.admin_repair import repair_orphan_supersedes


PROJECT = "proj_default"
DEC = "dec_01SELFSUPERSEDE0000000000"


async def _seed_superseded_decision(db) -> None:
    await db.execute(
        "INSERT INTO decisions (id, project_id, question, chosen, rationale, "
        "decided_by, kind, phase, status, scope_version) "
        "VALUES (?, ?, ?, ?, ?, 'pi', 'decision', 'test', 'superseded', 1)",
        [DEC, PROJECT, "q", "c", "r"],
    )


@pytest.mark.asyncio
async def test_self_pair_is_refused_in_dry_run(db):
    await _seed_superseded_decision(db)
    (report,) = await repair_orphan_supersedes(db, PROJECT, {DEC: DEC}, dry_run=True)

    assert report.applied is False
    assert report.failure_reason is not None
    assert "cannot supersede itself" in report.failure_reason
    assert [s.state for s in report.steps] == ["FAILED"]


@pytest.mark.asyncio
async def test_self_pair_writes_nothing_when_applied(db):
    await _seed_superseded_decision(db)
    (report,) = await repair_orphan_supersedes(db, PROJECT, {DEC: DEC}, dry_run=False)

    assert report.applied is False

    row = await db.fetchone("SELECT superseded_by, scope_version FROM decisions WHERE id = ?", [DEC])
    assert row["superseded_by"] is None
    assert row["scope_version"] == 1

    loops = await db.fetchone(
        "SELECT COUNT(*) AS n FROM entity_links "
        "WHERE link_type = 'supersedes' AND source_id = ? AND target_id = ?",
        [DEC, DEC],
    )
    assert loops["n"] == 0


@pytest.mark.asyncio
async def test_a_genuine_pair_still_repairs(db):
    """The guard must not block the case the repair exists for."""
    await _seed_superseded_decision(db)
    new_id = "dec_01SELFSUPERSEDE1111111111"
    await db.execute(
        "INSERT INTO decisions (id, project_id, question, chosen, rationale, "
        "decided_by, kind, phase, status, scope_version) "
        "VALUES (?, ?, ?, ?, ?, 'pi', 'decision', 'test', 'active', 1)",
        [new_id, PROJECT, "q2", "c2", "r2"],
    )

    (report,) = await repair_orphan_supersedes(db, PROJECT, {DEC: new_id}, dry_run=False)

    assert report.failure_reason is None
    row = await db.fetchone("SELECT superseded_by FROM decisions WHERE id = ?", [DEC])
    assert row["superseded_by"] == new_id
