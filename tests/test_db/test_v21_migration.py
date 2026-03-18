"""Tests for migration 012: v2.1 knowledge foundation."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Create a fresh database with all migrations applied."""
    db_path = str(tmp_path / "test_v21.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_journal_has_provenance_and_role_id(db: Database):
    """After migration 012, journal table has provenance and role_id columns."""
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, pinned,
            provenance, role_id, project_id)
           VALUES ('jrn_v21_1', 'note', 'test', 'brain', 'hypothesis', 'normal',
                   'active', 0, '{"type": "manual_entry"}', 'researcher_brain', 'proj_default')"""
    )
    await db.commit()
    row = await db.fetchone("SELECT provenance, role_id FROM journal WHERE id = 'jrn_v21_1'")
    assert row is not None
    assert row["provenance"] == '{"type": "manual_entry"}'
    assert row["role_id"] == "researcher_brain"


@pytest.mark.asyncio
async def test_journal_provenance_nullable(db: Database):
    """Provenance and role_id default to NULL for backward compat."""
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, pinned, project_id)
           VALUES ('jrn_v21_2', 'note', 'test', 'brain', 'hypothesis', 'normal',
                   'active', 0, 'proj_default')"""
    )
    await db.commit()
    row = await db.fetchone("SELECT provenance, role_id FROM journal WHERE id = 'jrn_v21_2'")
    assert row is not None
    assert row["provenance"] is None
    assert row["role_id"] is None


@pytest.mark.asyncio
async def test_missions_has_role_id(db: Database):
    """Missions table has role_id column after migration."""
    await db.execute(
        """INSERT INTO missions
           (id, phase, objective, status, role_id, project_id)
           VALUES ('msn_v21_1', 'p1', 'test objective', 'pending',
                   'executor_impl', 'proj_default')"""
    )
    await db.commit()
    row = await db.fetchone("SELECT role_id FROM missions WHERE id = 'msn_v21_1'")
    assert row is not None
    assert row["role_id"] == "executor_impl"


@pytest.mark.asyncio
async def test_checkpoints_has_role_id(db: Database):
    """Checkpoints table has role_id column after migration."""
    # Create a mission first to satisfy FK constraint
    await db.execute(
        """INSERT INTO missions (id, phase, objective, status, project_id)
           VALUES ('msn_v21_chk', 'p1', 'test', 'pending', 'proj_default')"""
    )
    await db.execute(
        """INSERT INTO checkpoints
           (id, mission_id, type, description, blocking, role_id, project_id)
           VALUES ('chk_v21_1', 'msn_v21_chk', 'decision', 'test', 1,
                   'executor_impl', 'proj_default')"""
    )
    await db.commit()
    row = await db.fetchone("SELECT role_id FROM checkpoints WHERE id = 'chk_v21_1'")
    assert row is not None
    assert row["role_id"] == "executor_impl"


@pytest.mark.asyncio
async def test_decisions_has_role_id(db: Database):
    """Decisions table has role_id column after migration."""
    await db.execute(
        """INSERT INTO decisions
           (id, phase, question, decided_by, status, kind, role_id, project_id)
           VALUES ('dec_v21_1', 'p1', 'test question?', 'brain', 'active',
                   'decision', 'reviewer_brain', 'proj_default')"""
    )
    await db.commit()
    row = await db.fetchone("SELECT role_id FROM decisions WHERE id = 'dec_v21_1'")
    assert row is not None
    assert row["role_id"] == "reviewer_brain"


@pytest.mark.asyncio
async def test_jobs_has_model_tier(db: Database):
    """Jobs table has model_tier column after migration."""
    await db.execute(
        """INSERT INTO jobs
           (id, job_type, project_id, status, model_tier)
           VALUES ('job_v21_1', 'note_auto_tag', 'proj_default', 'pending', 'fast')"""
    )
    await db.commit()
    row = await db.fetchone("SELECT model_tier FROM jobs WHERE id = 'job_v21_1'")
    assert row is not None
    assert row["model_tier"] == "fast"


@pytest.mark.asyncio
async def test_migration_idempotent(tmp_path: Path):
    """Running migrations twice does not fail."""
    db_path = str(tmp_path / "test_idem.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    # Run again — should be a no-op
    count = await database.run_migrations()
    assert count == 0
    await database.close()
