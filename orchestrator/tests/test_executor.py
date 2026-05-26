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


def test_EXECUTOR_SYSTEM_includes_phase_2_11_wrapper_vs_target_delta():
    """Phase 2.11 T2 (mis_01KRYT62XQK5NK3BY7G9BGRAPS; Brain-ratified scope
    per dec_01KRYT1GCP5N9CJZ2YE2N3BTBH Option A): EXECUTOR_SYSTEM gets a
    10th delta covering wrapper-vs-target distinction at mission_execute.

    Phase 2.10 surfaced that the brain `mission_execute` LLM interpreted
    the Phase 2.10 wrapper mission's T0-T7 task structure (from the
    Backbrief) as the work to execute, emitting a single rka_submit_report
    stub instead of 3× rka_update_note for the target mission's 3 cross-
    reference items. This delta locks the distinction at the prompt layer.

    Canonical marker phrase (chosen at scope-decision time for greppable
    locking): "work-target is the `mission_id` field"."""
    text = executor.EXECUTOR_SYSTEM
    assert "Wrapper-vs-target distinction" in text, (
        "Phase 2.11 T2: EXECUTOR_SYSTEM must include the wrapper-vs-target "
        "delta heading"
    )
    assert "work-target is the `mission_id` field" in text, (
        "Phase 2.11 T2: canonical marker phrase 'work-target is the "
        "`mission_id` field' missing from EXECUTOR_SYSTEM"
    )
    # Distinction-anchoring phrase: T0-T7 wrapper scaffolding callout.
    assert "wrapper scaffolding" in text, (
        "Phase 2.11 T2: delta must explicitly call out T0-T7 wrapper "
        "scaffolding as NOT the executor's work-target"
    )
    # The fix instruction: read target mission before planning.
    assert "rka_get_mission" in text, (
        "Phase 2.11 T2: delta must instruct LLM to read target mission "
        "via rka_get_mission before planning proposed_actions"
    )


def test_EXECUTOR_SYSTEM_delta_count_advances_through_phase_2_11():
    """Phase 2.11 T2 soft assertion — guard against accidental deletion of
    earlier deltas during future folds. Counts the section markers that
    indicate each fold layer's presence:

      - Phase 2.5 deltas: "Backbrief — Confirm Your Plan", "Guardrails.",
        "Report Submission.", "Repo-specific procedures." (4 markers)
      - Phase 2.7 action-proposals: "Action proposals."
      - Phase 2.11 wrapper-vs-target: "Wrapper-vs-target distinction"

    Total: 6 distinct section markers. If any are missing, a prior delta
    was likely overwritten."""
    text = executor.EXECUTOR_SYSTEM
    required_markers = [
        # Phase 2.5 deltas (4)
        "Backbrief — Confirm Your Plan",
        "Guardrails.",
        "Report Submission.",
        "Repo-specific procedures.",
        # Phase 2.7
        "Action proposals.",
        # Phase 2.11 (this T2)
        "Wrapper-vs-target distinction",
    ]
    missing = [m for m in required_markers if m not in text]
    assert not missing, (
        f"Phase 2.11 T2 soft assertion: EXECUTOR_SYSTEM is missing required "
        f"section markers: {missing!r}. A prior delta may have been "
        f"accidentally overwritten during a fold."
    )


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


