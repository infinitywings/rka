"""Unit tests for the 3 Executor nodes (T4)."""

from __future__ import annotations

from orchestrator.nodes import executor
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


def _state() -> dict:
    return make_initial_state(
        workflow_thread_id="thr_t4",
        mission_id="mis_t4_target",
        motivated_by_decision_id="dec_t4_d1",
    )


# ---------------------------------------------------------------------------
# 1. backbrief_draft
# ---------------------------------------------------------------------------


def test_backbrief_draft_returns_documented_state_shape():
    sdk = FakeSDK(canned_reply="Backbrief content with plan + risks.")
    mcp = FakeMCP()
    state = _state()
    state["brain_strategy"] = "Brain says do X first."

    update = executor.backbrief_draft(state, sdk, mcp)

    assert update["current_phase"] == "executor_backbrief"
    assert update["current_node"] == "backbrief_draft"
    assert update["executor_backbrief"] == "Backbrief content with plan + risks."
    assert update["executor_position"]
    assert len(update["artifacts"]) == 1
    assert update["artifacts"][0]["entity_type"] == "journal"


def test_backbrief_draft_writes_with_backbrief_and_upfront_tags():
    sdk = FakeSDK()
    mcp = FakeMCP()
    executor.backbrief_draft(_state(), sdk, mcp)
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert "backbrief" in note_call["tags"]
    assert "upfront" in note_call["tags"]
    assert note_call["source"] == "executor"


def test_backbrief_draft_prompt_includes_brain_strategy():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _state()
    state["brain_strategy"] = "EXPECTED STRATEGY MARKER"

    executor.backbrief_draft(state, sdk, mcp)
    assert "EXPECTED STRATEGY MARKER" in sdk.calls[0]["prompt"]


def test_backbrief_draft_sdk_uses_executor_system_prompt():
    sdk = FakeSDK()
    mcp = FakeMCP()
    executor.backbrief_draft(_state(), sdk, mcp)
    assert sdk.calls[0]["system"] == executor.EXECUTOR_SYSTEM


# ---------------------------------------------------------------------------
# 2. mission_execute
# ---------------------------------------------------------------------------


def test_mission_execute_writes_log_entry():
    sdk = FakeSDK(canned_reply="Modified file X; added test Y; no anomalies.")
    mcp = FakeMCP()
    state = _state()
    state["executor_backbrief"] = "Approved backbrief content"
    state["gate1_verdict"] = "approved"

    update = executor.mission_execute(state, sdk, mcp)

    assert update["current_phase"] == "executor_mission"
    note_call = next(c for c in mcp.calls if c["op"] == "rka_add_note")
    assert note_call["type"] == "log"
    assert "mission-execution" in note_call["tags"]


def test_mission_execute_prompt_includes_gate1_verdict():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _state()
    state["executor_backbrief"] = "bb"
    state["gate1_verdict"] = "approved"

    executor.mission_execute(state, sdk, mcp)
    assert "approved" in sdk.calls[0]["prompt"]


def test_mission_execute_updates_executor_position():
    sdk = FakeSDK(canned_reply="First-line summary that should be the position.")
    mcp = FakeMCP()

    update = executor.mission_execute(_state(), sdk, mcp)
    assert update["executor_position"].startswith("First-line summary")


# ---------------------------------------------------------------------------
# 3. submit_report
# ---------------------------------------------------------------------------


def test_submit_report_calls_rka_submit_report_with_mission_id():
    sdk = FakeSDK(canned_reply="Report body with all sections.")
    mcp = FakeMCP()
    state = _state()

    update = executor.submit_report(state, sdk, mcp)

    report_calls = [c for c in mcp.calls if c["op"] == "rka_submit_report"]
    assert len(report_calls) == 1
    assert report_calls[0]["related_mission"] == "mis_t4_target"
    assert update["final_report_id"] == "rep_fake_001"
    assert update["final_report_id"].startswith("rep_")


def test_submit_report_records_report_as_artifact():
    sdk = FakeSDK()
    mcp = FakeMCP()
    update = executor.submit_report(_state(), sdk, mcp)
    assert update["artifacts"][0]["entity_type"] == "report"
    assert update["artifacts"][0]["rka_id"].startswith("rep_")


def test_submit_report_without_mission_id_records_error():
    # Defensive path: state["mission_id"] absent → error appended, no
    # rka_submit_report call.
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _state()
    del state["mission_id"]

    update = executor.submit_report(state, sdk, mcp)
    assert update.get("final_report_id") is None
    assert update["errors"][0]["error_type"] == "missing_mission_id"
    # Crucially: no report submission attempted
    assert not any(c["op"] == "rka_submit_report" for c in mcp.calls)


def test_submit_report_prompt_summarizes_artifacts():
    sdk = FakeSDK()
    mcp = FakeMCP()
    state = _state()
    state["artifacts"] = [
        {"rka_id": "jrn_x", "entity_type": "journal", "node_name": "strategy_node"},
        {"rka_id": "jrn_y", "entity_type": "journal", "node_name": "mission_execute"},
    ]

    executor.submit_report(state, sdk, mcp)
    prompt = sdk.calls[0]["prompt"]
    assert "jrn_x" in prompt
    assert "jrn_y" in prompt


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_every_executor_node_sets_current_node():
    expected = [
        (executor.backbrief_draft, "backbrief_draft"),
        (executor.mission_execute, "mission_execute"),
        (executor.submit_report, "submit_report"),
    ]
    for fn, name in expected:
        sdk = FakeSDK()
        mcp = FakeMCP()
        update = fn(_state(), sdk, mcp)
        assert update["current_node"] == name


def test_every_executor_node_uses_executor_system_prompt():
    for fn in (executor.backbrief_draft, executor.mission_execute, executor.submit_report):
        sdk = FakeSDK()
        mcp = FakeMCP()
        fn(_state(), sdk, mcp)
        assert sdk.calls[0]["system"] == executor.EXECUTOR_SYSTEM
