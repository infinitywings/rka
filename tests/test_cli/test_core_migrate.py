"""Core migration-command regressions."""

from __future__ import annotations

from types import SimpleNamespace

from click.testing import CliRunner

import rka.config as config_module
from rka.cli import main
from rka.infra.database import Database


def test_migrate_initializes_base_and_phase2_schema(monkeypatch) -> None:
    calls: list[str] = []

    async def record(name: str, result=None):
        calls.append(name)
        return result

    monkeypatch.setattr(
        config_module,
        "RKAConfig",
        lambda: SimpleNamespace(database_url=":memory:"),
    )
    monkeypatch.setattr(Database, "connect", lambda self: record("connect"))
    monkeypatch.setattr(
        Database,
        "initialize_schema",
        lambda self: record("initialize_schema"),
    )
    monkeypatch.setattr(
        Database,
        "initialize_phase2_schema",
        lambda self: record("initialize_phase2_schema"),
    )
    monkeypatch.setattr(
        Database,
        "run_migrations",
        lambda self: record("run_migrations", 0),
    )
    monkeypatch.setattr(Database, "close", lambda self: record("close"))

    result = CliRunner().invoke(main, ["migrate"])

    assert result.exit_code == 0, result.output
    assert "Migration initialization complete (base + Phase 2)" in result.output
    assert "Applied 0 migration(s)." not in result.output
    assert calls == [
        "connect",
        "initialize_schema",
        "initialize_phase2_schema",
        "run_migrations",
        "close",
    ]
