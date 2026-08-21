"""Migration 030 preserves the agentic staleness-resolution contract."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from rka.infra.database import Database


_RESOLUTION_COLUMNS = {
    "staleness_reviewed_at",
    "staleness_verdict",
    "staleness_resolution",
    "staleness_resolution_journal_id",
    "staleness_resolved_by",
}


@pytest.mark.asyncio
async def test_fresh_schema_contains_staleness_resolution_columns(db) -> None:
    for table in ("claims", "evidence_clusters"):
        columns = {row["name"] for row in await db.fetchall(f"PRAGMA table_info({table})")}
        assert _RESOLUTION_COLUMNS <= columns

    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES ('jrn_migration_030', 'proj_default', 'finding',
                   'Migration source', 'pi', 'verified')"""
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, project_id)
           VALUES ('clm_migration_030', 'jrn_migration_030', 'evidence',
                   'Migration claim', 'proj_default')"""
    )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        await db.execute(
            """UPDATE claims SET staleness_verdict = 'invented'
               WHERE id = 'clm_migration_030'"""
        )


@pytest.mark.asyncio
async def test_reserved_030_applies_after_later_main_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).parents[2] / "rka" / "db" / "migrations"
    without_030 = tmp_path / "migrations-without-030"
    without_030.mkdir()
    for migration in source.glob("*.sql"):
        if migration.name.startswith("._") or migration.name == "030_staleness_resolution.sql":
            continue
        shutil.copy2(migration, without_030 / migration.name)

    monkeypatch.setattr(Database, "_migrations_directory", staticmethod(lambda: without_030))
    database = Database(str(tmp_path / "late-030.db"))
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    try:
        before = {row["name"] for row in await database.fetchall("PRAGMA table_info(claims)")}
        assert "staleness_verdict" not in before
        assert await database.fetchone(
            "SELECT filename FROM schema_migrations WHERE filename = ?",
            ["031_add_claim_evidence_status.sql"],
        ) == {"filename": "031_add_claim_evidence_status.sql"}

        only_030 = tmp_path / "migration-030-only"
        only_030.mkdir()
        shutil.copy2(source / "030_staleness_resolution.sql", only_030)
        monkeypatch.setattr(Database, "_migrations_directory", staticmethod(lambda: only_030))

        assert await database.run_migrations() == 1
        after = {row["name"] for row in await database.fetchall("PRAGMA table_info(claims)")}
        assert _RESOLUTION_COLUMNS <= after
        assert await database.run_migrations() == 0
    finally:
        await database.close()
