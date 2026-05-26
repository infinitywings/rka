"""Phase O, O4.2 — pi_plan_ratify (TWO-TAP + auto-create missions) tests.

Covers:
  - render_research_plan_markdown: every required section appears,
    totals computed
  - render: tolerant of missing/empty sections, non-dict input
  - _topo_sort_milestones: respects depends_on; stable order; tolerates
    cycles/dangling refs
  - payload shape: items, rendered_markdown, two_tap_required, totals,
    plan_journal_id
  - accept path:
      writes rka_add_decision with related_journal
      auto-creates one mis_… per milestone in topo order
      depends_on resolves to upstream mis_… (not the m_NN plan id)
      re-tags the plan journal 'ratified-plan-draft' → 'ratified-plan'
      state writes ratified_plan_decision_id + ratified_mission_ids +
        current_milestone_index=0
      artifacts emitted for decision + missions
  - reject path: no decision, no missions, no retag
  - correct path: brain_position carries the redirect; no missions
  - accept without plan content surfaces an error (defensive)
  - decision write failure → error, no missions created
  - mission create failure for one milestone → recorded but doesn't
    block remaining milestones
  - retag failure → recorded but other state writes proceed
  - parked_store + runner + graph registry wiring
"""

from __future__ import annotations

import json

import pytest

from orchestrator import graph
from orchestrator.nodes import pi
from orchestrator.nodes.pi import (
    _materialize_milestone_chain,
    _render_research_plan_markdown,
    _topo_sort_milestones,
)
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE, OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# _render_research_plan_markdown
# ---------------------------------------------------------------------------


def _plan_dict() -> dict:
    return {
        "refined_research_question": "Can Pi 5 sustain 5 tok/s INT4?",
        "hypotheses": [
            {"statement": "Yes", "falsifier": "benchmark<3", "confidence": "medium"},
        ],
        "variables": [
            {"name": "tps", "kind": "dependent", "description": "throughput", "measurement": "tps"},
        ],
        "experimental_matrix": "| run | model |\n|---|---|\n| 1 | 1B |",
        "literature_gaps": ["INT4 thermal study"],
        "milestones": [
            {
                "milestone_id": "m_01",
                "phase": "literature",
                "objective": "scan",
                "acceptance_criteria": "≥10 papers",
                "scope_boundaries": "out: synthesis",
                "estimated_llm_cost_usd": 0.5,
                "estimated_wall_clock_min": 30,
            },
            {
                "milestone_id": "m_02",
                "phase": "experiment_design",
                "objective": "design",
                "acceptance_criteria": "matrix locked",
                "scope_boundaries": "out: execute",
                "depends_on_milestone": "m_01",
                "estimated_llm_cost_usd": 1.20,
                "estimated_wall_clock_min": 45,
            },
        ],
        "open_risks": ["thermal"],
        "polished_idea_journal_id": "jrn_pol_aa",
    }


def test_render_plan_includes_all_required_sections():
    md = _render_research_plan_markdown(_plan_dict())
    assert "## Refined research question" in md
    assert "Pi 5 sustain 5 tok/s" in md
    assert "## Hypotheses (1)" in md
    assert "## Variables (1)" in md
    assert "## Experimental matrix" in md
    assert "## Mission queue (2 milestones" in md
    assert "$1.70" in md  # total cost
    assert "75 min" in md  # total wall-clock
    assert "## Literature gaps" in md
    assert "## Open risks" in md
    assert "m_01" in md
    assert "m_02" in md


def test_render_plan_missing_sections_fallback():
    md = _render_research_plan_markdown({})
    assert "(unspecified)" in md or "(none)" in md


def test_render_plan_non_dict_returns_explanation():
    assert "no plan" in _render_research_plan_markdown(None).lower()


# ---------------------------------------------------------------------------
# _topo_sort_milestones
# ---------------------------------------------------------------------------


def test_topo_sort_respects_dependencies():
    ms = [
        {"milestone_id": "m_02", "depends_on_milestone": "m_01"},
        {"milestone_id": "m_01"},
        {"milestone_id": "m_03", "depends_on_milestone": "m_02"},
    ]
    out = _topo_sort_milestones(ms)
    ids = [m["milestone_id"] for m in out]
    assert ids == ["m_01", "m_02", "m_03"]


def test_topo_sort_stable_for_independents():
    ms = [
        {"milestone_id": "m_01"},
        {"milestone_id": "m_02"},
        {"milestone_id": "m_03"},
    ]
    out = _topo_sort_milestones(ms)
    assert [m["milestone_id"] for m in out] == ["m_01", "m_02", "m_03"]


