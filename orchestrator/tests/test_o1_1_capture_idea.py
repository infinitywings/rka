"""Phase O, O1.1 — capture_idea + pi_idea_capture tests.

Covers:
  - capture_idea_node: state writes (current_node, phase, ingested_source_ids)
  - capture_idea_node: pre-loads existing journals tagged ['<project_id>', 'ingested-source']
  - capture_idea_node: tolerates empty project + missing project_id gracefully
  - pi_idea_capture: interrupt payload shape (type, title, prompt, project_id)
  - pi_idea_capture: free-form response_text lands on state["brain_position"]
  - pi_idea_capture: accept-only path (greenlight token) leaves brain_position untouched
  - pi_idea_capture: refreshes ingested_source_ids after the pause
  - pi_idea_capture: InterruptRecord emitted with correct node_name + response
  - Parked-store CHECK constraint accepts pi_idea_capture
  - Runner _ACCEPT_TOKEN_BY_TYPE maps pi_idea_capture → 'approve'
  - Runner _ONBOARDING_INTERRUPT_TYPES contains pi_idea_capture
  - graph.ONBOARDING_NODE_NAMES contains capture_idea + pi_idea_capture
"""

from __future__ import annotations

import pytest

from orchestrator import graph
from orchestrator.nodes import onboarding, pi
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE, OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# capture_idea_node
# ---------------------------------------------------------------------------


def test_capture_idea_writes_current_node_and_phase():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = {"project_id": "prj_test_01"}

    out = onboarding.capture_idea_node(state, sdk, mcp)

    assert out["current_node"] == "capture_idea"
    assert out["current_phase"] == "init"
    assert out["ingested_source_ids"] == []


def test_capture_idea_preloads_existing_ingested_sources():
    sdk = FakeSDK()
    mcp = FakeMCP()
    # Two journals tagged for this project as ingested sources; one
    # unrelated journal to verify the tag filter applies.
    mcp.journal_response = [
        {"id": "jrn_01", "tags": ["prj_test_01", "ingested-source"]},
        {"id": "jrn_02", "tags": ["prj_test_01", "ingested-source", "other"]},
        {"id": "jrn_99", "tags": ["prj_test_01", "literature"]},
    ]
    out = onboarding.capture_idea_node({"project_id": "prj_test_01"}, sdk, mcp)

    assert sorted(out["ingested_source_ids"]) == ["jrn_01", "jrn_02"]


def test_capture_idea_no_project_id_skips_query():
    sdk = FakeSDK()
    mcp = FakeMCP()

    out = onboarding.capture_idea_node({}, sdk, mcp)

    assert out["ingested_source_ids"] == []
    # MCP should not have been called when project_id is empty.
    assert not any(c["op"] == "rka_get_journal" for c in mcp.calls)


def test_capture_idea_tolerates_mcp_failure():
    """If RKA is unreachable, capture_idea should return an empty list,
    not propagate the exception — the interrupt below it must still park
    so the PI can manually surface the issue."""
    sdk = FakeSDK()

    class _RaisingMCP(FakeMCP):
        def rka_get_journal(self, **_kw):
            raise RuntimeError("RKA unreachable")

    mcp = _RaisingMCP()
    out = onboarding.capture_idea_node({"project_id": "prj_x"}, sdk, mcp)
    assert out["ingested_source_ids"] == []


# ---------------------------------------------------------------------------
# pi_idea_capture interrupt
# ---------------------------------------------------------------------------


def _make_capture_state(project_id: str = "prj_test_01") -> dict:
    return {"project_id": project_id, "current_phase": "init"}


def test_pi_idea_capture_payload_shape():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "approve"

    sdk = FakeSDK()
    mcp = FakeMCP()

    pi.pi_idea_capture(_make_capture_state(), sdk, mcp, fake_interrupt)

    p = captured["payload"]
    assert p["type"] == "pi_idea_capture"
    assert "PI idea capture" in p["title"]
    assert p["project_id"] == "prj_test_01"
    # Prompt should substitute the project_id placeholder.
    assert "prj_test_01" in p["prompt"]
    assert "rka_add_note" in p["prompt"]


