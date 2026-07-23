"""Shared fixtures for Writer skill tests.

The Writer skill scripts live under rka/skills/writer/scripts/ and are designed
as standalone CLI scripts, not as a Python package. These fixtures use
importlib.util.spec_from_file_location to load each script as an importable
module for unit testing. Each module is registered under a stable `writer_*`
name in `sys.modules`, as required by import machinery used by some scripts.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 test convention discovery: the rka
project uses pytest with asyncio_mode=auto; conftest.py provides per-area
fixtures. Writer tests do not need async or database fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml


SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3] / "rka" / "skills" / "writer" / "scripts"
)
SKILL_DIR = SCRIPTS_DIR.parent
REFS_DIR = SKILL_DIR / "references"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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
def verify_provenance():
    return _load_module("verify_provenance")


@pytest.fixture
def verify_citations():
    return _load_module("verify_citations")


@pytest.fixture
def overclaim_lint():
    return _load_module("overclaim_lint")


@pytest.fixture
def fetch_template():
    return _load_module("fetch_template")


@pytest.fixture
def chart_render():
    return _load_module("chart_render")


@pytest.fixture
def venue_loader():
    """Phase W1: venue.yaml loader (rka/skills/writer/scripts/venue_loader.py)."""
    return _load_module("venue_loader")


@pytest.fixture
def venue_md_generator():
    """Phase W1: venue.md generator (yaml → narrative MD)."""
    return _load_module("venue_md_generator")


@pytest.fixture
def cfp_loader():
    """Phase W2: CFP URL fetcher + override overlay."""
    return _load_module("cfp_loader")


@pytest.fixture
def claim_spine():
    """RKA-backed claim-spine parser, validator, renderer, and currency checker."""
    return _load_module("claim_spine")


@pytest.fixture
def claim_spine_fixture_dir() -> Path:
    return FIXTURES_DIR / "claim_spine"


@pytest.fixture
def claim_spine_data(claim_spine_fixture_dir: Path) -> dict:
    """Return a fresh copy of the valid v1 claim-spine fixture."""
    path = claim_spine_fixture_dir / "valid_spine.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def claim_spine_entities(claim_spine_fixture_dir: Path) -> dict[str, dict]:
    """Raw, API-shaped RKA entities for fully offline resolver tests."""
    path = claim_spine_fixture_dir / "rka_entities.json"
    return json.loads(path.read_text(encoding="utf-8"))["entities"]


@pytest.fixture
def make_claim_spine_resolver():
    """Build an isolated entity-id resolver from an in-memory entity mapping.

    A deep copy is returned on every call so validators cannot accidentally
    mutate the shared fixture and make later tests order-dependent.
    """
    def make(entities: dict[str, dict]):
        def resolve(entity_id: str):
            entity = entities.get(entity_id)
            return deepcopy(entity) if entity is not None else None

        return resolve

    return make


@pytest.fixture
def claim_spine_resolver(claim_spine_entities, make_claim_spine_resolver):
    return make_claim_spine_resolver(claim_spine_entities)


# Phase 2 mcp_tools backends (proper Python subpackage; import via rka.* path).
@pytest.fixture
def crossref_backend():
    from rka.skills.writer.mcp_tools.backends import crossref
    return crossref


@pytest.fixture
def openalex_backend():
    from rka.skills.writer.mcp_tools.backends import openalex
    return openalex


@pytest.fixture
def semantic_scholar_backend():
    from rka.skills.writer.mcp_tools.backends import semantic_scholar
    return semantic_scholar


@pytest.fixture
def arxiv_backend():
    from rka.skills.writer.mcp_tools.backends import arxiv_backend as ax
    return ax


@pytest.fixture
def serpapi_backend():
    from rka.skills.writer.mcp_tools.backends import serpapi_backend as sp
    return sp


@pytest.fixture
def skill_dir() -> Path:
    return SKILL_DIR


@pytest.fixture
def refs_dir() -> Path:
    return REFS_DIR


@pytest.fixture
def skill_md_path(skill_dir: Path) -> Path:
    return skill_dir / "SKILL.md"
