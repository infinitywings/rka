"""Migration 047 outline-profile schema and project boundary checks."""

from __future__ import annotations

import sqlite3

import pytest

from rka.infra.ids import generate_id


@pytest.mark.asyncio
async def test_outline_profile_schema_and_change_events(db_with_project) -> None:
    manuscript_id = generate_id("manuscript")
    parent_id = generate_id("manuscript_unit")
    child_id = generate_id("manuscript_unit")
    await db_with_project.execute(
        """INSERT INTO manuscripts
           (id, project_id, title, phase, state)
           VALUES (?, 'proj_default', 'Migration outline', 'planning', 'active')""",
        [manuscript_id],
    )
    for unit_id, key, sequence in (
        (parent_id, "PARENT", 0),
        (child_id, "CHILD", 10),
    ):
        await db_with_project.execute(
            """INSERT INTO manuscript_units
               (id, manuscript_id, project_id, local_key, kind, location, sequence)
               VALUES (?, ?, 'proj_default', ?, 'other', ?, ?)""",
            [unit_id, manuscript_id, key, f"outline/{key}", sequence],
        )
    await db_with_project.execute(
        """INSERT INTO manuscript_unit_outline_profiles
           (unit_id, manuscript_id, project_id, parent_unit_id, outline_level,
            communicative_job, intended_takeaway, evidence_plan)
           VALUES (?, ?, 'proj_default', ?, 3, 'Explain one point.',
                   'Reader understands it.', '["Use C1."]')""",
        [child_id, manuscript_id, parent_id],
    )
    await db_with_project.commit()

    row = await db_with_project.fetchone(
        "SELECT * FROM manuscript_unit_outline_profiles WHERE unit_id = ?",
        [child_id],
    )
    assert row["parent_unit_id"] == parent_id
    assert row["outline_level"] == 3
    event = await db_with_project.fetchone(
        """SELECT * FROM change_events
           WHERE source_table = 'manuscript_unit_outline_profiles'
             AND entity_id = ?""",
        [child_id],
    )
    assert event["entity_type"] == "manuscript_unit"


@pytest.mark.asyncio
async def test_outline_profile_rejects_cross_project_parent(db_with_project) -> None:
    await db_with_project.execute(
        "INSERT INTO projects (id, name) VALUES ('proj_outline_other', 'Other')"
    )
    own_manuscript = generate_id("manuscript")
    foreign_manuscript = generate_id("manuscript")
    own_unit = generate_id("manuscript_unit")
    foreign_unit = generate_id("manuscript_unit")
    await db_with_project.execute(
        """INSERT INTO manuscripts (id, project_id, title, phase, state)
           VALUES (?, 'proj_default', 'Own', 'planning', 'active')""",
        [own_manuscript],
    )
    await db_with_project.execute(
        """INSERT INTO manuscripts (id, project_id, title, phase, state)
           VALUES (?, 'proj_outline_other', 'Foreign', 'planning', 'active')""",
        [foreign_manuscript],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_units
           (id, manuscript_id, project_id, local_key, kind, location)
           VALUES (?, ?, 'proj_default', 'OWN', 'other', 'own')""",
        [own_unit, own_manuscript],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_units
           (id, manuscript_id, project_id, local_key, kind, location)
           VALUES (?, ?, 'proj_outline_other', 'FOREIGN', 'other', 'foreign')""",
        [foreign_unit, foreign_manuscript],
    )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        await db_with_project.execute(
            """INSERT INTO manuscript_unit_outline_profiles
               (unit_id, manuscript_id, project_id, parent_unit_id, outline_level)
               VALUES (?, ?, 'proj_default', ?, 3)""",
            [own_unit, own_manuscript, foreign_unit],
        )
