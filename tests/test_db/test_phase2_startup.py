"""Database startup tests for Phase 2 initialization."""

from __future__ import annotations

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

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(Database, "run_migrations", fake_run_migrations)
    monkeypatch.setattr(Database, "_load_sqlite_vec", fake_load_sqlite_vec)
    monkeypatch.setattr(db.conn, "executescript", fake_executescript)
    monkeypatch.setattr(db.conn, "commit", fake_commit)

    try:
        await db.initialize_phase2_schema()
    finally:
        await db.close()

    assert run_states == [True]
