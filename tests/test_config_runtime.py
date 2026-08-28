"""Stable path semantics for the Dockerless Core distribution."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from rka.config import RKAConfig
from rka.infra.database import Database


def _clear_runtime_env(monkeypatch) -> None:
    for name in (
        "RKA_DATA_DIR",
        "RKA_DB_PATH",
        "RKA_PROJECT_DIR",
        "RKA_EMBEDDINGS_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_database_lives_under_home_data_dir(monkeypatch, tmp_path: Path) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    config = RKAConfig(_env_file=None)

    assert config.data_dir == tmp_path / ".rka"
    assert Path(config.database_url) == tmp_path / ".rka" / "rka.db"


def test_data_dir_override_also_moves_the_default_database(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    data_dir = tmp_path / "shared-state"
    monkeypatch.setenv("RKA_DATA_DIR", str(data_dir))

    config = RKAConfig(_env_file=None)

    assert config.data_dir == data_dir
    assert Path(config.database_url) == data_dir / "rka.db"


def test_new_data_dir_is_created_with_private_permissions(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    data_dir = tmp_path / "new" / "private-state"
    monkeypatch.setenv("RKA_DATA_DIR", str(data_dir))

    config = RKAConfig(_env_file=None)

    assert config.data_dir == data_dir
    assert data_dir.is_dir()
    if os.name != "nt":
        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700


def test_data_dir_expands_home(monkeypatch, tmp_path: Path) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RKA_DATA_DIR", "~/custom-rka")

    config = RKAConfig(_env_file=None)

    assert config.data_dir == tmp_path / "custom-rka"


def test_relative_data_dir_is_rejected(monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("RKA_DATA_DIR", "relative-state")

    with pytest.raises(ValueError, match="RKA_DATA_DIR must be an absolute path"):
        RKAConfig(_env_file=None)


def test_explicit_absolute_database_path_wins(monkeypatch, tmp_path: Path) -> None:
    _clear_runtime_env(monkeypatch)
    explicit = tmp_path / "explicit" / "core.db"
    monkeypatch.setenv("RKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RKA_DB_PATH", str(explicit))

    config = RKAConfig(_env_file=None)

    assert Path(config.database_url) == explicit


def test_explicit_relative_database_preserves_project_local_behavior(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    project_dir = tmp_path / "legacy-project"

    config = RKAConfig(
        _env_file=None,
        data_dir=tmp_path / "data",
        project_dir=project_dir,
        db_path=Path("custom.db"),
    )

    assert Path(config.database_url) == project_dir / "custom.db"


def test_default_database_survives_config_round_trip(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    data_dir = tmp_path / "round-trip"
    original = RKAConfig(_env_file=None, data_dir=data_dir)

    restored = RKAConfig(_env_file=None, **original.model_dump())

    assert restored.db_path is None
    assert restored.database_url == original.database_url == str(data_dir / "rka.db")


def test_default_database_is_independent_of_current_directory(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    data_dir = tmp_path / "stable"
    monkeypatch.setenv("RKA_DATA_DIR", str(data_dir))
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.chdir(first)
    first_url = RKAConfig(_env_file=None).database_url
    monkeypatch.chdir(second)
    second_url = RKAConfig(_env_file=None).database_url

    assert first_url == second_url == str(data_dir / "rka.db")


def test_database_connect_creates_private_parent_and_file(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "rka.db"

    async def _connect() -> None:
        database = Database(str(db_path))
        await database.connect()
        await database.close()

    asyncio.run(_connect())

    assert db_path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(db_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