def test_execute_ratified_actions_dispatches_rka_bulk_update():
    """Phase 2.13 T3 (mis_01KRYZMEAT01SMNNXQXS3JRC4W): exercises the
    dispatch path for the newly-allowlisted rka_bulk_update tool. Closes
    the 10th trigger surfaced empirically by Phase 2.12, where brain
    proposed rka_bulk_update for cross-reference hygiene and the
    Phase 2.7 Option C defense-in-depth correctly rejected the action
    (`ratified_action_tool_not_allowed`). Phase 2.13 T1+T2 added the
    Protocol method, RestMCPClient fanout adapter, FakeMCP impl, and
    WRITE_TOOLS entry; this test asserts the dispatch now succeeds end
    to end.

    Mirror of Phase 2.12's three target cross-reference items so the
    test shape matches what Phase 2.14 will retry empirically."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["ratified_actions"] = [
        {
            "tool": "rka_bulk_update",
            "args": {
                "updates": [
                    {
                        "entity_type": "note",
                        "id": "jrn_01KQQ4K4GWFKHQBCQNC9F92JX4",
                        "data": {
                            "related_decisions": [
                                "dec_01KQNPC7A683HK0KRX1PAGNNED",
                                "dec_01KMX18FDAMN7T5YVZ7V8HV6RJ",
                                "dec_01KMX18FDAMN7T5YVZ7V8HV6RK",
                                "dec_01KP4P4QSSNZCTEHVT6QR7ZRYD",
                            ],
                        },
                    },
                ],
            },
            "rationale": "Item 1 — cross-reference hygiene",
        },
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    # The FakeMCP rka_bulk_update method was called exactly once.
    bulk_calls = [c for c in mcp.calls if c["op"] == "rka_bulk_update"]
    assert len(bulk_calls) == 1
    assert bulk_calls[0]["updates"][0]["id"] == "jrn_01KQQ4K4GWFKHQBCQNC9F92JX4"
    assert bulk_calls[0]["updates"][0]["entity_type"] == "note"

    # One artifact appended; entity_type is "bulk" per Phase 2.13 T2's
    # _WRITE_TOOL_ENTITY_TYPES map extension.
    assert "artifacts" in update
    assert len(update["artifacts"]) == 1
    assert update["artifacts"][0]["entity_type"] == "bulk"
    assert update["artifacts"][0]["node_name"] == "execute_ratified_actions"

    # No ErrorRecord — the dispatch path that fired the
    # ratified_action_tool_not_allowed error in Phase 2.12 now succeeds.
    assert "errors" not in update


# ---------------------------------------------------------------------------
# Phase-B (agentic) — Delta #19 + #20: WRITE_TOOLS enumeration in
# EXECUTOR_SYSTEM + action-independence (chain not yet supported)
# ---------------------------------------------------------------------------


def test_EXECUTOR_SYSTEM_enumerates_write_tools_allowlist():
    """Phase-B Delta #19: empirical driver was the Phase-A2 IoT-edge-LLM
    live test where Brain repeatedly proposed tools outside WRITE_TOOLS.
    The prompt now lists every dispatchable tool by name AND names the
    forbidden patterns. Locks both."""
    text = executor.EXECUTOR_SYSTEM
    # Every WRITE_TOOLS entry must appear in the enumeration.
    from orchestrator.llm_client import WRITE_TOOLS
    for tool in WRITE_TOOLS:
        assert tool in text, (
            f"Phase-B Delta #19: {tool!r} from WRITE_TOOLS must appear "
            f"in the EXECUTOR_SYSTEM allowlist enumeration"
        )
    # Forbidden patterns must be called out by name.
    for forbidden in (
        "rka_present_decision",
        "rka_resolve_checkpoint",
        "rka_supersede_decision",
        "rka_set_project",
    ):
        assert forbidden in text, (
            f"Phase-B Delta #19: {forbidden!r} must be explicitly named "
            f"as out-of-scope in the EXECUTOR_SYSTEM prompt"
        )
    # Canonical marker phrase for grep-locking.
    assert "Allowed write tools" in text


def test_EXECUTOR_SYSTEM_documents_chain_substitution_syntax():
    """Phase-C Delta #20 (revised): execute_ratified_actions now SUPPORTS
    chain substitution. The prompt teaches the {{PA-N.id}} syntax
    (1-indexed) so Brain uses it instead of literal placeholder strings
    like `REQUIRES_PA1_DECISION_ID` (the anti-pattern Phase-A2 live test
    surfaced)."""
    text = executor.EXECUTOR_SYSTEM
    assert "Action chaining" in text, "Phase-C Delta #20 marker phrase missing"
    assert "{{PA-1.id}}" in text or "{{PA-" in text, (
        "Phase-C: prompt must teach the {{PA-N.id}} substitution syntax"
    )
    # The literal anti-pattern Brain used in Phase-A2 must be called out.
    assert "REQUIRES_PA1_DECISION_ID" in text or "placeholder" in text.lower(), (
        "Phase-C: should call out the literal-placeholder anti-pattern "
        "Brain used in Phase-A2 live test"
    )
    assert "1-indexed" in text


# ---------------------------------------------------------------------------
# Phase-C (agentic) — chain substitution in execute_ratified_actions
# ---------------------------------------------------------------------------


class _ChainTrackingMCP:
    """FakeMCP that returns predictable ids and records the args it was
    called with (so chain-substitution tests can assert the substituted
    values actually reached the tool)."""

    def __init__(self, return_ids: list[str] | None = None):
        self.workflow_thread_id = "thr_test"
        self._return_ids = list(return_ids or [])
        self.calls: list[dict] = []

    def _record(self, op: str, **kw) -> str:
        self.calls.append({"op": op, **kw})
        if self._return_ids:
            return self._return_ids.pop(0)
        return f"{op}_id_{len(self.calls)}"

    def rka_add_note(self, **kw) -> str: return self._record("rka_add_note", **kw)
    def rka_add_decision(self, **kw) -> str: return self._record("rka_add_decision", **kw)
    def rka_update_note(self, **kw) -> str: return self._record("rka_update_note", **kw)
    def rka_create_mission(self, **kw) -> str: return self._record("rka_create_mission", **kw)
    def rka_submit_report(self, **kw) -> str: return self._record("rka_submit_report", **kw)
    def rka_submit_checkpoint(self, **kw) -> str: return self._record("rka_submit_checkpoint", **kw)
    def rka_bulk_update(self, **kw) -> str: return self._record("rka_bulk_update", **kw)
    def rka_update_mission_status(self, **kw) -> str: return self._record("rka_update_mission_status", **kw)
    def rka_ingest_document(self, **kw) -> str: return self._record("rka_ingest_document", **kw)


class _StubSDK:
    """No-op SDK used by tests that don't invoke an LLM call (e.g.
    execute_ratified_actions doesn't talk to the LLM)."""

    def complete(self, **kw) -> str:
        return ""


