"""Keep the source package and distribution product versions aligned."""

from __future__ import annotations

from pathlib import Path
import tomllib

from rka import __version__


def test_pyproject_version_matches_runtime_package() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
