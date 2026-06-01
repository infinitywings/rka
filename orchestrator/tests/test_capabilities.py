"""Phase 2.14 — capability-categories WRITE_TOOLS tests.

Covers:
  - WRITE_TOOLS is derived from TOOL_CAPABILITIES (no static drift)
  - Every WRITE_TOOLS entry has a capability bucket
  - `tools_for_capabilities` returns the right slice
  - `capability_of` returns None for unknown tools
  - `execute_ratified_actions` respects state["allowed_capabilities"]
"""

from __future__ import annotations

from orchestrator import llm_client
from orchestrator.llm_client import (
    ALL_CAPABILITIES,
    TOOL_CAPABILITIES,
    WRITE_TOOLS,
    capability_of,
    tools_for_capabilities,
)
from orchestrator.nodes import executor
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# Registry consistency
# ---------------------------------------------------------------------------


def test_write_tools_is_derived_from_tool_capabilities():
    """WRITE_TOOLS must be exactly the keys of TOOL_CAPABILITIES — no
    static drift between the two lists is allowed."""
    assert set(WRITE_TOOLS) == set(TOOL_CAPABILITIES.keys())


def test_every_write_tool_has_a_known_capability():
    """Every TOOL_CAPABILITIES value must be a recognized capability."""
    for tool, cap in TOOL_CAPABILITIES.items():
        assert cap in ALL_CAPABILITIES, f"{tool!r} maps to unknown capability {cap!r}"


def test_all_capabilities_are_covered():
    """Every capability in ALL_CAPABILITIES should have at least one tool
    mapped to it — otherwise the bucket is dead."""
    used = set(TOOL_CAPABILITIES.values())
    for cap in ALL_CAPABILITIES:
        assert cap in used, f"capability {cap!r} has no tools"


def test_no_tool_in_multiple_capabilities():
    """TOOL_CAPABILITIES is a dict; each tool maps to exactly one
    capability by construction. This test is the canary that catches
    any future refactor that turns it into a multi-valued mapping."""
    counts: dict[str, int] = {}
    for tool in TOOL_CAPABILITIES:
        counts[tool] = counts.get(tool, 0) + 1
    for tool, n in counts.items():
        assert n == 1, f"{tool!r} appears {n} times"


# ---------------------------------------------------------------------------
# tools_for_capabilities / capability_of
# ---------------------------------------------------------------------------


def test_tools_for_capabilities_none_returns_all():
    assert tools_for_capabilities(None) == tuple(TOOL_CAPABILITIES.keys())
    assert tools_for_capabilities() == tuple(TOOL_CAPABILITIES.keys())


def test_tools_for_capabilities_single_bucket():
    record = tools_for_capabilities(("record_knowledge",))
    assert "rka_add_note" in record
    assert "rka_add_decision" in record
    # Not record_knowledge:
    assert "rka_update_note" not in record
    assert "rka_create_mission" not in record


def test_tools_for_capabilities_multiple_buckets():
    out = tools_for_capabilities(("record_knowledge", "execution_gates"))
    assert "rka_add_note" in out
    assert "rka_submit_checkpoint" in out
    assert "rka_create_mission" not in out


def test_tools_for_capabilities_empty_list_returns_empty():
    """Empty capability allowlist → no tools (lockdown mode)."""
    assert tools_for_capabilities(()) == ()
    assert tools_for_capabilities([]) == ()


def test_capability_of_known_tool():
    assert capability_of("rka_add_note") == "record_knowledge"
    assert capability_of("rka_submit_checkpoint") == "execution_gates"
    assert capability_of("rka_create_mission") == "mission_lifecycle"
    assert capability_of("rka_ingest_document") == "ingestion"
    assert capability_of("rka_update_note") == "update_knowledge"


def test_capability_of_unknown_tool_returns_none():
    assert capability_of("rka_get_status") is None  # read tool
    assert capability_of("not_a_tool") is None


# ---------------------------------------------------------------------------
# execute_ratified_actions — capability-scoped dispatch
# ---------------------------------------------------------------------------


def _state(**overrides) -> dict:
    s = make_initial_state(
        workflow_thread_id="thr_2_14",
        mission_id="mis_test",
        motivated_by_decision_id="dec_test",
    )
    s.update(overrides)
    return s


