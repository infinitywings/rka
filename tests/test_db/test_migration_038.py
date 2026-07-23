"""Migration 038 contracts for authoritative manuscript reference membership."""

from __future__ import annotations

import json
import sqlite3

import pytest


async def _seed_reference_scopes(db) -> None:
    """Create two projects with manuscripts and literature for FK tests."""
    await db.execute(
        """INSERT INTO projects (id, name, created_by)
           VALUES ('proj_reference_foreign', 'Reference Foreign', 'test')"""
    )
    await db.execute(
        """INSERT INTO manuscripts (id, project_id, title)
           VALUES ('man_ref_default', 'proj_default', 'Default manuscript')"""
    )
    await db.execute(
        """INSERT INTO manuscripts (id, project_id, title)
           VALUES (
               'man_ref_foreign',
               'proj_reference_foreign',
               'Foreign manuscript'
           )"""
    )
    await db.execute(
        """INSERT INTO literature (id, title, added_by, project_id)
           VALUES (
               'lit_ref_default',
               'Default reference',
               'web_ui',
               'proj_default'
           )"""
    )
    await db.execute(
        """INSERT INTO literature (id, title, added_by, project_id)
           VALUES (
               'lit_ref_default_two',
               'Second default reference',
               'web_ui',
               'proj_default'
           )"""
    )
    await db.execute(
        """INSERT INTO literature (id, title, added_by, project_id)
           VALUES (
               'lit_ref_foreign',
               'Foreign reference',
               'web_ui',
               'proj_reference_foreign'
           )"""
    )


async def _insert_member(
    db,
    *,
    member_id: str,
    citation_key: str,
    literature_id: str = "lit_ref_default",
    manuscript_id: str = "man_ref_default",
    project_id: str = "proj_default",
    state: str = "active",
    retired_at: str | None = None,
) -> None:
    await db.execute(
        """INSERT INTO manuscript_reference_members (
               id, manuscript_id, project_id, citation_key, literature_id,
               state, retired_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            member_id,
            manuscript_id,
            project_id,
            citation_key,
            literature_id,
            state,
            retired_at,
        ],
    )


@pytest.mark.asyncio
async def test_reference_members_require_same_project_parents(db) -> None:
    await _seed_reference_scopes(db)

    with pytest.raises(sqlite3.IntegrityError):
        await _insert_member(
            db,
            member_id="mrf_foreign_manuscript",
            citation_key="ForeignManuscript2026",
            manuscript_id="man_ref_foreign",
        )

    with pytest.raises(sqlite3.IntegrityError):
        await _insert_member(
            db,
            member_id="mrf_foreign_literature",
            citation_key="ForeignLiterature2026",
            literature_id="lit_ref_foreign",
        )

    assert await db.fetchall("SELECT * FROM manuscript_reference_members") == []
    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_active_reference_uniqueness_is_case_insensitive_and_by_literature(
    db,
) -> None:
    await _seed_reference_scopes(db)
    await _insert_member(
        db,
        member_id="mrf_unique_original",
        citation_key="Smith2026",
    )

    with pytest.raises(sqlite3.IntegrityError):
        await _insert_member(
            db,
            member_id="mrf_duplicate_key",
            citation_key="smith2026",
            literature_id="lit_ref_default_two",
        )

    with pytest.raises(sqlite3.IntegrityError):
        await _insert_member(
            db,
            member_id="mrf_duplicate_literature",
            citation_key="Jones2026",
        )

    retired_at = "2026-07-23T12:00:00.000Z"
    await db.execute(
        """UPDATE manuscript_reference_members
           SET state = 'retired', retired_at = ?, updated_at = ?
           WHERE id = 'mrf_unique_original'""",
        [retired_at, retired_at],
    )
    await _insert_member(
        db,
        member_id="mrf_unique_replacement",
        citation_key="smith2026",
    )

    rows = await db.fetchall(
        """SELECT id, state
           FROM manuscript_reference_members
           ORDER BY id"""
    )
    assert rows == [
        {"id": "mrf_unique_original", "state": "retired"},
        {"id": "mrf_unique_replacement", "state": "active"},
    ]


@pytest.mark.asyncio
async def test_reference_member_identity_and_lifecycle_are_immutable(db) -> None:
    await _seed_reference_scopes(db)

    with pytest.raises(sqlite3.IntegrityError):
        await _insert_member(
            db,
            member_id="mrf_invalid_active_timestamp",
            citation_key="InvalidActive2026",
            retired_at="2026-07-23T12:00:00.000Z",
        )
    with pytest.raises(sqlite3.IntegrityError):
        await _insert_member(
            db,
            member_id="mrf_invalid_retired_timestamp",
            citation_key="InvalidRetired2026",
            state="retired",
        )

    await _insert_member(
        db,
        member_id="mrf_lifecycle",
        citation_key="Lifecycle2026",
    )
    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        await db.execute(
            """UPDATE manuscript_reference_members
               SET citation_key = 'Changed2026'
               WHERE id = 'mrf_lifecycle'"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        await db.execute(
            """UPDATE manuscript_reference_members
               SET created_at = '2026-07-23T00:00:00.000Z'
               WHERE id = 'mrf_lifecycle'"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        await db.execute(
            """UPDATE manuscript_reference_members
               SET updated_at = '2026-07-23T00:00:00.000Z'
               WHERE id = 'mrf_lifecycle'"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """UPDATE manuscript_reference_members
               SET state = 'retired'
               WHERE id = 'mrf_lifecycle'"""
        )

    retired_at = "2026-07-23T12:01:00.000Z"
    await db.execute(
        """UPDATE manuscript_reference_members
           SET state = 'retired', retired_at = ?, updated_at = ?
           WHERE id = 'mrf_lifecycle'""",
        [retired_at, retired_at],
    )
    row = await db.fetchone(
        """SELECT citation_key, literature_id, state, retired_at
           FROM manuscript_reference_members
           WHERE id = 'mrf_lifecycle'"""
    )
    assert row == {
        "citation_key": "Lifecycle2026",
        "literature_id": "lit_ref_default",
        "state": "retired",
        "retired_at": retired_at,
    }

    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        await db.execute(
            """UPDATE manuscript_reference_members
               SET state = 'active', retired_at = NULL
               WHERE id = 'mrf_lifecycle'"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        await db.execute(
            """UPDATE manuscript_reference_members
               SET updated_at = '2026-07-23T12:02:00.000Z'
               WHERE id = 'mrf_lifecycle'"""
        )


