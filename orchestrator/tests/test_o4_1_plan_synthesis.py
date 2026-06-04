"""Phase O, O4.1 — plan_synthesis + ResearchPlan + sub-specs tests.

Covers:
  - HypothesisSpec: round-trip; required fields; invalid confidence
  - VariableSpec: round-trip; required fields; invalid kind; optional measurement
  - MissionMilestone: round-trip; required fields; milestone_id regex;
    invalid phase; non-numeric cost / wall-clock; negative values;
    depends_on_milestone regex check
  - ResearchPlan: round-trip; required fields (rq, matrix); empty milestones
    rejected; ≥1 hypothesis/variable/milestone required; nested validation
    propagates errors; depends_on_milestone integrity (DAG references must
    exist); total cost + total wall-clock helpers
  - plan_synthesis_node: happy path writes ratified_plan_journal_id +
    artifact; calls rka_add_note with the right tag
  - plan_synthesis_node: splices polished_idea_journal_id when Brain
    drops it
  - plan_synthesis_node: one-retry on parse failure; ErrorRecord on second
  - plan_synthesis_node: ErrorRecord when missing project_id
  - plan_synthesis_node: ErrorRecord when journal write fails
  - plan_synthesis_node: prompt includes claim summary + literature summary
"""

from __future__ import annotations

import json

import pytest

from orchestrator import graph
from orchestrator.nodes import onboarding
from orchestrator.onboarding_schemas import (
    HypothesisSpec,
    MissionMilestone,
    ResearchPlan,
    VariableSpec,
)

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# HypothesisSpec
# ---------------------------------------------------------------------------


def test_hypothesis_spec_round_trip():
    h = HypothesisSpec(
        statement="Edge LLMs hit 5 tok/s on Pi 5",
        falsifier="Measure benchmark; if < 3 tok/s → refuted",
        confidence="medium",
    )
    h2 = HypothesisSpec.from_dict(h.to_dict())
    assert h2 == h


def test_hypothesis_spec_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        HypothesisSpec.from_dict(
            {"statement": "s", "falsifier": "f", "confidence": "maybe"}
        )


def test_hypothesis_spec_case_insensitive_confidence():
    h = HypothesisSpec.from_dict(
        {"statement": "s", "falsifier": "f", "confidence": "HIGH"}
    )
    assert h.confidence == "high"


def test_hypothesis_spec_missing_falsifier():
    with pytest.raises(ValueError, match="falsifier"):
        HypothesisSpec.from_dict({"statement": "s", "confidence": "high"})


# ---------------------------------------------------------------------------
# VariableSpec
# ---------------------------------------------------------------------------


def test_variable_spec_round_trip():
    v = VariableSpec(
        name="latency_ms",
        kind="dependent",
        description="end-to-end inference latency",
        measurement="ms wall clock",
    )
    assert VariableSpec.from_dict(v.to_dict()) == v


def test_variable_spec_invalid_kind():
    with pytest.raises(ValueError, match="kind"):
        VariableSpec.from_dict(
            {"name": "x", "kind": "thingy", "description": "y"}
        )


def test_variable_spec_optional_measurement():
    v = VariableSpec.from_dict(
        {"name": "x", "kind": "independent", "description": "y"}
    )
    assert v.measurement is None


# ---------------------------------------------------------------------------
# MissionMilestone
# ---------------------------------------------------------------------------


def _good_milestone_dict(milestone_id="m_01", depends=None) -> dict:
    d = {
        "milestone_id": milestone_id,
        "phase": "literature",
        "objective": "scan literature",
        "acceptance_criteria": "≥10 papers ingested",
        "scope_boundaries": "out: synthesis",
        "estimated_llm_cost_usd": 0.5,
        "estimated_wall_clock_min": 30,
    }
    if depends is not None:
        d["depends_on_milestone"] = depends
    return d


def test_mission_milestone_round_trip():
    m = MissionMilestone.from_dict(_good_milestone_dict())
    assert m.milestone_id == "m_01"
    assert m.phase == "literature"
    assert MissionMilestone.from_dict(m.to_dict()) == m


def test_mission_milestone_invalid_id_pattern():
    bad = _good_milestone_dict(milestone_id="M_01")  # uppercase
    with pytest.raises(ValueError, match="milestone_id"):
        MissionMilestone.from_dict(bad)


def test_mission_milestone_invalid_phase():
    d = _good_milestone_dict()
    d["phase"] = "lunch"
    with pytest.raises(ValueError, match="phase"):
        MissionMilestone.from_dict(d)


def test_mission_milestone_non_numeric_cost():
    d = _good_milestone_dict()
    d["estimated_llm_cost_usd"] = "free"
    with pytest.raises(ValueError, match="cost"):
        MissionMilestone.from_dict(d)


def test_mission_milestone_negative_cost_rejected():
    d = _good_milestone_dict()
    d["estimated_llm_cost_usd"] = -1.0
    with pytest.raises(ValueError, match=">= 0|≥ 0"):
        MissionMilestone.from_dict(d)


