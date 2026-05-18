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


def test_backbrief_draft_includes_mission_body():
    """Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T5): backbrief_draft must
    fetch the mission via rka_get_mission and include objective + tasks +
    acceptance_criteria + scope_boundaries in the LLM prompt. Mirrors the
    T4 fix in brain.strategy_node / brain.confirmation_brief — without the
    body, real Claude produces a SKELETON Backbrief and gate1 correctly
    REDIRECTS."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    mcp.mission_response = {
        "id": "mis_t4_target",
        "objective": "BB_OBJECTIVE_MARKER",
        "tasks": [
            {"description": "BB_TASK_ALPHA", "status": "pending"},
            {"description": "BB_TASK_BETA", "status": "active"},
        ],
        "acceptance_criteria": "BB_ACCEPTANCE_MARKER",
        "scope_boundaries": "BB_SCOPE_MARKER",
    }
    state = _state()

    executor.backbrief_draft(state, sdk, mcp)

    mission_calls = [c for c in mcp.calls if c["op"] == "rka_get_mission"]
    assert mission_calls, "backbrief_draft must call rka_get_mission"
    assert mission_calls[0]["id"] == "mis_t4_target"

    prompt = sdk.calls[0]["prompt"]
    for marker in (
        "BB_OBJECTIVE_MARKER",
        "BB_TASK_ALPHA",
        "BB_TASK_BETA",
        "BB_ACCEPTANCE_MARKER",
        "BB_SCOPE_MARKER",
    ):
        assert marker in prompt, f"backbrief_draft prompt missing mission body marker: {marker}"


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
    """Phase 2.7 T5 (jrn_01KRXQJJXKRAH1GB6FTZEQDAXQ) — corrected contract.
    RKA's data model stores reports inline on missions; there is no
    separate `Report` entity with a `rep_*` prefix. The return value of
    rka_submit_report IS the mission_id under which the report was filed.
    The Phase 2.5 assertion `final_report_id.startswith("rep_")` was wrong
    against the real REST surface — only FakeMCP's fake `rep_fake_NNN`
    let it pass."""
    sdk = FakeSDK(canned_reply="Report body with all sections.")
    mcp = FakeMCP()
    state = _state()

    update = executor.submit_report(state, sdk, mcp)

    report_calls = [c for c in mcp.calls if c["op"] == "rka_submit_report"]
    assert len(report_calls) == 1
    assert report_calls[0]["related_mission"] == "mis_t4_target"
    # Return value is the mission_id under which the report was filed.
    assert update["final_report_id"] == "mis_t4_target"
    assert update["final_report_id"] == state["mission_id"]


def test_submit_report_records_report_as_artifact():
    """The artifact records the report submission; rka_id is the
    mission_id (inline-report convention), entity_type tagged 'report' so
    audit walks can still distinguish report-submissions from other
    journal writes against the same mission."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    update = executor.submit_report(_state(), sdk, mcp)
    assert update["artifacts"][0]["entity_type"] == "report"
    # rka_id matches mission_id, NOT a synthetic `rep_*` prefix.
    assert update["artifacts"][0]["rka_id"] == "mis_t4_target"


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


def test_EXECUTOR_SYSTEM_includes_phase_2_5_deltas():
    """Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T3): EXECUTOR_SYSTEM is
    extended with prose from 4 runtime-relevant deltas per the Brain-
    ratified Option-C scope (dec_01KRVHZ4P3F1GXE75RRAQX3BTP +
    chk_01KRVH890GKYCY9A28TM02STQ1):

      Delta #1  — Version-drift re-verification (token: "info.version")
      Delta #8  — Defensive missing-required-field paths
                    (token: "ErrorRecord over raising")
      Delta #14b — Metric divergence-as-headline / Report Submission
                    (token: "expected X, observed Y")
      Delta #17 — Affordance G — 422 is integrity, not transient
                    (token: "integrity error")

    5 other deltas are SKIPPED-PYTHON (already enforced in orchestrator
    source code; tracked in skill-prompt-deltas.md with code-path
    references — see Phase 2.5 T6 metadata commit).
    """
    text = executor.EXECUTOR_SYSTEM
    # Base identity preserved.
    assert "You are the Executor" in text

    # Phase 2.5 delta markers — each from a runtime-relevant delta.
    expected_markers = [
        ("delta #1 Version-drift",      "info.version"),
        ("delta #8 ErrorRecord paths",  "ErrorRecord over raising"),
        ("delta #14b Divergence",       "expected X, observed Y"),
        ("delta #17 Affordance G/422",  "integrity error"),
    ]
    missing = [label for label, marker in expected_markers if marker not in text]
    assert not missing, (
        f"EXECUTOR_SYSTEM missing Phase 2.5 delta markers: {missing}. "
        f"Each runtime-relevant delta's prose must include the substring "
        f"locked by this test so future refactors can't silently drop them."
    )


