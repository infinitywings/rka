"""Regression tests for scenarios.jsonl tools_invoked invariants.

Per Phase-3.2 T2 (mis_01KS5CRMZ0AGN0M5B694Q3M8B1, chk_01KS5EZ6Z2D51Q1AW628DNA17Y):
seven failing scenarios were classified A1 (incomplete tools_invoked) and patched
to add the candidate-gen tools that surface their expected_entities. These tests
lock the invariants so a future scenario-corpus edit cannot silently regress
the diagnostic-fix.

Each test asserts that a specific scenario_id's tools_invoked array contains
the tool(s) the T1 diagnostic identified as load-bearing for that scenario's
critical recall.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "corpus" / "scenarios.jsonl"


def _load_scenarios() -> dict[str, dict]:
    out = {}
    for line in _SCENARIOS_PATH.read_text().splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        out[s["scenario_id"]] = s
    return out


# Per-scenario invariants from chk_01KS5EZ6Z2D51Q1AW628DNA17Y diagnostic table.
# Each tuple is (scenario_id, required_tools).
_A1_INVARIANTS = [
    (
        "brain-session-start-fresh-resume",
        ["rka_multi_hop_retrieval", "rka_get_journal"],
    ),
    (
        "brain-session-start-multi-mission-state",
        ["rka_multi_hop_retrieval", "rka_get_journal"],
    ),
    (
        "brain-session-start-post-release",
        ["rka_multi_hop_retrieval", "rka_get_journal", "rka_get_research_map"],
    ),
    (
        "brain-contradiction-llm-removed-vs-enrichment-preserved",
        ["rka_get_research_map"],
    ),
    (
        "executor-mission-pickup-orchestrator",
        ["rka_multi_hop_retrieval"],
    ),
    (
        "executor-backbrief-eval-v2-t2",
        ["rka_multi_hop_retrieval"],
    ),
    (
        "executor-backbrief-bookkeeper-invariant-check",
        ["rka_get_research_map"],
    ),
]


@pytest.mark.parametrize("scenario_id,required_tools", _A1_INVARIANTS)
def test_scenario_tools_invoked_includes_required_candidate_gen_tool(
    scenario_id: str, required_tools: list[str]
) -> None:
    scenarios = _load_scenarios()
    assert scenario_id in scenarios, f"scenario {scenario_id} missing from corpus"
    tools = scenarios[scenario_id]["tools_invoked"]
    for tool in required_tools:
        assert tool in tools, (
            f"{scenario_id} tools_invoked must include {tool} "
            f"(Phase-3.2 T2 A1 fix per chk_01KS5EZ6Z2D51Q1AW628DNA17Y); "
            f"current: {tools}"
        )


def test_all_a1_scenarios_have_at_least_one_candidate_gen_tool() -> None:
    """Sanity: every A1-fixed scenario must invoke at least one of the
    retrieval surfaces that the T1 diagnostic identified as candidate-gen
    capable for topical entity discovery."""
    candidate_gen_tools = {
        "rka_multi_hop_retrieval",
        "rka_get_journal",
        "rka_get_research_map",
        "rka_get_ego_graph",
        "rka_assemble_evidence",
    }
    scenarios = _load_scenarios()
    for scenario_id, _ in _A1_INVARIANTS:
        tools = set(scenarios[scenario_id]["tools_invoked"])
        intersect = tools & candidate_gen_tools
        assert intersect, (
            f"{scenario_id} has no candidate-gen tool in tools_invoked "
            f"(would regress to the pre-T2 failure mode); current: {tools}"
        )
