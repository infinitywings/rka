"""Migration 043 adds planning branches without disturbing existing data."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rka.infra.database import Database
from rka.models.planning import PlanningBranchCreate
from rka.services.planning import ManuscriptPlanningService


@pytest.mark.asyncio
async def test_042_upgrade_adds_recoverable_planning_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).parents[2] / "rka" / "db" / "migrations"
    before_dir = tmp_path / "migrations-before-043"
    before_dir.mkdir()
    for migration in source.glob("*.sql"):
        if migration.name.startswith("._"):
            continue
        if int(migration.name.split("_", 1)[0]) <= 42:
            shutil.copy2(migration, before_dir / migration.name)

    monkeypatch.setattr(Database, "_migrations_directory", staticmethod(lambda: before_dir))
    database = Database(str(tmp_path / "upgrade-042.db"))
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    try:
        await database.execute(
            """INSERT INTO journal
               (id, project_id, type, content, source, confidence)
               VALUES ('jrn_before_planning', 'proj_default', 'finding',
                       'Existing evidence survives migration.', 'executor', 'tested')"""
        )
        await database.commit()

        upgrade_dir = tmp_path / "migration-043-only"
        upgrade_dir.mkdir()
        migration_043 = source / "043_add_manuscript_planning_branches.sql"
        shutil.copy2(migration_043, upgrade_dir / migration_043.name)
        monkeypatch.setattr(Database, "_migrations_directory", staticmethod(lambda: upgrade_dir))

        assert await database.run_migrations() == 1
        branch = await ManuscriptPlanningService(database, project_id="proj_default").create_branch(
            PlanningBranchCreate(
                name="primary",
                purpose="Develop a paper framing without requiring a manuscript yet.",
                created_by="pi",
                reason="Begin project-level deliberation.",
            )
        )

        assert branch["branch"]["state"] == "selected"
        assert branch["branch"]["context_key"] == "project"
        assert await database.fetchone(
            "SELECT content FROM journal WHERE id = 'jrn_before_planning'"
        ) == {"content": "Existing evidence survives migration."}
        assert await database.fetchall("PRAGMA foreign_key_check") == []
        assert await database.fetchone(
            "SELECT filename FROM schema_migrations WHERE filename = ?",
            [migration_043.name],
        ) == {"filename": migration_043.name}
    finally:
        await database.close()
