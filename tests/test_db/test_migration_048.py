"""Migration 048 attributes the complete outline-profile event lifecycle."""

from __future__ import annotations

import pytest

from rka.infra.ids import generate_id


@pytest.mark.asyncio
async def test_outline_profile_events_include_manuscript_unit_and_delete(
    db_with_project,
) -> None:
    manuscript_id = generate_id("manuscript")
    unit_id = generate_id("manuscript_unit")
    await db_with_project.execute(
        """INSERT INTO manuscripts
           (id, project_id, title, phase, state)
           VALUES (?, 'proj_default', 'Attributed outline', 'planning', 'active')""",
        [manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_units
           (id, manuscript_id, project_id, local_key, kind, location)
           VALUES (?, ?, 'proj_default', 'ROOT', 'other', 'outline/root')""",
        [unit_id, manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_unit_outline_profiles
           (unit_id, manuscript_id, project_id, outline_level)
           VALUES (?, ?, 'proj_default', 2)""",
        [unit_id, manuscript_id],
    )
    await db_with_project.execute(
        """UPDATE manuscript_unit_outline_profiles
           SET communicative_job = 'Frame the paper.' WHERE unit_id = ?""",
        [unit_id],
    )
    await db_with_project.execute(
        "DELETE FROM manuscript_unit_outline_profiles WHERE unit_id = ?",
        [unit_id],
    )
    await db_with_project.commit()

    events = await db_with_project.fetchall(
        """SELECT operation, manuscript_id, manuscript_unit_id
           FROM change_events
           WHERE source_table = 'manuscript_unit_outline_profiles'
             AND entity_id = ?
           ORDER BY cursor""",
        [unit_id],
    )
    assert events == [
        {
            "operation": operation,
            "manuscript_id": manuscript_id,
            "manuscript_unit_id": unit_id,
        }
        for operation in ("insert", "update", "delete")
    ]


@pytest.mark.asyncio
async def test_migration_048_is_recorded_once(db) -> None:
    assert await db.fetchone(
        "SELECT filename FROM schema_migrations WHERE filename = ?",
        ["048_harden_outline_change_events.sql"],
    ) == {"filename": "048_harden_outline_change_events.sql"}
    assert await db.run_migrations() == 0
