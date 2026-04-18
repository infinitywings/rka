"""Tests for migration 018: bi-temporal valid_until + calibration_outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from rka.infra.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Fresh DB with the full migration chain (schema.sql + 001..latest)."""
    db_path = str(tmp_path / "test_018.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_valid_until_columns_exist(db: Database):
    """claims.valid_until and evidence_clusters.synthesis_valid_until exist, both nullable."""
    claim_cols = {r["name"]: r["notnull"] for r in await db.fetchall("PRAGMA table_info(claims)")}
    assert "valid_until" in claim_cols
    assert claim_cols["valid_until"] == 0  # nullable

    # Migration 014's valid_from stays intact — the new column is a pair, not a replacement.
    assert "valid_from" in claim_cols
    assert "staleness" in claim_cols
    assert "stale_reason" in claim_cols

    cluster_cols = {r["name"]: r["notnull"] for r in await db.fetchall("PRAGMA table_info(evidence_clusters)")}
    assert "synthesis_valid_until" in cluster_cols
    assert cluster_cols["synthesis_valid_until"] == 0


@pytest.mark.asyncio
async def test_calibration_outcomes_schema(db: Database):
    """calibration_outcomes table shape matches the spec."""
    rows = await db.fetchall("PRAGMA table_info(calibration_outcomes)")
    columns = {r["name"]: r["type"] for r in rows}
    expected = {
        "id": "TEXT",
        "decision_id": "TEXT",
        "project_id": "TEXT",
        "outcome": "TEXT",
        "outcome_details": "TEXT",
        "recorded_at": "TEXT",
        "recorded_by": "TEXT",
    }
    assert columns == expected


@pytest.mark.asyncio
async def test_calibration_outcomes_fk_enforced(db: Database):
    """FK on calibration_outcomes.decision_id rejects inserts against a non-existent decision."""
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO calibration_outcomes (id, decision_id, project_id, outcome)
               VALUES ('co_bad', 'dec_missing', 'proj_default', 'succeeded')""",
        )


@pytest.mark.asyncio
async def test_calibration_outcomes_enum_check(db: Database):
    """CHECK constraint rejects outcome values outside the allowed enum."""
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
           VALUES ('dec_cal', 'p1', 'Q?', 'brain', 'active', 'proj_default')""",
    )
    await db.commit()

    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO calibration_outcomes (id, decision_id, project_id, outcome)
               VALUES ('co_bad_enum', 'dec_cal', 'proj_default', 'bogus')""",
        )


@pytest.mark.asyncio
async def test_valid_until_defaults_null_and_updatable(db: Database):
    """New claims default to valid_until=NULL; UPDATE to set a value works."""
    # Seed parent journal + claim.
    await db.execute(
        """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
           VALUES ('jrn_1', 'note', 'src', 'brain', 'hypothesis', 'normal', 'active', 0, 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO claims (id, source_entry_id, claim_type, content, project_id)
           VALUES ('clm_1', 'jrn_1', 'evidence', 'test claim', 'proj_default')""",
    )
    await db.commit()

    row = await db.fetchone("SELECT valid_until FROM claims WHERE id = 'clm_1'")
    assert row["valid_until"] is None

    await db.execute(
        "UPDATE claims SET valid_until = '2026-04-17T20:00:00Z' WHERE id = 'clm_1'"
    )
    await db.commit()
    row = await db.fetchone("SELECT valid_until FROM claims WHERE id = 'clm_1'")
    assert row["valid_until"] == '2026-04-17T20:00:00Z'
