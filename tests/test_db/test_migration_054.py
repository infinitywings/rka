"""Migration 054 adds source registration without disturbing populated Core data."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from rka.infra.database import Database


@pytest.mark.asyncio
async def test_054_upgrades_populated_database_and_enforces_immutable_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).parents[2] / "rka" / "db" / "migrations"
    before_dir = tmp_path / "migrations-before-054"
    before_dir.mkdir()
    for migration in source.glob("*.sql"):
        if migration.name.startswith("._"):
            continue
        if int(migration.name.split("_", 1)[0]) <= 53:
            shutil.copy2(migration, before_dir / migration.name)
    monkeypatch.setattr(Database, "_migrations_directory", staticmethod(lambda: before_dir))

    database = Database(str(tmp_path / "upgrade-053.db"))
    await database.connect()
    await database.initialize_schema()
    await database.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES ('jrn_before_054', 'proj_default', 'note', 'preserved', 'pi', 'tested')"""
    )
    await database.execute(
        """INSERT INTO artifacts
           (id, filename, filepath, file_size, content_hash, project_id)
           VALUES ('art_before_054', 'source.txt', '/tmp/source.txt', 3, ?, 'proj_default')""",
        ["a" * 64],
    )

    upgrade_dir = tmp_path / "migration-054-only"
    upgrade_dir.mkdir()
    migration = source / "054_add_registered_sources.sql"
    shutil.copy2(migration, upgrade_dir / migration.name)
    monkeypatch.setattr(Database, "_migrations_directory", staticmethod(lambda: upgrade_dir))
    try:
        assert await database.run_migrations() == 1
        assert await database.fetchone(
            "SELECT content FROM journal WHERE id = 'jrn_before_054'"
        ) == {"content": "preserved"}
        assert await database.fetchall("PRAGMA foreign_key_check") == []
        for table in ("registered_sources", "source_admissions"):
            assert await database.fetchone(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                [table],
            ) == {"name": table}

        await database.execute(
            """INSERT INTO registered_sources (
                   id, project_id, artifact_id, source_kind, content_mode, title,
                   content_hash, manifest_hash, ownership_kind, provenance, registered_by
               ) VALUES (
                   'src_migration_054', 'proj_default', 'art_before_054', 'file',
                   'bytes', 'Preserved file', ?, ?, 'unknown', '{}', 'pi'
               )""",
            ["a" * 64, "b" * 64],
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await database.execute(
                "UPDATE registered_sources SET title = 'changed' WHERE id = 'src_migration_054'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="project-authorized"):
            await database.execute(
                "DELETE FROM registered_sources WHERE id = 'src_migration_054'"
            )
    finally:
        await database.close()
