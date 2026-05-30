"""Gap 3A — mission `capabilities` field seeds state["allowed_capabilities"].

Pre-Gap-3A, the Phase 2.14 capability allowlist was plumbed but no
caller populated it. Now `start_run_commit` reads `mission["capabilities"]`
and threads it through to `start_run_drive` → `make_initial_state` →
`state["allowed_capabilities"]` → `execute_ratified_actions` enforcement.
"""

from __future__ import annotations

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


class _MissionMCP(FakeMCP):
    """FakeMCP that returns a scripted mission dict from rka_get_mission."""

    def __init__(self, mission: dict):
        super().__init__()
        self._mission = mission

    def rka_get_mission(self, *, id):
        return self._mission


def _make_runner(store, mission: dict):
    return OrchestratorRunner(
        store=store,
        sdk_factory=lambda _p, _ws="": FakeSDK(),
        mcp_factory=lambda _t, _p: _MissionMCP(mission),
        saver_factory=lambda _t: None,
    )


# ---------------------------------------------------------------------------
# make_initial_state
# ---------------------------------------------------------------------------


def test_make_initial_state_defaults_to_empty_allowed_capabilities():
    """No restriction by default — pre-2.14 behavior preserved."""
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
    )
    assert state["allowed_capabilities"] == []


def test_make_initial_state_accepts_capabilities_list():
    """Caller can seed the allowlist directly."""
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
        allowed_capabilities=["record_knowledge", "execution_gates"],
    )
    assert state["allowed_capabilities"] == ["record_knowledge", "execution_gates"]


def test_make_initial_state_copies_capabilities_list_not_alias():
    """Caller list mutation shouldn't poison state — defensive copy."""
    caller_list = ["record_knowledge"]
    state = make_initial_state(
        workflow_thread_id="thr_t",
        mission_id="mis_t",
        motivated_by_decision_id="dec_t",
        allowed_capabilities=caller_list,
    )
    caller_list.append("mission_lifecycle")
    assert state["allowed_capabilities"] == ["record_knowledge"]


# ---------------------------------------------------------------------------
# start_run_commit reads mission.capabilities
# ---------------------------------------------------------------------------


def test_start_run_commit_reads_mission_capabilities_into_ack():
    """A mission carrying capabilities=[...] surfaces them in the ack so
    start_run_drive can seed state."""
    store = ParkedStore(":memory:")
    mission = {
        "id": "mis_001",
        "motivated_by_decision": "dec_a",
        "capabilities": ["record_knowledge", "execution_gates"],
    }
    runner = _make_runner(store, mission)

    ack = runner.start_run_commit(
        mission_id="mis_001",
        project_id="prj_x",
        workflow_thread_id="thr_001",
    )

    assert ack["allowed_capabilities"] == ["record_knowledge", "execution_gates"]
    store.close()


def test_start_run_commit_missing_capabilities_yields_empty_list():
    """Pre-Gap-3A missions (no capabilities field) → empty list = no
    restriction. Pre-2.14 behavior preserved."""
    store = ParkedStore(":memory:")
    mission = {"id": "mis_002", "motivated_by_decision": "dec_b"}
    runner = _make_runner(store, mission)

    ack = runner.start_run_commit(
        mission_id="mis_002",
        project_id="prj_x",
        workflow_thread_id="thr_002",
    )
    assert ack["allowed_capabilities"] == []
    store.close()


def test_start_run_commit_malformed_capabilities_is_ignored():
    """Defensive: a mission with capabilities='record_knowledge' (string
    not list) silently degrades to empty allowlist. The state-level
    malformed-detection guard in execute_ratified_actions also fires if
    the LLM/store ever puts a bad value into state directly, but here
    we filter at the source."""
    store = ParkedStore(":memory:")
    mission = {
        "id": "mis_003",
        "motivated_by_decision": "dec_c",
        "capabilities": "record_knowledge",  # typo: string not list
    }
    runner = _make_runner(store, mission)

    ack = runner.start_run_commit(
        mission_id="mis_003",
        project_id="prj_x",
        workflow_thread_id="thr_003",
    )
    assert ack["allowed_capabilities"] == []
    store.close()


def test_start_run_commit_filters_non_string_entries():
    """A list with non-string entries is treated as malformed (filtered
    to empty) so partial garbage doesn't reach state."""
    store = ParkedStore(":memory:")
    mission = {
        "id": "mis_004",
        "motivated_by_decision": "dec_d",
        "capabilities": ["record_knowledge", 123, None],
    }
    runner = _make_runner(store, mission)

    ack = runner.start_run_commit(
        mission_id="mis_004",
        project_id="prj_x",
        workflow_thread_id="thr_004",
    )
    assert ack["allowed_capabilities"] == []
    store.close()
