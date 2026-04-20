"""Tests for migration 019: hooks + hook_executions + brain_notifications."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from rka.infra.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    db_path = str(tmp_path / "test_019.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_hooks_table_shape(db: Database):
    rows = await db.fetchall("PRAGMA table_info(hooks)")
    cols = {r["name"] for r in rows}
    assert {"id", "event", "scope", "project_id", "handler_type",
            "handler_config", "enabled", "name", "created_by",
            "created_at", "failure_policy"}.issubset(cols)


@pytest.mark.asyncio
async def test_hooks_event_check_enforced(db: Database):
    """hooks.event CHECK constraint rejects unknown event names."""
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO hooks (id, event, project_id, handler_type, handler_config, name)
               VALUES ('hk_bad', 'post_rocket_launch', 'proj_default', 'sql', '{}', 'bad')""",
        )


@pytest.mark.asyncio
async def test_hooks_handler_type_check_enforced(db: Database):
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO hooks (id, event, project_id, handler_type, handler_config, name)
               VALUES ('hk_bad2', 'session_start', 'proj_default', 'shell', '{}', 'bad')""",
        )


@pytest.mark.asyncio
async def test_hook_executions_fk_enforced(db: Database):
    """hook_executions.hook_id FK → hooks rejects orphan rows."""
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO hook_executions (id, hook_id, project_id, status)
               VALUES ('hkx_orphan', 'hk_nonexistent', 'proj_default', 'success')""",
        )


@pytest.mark.asyncio
async def test_hook_executions_status_check(db: Database):
    # Seed a parent hook first.
    await db.execute(
        """INSERT INTO hooks (id, event, project_id, handler_type, handler_config, name)
           VALUES ('hk_p', 'session_start', 'proj_default', 'sql', '{}', 'parent')""",
    )
    await db.commit()
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO hook_executions (id, hook_id, project_id, status)
               VALUES ('hkx_bad', 'hk_p', 'proj_default', 'purple')""",
        )


@pytest.mark.asyncio
async def test_brain_notifications_table_and_severity_check(db: Database):
    rows = await db.fetchall("PRAGMA table_info(brain_notifications)")
    cols = {r["name"] for r in rows}
    assert {"id", "project_id", "hook_id", "created_at", "cleared_at",
            "content", "severity"}.issubset(cols)
    # Severity CHECK
    with pytest.raises(Exception):
        await db.execute(
            """INSERT INTO brain_notifications (id, project_id, content, severity)
               VALUES ('bnt_bad', 'proj_default', '{}', 'panicked')""",
        )


@pytest.mark.asyncio
async def test_migration_019_applies_on_existing_db(db: Database):
    """Running initialize_schema twice (simulating re-apply) stays idempotent."""
    # Fixture already ran the full migration chain. Run it again — IF NOT EXISTS
    # in every CREATE statement keeps it idempotent.
    await db.initialize_schema()
    await db.initialize_phase2_schema()
    rows = await db.fetchall("PRAGMA table_info(hooks)")
    assert len(rows) > 0  # table still exists