# ---------------------------------------------------------------------------
# Phase 2.7 T3c — mission_execute structured proposed_actions output contract
# (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R; PI-ratified per jrn_01KRXP96THHEAKCGB0P0KGV7Y9)
# ---------------------------------------------------------------------------


def test_EXECUTOR_SYSTEM_includes_phase_2_7_action_proposals_prose():
    """Phase 2.7 T3c: EXECUTOR_SYSTEM is extended with the Action proposals
    directive instructing the LLM to emit a structured JSON proposed_actions
    block at the end of mission_execute's reply."""
    text = executor.EXECUTOR_SYSTEM
    assert "Action proposals" in text
    assert "proposed_actions" in text
    assert "pi_decision_select" in text


def test_mission_execute_parses_proposed_actions_happy_path():
    """When the LLM ends its reply with a well-formed JSON block carrying
    `proposed_actions`, mission_execute extracts the list and writes it to
    state["proposed_actions"]. No ErrorRecord."""
    canned = (
        "Did the cross-reference analysis. Item 1 cites 4 decisions in its "
        "Provenance section.\n\n"
        '```json\n'
        '{"proposed_actions": ['
        '  {"tool": "rka_update_note", "args": {"id": "jrn_target_1", '
        '"related_decisions": ["dec_a", "dec_b"]}, "rationale": "Item 1 cites these"}'
        ']}'
        '\n```'
    )
    sdk = FakeSDK(canned_reply=canned)
    mcp = FakeMCP()
    update = executor.mission_execute(_state(), sdk, mcp)
    assert update["proposed_actions"] == [
        {
            "tool": "rka_update_note",
            "args": {"id": "jrn_target_1", "related_decisions": ["dec_a", "dec_b"]},
            "rationale": "Item 1 cites these",
        }
    ]
    # No ErrorRecord on happy path.
    assert "errors" not in update


def test_mission_execute_parses_proposed_actions_trailing_bare_json():
    """The LLM may emit the JSON either fenced (```json ...```) or as a
    bare trailing object. Both should parse."""
    canned = (
        "All done.\n\n"
        '{"proposed_actions": [{"tool": "rka_update_note", "args": {"id": "jrn_x"}, "rationale": "r"}]}'
    )
    sdk = FakeSDK(canned_reply=canned)
    mcp = FakeMCP()
    update = executor.mission_execute(_state(), sdk, mcp)
    assert len(update["proposed_actions"]) == 1
    assert update["proposed_actions"][0]["tool"] == "rka_update_note"


def test_mission_execute_falls_back_on_malformed_json():
    """Phase 2.5 Delta #7 conservative-malformed-input default: when the
    LLM emits malformed JSON (or omits the block entirely), mission_execute
    writes proposed_actions=[] AND appends an ErrorRecord."""
    canned = "All done. No JSON block at end of message."
    sdk = FakeSDK(canned_reply=canned)
    mcp = FakeMCP()
    update = executor.mission_execute(_state(), sdk, mcp)
    assert update["proposed_actions"] == []
    assert "errors" in update
    assert update["errors"][0]["error_type"] == "proposed_actions_parse_failure"


