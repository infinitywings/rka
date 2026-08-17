"""Migration 049 typed academic-writing schema and event contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rka.infra.ids import generate_id


MIGRATION_049 = (
    Path(__file__).parents[2]
    / "rka"
    / "db"
    / "migrations"
    / "049_add_typed_academic_writing_core.sql"
)


def test_late_application_preserves_existing_rows_with_honest_defaults(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "late-049.db")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE manuscript_units (
                id TEXT NOT NULL,
                manuscript_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (id, manuscript_id, project_id)
            );
            CREATE TABLE manuscript_reference_members (
                id TEXT NOT NULL,
                manuscript_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (id, manuscript_id, project_id)
            );
            CREATE TABLE manuscript_unit_outline_profiles (
                unit_id TEXT PRIMARY KEY,
                manuscript_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                outline_level INTEGER NOT NULL DEFAULT 4,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE manuscript_unit_evidence (
                manuscript_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                evidence_claim_id TEXT NOT NULL,
                role TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                created_at TEXT,
                PRIMARY KEY (unit_id, evidence_claim_id, role)
            );
            CREATE TABLE manuscript_claim_versions (
                claim_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                manuscript_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                exact_wording TEXT NOT NULL,
                allowed_wording TEXT NOT NULL,
                prohibited_wording TEXT NOT NULL,
                created_at TEXT,
                PRIMARY KEY (claim_id, version)
            );
            CREATE TABLE change_events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                source_table TEXT NOT NULL,
                operation TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                manuscript_id TEXT,
                manuscript_claim_id TEXT,
                manuscript_unit_id TEXT,
                related_entity_type TEXT,
                related_entity_id TEXT,
                details TEXT
            );
            INSERT INTO manuscript_units
            VALUES ('mun_existing', 'man_existing', 'prj_existing');
            INSERT INTO manuscript_unit_outline_profiles
            VALUES ('mun_existing', 'man_existing', 'prj_existing', 3, NULL, NULL);
            INSERT INTO manuscript_unit_evidence
            VALUES (
                'man_existing', 'prj_existing', 'mun_existing',
                'clm_existing', 'support', 0, NULL
            );
            INSERT INTO manuscript_claim_versions
            VALUES (
                'mcl_existing', 1, 'man_existing', 'prj_existing',
                'Bounded claim.', 'Bounded claim.', '["Overclaim."]', NULL
            );
            """
        )
        connection.executescript(MIGRATION_049.read_text())

        assert connection.execute(
            """SELECT unit_role, rhetorical_move
               FROM manuscript_unit_outline_profiles"""
        ).fetchone() == ("unspecified", "unspecified")
        assert connection.execute(
            """SELECT supported_proposition, warrant
               FROM manuscript_unit_evidence"""
        ).fetchone() == (None, None)
        assert connection.execute(
            """SELECT conditions, falsification_criteria
               FROM manuscript_claim_versions"""
        ).fetchone() == ("[]", "[]")
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_typed_academic_columns_and_citation_events(db_with_project) -> None:
    manuscript_id = generate_id("manuscript")
    unit_id = generate_id("manuscript_unit")
    reference_id = generate_id("manuscript_reference")
    citation_id = generate_id("manuscript_unit_citation")
    literature_id = generate_id("literature")
    await db_with_project.execute(
        """INSERT INTO manuscripts (id, project_id, title)
           VALUES (?, 'proj_default', 'Typed migration')""",
        [manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_units
           (id, manuscript_id, project_id, local_key, kind, location)
           VALUES (?, ?, 'proj_default', 'R1', 'other', 'results')""",
        [unit_id, manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_unit_outline_profiles
           (unit_id, manuscript_id, project_id, outline_level,
            unit_role, rhetorical_move)
           VALUES (?, ?, 'proj_default', 3, 'result', 'present_result')""",
        [unit_id, manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO literature
           (id, title, authors, year, doi, status, added_by, project_id)
           VALUES (?, 'Typed citation', '[]', 2026, '10.1000/typed',
                   'cited', 'pi', 'proj_default')""",
        [literature_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_reference_members
           (id, manuscript_id, project_id, citation_key, literature_id)
           VALUES (?, ?, 'proj_default', 'typed2026', ?)""",
        [reference_id, manuscript_id, literature_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_unit_citations
           (id, manuscript_id, project_id, unit_id, reference_member_id,
            citation_role, supported_proposition, verification_state)
           VALUES (?, ?, 'proj_default', ?, ?, 'imports',
                   'The unit imports a prior definition.', 'self_attested')""",
        [citation_id, manuscript_id, unit_id, reference_id],
    )
    await db_with_project.commit()

    profile = await db_with_project.fetchone(
        """SELECT unit_role, rhetorical_move
           FROM manuscript_unit_outline_profiles WHERE unit_id = ?""",
        [unit_id],
    )
    assert profile == {"unit_role": "result", "rhetorical_move": "present_result"}
    event = await db_with_project.fetchone(
        """SELECT entity_type, manuscript_id, manuscript_unit_id,
                  related_entity_type, related_entity_id
           FROM change_events
           WHERE source_table = 'manuscript_unit_citations' AND entity_id = ?""",
        [citation_id],
    )
    assert event == {
        "entity_type": "manuscript_citation",
        "manuscript_id": manuscript_id,
        "manuscript_unit_id": unit_id,
        "related_entity_type": "manuscript_reference",
        "related_entity_id": reference_id,
    }


@pytest.mark.asyncio
async def test_typed_academic_constraints_and_migration_restart(db) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """INSERT INTO manuscript_unit_citations
               (id, manuscript_id, project_id, unit_id, reference_member_id,
                citation_role, supported_proposition)
               VALUES ('muc_bad', 'man_bad', 'proj_default', 'mun_bad',
                       'mrf_bad', 'mentions', 'Invalid role')"""
        )
    assert await db.fetchone(
        "SELECT filename FROM schema_migrations WHERE filename = ?",
        ["049_add_typed_academic_writing_core.sql"],
    ) == {"filename": "049_add_typed_academic_writing_core.sql"}
    assert await db.run_migrations() == 0