def test_dispatch_when_no_allowed_capabilities_dispatches_all():
    """Pre-2.14 behavior: empty / missing allowed_capabilities means no
    capability restriction — all tools dispatchable."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n1"}, "rationale": "r"},
        {"tool": "rka_create_mission", "args": {"objective": "g", "motivated_by_decision": "dec_t", "acceptance_criteria": ["a"]}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    add_calls = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    mission_calls = [c for c in mcp.calls if c["op"] == "rka_create_mission"]
    assert len(add_calls) == 1
    assert len(mission_calls) == 1
    assert "errors" not in update


def test_dispatch_with_allowed_capabilities_filters_out_others():
    """When state['allowed_capabilities']=['record_knowledge'], a
    rka_create_mission action (mission_lifecycle) gets blocked with a
    capability_not_allowed ErrorRecord."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = ["record_knowledge"]
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n1"}, "rationale": "r"},
        {"tool": "rka_create_mission", "args": {"objective": "g", "motivated_by_decision": "dec_t", "acceptance_criteria": ["a"]}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    # rka_add_note dispatched (record_knowledge in allowlist).
    assert any(c["op"] == "rka_add_note" for c in mcp.calls)
    # rka_create_mission blocked.
    assert all(c["op"] != "rka_create_mission" for c in mcp.calls)
    # ErrorRecord captures the capability mismatch.
    assert "errors" in update
    err = update["errors"][0]
    assert err["error_type"] == "ratified_action_capability_not_allowed"
    assert "mission_lifecycle" in err["detail"]
    assert "record_knowledge" in err["detail"]


def test_dispatch_with_multiple_allowed_capabilities():
    """Workflow allowed_capabilities is a list; tools belonging to any
    listed capability are dispatched."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = ["record_knowledge", "execution_gates"]
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n1"}, "rationale": "r"},
        {
            "tool": "rka_submit_checkpoint",
            "args": {"reason": "test", "type": "decision", "mission_id": "mis_t"},
            "rationale": "r",
        },
        {"tool": "rka_create_mission", "args": {"objective": "g", "motivated_by_decision": "dec_t", "acceptance_criteria": ["a"]}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)

    note_calls = [c for c in mcp.calls if c["op"] == "rka_add_note"]
    chk_calls = [c for c in mcp.calls if c["op"] == "rka_submit_checkpoint"]
    mission_calls = [c for c in mcp.calls if c["op"] == "rka_create_mission"]
    assert len(note_calls) == 1
    assert len(chk_calls) == 1
    assert len(mission_calls) == 0
    # One capability rejection ErrorRecord.
    assert len(update.get("errors") or []) == 1


def test_dispatch_with_empty_list_allowed_capabilities_dispatches_all():
    """An empty list is treated as 'no restriction' — pre-2.14 semantics
    preserved. (A truly locked-down workflow has to use the tools_for_
    capabilities helper at allowlist-build time, not state-level.)"""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = []  # empty → no restriction
    state["ratified_actions"] = [
        {"tool": "rka_create_mission", "args": {"objective": "g", "motivated_by_decision": "dec_t", "acceptance_criteria": ["a"]}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)
    assert any(c["op"] == "rka_create_mission" for c in mcp.calls)
    assert "errors" not in update


def test_dispatch_with_unknown_capability_in_state_is_inert():
    """A typo'd capability in allowed_capabilities just rejects all
    tools without crashing — the workflow proceeds and the ErrorRecord
    flags the issue."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = ["NOT_A_REAL_CAPABILITY"]
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n"}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)
    # Tool blocked because its capability (record_knowledge) is not in
    # the (unknown-only) allowlist.
    assert all(c["op"] != "rka_add_note" for c in mcp.calls)
    assert update["errors"][0]["error_type"] == "ratified_action_capability_not_allowed"


# ---------------------------------------------------------------------------
# Phase 2.14 adversarial-review M1 — malformed allowed_capabilities
# ---------------------------------------------------------------------------


def test_dispatch_with_string_allowed_capabilities_emits_malformed_error():
    """A string instead of a list (a common typo) used to silently
    degrade to per-character iteration. Now we surface an ErrorRecord
    and degrade to pre-2.14 (no restriction) behavior. The tools still
    dispatch so the workflow doesn't break — but the operator sees the
    typo in errors."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = "record_knowledge"  # typo: not a list
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n"}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)
    # Pre-2.14 fallback: tool still dispatched.
    assert any(c["op"] == "rka_add_note" for c in mcp.calls)
    # ErrorRecord surfaces the typo.
    error_types = [e["error_type"] for e in update.get("errors") or []]
    assert "ratified_action_capability_allowlist_malformed" in error_types


def test_dispatch_with_int_in_allowed_capabilities_emits_malformed_error():
    """A list containing non-string entries is also rejected."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = ["record_knowledge", 123]
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n"}, "rationale": "r"},
    ]

    update = executor.execute_ratified_actions(state, sdk, mcp)
    error_types = [e["error_type"] for e in update.get("errors") or []]
    assert "ratified_action_capability_allowlist_malformed" in error_types
    # Pre-2.14 fallback: tool dispatched.
    assert any(c["op"] == "rka_add_note" for c in mcp.calls)


def test_dispatch_with_set_allowed_capabilities_is_accepted():
    """sets and tuples are equally valid containers — coverage check."""
    mcp = FakeMCP()
    sdk = FakeSDK()
    state = _state()
    state["allowed_capabilities"] = {"record_knowledge"}
    state["ratified_actions"] = [
        {"tool": "rka_add_note", "args": {"content": "n"}, "rationale": "r"},
        {"tool": "rka_create_mission", "args": {"objective": "g", "motivated_by_decision": "dec_t", "acceptance_criteria": ["a"]}, "rationale": "r"},
    ]
    update = executor.execute_ratified_actions(state, sdk, mcp)
    assert any(c["op"] == "rka_add_note" for c in mcp.calls)
    assert all(c["op"] != "rka_create_mission" for c in mcp.calls)
    # No malformed-allowlist error.
    error_types = [e["error_type"] for e in update.get("errors") or []]
    assert "ratified_action_capability_allowlist_malformed" not in error_types
