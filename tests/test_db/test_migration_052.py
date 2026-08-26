"""Migration 052 claim-membership uniqueness and count repair."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


MIGRATION_052 = (
    Path(__file__).parents[2]
    / "rka"
    / "db"
    / "migrations"
    / "052_claim_edge_membership_integrity.sql"
)


def test_migration_052_deduplicates_membership_and_repairs_counts(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "late-052.db")
    try:
        connection.executescript(
            """
            CREATE TABLE evidence_clusters (
                id TEXT PRIMARY KEY,
                claim_count INTEGER DEFAULT 0,
                updated_at TEXT,
                project_id TEXT NOT NULL
            );
            CREATE TABLE claim_edges (
                id TEXT PRIMARY KEY,
                source_claim_id TEXT NOT NULL,
                target_claim_id TEXT,
                cluster_id TEXT,
                relation TEXT NOT NULL,
                confidence REAL,
                project_id TEXT NOT NULL,
                created_at TEXT
            );
            INSERT INTO evidence_clusters
            VALUES ('ecl_one', 9, NULL, 'prj_one');
            INSERT INTO evidence_clusters
            VALUES ('ecl_null_count', NULL, NULL, 'prj_one');
            INSERT INTO claim_edges VALUES
              ('ced_oldest', 'clm_one', NULL, 'ecl_one', 'member_of',
               1.0, 'prj_one', '2026-01-01T00:00:00Z'),
              ('ced_duplicate', 'clm_one', NULL, 'ecl_one', 'member_of',
               0.5, 'prj_one', '2026-01-02T00:00:00Z');
            """
        )

        connection.executescript(MIGRATION_052.read_text())

        assert connection.execute(
            """SELECT id FROM claim_edges
               WHERE relation = 'member_of'"""
        ).fetchall() == [("ced_oldest",)]
        assert connection.execute(
            "SELECT claim_count FROM evidence_clusters WHERE id = 'ecl_one'"
        ).fetchone() == (1,)
        assert connection.execute(
            """SELECT claim_count FROM evidence_clusters
               WHERE id = 'ecl_null_count'"""
        ).fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO claim_edges
                   (id, source_claim_id, cluster_id, relation, project_id)
                   VALUES ('ced_again', 'clm_one', 'ecl_one', 'member_of',
                           'prj_one')"""
            )
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_migration_052_is_registered_and_restart_safe(db_with_project) -> None:
    assert await db_with_project.fetchone(
        "SELECT 1 FROM schema_migrations WHERE filename = ?",
        [MIGRATION_052.name],
    ) == {"1": 1}
    assert await db_with_project.run_migrations() == 0
