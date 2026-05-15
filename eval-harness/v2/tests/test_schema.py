"""T1 tests for the Eval-v2 scenario schema + validator.

Mission spec calls for 3 tests:
  1. valid scenario passes
  2. missing expected_entities fails
  3. bad entity_type fails

This file adds a few extras to lock the runtime constraints (critical-
floor, entity_id/type prefix consistency, duplicate scenario_id).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Make the v2 package importable when running pytest from the repo root.
import sys
_V2_DIR = Path(__file__).resolve().parent.parent
if str(_V2_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V2_DIR.parent))

from v2.schema_validator import (
    ScenarioValidationError,
    load_corpus,
    validate_corpus,
    validate_scenario,
)


def _valid_scenario() -> dict:
    """Reusable known-good scenario."""
    return {
        "scenario_id": "brain-session-start-fresh",
        "actor": "brain",
        "trigger": "Brain resumes rka_development after 2-day break",
        "tools_invoked": [
            "rka_get_context",
            "rka_get_status",
            "rka_get_checkpoints",
        ],
        "expected_entities": [
            {"entity_id": "dec_01ABC0000000000000000000", "entity_type": "decision", "importance": "critical"},
            {"entity_id": "mis_01DEF0000000000000000000", "entity_type": "mission", "importance": "critical"},
            {"entity_id": "chk_01GHI0000000000000000000", "entity_type": "checkpoint", "importance": "critical"},
            {"entity_id": "jrn_01JKL0000000000000000000", "entity_type": "journal", "importance": "useful"},
            {"entity_id": "ecl_01MNO0000000000000000000", "entity_type": "cluster", "importance": "nice-to-have"},
        ],
        "context_length_budget_estimate": 8000,
        "notes": "Canonical Brain session-start pattern.",
    }


# ---------------------------------------------------------------------------
# Required test #1 — valid scenario passes
# ---------------------------------------------------------------------------


def test_valid_scenario_passes():
    validate_scenario(_valid_scenario())


# ---------------------------------------------------------------------------
# Required test #2 — missing expected_entities fails
# ---------------------------------------------------------------------------


def test_missing_expected_entities_fails():
    scenario = _valid_scenario()
    del scenario["expected_entities"]
    with pytest.raises(ScenarioValidationError) as ctx:
        validate_scenario(scenario)
    assert "expected_entities" in str(ctx.value) or "required" in str(ctx.value).lower()


# ---------------------------------------------------------------------------
# Required test #3 — bad entity_type fails
# ---------------------------------------------------------------------------


def test_bad_entity_type_fails():
    scenario = _valid_scenario()
    scenario["expected_entities"][0]["entity_type"] = "magic-unknown"
    with pytest.raises(ScenarioValidationError) as ctx:
        validate_scenario(scenario)
    assert "magic-unknown" in str(ctx.value) or "entity_type" in str(ctx.value)


# ---------------------------------------------------------------------------
# Extras — locked runtime constraints
# ---------------------------------------------------------------------------


def test_below_critical_floor_fails():
    """Validator requires >=3 critical-tagged entities per scenario."""
    scenario = _valid_scenario()
    # Demote two of the three critical entries to useful.
    scenario["expected_entities"][0]["importance"] = "useful"
    scenario["expected_entities"][1]["importance"] = "useful"
    with pytest.raises(ScenarioValidationError, match="critical"):
        validate_scenario(scenario)


def test_entity_id_prefix_mismatch_fails():
    """Validator catches entity_type vs entity_id-prefix divergence."""
    scenario = _valid_scenario()
    # Claim entity_type=decision but supply a journal-prefixed id.
    scenario["expected_entities"][0]["entity_type"] = "decision"
    scenario["expected_entities"][0]["entity_id"] = "jrn_01ABC0000000000000000000"
    with pytest.raises(ScenarioValidationError, match="prefix"):
        validate_scenario(scenario)


def test_invalid_actor_fails():
    scenario = _valid_scenario()
    scenario["actor"] = "pi"  # not in the brain|executor enum
    with pytest.raises(ScenarioValidationError):
        validate_scenario(scenario)


def test_below_minimum_expected_entities_count_fails():
    """Schema requires minItems=5 on expected_entities."""
    scenario = _valid_scenario()
    scenario["expected_entities"] = scenario["expected_entities"][:3]
    with pytest.raises(ScenarioValidationError, match="too short|expected_entities"):
        validate_scenario(scenario)


def test_empty_tools_invoked_fails():
    scenario = _valid_scenario()
    scenario["tools_invoked"] = []
    with pytest.raises(ScenarioValidationError, match="too short|tools_invoked"):
        validate_scenario(scenario)


def test_bad_scenario_id_slug_fails():
    scenario = _valid_scenario()
    scenario["scenario_id"] = "Brain Session Start"  # spaces + caps
    with pytest.raises(ScenarioValidationError):
        validate_scenario(scenario)


def test_unknown_top_level_field_fails():
    """`additionalProperties: false` on the schema rejects unexpected fields."""
    scenario = _valid_scenario()
    scenario["misc_extra"] = "should not be here"
    with pytest.raises(ScenarioValidationError):
        validate_scenario(scenario)


def test_validate_corpus_returns_scenario_ids(tmp_path: Path):
    corpus = [
        _valid_scenario(),
        {**_valid_scenario(), "scenario_id": "executor-mission-pickup-fresh"},
    ]
    ids = validate_corpus(corpus)
    assert ids == ["brain-session-start-fresh", "executor-mission-pickup-fresh"]


def test_duplicate_scenario_id_fails():
    corpus = [_valid_scenario(), _valid_scenario()]
    with pytest.raises(ScenarioValidationError, match="duplicate"):
        validate_corpus(corpus)


def test_load_corpus_reads_jsonl(tmp_path: Path):
    path = tmp_path / "scenarios.jsonl"
    lines = [
        json.dumps(_valid_scenario()),
        "",  # blank line tolerated
        json.dumps({**_valid_scenario(), "scenario_id": "second-scenario"}),
    ]
    path.write_text("\n".join(lines) + "\n")
    out = load_corpus(path)
    assert len(out) == 2
    assert out[0]["scenario_id"] == "brain-session-start-fresh"
    assert out[1]["scenario_id"] == "second-scenario"
