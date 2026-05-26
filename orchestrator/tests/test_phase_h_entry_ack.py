"""Phase O — Phase H: pi_phase_entry_ack (per-milestone go/no-go) tests.

Covers:
  - Payload shape: current_mission_id, current_mission, remaining_*,
    current_milestone_index
  - Mission entity hydrated via rka_get_mission
  - accept advances current_milestone_index by 1
  - 'approve' (greenlight token) also accepted
  - reject leaves index unchanged, no brain_position
  - correct (freeform) leaves index unchanged, brain_position carries
    the redirect
  - end-of-queue: empty remaining_mission_ids, mission fetch skipped
  - rka_get_mission failure is tolerated (mission dict empty)
  - parked_store + runner + graph wiring
"""

from __future__ import annotations

import pytest

from orchestrator import graph
from orchestrator.nodes import pi
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE, OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


def _state_with_queue(*ids, idx=0) -> dict:
    return {
        "project_id": "prj_x",
        "ratified_mission_ids": list(ids),
        "current_milestone_index": idx,
    }


def test_pi_phase_entry_ack_payload_shape():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    mcp = FakeMCP()
    mcp.mission_response = {
        "id": "mis_aa",
        "objective": "scan literature",
        "phase": "literature",
        "status": "pending",
    }
    pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa", "mis_bb", "mis_cc"), FakeSDK(), mcp, fake_interrupt
    )

    p = captured["payload"]
    assert p["type"] == "pi_phase_entry_ack"
    assert "Mission queue" in p["title"]
    assert p["current_mission_id"] == "mis_aa"
    assert p["current_mission"]["objective"] == "scan literature"
    assert p["remaining_mission_ids"] == ["mis_aa", "mis_bb", "mis_cc"]
    assert p["remaining_count"] == 3
    assert p["current_milestone_index"] == 0
    assert p["items"] == [p["current_mission"]]


def test_pi_phase_entry_ack_accept_advances_index():
    out = pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa", "mis_bb"),
        FakeSDK(),
        FakeMCP(),
        lambda _p: "accept",
    )
    assert out["current_milestone_index"] == 1
    assert "brain_position" not in out


def test_pi_phase_entry_ack_approve_token_also_advances():
    """The greenlight 'approve' substring also counts as accept for
    Phase H (per runner _ACCEPT_TOKEN_BY_TYPE mapping pi_phase_entry_ack
    → 'approve')."""
    out = pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa"), FakeSDK(), FakeMCP(), lambda _p: "approve"
    )
    assert out["current_milestone_index"] == 1


def test_pi_phase_entry_ack_reject_leaves_index_unchanged():
    out = pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa", "mis_bb", idx=1),
        FakeSDK(),
        FakeMCP(),
        lambda _p: "reject",
    )
    # No current_milestone_index update — runner can read the existing
    # state value (1) on resume.
    assert "current_milestone_index" not in out
    assert "brain_position" not in out


def test_pi_phase_entry_ack_correct_carries_redirect():
    feedback = "Skip mis_bb; jump straight to mis_cc."
    out = pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa", "mis_bb", "mis_cc"),
        FakeSDK(),
        FakeMCP(),
        lambda _p: feedback,
    )
    assert "current_milestone_index" not in out
    assert out["brain_position"] == feedback


def test_pi_phase_entry_ack_end_of_queue_skips_mission_fetch():
    """When current_milestone_index points past the end, no mission is
    fetched, payload's current_mission_id is None."""
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    mcp = FakeMCP()
    pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa", idx=5),  # idx > len
        FakeSDK(),
        mcp,
        fake_interrupt,
    )
    p = captured["payload"]
    assert p["current_mission_id"] is None
    assert p["remaining_mission_ids"] == []
    assert p["remaining_count"] == 0
    # No rka_get_mission call.
    assert not any(c["op"] == "rka_get_mission" for c in mcp.calls)


def test_pi_phase_entry_ack_tolerates_mission_fetch_failure():
    class _MissionFailMCP(FakeMCP):
        def rka_get_mission(self, id=None):
            raise RuntimeError("rka down")

    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    pi.pi_phase_entry_ack(
        _state_with_queue("mis_aa"), FakeSDK(), _MissionFailMCP(), fake_interrupt
    )
    p = captured["payload"]
    assert p["current_mission_id"] == "mis_aa"
    # Mission dict is empty — render-time skill must tolerate.
    assert p["current_mission"] == {}


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_parked_store_accepts_pi_phase_entry_ack():
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_phase_entry_ack",
        payload={"type": "pi_phase_entry_ack", "title": "x"},
    )
    assert iid.startswith("int_")
    store.close()


def test_runner_accept_token_for_phase_entry_ack_is_approve():
    assert _ACCEPT_TOKEN_BY_TYPE["pi_phase_entry_ack"] == "approve"


def test_runner_recognizes_pi_phase_entry_ack_as_onboarding():
    assert "pi_phase_entry_ack" in OrchestratorRunner._ONBOARDING_INTERRUPT_TYPES


def test_graph_onboarding_node_names_include_pi_phase_entry_ack():
    assert "pi_phase_entry_ack" in graph.ONBOARDING_NODE_NAMES