def test_mission_execute_emits_empty_proposed_actions_explicitly():
    """When the LLM emits `proposed_actions: []` (planning concluded no
    action needed), the parse succeeds with an empty list and NO error."""
    canned = 'Done. {"proposed_actions": []}'
    sdk = FakeSDK(canned_reply=canned)
    mcp = FakeMCP()
    update = executor.mission_execute(_state(), sdk, mcp)
    assert update["proposed_actions"] == []
    assert "errors" not in update


# ---------------------------------------------------------------------------
# Phase 2.7 T3e — execute_ratified_actions parent-side WRITE_TOOLS dispatch
# ---------------------------------------------------------------------------


def test_execute_ratified_actions_dispatches_to_mcp_methods():
    """Happy path: each ratified action invokes the corresponding MCPClient
    method via getattr(mcp, tool)(**args). Successful calls append
    ArtifactRefs; entity_type matches _WRITE_TOOL_ENTITY_TYPES."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["ratified_actions"] = [
        {
            "tool": "rka_update_note",
            "args": {"id": "jrn_target_1", "related_decisions": ["dec_a"]},
            "rationale": "Provenance cite",
        },
        {
            "tool": "rka_add_note",
            "args": {"content": "Probe note", "related_mission": "mis_t4_target"},
            "rationale": "Test write",
        },
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    # Two MCP write calls fired.
    update_calls = [c for c in mcp.calls if c["op"] == "rka_update_note"]
    add_calls = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    assert len(update_calls) == 1
    assert update_calls[0]["id"] == "jrn_target_1"
    assert update_calls[0]["related_decisions"] == ["dec_a"]
    assert len(add_calls) == 1
    # Two artifacts appended; one is `journal` (rka_update_note), other `journal` (rka_add_note).
    assert len(update["artifacts"]) == 2
    assert all(a["node_name"] == "execute_ratified_actions" for a in update["artifacts"])
    assert all(a["entity_type"] == "journal" for a in update["artifacts"])


def test_execute_ratified_actions_refuses_tool_not_in_WRITE_TOOLS():
    """Defense in depth: even if the LLM bypasses the subprocess
    disallowed_tools and a ratified_action carries a non-WRITE_TOOLS name,
    execute_ratified_actions refuses + appends an ErrorRecord."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["ratified_actions"] = [
        {"tool": "rka_get_status", "args": {}, "rationale": "should be rejected"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    # No MCP write fired.
    assert all(c["op"] != "rka_get_status" for c in mcp.calls)
    # ErrorRecord appended.
    assert "errors" in update
    assert update["errors"][0]["error_type"] == "ratified_action_tool_not_allowed"
    assert "rka_get_status" in update["errors"][0]["detail"]


def test_execute_ratified_actions_no_op_when_empty():
    """Default state: when state["ratified_actions"] is absent or empty
    (PI rejected or never populated), the node is a no-op — no MCP calls,
    no artifacts, no errors. Allows the graph topology to wire the node
    unconditionally between pi_decision_select and final_synthesis."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    # ratified_actions intentionally not set; defaults to empty.

    update = executor.execute_ratified_actions(state, sdk, mcp)

    assert update["current_node"] == "execute_ratified_actions"
    assert "artifacts" not in update
    assert "errors" not in update
    # No MCP calls of any kind.
    assert mcp.calls == []


def test_execute_ratified_actions_captures_call_failure_as_ErrorRecord():
    """When the mcp call raises, surface as an ErrorRecord — don't crash
    the workflow. Honors Phase 2.5 Delta #8 'ErrorRecord over raising'."""

    class _BoomMCP(FakeMCP):
        def rka_update_note(self, id, **kw):  # noqa: ARG002
            raise RuntimeError("simulated REST 500")

    mcp = _BoomMCP()
    sdk = FakeSDK()
    state = _state()
    state["ratified_actions"] = [
        {"tool": "rka_update_note", "args": {"id": "jrn_x"}, "rationale": "test"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    assert "artifacts" not in update
    assert "errors" in update
    assert update["errors"][0]["error_type"] == "ratified_action_call_failed"