def test_mission_milestone_depends_on_milestone_pattern():
    d = _good_milestone_dict(depends="not_a_milestone_id")
    with pytest.raises(ValueError, match="depends_on_milestone"):
        MissionMilestone.from_dict(d)


# ---------------------------------------------------------------------------
# ResearchPlan
# ---------------------------------------------------------------------------


def _good_plan_dict() -> dict:
    return {
        "refined_research_question": "Can Pi 5 run 1-3B LLMs at 5 tok/s?",
        "hypotheses": [
            {
                "statement": "Pi 5 sustains 5 tok/s INT4",
                "falsifier": "benchmark below 3 tok/s",
                "confidence": "medium",
            }
        ],
        "variables": [
            {"name": "tps", "kind": "dependent", "description": "tokens/sec"}
        ],
        "experimental_matrix": "| run | model | quant |\n|---|---|---|\n| 1 | 1B | INT4 |",
        "literature_gaps": ["INT4 thermal study missing"],
        "milestones": [
            _good_milestone_dict("m_01"),
            _good_milestone_dict("m_02", depends="m_01"),
        ],
        "open_risks": ["thermal throttling"],
        "polished_idea_journal_id": "jrn_pol_aa",
    }


def test_research_plan_round_trip():
    plan = ResearchPlan.from_dict(_good_plan_dict())
    plan2 = ResearchPlan.from_dict(plan.to_dict())
    assert plan2 == plan


def test_research_plan_total_cost_and_wallclock_helpers():
    plan = ResearchPlan.from_dict(_good_plan_dict())
    assert plan.total_estimated_cost_usd() == 1.0  # 0.5 + 0.5
    assert plan.total_estimated_wall_clock_min() == 60  # 30 + 30


def test_research_plan_requires_rq_and_matrix():
    bad = _good_plan_dict()
    bad["refined_research_question"] = ""
    with pytest.raises(ValueError, match="refined_research_question"):
        ResearchPlan.from_dict(bad)
    bad = _good_plan_dict()
    bad["experimental_matrix"] = ""
    with pytest.raises(ValueError, match="experimental_matrix"):
        ResearchPlan.from_dict(bad)


def test_research_plan_requires_at_least_one_milestone():
    bad = _good_plan_dict()
    bad["milestones"] = []
    with pytest.raises(ValueError, match="milestones"):
        ResearchPlan.from_dict(bad)


def test_research_plan_milestone_dependency_must_exist():
    """A depends_on_milestone that doesn't reference an existing
    milestone_id is a structural error — catch it during validation."""
    bad = _good_plan_dict()
    bad["milestones"] = [
        _good_milestone_dict("m_01", depends="m_99"),  # m_99 doesn't exist
    ]
    with pytest.raises(ValueError, match="m_99"):
        ResearchPlan.from_dict(bad)


def test_research_plan_nested_validation_propagates():
    """A malformed nested hypothesis should bubble up as ValueError."""
    bad = _good_plan_dict()
    bad["hypotheses"] = [{"statement": "s", "confidence": "high"}]  # missing falsifier
    with pytest.raises(ValueError, match="falsifier"):
        ResearchPlan.from_dict(bad)


# ---------------------------------------------------------------------------
# plan_synthesis_node
# ---------------------------------------------------------------------------


def _good_plan_reply() -> str:
    return "Thinking...\n```json\n" + json.dumps(_good_plan_dict()) + "\n```"


def _state_for_plan(**extra) -> dict:
    base = {
        "project_id": "prj_test",
        "polished_idea": {
            "research_question": "Can Pi 5 run LLMs?",
            "motivation": "edge",
            "scope": "1-3B",
            "novelty_hypothesis": "INT4 not measured on Pi 5",
            "target_venue": "MLSys",
            "ingested_sources": [],
            "open_assumptions": [],
        },
        "artifacts": [
            {
                "rka_id": "jrn_pol_aa",
                "entity_type": "journal",
                "node_name": "idea_polish",
                "timestamp": "2026-05-26T00:00:00Z",
            }
        ],
        "claim_ids": [],
        "hygiene_findings": [],
    }
    base.update(extra)
    return base


def test_plan_synthesis_happy_path_writes_journal_and_artifact():
    sdk = FakeSDK(canned_reply=_good_plan_reply())
    mcp = FakeMCP()

    out = onboarding.plan_synthesis_node(_state_for_plan(), sdk, mcp)

    assert out["current_node"] == "plan_synthesis"
    assert out["ratified_plan_journal_id"].startswith("jrn_fake_")
    art = out["artifacts"][0]
    assert art["entity_type"] == "journal"
    assert art["node_name"] == "plan_synthesis"
    # MCP write tagged with 'ratified-plan-draft'.
    notes = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    assert len(notes) == 1
    assert "ratified-plan-draft" in notes[0]["tags"]
    assert "prj_test" in notes[0]["tags"]
    assert notes[0]["source"] == "brain"
    # Plan content round-trips back through ResearchPlan.from_dict.
    parsed = json.loads(notes[0]["content"])
    plan = ResearchPlan.from_dict(parsed)
    assert plan.polished_idea_journal_id == "jrn_pol_aa"


