"""Shared fixtures for Writer skill tests.

The Writer skill scripts live under rka/skills/writer/scripts/ and are designed
as standalone CLI scripts, not as a Python package. These fixtures use
importlib.util.spec_from_file_location to load each script as an importable
module for unit testing without polluting sys.modules globally.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 test convention discovery: the rka
project uses pytest with asyncio_mode=auto; conftest.py provides per-area
fixtures. Writer tests do not need async or database fixtures.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3] / "rka" / "skills" / "writer" / "scripts"
)
SKILL_DIR = SCRIPTS_DIR.parent
REFS_DIR = SKILL_DIR / "references"


def _load_module(name: str):
    """Load a Writer script at <name>.py as an importable module."""
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"writer_{name}", path)
    assert spec is not None and spec.loader is not None, f"failed to load {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"writer_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ai_tic_lint():
    return _load_module("ai_tic_lint")


@pytest.fixture
def bridge_repetition_check():
    return _load_module("bridge_repetition_check")


@pytest.fixture
def layout_audit():
    return _load_module("layout_audit")


@pytest.fixture
def validate_references():
    return _load_module("validate_references")


@pytest.fixture
def fetch_template():
    return _load_module("fetch_template")


@pytest.fixture
def chart_render():
    return _load_module("chart_render")


@pytest.fixture
def skill_dir() -> Path:
    return SKILL_DIR


@pytest.fixture
def refs_dir() -> Path:
    return REFS_DIR


@pytest.fixture
def skill_md_path(skill_dir: Path) -> Path:
    return skill_dir / "SKILL.md"
