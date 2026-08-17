"""Migration 050 source proposal immutability and restart contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rka.infra.ids import generate_id


MIGRATION_050 = (
    Path(__file__).parents[2]
    / "rka"
    / "db"
    / "migrations"
    / "050_add_manuscript_source_sync.sql"
)


def test_migration_050_applies_late_without_mutating_existing_manuscript(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "late-050.db")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY
            );
            CREATE TABLE manuscripts (
                id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (id, project_id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE TABLE semantic_patch_context_manifests (
                id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (id, project_id)
            );
            CREATE TABLE change_events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                source_table TEXT NOT NULL,
                operation TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                manuscript_id TEXT,
                details TEXT
            );
            CREATE TABLE project_deletion_authorizations (
                project_id TEXT PRIMARY KEY
            );
            INSERT INTO projects VALUES ('prj_existing');
            INSERT INTO manuscripts
            VALUES ('man_existing', 'prj_existing', 'Existing manuscript');
            """
        )

        connection.executescript(MIGRATION_050.read_text())

        assert connection.execute(
            "SELECT title FROM manuscripts WHERE id = 'man_existing'"
        ).fetchone() == ("Existing manuscript",)
        assert {
            row[0]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'table' AND name LIKE 'manuscript_source_%'"""
            )
        } == {"manuscript_source_proposals", "manuscript_source_events"}
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_migration_050_tables_triggers_and_restart(db_with_project) -> None:
    tables = {
        row["name"]
        for row in await db_with_project.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"manuscript_source_proposals", "manuscript_source_events"} <= tables
    assert generate_id("manuscript_source_proposal").startswith("msp_")
    assert generate_id("manuscript_source_event").startswith("mse_")
    assert await db_with_project.run_migrations() == 0


@pytest.mark.asyncio
async def test_source_event_and_proposal_content_are_immutable(db_with_project) -> None:
    manuscript_id = generate_id("manuscript")
    proposal_id = generate_id("manuscript_source_proposal")
    await db_with_project.execute(
        """INSERT INTO manuscripts
           (id, project_id, title, phase, state)
           VALUES (?, 'proj_default', 'Source migration', 'planning', 'active')""",
        [manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_source_proposals
           (id, project_id, manuscript_id, origin, relative_path, source_format,
            base_content_hash, proposed_content, proposed_content_hash,
            created_by, reason, boundary)
           VALUES (?, 'proj_default', ?, 'human', 'main.md', 'markdown',
                   ?, 'after', ?, 'web_ui', 'Test proposal.', 'none')""",
        [proposal_id, manuscript_id, "a" * 64, "b" * 64],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_source_events
           (id, proposal_id, project_id, proposal_revision, action, actor, reason)
           VALUES (?, ?, 'proj_default', 1, 'proposed', 'web_ui', 'Test event.')""",
        [generate_id("manuscript_source_event"), proposal_id],
    )
    await db_with_project.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db_with_project.execute(
            "UPDATE manuscript_source_events SET reason = 'changed' WHERE proposal_id = ?",
            [proposal_id],
        )
    await db_with_project.conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await db_with_project.execute(
            "UPDATE manuscript_source_proposals SET proposed_content = 'changed' WHERE id = ?",
            [proposal_id],
        )
