"""Shared fixtures for RKA tests."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from rka.infra.database import Database


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Create a fresh in-memory database with schema initialized."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    await database.initialize_schema()
    await database.initialize_phase2_schema()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def db_with_project(db: Database):
    """Database with project_state initialized."""
    await db.execute(
        """INSERT INTO project_state (id, project_name, project_description, current_phase, phases_config)
           VALUES (1, 'Test Project', 'Unit test project', 'phase_1',
                   '["phase_1", "phase_2", "phase_3"]')"""
    )
    await db.commit()
    return db
