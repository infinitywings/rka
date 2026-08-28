"""Core backup-command regressions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import rka.config as config_module
from rka.cli import main


def test_backup_command_uses_consistent_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "nested" / "backup.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO records DEFAULT VALUES")

    monkeypatch.setattr(
        config_module,
        "RKAConfig",
        lambda: SimpleNamespace(database_url=str(source)),
    )

    result = CliRunner().invoke(main, ["backup", "--output", str(destination)])

    assert result.exit_code == 0, result.output
    assert f"Backed up to {destination.resolve()}" in result.output
    assert "SHA-256:" in result.output
    with sqlite3.connect(destination) as restored:
        assert restored.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_backup_command_fails_without_replacing_destination(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "corrupt.db"
    destination = tmp_path / "backup.db"
    source.write_bytes(b"corrupt")
    destination.write_bytes(b"keep me")
    monkeypatch.setattr(
        config_module,
        "RKAConfig",
        lambda: SimpleNamespace(database_url=str(source)),
    )

    result = CliRunner().invoke(main, ["backup", "--output", str(destination)])

    assert result.exit_code != 0
    assert destination.read_bytes() == b"keep me"