def test_topo_sort_tolerates_dangling_ref():
    """A milestone that depends on a non-existent ID still ends up in
    the output (we don't crash). Should never happen in a validated
    ResearchPlan but the renderer must be safe."""
    ms = [
        {"milestone_id": "m_01", "depends_on_milestone": "m_DNE"},
    ]
    out = _topo_sort_milestones(ms)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# _materialize_milestone_chain
# ---------------------------------------------------------------------------


def test_materialize_chain_resolves_plan_id_to_mission_id_in_depends_on():
    """The key behavior: m_NN's depends_on_milestone is a PLAN id; the
    auto-created mission's depends_on is the upstream MIS id."""
    mcp = FakeMCP()
    ids, errors = _materialize_milestone_chain(
        mcp=mcp,
        decision_id="dec_aa",
        plan=_plan_dict(),
        project_id="prj_x",
    )
    assert errors == []
    assert len(ids) == 2  # m_01 + m_02 → 2 missions
    creates = [c for c in mcp.calls if c["op"] == "rka_create_mission"]
    # First mission (m_01): no depends_on.
    assert creates[0].get("depends_on") is None
    # Second mission (m_02): depends_on resolves to first mission's mis ID.
    assert creates[1].get("depends_on") == ids[0]
    # The mission ID in depends_on is NOT 'm_01' (the plan id).
    assert creates[1].get("depends_on") != "m_01"
    # phase + scope_boundaries propagated.
    assert creates[1]["phase"] == "experiment_design"
    assert creates[1]["scope_boundaries"] == "out: execute"


def test_materialize_chain_records_failure_continues_others():
    """If one mission create fails, the chain records an error but
    keeps materializing later independent milestones."""

    class _PartialFailMCP(FakeMCP):
        def rka_create_mission(self, objective: str, **kw):
            if "design" in objective:
                raise RuntimeError("create blocked")
            return super().rka_create_mission(objective, **kw)

    mcp = _PartialFailMCP()
    ids, errors = _materialize_milestone_chain(
        mcp=mcp, decision_id="dec_aa", plan=_plan_dict(), project_id="prj_x"
    )
    # m_01 (scan) succeeded; m_02 (design) failed.
    assert len(ids) == 1
    assert len(errors) == 1
    assert errors[0]["error_type"] == "pi_plan_ratify_mission_create_failed"


# ---------------------------------------------------------------------------
# pi_plan_ratify — payload shape
# ---------------------------------------------------------------------------


def _state_with_plan_journal() -> dict:
    return {
        "project_id": "prj_x",
        "ratified_plan_journal_id": "jrn_plan_aa",
    }


def _plan_loaded_mcp() -> FakeMCP:
    """FakeMCP whose rka_get returns the plan JSON as content."""

    class _PlanMCP(FakeMCP):
        def rka_get(self, id: str) -> dict:
            self._record("rka_get", id=id)
            return {"id": id, "content": json.dumps(_plan_dict())}

    return _PlanMCP()


def test_pi_plan_ratify_payload_shape():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    pi.pi_plan_ratify(_state_with_plan_journal(), FakeSDK(), _plan_loaded_mcp(), fake_interrupt)

    p = captured["payload"]
    assert p["type"] == "pi_plan_ratify"
    assert p["two_tap_required"] is True
    assert "licenses autonomy" in p["title"].lower() or "TWO-TAP" in p["title"]
    assert p["plan_journal_id"] == "jrn_plan_aa"
    assert p["total_estimated_cost_usd"] == 1.70
    assert p["total_estimated_wall_clock_min"] == 75
    # The plan dict on items[0].
    assert len(p["items"]) == 1
    assert p["items"][0]["milestones"][0]["milestone_id"] == "m_01"
    # Markdown blob.
    assert "Mission queue (2 milestones" in p["rendered_markdown"]
    # Authorization phrasing in the two-tap label.
    assert "Authorize" in p["two_tap_label"]
    assert "$1.70" in p["two_tap_label"]


# ---------------------------------------------------------------------------
# pi_plan_ratify — accept path
# ---------------------------------------------------------------------------


def test_pi_plan_ratify_accept_writes_decision_and_missions():
    mcp = _plan_loaded_mcp()
    out = pi.pi_plan_ratify(
        _state_with_plan_journal(), FakeSDK(), mcp, lambda _p: "accept"
    )
    # Decision written.
    decisions = [c for c in mcp.calls if c["op"] == "rka_add_decision"]
    assert len(decisions) == 1
    assert "jrn_plan_aa" in decisions[0]["related_journal"]
    # Missions written (2 milestones → 2 missions).
    missions = [c for c in mcp.calls if c["op"] == "rka_create_mission"]
    assert len(missions) == 2
    # Re-tag of the plan journal.
    retags = [c for c in mcp.calls if c["op"] == "rka_update_note"]
    assert len(retags) == 1
    assert "ratified-plan" in retags[0]["tags"]
    # State writes.
    assert out["ratified_plan_decision_id"].startswith("dec_fake_")
    assert len(out["ratified_mission_ids"]) == 2
    assert out["current_milestone_index"] == 0
    # Artifacts: 1 decision + 2 missions.
    assert len(out["artifacts"]) == 3
    types_ = [a["entity_type"] for a in out["artifacts"]]
    assert types_.count("decision") == 1
    assert types_.count("mission") == 2


