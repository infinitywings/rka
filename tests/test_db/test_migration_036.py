"""Schema contract for canonical asynchronous reference validation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rka.models.manuscript_native import ManuscriptCreate
from rka.services.jobs import JobQueue
from rka.services.manuscript import ManuscriptService
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.notes import NoteService


@pytest.mark.asyncio
async def test_async_reference_validation_columns_and_constraints(db) -> None:
    columns = {
        row["name"]
        for row in await db.fetchall(
            "PRAGMA table_info(reference_validation_attestations)"
        )
    }
    assert {
        "canonical_manuscript_id",
        "legacy_journal_id",
        "validation_job_id",
    } <= columns

    manuscript = await NativeManuscriptService(
        db, project_id="proj_default"
    ).create(ManuscriptCreate(title="Migration test"))
    job_id = await JobQueue(db).enqueue(
        "reference_validate",
        entity_type="manuscript",
        entity_id=manuscript.id,
        payload={"schema": "test"},
    )
    await db.execute(
        """INSERT INTO reference_validation_attestations
           (id, project_id, manuscript_id, canonical_manuscript_id,
            validation_job_id, input_authors, status,
            retraction_check_enabled, retraction_checked, sources_tried,
            sources_confirmed, notes, stage_trace, full_json_payload,
            started_at, completed_at)
           VALUES (?, 'proj_default', ?, ?, ?, '[]', 'error', 1, 0,
                   '[]', '[]', '[]', '{}', ?, 'start', 'end')""",
        [
            "rvd_async_migration",
            manuscript.id,
            manuscript.id,
            job_id,
            json.dumps({"result": {"status": "error"}}),
        ],
    )
    await db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db.execute(
            """UPDATE reference_validation_attestations
               SET status = 'VERIFIED' WHERE id = 'rvd_async_migration'"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO reference_validation_attestations
               (id, project_id, manuscript_id, canonical_manuscript_id,
                validation_job_id, input_authors, status,
                retraction_check_enabled, retraction_checked, sources_tried,
                sources_confirmed, notes, stage_trace, full_json_payload,
                started_at, completed_at)
               VALUES ('rvd_duplicate_job', 'proj_default', ?, ?, ?, '[]',
                       'error', 1, 0, '[]', '[]', '[]', '{}', '{}',
                       'start', 'end')""",
            [manuscript.id, manuscript.id, job_id],
        )


@pytest.mark.asyncio
async def test_reference_validation_change_event_uses_canonical_manuscript(db) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id="proj_default"
    ).create(ManuscriptCreate(title="Cursor test"))
    await db.execute(
        """INSERT INTO reference_validation_attestations
           (id, project_id, manuscript_id, canonical_manuscript_id,
            input_authors, status, retraction_check_enabled,
            retraction_checked, sources_tried, sources_confirmed, notes,
            stage_trace, full_json_payload, started_at, completed_at)
           VALUES ('rvd_cursor_test', 'proj_default', ?, ?, '[]', 'error',
                   1, 0, '[]', '[]', '[]', '{}', '{}', 'start', 'end')""",
        [manuscript.id, manuscript.id],
    )
    await db.commit()

    event = await db.fetchone(
        """SELECT manuscript_id, related_entity_type, related_entity_id
           FROM change_events
           WHERE source_table = 'reference_validation_attestations'
             AND entity_id = 'rvd_cursor_test'"""
    )
    assert event == {
        "manuscript_id": manuscript.id,
        "related_entity_type": "manuscript",
        "related_entity_id": manuscript.id,
    }


@pytest.mark.asyncio
async def test_migration_preserves_legacy_attestation_and_adds_exact_binding(db) -> None:
    legacy = await ManuscriptService(
        db,
        notes=NoteService(db, project_id="proj_default"),
        project_id="proj_default",
    ).register("USENIX", "Historical validation")
    canonical = await NativeManuscriptService(
        db, project_id="proj_default"
    ).resolve_id(legacy.id)
    assert canonical is not None

    # Recreate the migration-032 table to exercise an actual 035 -> 036
    # upgrade with a pre-existing immutable row.
    await db.conn.execute("DROP TABLE reference_validation_attestations")
    migration_032 = (
        Path(__file__).parents[2]
        / "rka"
        / "db"
        / "migrations"
        / "032_add_reference_validation_attestations.sql"
    ).read_text(encoding="utf-8")
    await db.conn.executescript(migration_032)
    await db.execute(
        """INSERT INTO reference_validation_attestations (
               id, project_id, manuscript_id, input_authors, status,
               retraction_check_enabled, retraction_checked, sources_tried,
               sources_confirmed, notes, stage_trace, full_json_payload,
               started_at, completed_at
           ) VALUES (
               'rvd_historical', 'proj_default', ?, '[]', 'VERIFIED',
               1, 1, '[]', '[]', '[]', '{}', '{"historical":true}',
               'start', 'end'
           )""",
        [legacy.id],
    )
    await db.execute(
        "DELETE FROM schema_migrations WHERE filename = ?",
        ["036_async_reference_validation.sql"],
    )
    await db.commit()

    assert await db.run_migrations() == 1
    row = await db.fetchone(
        "SELECT * FROM reference_validation_attestations WHERE id = 'rvd_historical'"
    )
    assert row["manuscript_id"] == legacy.id
    assert row["canonical_manuscript_id"] == canonical
    assert row["legacy_journal_id"] == legacy.id
    assert row["validation_job_id"] is None
    assert json.loads(row["full_json_payload"]) == {"historical": True}


@pytest.mark.asyncio
async def test_migration_quarantines_cross_project_edges_and_malformed_json(db) -> None:
    await db.execute(
        """INSERT INTO projects (id, name, created_by)
           VALUES ('proj_migration_other', 'Migration Other', 'test')"""
    )
    await db.execute(
        """INSERT INTO journal (
               id, type, content, source, confidence, importance, project_id
           ) VALUES (
               'jrn_cross_project', 'finding', 'Historical source', 'pi',
               'verified', 'normal', 'proj_migration_other'
           )"""
    )
    await db.execute(
        """INSERT INTO literature (id, title, project_id)
           VALUES ('lit_cross_project', 'Historical reference',
                   'proj_migration_other')"""
    )
    await db.commit()

    await db.conn.execute("DROP TABLE reference_validation_attestations")
    migration_032 = (
        Path(__file__).parents[2]
        / "rka"
        / "db"
        / "migrations"
        / "032_add_reference_validation_attestations.sql"
    ).read_text(encoding="utf-8")
    await db.conn.executescript(migration_032)
    # Migration 032's id-only foreign keys legally allowed both references,
    # even though their rows belonged to a different project.
    await db.execute(
        """INSERT INTO reference_validation_attestations (
               id, project_id, manuscript_id, literature_id, input_authors,
               status, retraction_check_enabled, retraction_checked,
               sources_tried, sources_confirmed, notes, stage_trace,
               full_json_payload, started_at, completed_at
           ) VALUES (
               'rvd_cross_project', 'proj_default', 'jrn_cross_project',
               'lit_cross_project', '{"wrong":"shape"}', 'error', 1, 0,
               '[', '{}', '[]', '[]', 'not-json', 'start', 'end'
           )"""
    )
    await db.execute(
        "DELETE FROM schema_migrations WHERE filename = ?",
        ["036_async_reference_validation.sql"],
    )
    await db.commit()

    assert await db.run_migrations() == 1
    row = await db.fetchone(
        """SELECT manuscript_id, canonical_manuscript_id, legacy_journal_id,
                  literature_id, input_authors, sources_tried,
                  sources_confirmed, notes, stage_trace, full_json_payload
           FROM reference_validation_attestations
           WHERE id = 'rvd_cross_project'"""
    )
    assert row["manuscript_id"] == "jrn_cross_project"
    assert row["canonical_manuscript_id"] is None
    assert row["legacy_journal_id"] is None
    assert row["literature_id"] is None
    assert json.loads(row["input_authors"]) == []
    assert json.loads(row["sources_tried"]) == []
    assert json.loads(row["sources_confirmed"]) == []
    assert json.loads(row["notes"]) == []
    assert json.loads(row["stage_trace"]) == {}
    assert json.loads(row["full_json_payload"]) == {
        "migration_normalized": 1,
        "legacy_payload_text": "not-json",
    }

    issues = await db.fetchall(
        """SELECT issue_code
           FROM reference_validation_migration_issues
           WHERE attestation_id = 'rvd_cross_project'
           ORDER BY issue_code"""
    )
    assert [row["issue_code"] for row in issues] == [
        "invalid_json_full_json_payload",
        "invalid_json_input_authors",
        "invalid_json_sources_confirmed",
        "invalid_json_sources_tried",
        "invalid_json_stage_trace",
        "literature_project_mismatch",
        "manuscript_project_mismatch",
    ]
    assert await db.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_attestation_project_scopes_literature_and_validation_job(db) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id="proj_default"
    ).create(ManuscriptCreate(title="Scoped attestation"))
    await db.execute(
        """INSERT INTO projects (id, name, created_by)
           VALUES ('proj_attestation_other', 'Attestation Other', 'test')"""
    )
    await db.execute(
        """INSERT INTO literature (id, title, project_id)
           VALUES ('lit_attestation_other', 'Other-project reference',
                   'proj_attestation_other')"""
    )
    await db.execute(
        """INSERT INTO jobs (
               id, job_type, project_id, entity_type, entity_id, payload
           ) VALUES (
               'job_attestation_other', 'reference_validate',
               'proj_attestation_other', 'manuscript', ?, '{}'
           )""",
        [manuscript.id],
    )
    await db.execute(
        """INSERT INTO jobs (
               id, job_type, project_id, entity_type, entity_id, payload
           ) VALUES (
               'job_wrong_semantics', 'note_embed', 'proj_default',
               'manuscript', ?, '{}'
           )""",
        [manuscript.id],
    )
    await db.commit()

    insert_sql = """INSERT INTO reference_validation_attestations (
                        id, project_id, manuscript_id,
                        canonical_manuscript_id, validation_job_id,
                        literature_id, input_authors, status,
                        retraction_check_enabled, retraction_checked,
                        sources_tried, sources_confirmed, notes, stage_trace,
                        full_json_payload, started_at, completed_at
                    ) VALUES (
                        ?, 'proj_default', ?, ?, ?, ?, '[]', 'error',
                        1, 0, '[]', '[]', '[]', '{}', '{}', 'start', 'end'
                    )"""

    with pytest.raises(sqlite3.IntegrityError, match="same-project"):
        await db.execute(
            insert_sql,
            [
                "rvd_cross_project_job",
                manuscript.id,
                manuscript.id,
                "job_attestation_other",
                None,
            ],
        )
    await db.conn.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="same-project"):
        await db.execute(
            insert_sql,
            [
                "rvd_wrong_job_semantics",
                manuscript.id,
                manuscript.id,
                "job_wrong_semantics",
                None,
            ],
        )
    await db.conn.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        await db.execute(
            insert_sql,
            [
                "rvd_cross_project_literature",
                manuscript.id,
                manuscript.id,
                None,
                "lit_attestation_other",
            ],
        )
    await db.conn.rollback()


@pytest.mark.asyncio
async def test_attestation_json_columns_require_expected_shapes(db) -> None:
    manuscript = await NativeManuscriptService(
        db, project_id="proj_default"
    ).create(ManuscriptCreate(title="JSON constraints"))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
        await db.execute(
            """INSERT INTO reference_validation_attestations (
                   id, project_id, manuscript_id, canonical_manuscript_id,
                   input_authors, status, retraction_check_enabled,
                   retraction_checked, sources_tried, sources_confirmed,
                   notes, stage_trace, full_json_payload, started_at,
                   completed_at
               ) VALUES (
                   'rvd_bad_json_shape', 'proj_default', ?, ?, '{}', 'error',
                   1, 0, '[]', '[]', '[]', '{}', '{}', 'start', 'end'
               )""",
            [manuscript.id, manuscript.id],
        )
    await db.conn.rollback()