def test_pi_idea_capture_correct_carries_idea_text_to_brain_position():
    idea_text = (
        "We want to study how LLMs can run on smart-home edge devices "
        "for personalization without leaking data to the cloud."
    )

    def fake_interrupt(_payload):
        return idea_text

    out = pi.pi_idea_capture(_make_capture_state(), FakeSDK(), FakeMCP(), fake_interrupt)

    assert out["current_node"] == "pi_idea_capture"
    assert out["brain_position"].startswith("We want to study how LLMs")
    # InterruptRecord captured.
    assert len(out["interrupts"]) == 1
    assert out["interrupts"][0]["node_name"] == "pi_idea_capture"
    assert out["interrupts"][0]["response"] == idea_text


def test_pi_idea_capture_accept_leaves_brain_position_untouched():
    """When PI just hits accept (resume_token='approve'), the response
    is the literal greenlight token — not idea text — and brain_position
    must NOT be set with it (otherwise idea_polish would treat 'approve'
    as the project description)."""

    def fake_interrupt(_payload):
        return "approve"

    out = pi.pi_idea_capture(_make_capture_state(), FakeSDK(), FakeMCP(), fake_interrupt)

    assert "brain_position" not in out


def test_pi_idea_capture_refreshes_ingested_sources_after_pause():
    """During the pause the PI may have called rka_add_note one or more
    times. After the interrupt resumes, the node should re-query."""

    def fake_interrupt(_payload):
        return "approve"

    mcp = FakeMCP()
    mcp.journal_response = [
        {"id": "jrn_AA", "tags": ["prj_p1", "ingested-source"]},
        {"id": "jrn_BB", "tags": ["prj_p1", "ingested-source"]},
        {"id": "jrn_CC", "tags": ["prj_p1", "ingested-source"]},
    ]
    out = pi.pi_idea_capture({"project_id": "prj_p1"}, FakeSDK(), mcp, fake_interrupt)
    assert sorted(out["ingested_source_ids"]) == ["jrn_AA", "jrn_BB", "jrn_CC"]


def test_pi_idea_capture_truncates_long_response():
    """brain_position is capped at 5000 chars to keep state bounded."""
    long_text = "a" * 7000

    def fake_interrupt(_payload):
        return long_text

    out = pi.pi_idea_capture(_make_capture_state(), FakeSDK(), FakeMCP(), fake_interrupt)
    assert len(out["brain_position"]) == 5000


# ---------------------------------------------------------------------------
# Schema + registry wiring
# ---------------------------------------------------------------------------


def test_parked_store_accepts_pi_idea_capture():
    """Schema CHECK constraint must accept the new Phase O interrupt type."""
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_idea_capture",
        payload={"type": "pi_idea_capture", "title": "x"},
    )
    assert iid.startswith("int_")
    store.close()


def test_runner_accept_token_for_idea_capture_is_approve():
    """pi_idea_capture is a free-form input gate (greenlight-class)."""
    assert _ACCEPT_TOKEN_BY_TYPE["pi_idea_capture"] == "approve"


def test_runner_recognizes_pi_idea_capture_as_onboarding():
    """The runner routes pi_idea_capture responses via the onboarding
    compile factory, not the mission compile factory."""
    assert "pi_idea_capture" in OrchestratorRunner._ONBOARDING_INTERRUPT_TYPES


def test_graph_onboarding_node_names_include_capture_idea():
    """audit-symmetry: every current_node="capture_idea" or "pi_idea_capture"
    string must be declared in ONBOARDING_NODE_NAMES."""
    assert "capture_idea" in graph.ONBOARDING_NODE_NAMES
    assert "pi_idea_capture" in graph.ONBOARDING_NODE_NAMES


# ---------------------------------------------------------------------------
# Phase O interrupt-type set sanity check (catches forgotten registrations)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interrupt_type",
    [
        "pi_idea_capture",
        "pi_scope_ratify",
        "pi_deepresearch_prompt",
        "pi_claims_review",
        "pi_plan_ratify",
        "pi_phase_entry_ack",
    ],
)
def test_all_phase_o_interrupt_types_registered(interrupt_type):
    """Every Phase O interrupt is in the runner's accept-token map AND
    the onboarding-routing set AND the parked store accepts it."""
    assert interrupt_type in _ACCEPT_TOKEN_BY_TYPE
    assert interrupt_type in OrchestratorRunner._ONBOARDING_INTERRUPT_TYPES
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    # Schema CHECK is the real test — if the constraint rejects, the
    # call raises sqlite3.IntegrityError.
    store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type=interrupt_type,
        payload={"type": interrupt_type, "title": "x"},
    )
    store.close()