def test_pi_plan_ratify_accept_without_plan_content_returns_error():
    """Defensive: PI accepts but the plan journal is missing/empty."""

    class _EmptyJournalMCP(FakeMCP):
        def rka_get(self, id: str) -> dict:
            self._record("rka_get", id=id)
            return {"id": id, "content": ""}

    out = pi.pi_plan_ratify(
        _state_with_plan_journal(), FakeSDK(), _EmptyJournalMCP(), lambda _p: "accept"
    )
    assert out["errors"][0]["error_type"] == "pi_plan_ratify_no_plan"


def test_pi_plan_ratify_decision_write_failure():
    class _DecFailMCP(_plan_loaded_mcp().__class__):
        def rka_add_decision(self, content: str, **kw):
            raise RuntimeError("dec blocked")

    out = pi.pi_plan_ratify(
        _state_with_plan_journal(), FakeSDK(), _DecFailMCP(), lambda _p: "accept"
    )
    # decision_id ends up empty so no missions get created.
    assert out["ratified_plan_decision_id"] == ""
    assert out["ratified_mission_ids"] == []
    assert any(
        e["error_type"] == "pi_plan_ratify_decision_write_failed"
        for e in out["errors"]
    )


def test_pi_plan_ratify_retag_failure_is_recorded_but_other_state_proceeds():
    class _RetagFailMCP(_plan_loaded_mcp().__class__):
        def rka_update_note(self, id: str, **kw):
            raise RuntimeError("retag blocked")

    out = pi.pi_plan_ratify(
        _state_with_plan_journal(), FakeSDK(), _RetagFailMCP(), lambda _p: "accept"
    )
    # Decision + missions still landed.
    assert out["ratified_plan_decision_id"]
    assert len(out["ratified_mission_ids"]) == 2
    # The retag failure recorded.
    assert any(
        e["error_type"] == "pi_plan_ratify_journal_retag_failed"
        for e in out["errors"]
    )


# ---------------------------------------------------------------------------
# pi_plan_ratify — reject / correct
# ---------------------------------------------------------------------------


def test_pi_plan_ratify_reject_path_no_side_effects():
    mcp = _plan_loaded_mcp()
    out = pi.pi_plan_ratify(
        _state_with_plan_journal(), FakeSDK(), mcp, lambda _p: "reject"
    )
    # No decision, no missions, no retag.
    assert not any(c["op"] == "rka_add_decision" for c in mcp.calls)
    assert not any(c["op"] == "rka_create_mission" for c in mcp.calls)
    assert not any(c["op"] == "rka_update_note" for c in mcp.calls)
    assert "ratified_plan_decision_id" not in out
    assert "ratified_mission_ids" not in out
    assert "brain_position" not in out


def test_pi_plan_ratify_correct_carries_redirect_no_side_effects():
    feedback = "Reduce to 3 milestones; the m_02 / m_03 split is artificial."
    mcp = _plan_loaded_mcp()
    out = pi.pi_plan_ratify(
        _state_with_plan_journal(), FakeSDK(), mcp, lambda _p: feedback
    )
    assert out["brain_position"] == feedback
    # No writes.
    assert not any(c["op"] == "rka_add_decision" for c in mcp.calls)


# ---------------------------------------------------------------------------
# Schema + registry wiring
# ---------------------------------------------------------------------------


def test_parked_store_accepts_pi_plan_ratify():
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_plan_ratify",
        payload={"type": "pi_plan_ratify", "title": "x"},
    )
    assert iid.startswith("int_")
    store.close()


def test_runner_accept_token_for_plan_ratify_is_accept():
    assert _ACCEPT_TOKEN_BY_TYPE["pi_plan_ratify"] == "accept"


def test_runner_recognizes_pi_plan_ratify_as_onboarding():
    assert "pi_plan_ratify" in OrchestratorRunner._ONBOARDING_INTERRUPT_TYPES


def test_graph_onboarding_node_names_include_pi_plan_ratify():
    assert "pi_plan_ratify" in graph.ONBOARDING_NODE_NAMES
