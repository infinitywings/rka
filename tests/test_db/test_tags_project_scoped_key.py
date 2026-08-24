"""Tag uniqueness is per project, not global.

`tags` predates multi-project RKA: its primary key was
`(tag, entity_type, entity_id)`, and migration 004 added `project_id` as a
column without touching the key. Every other table's uniqueness is
project-scoped; this one stayed global.

Invisible in normal use, because entity ids are unique across projects anyway.
It bites when a knowledge pack is imported into a database that already holds
its source project — import preserves entity ids, so the first duplicated tag
aborts the whole import with

    UNIQUE constraint failed: tags.tag, tags.entity_type, tags.entity_id

Cloning a project for testing is that operation, and so is importing the
published example pack into an instance that already has it.
"""

from __future__ import annotations

import sqlite3

import pytest


async def _tag(db, *, project_id: str, entity_id: str = "jrn_shared", tag: str = "phase-1") -> None:
    await db.execute(
        "INSERT INTO tags (tag, entity_type, entity_id, project_id) VALUES (?, 'journal', ?, ?)",
        [tag, entity_id, project_id],
    )
    await db.commit()


@pytest.mark.asyncio
async def test_the_same_tag_and_entity_id_can_exist_in_two_projects(db):
    """The regression: a pack import re-creating entity ids must not collide."""
    await _tag(db, project_id="prj_one")
    await _tag(db, project_id="prj_two")

    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM tags WHERE entity_id = 'jrn_shared' AND tag = 'phase-1'"
    )
    assert row["n"] == 2


@pytest.mark.asyncio
async def test_a_duplicate_within_one_project_is_still_refused(db):
    """The guard against the fix over-relaxing: uniqueness still holds."""
    await _tag(db, project_id="prj_one")

    with pytest.raises(sqlite3.IntegrityError):
        await _tag(db, project_id="prj_one")


@pytest.mark.asyncio
async def test_the_primary_key_names_the_project(db):
    row = await db.fetchone("SELECT sql FROM sqlite_master WHERE name = 'tags'")
    key = row["sql"].split("PRIMARY KEY")[1]
    assert "project_id" in key, (
        "tag uniqueness must be project-scoped; a global key aborts any pack "
        "import into a database that already holds the source project"
    )


@pytest.mark.asyncio
async def test_the_change_triggers_survived_the_rebuild(db):
    """A rebuild drops triggers with the old table, and silently.

    Writes keep working; the change cursor just stops seeing tag edges. This
    assertion was missing from the first draft of the migration, and three
    existing change-tracking tests caught it.
    """
    rows = await db.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'tags'"
    )
    names = {r["name"] for r in rows}
    assert names >= {
        "trg_change_tags_insert",
        "trg_change_tags_update",
        "trg_change_tags_delete",
    }


@pytest.mark.asyncio
async def test_a_tag_write_still_lands_in_the_change_cursor(db):
    """Trigger presence is not the same as trigger function."""
    before = await db.fetchone(
        "SELECT COUNT(*) AS n FROM change_events WHERE source_table = 'tags'"
    )
    await _tag(db, project_id="prj_cursor", entity_id="jrn_cursor")
    after = await db.fetchone(
        "SELECT COUNT(*) AS n FROM change_events WHERE source_table = 'tags'"
    )
    assert after["n"] == before["n"] + 1


@pytest.mark.asyncio
async def test_the_lookup_indexes_survived_the_rebuild(db):
    """A table rebuild silently drops indexes that are not recreated."""
    rows = await db.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tags'"
    )
    names = {r["name"] for r in rows}
    assert {"idx_tags_entity", "idx_tags_tag", "idx_tags_project"} <= names