def _state_with_actions(actions: list[dict]) -> dict:
    """Shorthand: build a minimal state dict with ratified_actions set."""
    return {"mission_id": "mis_test", "ratified_actions": actions}


def test_chain_substitution_resolves_pa1_id_into_pa2_args():
    """Phase-C happy path: PA-2 references {{PA-1.id}} and gets PA-1's
    actual return value substituted before dispatch."""
    mcp = _ChainTrackingMCP(return_ids=["dec_chain_001", "jrn_chain_002"])
    state = _state_with_actions(
        [
            {
                "tool": "rka_add_decision",
                "args": {
                    "content": "Adopt approach X",
                    "related_journal": ["jrn_seed"],
                },
                "rationale": "PA-1: create decision",
            },
            {
                "tool": "rka_add_note",
                "args": {
                    "content": "Implementation note for decision {{PA-1.id}}",
                    "related_decisions": ["{{PA-1.id}}"],
                },
                "rationale": "PA-2: note referencing PA-1",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)

    # Both dispatched; PA-2's content + related_decisions contain the
    # substituted PA-1 return id, not the literal placeholder.
    assert len(mcp.calls) == 2
    pa2_call = mcp.calls[1]
    assert pa2_call["op"] == "rka_add_note"
    assert pa2_call["content"] == "Implementation note for decision dec_chain_001"
    assert pa2_call["related_decisions"] == ["dec_chain_001"]
    assert "{{PA-1.id}}" not in str(pa2_call)

    # Both produced artifacts; no errors.
    assert len(update["artifacts"]) == 2
    assert "errors" not in update


def test_chain_substitution_handles_nested_dict_and_list_args():
    """Substitution recurses into nested dicts and lists, not just
    top-level string values."""
    mcp = _ChainTrackingMCP(return_ids=["dec_root", "jrn_child"])
    state = _state_with_actions(
        [
            {"tool": "rka_add_decision", "args": {"content": "x"}, "rationale": ""},
            {
                "tool": "rka_add_note",
                "args": {
                    "content": "ok",
                    "tags": ["plain", "decision={{PA-1.id}}"],
                    "metadata": {"linked_to": "{{PA-1.id}}", "depth": 1},
                },
                "rationale": "",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    pa2 = mcp.calls[1]
    assert pa2["tags"] == ["plain", "decision=dec_root"]
    assert pa2["metadata"] == {"linked_to": "dec_root", "depth": 1}
    assert "errors" not in update


def test_chain_substitution_rejects_forward_reference():
    """PA-1 referencing PA-2 (or itself) is an error; PA-1 skipped,
    PA-2 still attempts and succeeds (no chain reference to satisfy)."""
    mcp = _ChainTrackingMCP(return_ids=["dec_pa2"])
    state = _state_with_actions(
        [
            {
                "tool": "rka_add_note",
                "args": {"content": "ref {{PA-2.id}}"},
                "rationale": "PA-1: forward ref",
            },
            {
                "tool": "rka_add_decision",
                "args": {"content": "ok"},
                "rationale": "PA-2: independent",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    # PA-1 skipped (forward ref); PA-2 dispatched normally.
    assert len(mcp.calls) == 1
    assert mcp.calls[0]["op"] == "rka_add_decision"
    # One error from PA-1.
    errs = update.get("errors", [])
    assert len(errs) == 1
    assert errs[0]["error_type"] == "ratified_action_chain_resolution_failed"
    assert "PA-1" in errs[0]["detail"] and "forward-ref" in errs[0]["detail"]


def test_chain_substitution_rejects_self_reference():
    """PA-1 referencing PA-1 in its own args is a self-reference error."""
    mcp = _ChainTrackingMCP()
    state = _state_with_actions(
        [
            {
                "tool": "rka_add_note",
                "args": {"content": "self {{PA-1.id}}"},
                "rationale": "",
            }
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    assert mcp.calls == []
    errs = update.get("errors", [])
    assert len(errs) == 1
    assert "PA-1" in errs[0]["detail"]


def test_chain_substitution_rejects_out_of_range():
    """Reference to PA-99 when only 2 actions exist is out-of-range."""
    mcp = _ChainTrackingMCP(return_ids=["dec_001"])
    state = _state_with_actions(
        [
            {"tool": "rka_add_decision", "args": {"content": "x"}, "rationale": ""},
            {
                "tool": "rka_add_note",
                "args": {"content": "bogus {{PA-99.id}}"},
                "rationale": "",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    # PA-1 dispatched; PA-2 skipped (out of range).
    assert len(mcp.calls) == 1
    errs = update.get("errors", [])
    assert any(
        "out of range" in e["detail"] and "PA-99" in e["detail"] for e in errs
    )


def test_chain_substitution_rejects_unsupported_field():
    """Only `.id` is supported in Phase-C; `.timestamp` etc. should error."""
    mcp = _ChainTrackingMCP(return_ids=["dec_001"])
    state = _state_with_actions(
        [
            {"tool": "rka_add_decision", "args": {"content": "x"}, "rationale": ""},
            {
                "tool": "rka_add_note",
                "args": {"content": "ts: {{PA-1.timestamp}}"},
                "rationale": "",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    errs = update.get("errors", [])
    assert any("unsupported chain field" in e["detail"] for e in errs)


def test_chain_substitution_rejects_reference_to_failed_prior_action():
    """If PA-1 failed (no rka_id), PA-2's reference to {{PA-1.id}} must
    fail too — never substitute an empty string silently."""
    # Build an MCP where PA-1 raises an exception, PA-2 references PA-1.
    class _FailingMCP(_ChainTrackingMCP):
        def rka_add_decision(self, **kw):
            raise RuntimeError("simulated PA-1 failure")

    mcp = _FailingMCP()
    state = _state_with_actions(
        [
            {"tool": "rka_add_decision", "args": {"content": "x"}, "rationale": ""},
            {
                "tool": "rka_add_note",
                "args": {"content": "depends on {{PA-1.id}}"},
                "rationale": "",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    errs = update.get("errors", [])
    # Two errors: PA-1 call_failed + PA-2 chain_resolution_failed.
    error_types = {e["error_type"] for e in errs}
    assert "ratified_action_call_failed" in error_types
    assert "ratified_action_chain_resolution_failed" in error_types
    # PA-2 wasn't dispatched (no second call).
    assert len(mcp.calls) == 0


def test_chain_substitution_no_braces_passthrough():
    """Args without `{{` markers pass through unchanged (fast path)."""
    mcp = _ChainTrackingMCP(return_ids=["jrn_001"])
    state = _state_with_actions(
        [
            {
                "tool": "rka_add_note",
                "args": {"content": "no chain refs here", "tags": ["x"]},
                "rationale": "",
            }
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    assert mcp.calls[0]["content"] == "no chain refs here"
    assert "errors" not in update


def test_chain_substitution_works_across_three_step_chain():
    """3-step chain: PA-1 → PA-2 → PA-3 each referencing the prior."""
    mcp = _ChainTrackingMCP(return_ids=["mis_x", "dec_y", "jrn_z"])
    state = _state_with_actions(
        [
            {
                "tool": "rka_create_mission",
                "args": {
                    "objective": "test",
                    "motivated_by_decision": "dec_seed",
                    "acceptance_criteria": ["a"],
                },
                "rationale": "PA-1",
            },
            {
                "tool": "rka_add_decision",
                "args": {
                    "content": "ratify {{PA-1.id}}",
                    "related_journal": ["jrn_seed"],
                },
                "rationale": "PA-2 → refs PA-1",
            },
            {
                "tool": "rka_add_note",
                "args": {
                    "content": "for mission {{PA-1.id}} per decision {{PA-2.id}}",
                    "related_mission": "{{PA-1.id}}",
                    "related_decisions": ["{{PA-2.id}}"],
                },
                "rationale": "PA-3 → refs both",
            },
        ]
    )
    update = executor.execute_ratified_actions(state, _StubSDK(), mcp)
    pa3 = mcp.calls[2]
    assert pa3["content"] == "for mission mis_x per decision dec_y"
    assert pa3["related_mission"] == "mis_x"
    assert pa3["related_decisions"] == ["dec_y"]
    assert len(update["artifacts"]) == 3
    assert "errors" not in update
