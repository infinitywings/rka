"""v0.6.11 — pi_decision_select in-run redraft (mission_redraft node).

When the PI sends a `correct` action at the pi_decision_select TWO-TAP
gate, the run previously dead-ended at escalation_router (synthesizing an
unclassified checkpoint and dropping the correction in-run). Now it routes
to `mission_redraft`, which revises proposed_actions via one LLM call and
re-renders decision_present for re-ratification, bounded by
MAX_DECISION_REDRAFTS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from orchestrator.nodes import executor
from orchestrator.response_tokens import REDIRECT_SENTINEL
from orchestrator.state import MAX_DECISION_REDRAFTS, make_initial_state
from orchestrator import graph as graph_mod
from tests._fakes import FakeMCP


@dataclass
class _ScriptedSDK:
    """SDK fake whose complete() returns a canned reply carrying a
    proposed_actions JSON block."""

    reply: str = '{"proposed_actions": []}'
    last_call_cost_usd: float = 0.0
    calls: list[dict] = field(default_factory=list)

    def complete(self, prompt, *, max_tokens=4096, system=None, timeout_s=None):
        self.calls.append({"prompt": prompt, "system": system, "timeout_s": timeout_s})
        return self.reply


def _initial_state() -> dict:
    return make_initial_state(
        workflow_thread_id="thr_t", mission_id="mis_t",
        motivated_by_decision_id="dec_t",
    )


def _decision_interrupt_record(text: str, *, ts="2026-06-05T00:00:00.000Z") -> dict:
    return {
        "node_name": "pi_decision_select",
        "payload_size": 1,
        "response": REDIRECT_SENTINEL + text,
        "timestamp": ts,
        "batch_review_used": False,
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_route_after_pi_decision_correct_goes_to_mission_redraft():
    state = _initial_state()
    state["interrupts"] = [_decision_interrupt_record("use rka_update_note not add")]
    assert graph_mod._route_after_pi_decision(state) == "mission_redraft"


def test_route_after_pi_decision_accept_goes_to_execute():
    state = _initial_state()
    state["interrupts"] = [{
        "node_name": "pi_decision_select", "response": "accept",
        "timestamp": "t", "payload_size": 1, "batch_review_used": False,
    }]
    assert graph_mod._route_after_pi_decision(state) == "execute_ratified_actions"


def test_route_after_pi_decision_reject_escalates():
    state = _initial_state()
    state["interrupts"] = [{
        "node_name": "pi_decision_select", "response": "reject",
        "timestamp": "t", "payload_size": 1, "batch_review_used": False,
    }]
    assert graph_mod._route_after_pi_decision(state) == "escalation_router"


def test_route_after_pi_decision_correct_with_accept_substring_not_smuggled():
    """A correction containing 'accept' must still route to redraft (sentinel
    short-circuit), NOT bypass to execute_ratified_actions."""
    state = _initial_state()
    state["interrupts"] = [
        _decision_interrupt_record("do not accept this — revise the writes")
    ]
    assert graph_mod._route_after_pi_decision(state) == "mission_redraft"


def test_route_after_mission_redraft_happy_goes_to_decision_present():
    state = _initial_state()
    state["next_node_override"] = ""
    assert graph_mod._route_after_mission_redraft(state) == "decision_present"


def test_route_after_mission_redraft_override_escalates():
    state = _initial_state()
    state["next_node_override"] = "escalation_router"
    assert graph_mod._route_after_mission_redraft(state) == "escalation_router"


# ---------------------------------------------------------------------------
# mission_redraft node
# ---------------------------------------------------------------------------


def test_mission_redraft_revises_proposed_actions():
    state = _initial_state()
    state["interrupts"] = [_decision_interrupt_record("use rka_update_note")]
    state["proposed_actions"] = [{"tool": "rka_add_note", "args": {"content": "x"}}]
    state["decision_redrafts"] = 0

    revised = '{"proposed_actions": [{"tool": "rka_update_note", "args": {"id": "jrn_1"}}]}'
    sdk = _ScriptedSDK(reply=revised)
    update = executor.mission_redraft(state, sdk, FakeMCP())

    assert update["current_node"] == "mission_redraft"
    assert update["decision_redrafts"] == 1
    assert update["next_node_override"] == ""
    # The parser may normalize each action (e.g. add a default rationale);
    # assert the load-bearing fields rather than exact dict equality.
    assert len(update["proposed_actions"]) == 1
    revised_action = update["proposed_actions"][0]
    assert revised_action["tool"] == "rka_update_note"
    assert revised_action["args"] == {"id": "jrn_1"}
    # The correction text reached the prompt.
    assert "use rka_update_note" in sdk.calls[0]["prompt"]
    # Tool-use timeout budget used.
    from orchestrator.llm_client import SDK_TIMEOUT_TOOL_USE_S
    assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_TOOL_USE_S


def test_mission_redraft_budget_exceeded_emits_classified_error():
    state = _initial_state()
    state["interrupts"] = [_decision_interrupt_record("again")]
    state["decision_redrafts"] = MAX_DECISION_REDRAFTS  # next would exceed

    update = executor.mission_redraft(state, _ScriptedSDK(), FakeMCP())

    assert update["next_node_override"] == "escalation_router"
    errs = update["errors"]
    assert len(errs) == 1
    assert errs[0]["error_type"] == "decision_redraft_budget_exceeded"
    assert errs[0]["node_name"] == "mission_redraft"


def test_mission_redraft_missing_redirect_emits_classified_error():
    state = _initial_state()
    state["interrupts"] = []  # no redirect record

    update = executor.mission_redraft(state, _ScriptedSDK(), FakeMCP())

    assert update["next_node_override"] == "escalation_router"
    assert update["errors"][0]["error_type"] == "decision_redirect_text_missing"


def test_mission_redraft_empty_redirect_text_emits_classified_error():
    state = _initial_state()
    # Sentinel with no usable text after strip.
    state["interrupts"] = [_decision_interrupt_record("")]

    update = executor.mission_redraft(state, _ScriptedSDK(), FakeMCP())

    assert update["next_node_override"] == "escalation_router"
    assert update["errors"][0]["error_type"] == "decision_redirect_text_empty"


def test_mission_redraft_only_reads_decision_gate_redirects():
    """A redirect at pi_greenlight must NOT be consumed by mission_redraft —
    node_name filtering prevents cross-gate leakage."""
    state = _initial_state()
    state["interrupts"] = [{
        "node_name": "pi_greenlight",
        "response": REDIRECT_SENTINEL + "greenlight correction",
        "timestamp": "t", "payload_size": 1, "batch_review_used": False,
    }]
    update = executor.mission_redraft(state, _ScriptedSDK(), FakeMCP())
    # No pi_decision_select redirect → missing-text classified error.
    assert update["errors"][0]["error_type"] == "decision_redirect_text_missing"


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------


def test_mission_redraft_in_node_names():
    assert "mission_redraft" in graph_mod.NODE_NAMES
    # Executor band grew to 6.
    assert graph_mod.NODE_NAMES.count("mission_redraft") == 1