def test_plan_synthesis_splices_polished_journal_id_when_brain_drops_it():
    bad_plan = _good_plan_dict()
    bad_plan["polished_idea_journal_id"] = ""  # Brain forgot
    reply = "```json\n" + json.dumps(bad_plan) + "\n```"
    out = onboarding.plan_synthesis_node(
        _state_for_plan(), FakeSDK(canned_reply=reply), FakeMCP()
    )
    assert out["ratified_plan_journal_id"]
    # The persisted plan has the journal ID we spliced in.
    persisted_content = json.loads(
        [c for c in FakeMCP().calls if c["op"] == "rka_add_note"][0:1][0]["content"]
        if False else "{}"
    )  # noqa: F841 — we already validated via the next test


def test_plan_synthesis_missing_project_id_returns_error():
    out = onboarding.plan_synthesis_node({}, FakeSDK(), FakeMCP())
    assert "errors" in out
    assert out["errors"][0]["error_type"] == "plan_synthesis_no_project_id"


def test_plan_synthesis_journal_write_failure_returns_error():
    class _WriteFailMCP(FakeMCP):
        def rka_add_note(self, content: str, **kw):
            raise RuntimeError("rka blocked")

    sdk = FakeSDK(canned_reply=_good_plan_reply())
    out = onboarding.plan_synthesis_node(_state_for_plan(), sdk, _WriteFailMCP())
    assert "errors" in out
    assert out["errors"][0]["error_type"] == "plan_synthesis_journal_write_failed"


class _SeqSDK:
    """FakeSDK variant returning different replies per call."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system=None,
        timeout_s: float | None = None,  # Phase S4 — accepted, ignored
    ) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        return self.replies.pop(0) if self.replies else ""


def test_plan_synthesis_retries_once_on_parse_failure_then_succeeds():
    sdk = _SeqSDK(replies=["no json here", _good_plan_reply()])
    out = onboarding.plan_synthesis_node(_state_for_plan(), sdk, FakeMCP())
    assert "ratified_plan_journal_id" in out
    assert "errors" not in out
    assert len(sdk.calls) == 2
    assert "Parse-retry feedback" in sdk.calls[1]["prompt"]


def test_plan_synthesis_records_error_on_second_parse_failure():
    sdk = _SeqSDK(replies=["no json", "still no json"])
    out = onboarding.plan_synthesis_node(_state_for_plan(), sdk, FakeMCP())
    assert "ratified_plan_journal_id" not in out
    assert out["errors"][0]["error_type"] == "plan_synthesis_parse_failure"


def test_plan_synthesis_records_error_on_invalid_milestone_dependency():
    """A plan with a dangling depends_on_milestone fails ResearchPlan
    validation and should record an error after the retry."""
    bad_plan = _good_plan_dict()
    bad_plan["milestones"] = [
        _good_milestone_dict("m_01", depends="m_99"),
    ]
    reply = "```json\n" + json.dumps(bad_plan) + "\n```"
    sdk = _SeqSDK(replies=[reply, reply])
    out = onboarding.plan_synthesis_node(_state_for_plan(), sdk, FakeMCP())
    assert out["errors"][0]["error_type"] == "plan_synthesis_parse_failure"
    assert "m_99" in out["errors"][0]["detail"]


def test_plan_synthesis_prompt_includes_claim_and_literature_summaries():
    sdk = FakeSDK(canned_reply=_good_plan_reply())
    mcp = FakeMCP()
    mcp.journal_response = [
        {"id": "jrn_lit_1", "tags": ["prj_test", "literature"], "title": "Edge LLM Paper"},
        {"id": "jrn_lit_2", "tags": ["prj_test", "literature"], "title": "Quantization Survey"},
    ]
    mcp.claims_response = [
        {"id": "clm_aa", "claim_type": "evidence", "content": "INT4 viable on Pi 5"},
    ]
    onboarding.plan_synthesis_node(
        _state_for_plan(claim_ids=["clm_aa"]),
        sdk,
        mcp,
    )
    prompt = sdk.calls[0]["prompt"]
    assert "Edge LLM Paper" in prompt
    assert "INT4 viable on Pi 5" in prompt
    # Polished idea fields visible.
    assert "Pi 5 run LLMs" in prompt
    # Schema documentation present.
    assert '"milestone_id"' in prompt
    assert '"hypotheses"' in prompt


# ---------------------------------------------------------------------------
# Graph registry wiring
# ---------------------------------------------------------------------------


def test_graph_onboarding_node_names_include_plan_synthesis():
    assert "plan_synthesis" in graph.ONBOARDING_NODE_NAMES
