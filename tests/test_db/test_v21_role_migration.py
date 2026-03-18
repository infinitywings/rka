"""Tests for v2.1 Phase 1: migration 013 correctness."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from rka.infra.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    db_path = str(tmp_path / "test_migration_013.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_agent_roles_columns(db: Database):
    """agent_roles has all required columns."""
    info = await db.fetchall("PRAGMA table_info(agent_roles)")
    cols = {row["name"] for row in info}
    required = {
        "id", "project_id", "name", "description", "system_prompt_template",
        "subscriptions", "subscription_filters", "role_state", "learnings_digest",
        "autonomy_profile", "model", "model_tier", "tools_config",
        "active_session_id", "last_active_at", "created_at", "updated_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


@pytest.mark.asyncio
async def test_role_events_columns(db: Database):
    """role_events has all required columns."""
    info = await db.fetchall("PRAGMA table_info(role_events)")
    cols = {row["name"] for row in info}
    required = {
        "id", "project_id", "target_role_id", "event_type", "source_role_id",
        "source_entity_id", "source_entity_type", "payload", "status",
        "priority", "depends_on", "created_at", "processed_at", "acked_at",
    }
    assert required.issubset(cols), f"Missing columns: {required - cols}"


@pytest.mark.asyncio
async def test_role_events_status_check(db: Database):
    """role_events.status must be one of the valid values."""
    # Insert a valid status should work
    await db.execute(
        "INSERT INTO agent_roles (id, project_id, name) VALUES ('arl_test', 'proj_default', 'test_role')"
    )
    await db.execute(
        """INSERT INTO role_events (id, project_id, target_role_id, event_type, status)
           VALUES ('rve_ok', 'proj_default', 'arl_test', 'test', 'pending')"""
    )
    await db.commit()

    # Invalid status should fail
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO role_events (id, project_id, target_role_id, event_type, status)
               VALUES ('rve_bad', 'proj_default', 'arl_test', 'test', 'invalid_status')"""
        )
        await db.commit()


@pytest.mark.asyncio
async def test_unique_project_name_constraint(db: Database):
    """(project_id, name) should be unique on agent_roles."""
    await db.execute(
        "INSERT INTO agent_roles (id, project_id, name) VALUES ('arl_1', 'proj_default', 'dupe')"
    )
    await db.commit()
    with pytest.raises(Exception):
        await db.execute(
            "INSERT INTO agent_roles (id, project_id, name) VALUES ('arl_2', 'proj_default', 'dupe')"
        )
        await db.commit()


@pytest.mark.asyncio
async def test_migration_idempotent_on_rerun(db: Database):
    """Re-running migrations should apply 0 new ones."""
    count = await db.run_migrations()
    assert count == 0
