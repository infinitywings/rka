"""Migration 031 separates evidence assessment from claim grounding."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).parents[2]
    / "rka"
    / "db"
    / "migrations"
    / "031_add_claim_evidence_status.sql"
)


def test_migration_preserves_legacy_claim_without_inferring_support(tmp_path: Path) -> None:
    """A legacy verified bit migrates to unassessed, never supported."""
    connection = sqlite3.connect(tmp_path / "migration-031.db")
    try:
        connection.executescript(
            """
            CREATE TABLE claims (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                verified INTEGER DEFAULT 0
            );
            INSERT INTO claims (id, project_id, verified)
            VALUES ('clm_legacy', 'prj_test', 1);
            """
        )
        connection.executescript(MIGRATION.read_text())

        row = connection.execute(
            "SELECT verified, evidence_status FROM claims WHERE id = 'clm_legacy'"
        ).fetchone()
        assert row == (1, "unassessed")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE claims SET evidence_status = 'verified' WHERE id = 'clm_legacy'"
            )
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_fresh_database_exposes_closed_evidence_status_column(db) -> None:
    """The normal migration runner installs the column and its index."""
    columns = await db.fetchall("PRAGMA table_info(claims)")
    evidence = next(c for c in columns if c["name"] == "evidence_status")
    assert evidence["notnull"] == 1
    assert evidence["dflt_value"] == "'unassessed'"

    indexes = await db.fetchall("PRAGMA index_list(claims)")
    assert "idx_claims_evidence_status" in {i["name"] for i in indexes}