@pytest.mark.asyncio
async def test_reference_member_delete_requires_matching_project_authorization(
    db,
) -> None:
    await _seed_reference_scopes(db)
    await _insert_member(
        db,
        member_id="mrf_delete_guard",
        citation_key="DeleteGuard2026",
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await db.execute(
            """DELETE FROM manuscript_reference_members
               WHERE id = 'mrf_delete_guard'"""
        )
    assert await db.fetchone(
        """SELECT id FROM manuscript_reference_members
           WHERE id = 'mrf_delete_guard'"""
    ) == {"id": "mrf_delete_guard"}

    await db.execute(
        """INSERT INTO project_deletion_authorizations (project_id)
           VALUES ('proj_reference_foreign')"""
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await db.execute(
            """DELETE FROM manuscript_reference_members
               WHERE id = 'mrf_delete_guard'"""
        )
    await db.execute(
        """DELETE FROM project_deletion_authorizations
           WHERE project_id = 'proj_reference_foreign'"""
    )

    await db.execute(
        """INSERT INTO project_deletion_authorizations (project_id)
           VALUES ('proj_default')"""
    )
    await db.execute(
        """DELETE FROM manuscript_reference_members
           WHERE id = 'mrf_delete_guard'"""
    )
    await db.execute(
        """DELETE FROM project_deletion_authorizations
           WHERE project_id = 'proj_default'"""
    )

    assert await db.fetchone(
        """SELECT id FROM manuscript_reference_members
           WHERE id = 'mrf_delete_guard'"""
    ) is None
    assert await db.fetchall("SELECT * FROM project_deletion_authorizations") == []


@pytest.mark.asyncio
async def test_reference_membership_insert_and_retire_emit_semantic_events(
    db,
) -> None:
    await _seed_reference_scopes(db)
    await _insert_member(
        db,
        member_id="mrf_event",
        citation_key="Event2026",
    )
    retired_at = "2026-07-23T12:03:00.000Z"
    await db.execute(
        """UPDATE manuscript_reference_members
           SET state = 'retired', retired_at = ?, updated_at = ?
           WHERE id = 'mrf_event'""",
        [retired_at, retired_at],
    )

    events = await db.fetchall(
        """SELECT operation, entity_type, entity_id, manuscript_id,
                  related_entity_type, related_entity_id, details
           FROM change_events
           WHERE source_table = 'manuscript_reference_members'
             AND entity_id = 'mrf_event'
           ORDER BY cursor"""
    )
    assert len(events) == 2
    assert events[0] | {"details": json.loads(events[0]["details"])} == {
        "operation": "insert",
        "entity_type": "manuscript_reference",
        "entity_id": "mrf_event",
        "manuscript_id": "man_ref_default",
        "related_entity_type": "literature",
        "related_entity_id": "lit_ref_default",
        "details": {
            "citation_key": "Event2026",
            "state": "active",
        },
    }
    assert events[1] | {"details": json.loads(events[1]["details"])} == {
        "operation": "update",
        "entity_type": "manuscript_reference",
        "entity_id": "mrf_event",
        "manuscript_id": "man_ref_default",
        "related_entity_type": "literature",
        "related_entity_id": "lit_ref_default",
        "details": {
            "citation_key": "Event2026",
            "state": "retired",
            "previous_citation_key": "Event2026",
            "previous_state": "active",
            "previous_literature_id": "lit_ref_default",
        },
    }
