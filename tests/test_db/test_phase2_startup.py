"""Database startup tests for Phase 2 initialization."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from rka.infra.database import Database


@pytest.mark.asyncio
async def test_initialize_phase2_schema_reruns_migrations_after_vec_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db = Database(str(tmp_path / "phase2.db"))
    await db.connect()

    run_states: list[bool] = []

    async def fake_run_migrations(self: Database) -> int:
        run_states.append(self.vec_available)
        return 0

    async def fake_load_sqlite_vec(self: Database) -> None:
        self._vec_loaded = True

    async def fake_executescript(sql: str) -> None:
        return None

    monkeypatch.setattr(Database, "run_migrations", fake_run_migrations)
    monkeypatch.setattr(Database, "_load_sqlite_vec", fake_load_sqlite_vec)
    monkeypatch.setattr(db.conn, "executescript", fake_executescript)

    try:
        await db.initialize_phase2_schema()
    finally:
        await db.close()

    assert run_states == [True, True]


@pytest.mark.asyncio
async def test_phase2_schema_lock_has_bounded_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "phase2-timeout.db"
    db = Database(str(db_path))
    await db.connect()
    lock_path = db_path.with_name(f"{db_path.name}.phase2.lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setenv("RKA_MIGRATION_LOCK_TIMEOUT_MS", "25")

    try:
        with pytest.raises(TimeoutError, match="Phase 2 startup lock"):
            async with db._phase2_schema_lock():
                pytest.fail("contended sidecar lock must not be entered")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        await db.close()
