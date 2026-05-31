"""Unit tests for the 3 PI interrupt nodes (T5).

Each test injects a `FakeInterrupt` callable that records the payload
handed to it and returns a canned PI response. This lets tests verify
the exact shape of the payload (including obs #15 batch-review metadata)
without spinning up a LangGraph runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from orchestrator.nodes import pi
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


@dataclass
class FakeInterrupt:
    """Callable double for `langgraph.types.interrupt`."""

    canned_response: Any = "approve"
    captured_payloads: list[dict] = field(default_factory=list)

    def __call__(self, payload: dict) -> Any:
        self.captured_payloads.append(payload)
        return self.canned_response


def _state() -> dict:
    return make_initial_state(
        workflow_thread_id="thr_t5",
        mission_id="mis_t5",
        motivated_by_decision_id="dec_t5",
    )


# ---------------------------------------------------------------------------
# 1. pi_greenlight
# ---------------------------------------------------------------------------


def test_pi_greenlight_records_interrupt_event():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="approve")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": "brief X", "options": ["approve", "redirect"]}
    ]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)

    assert update["current_phase"] == "pi_greenlight"
    assert update["current_node"] == "pi_greenlight"
    assert len(update["interrupts"]) == 1
    rec = update["interrupts"][0]
    assert rec["node_name"] == "pi_greenlight"
    assert rec["response"] == "approve"
    assert rec["payload_size"] == 1
    assert rec["batch_review_used"] is False


def test_pi_greenlight_clears_consumed_confirmation_briefs():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": "C1"},
        {"source_node": "decision_present", "context": "D1"},
    ]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)
    # confirmation_brief item consumed; decision_present item remains.
    assert len(update["decisions_to_present"]) == 1
    assert update["decisions_to_present"][0]["source_node"] == "decision_present"


def test_pi_greenlight_payload_contains_title():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [{"source_node": "confirmation_brief", "context": "x"}]

    pi.pi_greenlight(state, sdk, mcp, interrupt_fn)
    captured = interrupt_fn.captured_payloads[0]
    assert captured["title"].startswith("PI approval")
    assert captured["type"] == "pi_greenlight"


def test_pi_greenlight_approve_copies_proposed_capabilities_to_allowed():
    """Phase-X² latent-bug fix at nodes/pi.py:115.

    pi_greenlight's accept token is 'approve' (per
    _ACCEPT_TOKEN_BY_TYPE in runner.py); the original is_accept check
    tested for the 'accept' substring, which is NOT contained in
    'approve' — so the proposed_capabilities → allowed_capabilities
    plumbing silently never fired. Pin the fix: on a literal 'approve'
    response, the proposed_capabilities from strategy_node MUST be
    copied to allowed_capabilities. Sentinel guard still short-circuits
    any approve-smuggling correct token (separate test below)."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="approve")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": "brief"}
    ]
    state["proposed_capabilities"] = ["record_knowledge", "execution_gates"]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)

    assert update.get("allowed_capabilities") == [
        "record_knowledge",
        "execution_gates",
    ]


def test_pi_greenlight_accept_substring_also_copies_capabilities():
    """Symmetric guard: 'accept' substring (used at other pi_* gates
    via copy-paste) ALSO triggers the plumbing — the fix accepts
    either token to stay forward-compatible."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": "brief"}
    ]
    state["proposed_capabilities"] = ["mission_lifecycle"]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)

    assert update.get("allowed_capabilities") == ["mission_lifecycle"]


def test_pi_greenlight_sentinel_redirect_does_not_copy_capabilities():
    """Adversarial: REDIRECT_SENTINEL-prefixed body containing 'approve'
    as a substring (e.g. 'I cannot approve this — redo') must NOT
    trigger the plumbing. is_redirect_token short-circuits BEFORE the
    substring check, so the smuggled 'approve' has no effect."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL

    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(
        canned_response=REDIRECT_SENTINEL + "I cannot approve this — redo"
    )
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": "brief"}
    ]
    state["proposed_capabilities"] = ["record_knowledge"]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)

    # No allowed_capabilities write — the redirect is not an accept.
    assert "allowed_capabilities" not in update


def test_pi_greenlight_reject_does_not_copy_capabilities():
    """Plain reject (no sentinel, no 'accept'/'approve' substring) must
    NOT copy capabilities."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="reject this brief")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": "brief"}
    ]
    state["proposed_capabilities"] = ["record_knowledge"]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)

    assert "allowed_capabilities" not in update


# ---------------------------------------------------------------------------
# 2. pi_decision_select
# ---------------------------------------------------------------------------


def test_pi_decision_select_creates_decision_on_accept():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["decisions_to_present"] = [
        {
            "source_node": "decision_present",
            "context": "decision content",
            "source_artifact": "jrn_source_001",
        }
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn)

    assert update["current_phase"] == "pi_decision"
    decision_calls = [c for c in mcp.calls if c["op"] == "rka_add_decision"]
    assert len(decision_calls) == 1
    assert decision_calls[0]["related_journal"] == ["jrn_source_001"]
    assert "pi-accepted" in decision_calls[0]["tags"]
    # The new decision lands as an artifact.
    decision_artifact = next(a for a in update["artifacts"] if a["entity_type"] == "decision")
    assert decision_artifact["rka_id"].startswith("dec_")


def test_pi_decision_select_does_not_create_decision_on_reject():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="reject")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": "c"}
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn)
    assert not any(c["op"] == "rka_add_decision" for c in mcp.calls)
    assert "artifacts" not in update or all(
        a["entity_type"] != "decision" for a in update.get("artifacts", [])
    )


def test_pi_decision_select_clears_consumed_decisions():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": "D1"},
        {"source_node": "confirmation_brief", "context": "C1"},
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn)
    assert len(update["decisions_to_present"]) == 1
    assert update["decisions_to_present"][0]["source_node"] == "confirmation_brief"


# ---------------------------------------------------------------------------
# 3. pi_acceptance
# ---------------------------------------------------------------------------


def test_pi_acceptance_sets_terminal_complete_on_accept():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["final_report_id"] = "rep_xyz"

    update = pi.pi_acceptance(state, sdk, mcp, interrupt_fn)
    assert update["terminal_state"] == "complete"


def test_pi_acceptance_sets_terminal_escalated_on_reject():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="reject")
    state = _state()
    state["final_report_id"] = "rep_xyz"

    update = pi.pi_acceptance(state, sdk, mcp, interrupt_fn)
    assert update["terminal_state"] == "escalated"


def test_pi_acceptance_payload_includes_run_digest():
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["final_report_id"] = "rep_abc"
    state["artifacts"] = [{"rka_id": "jrn_1"}, {"rka_id": "jrn_2"}]
    state["interrupts"] = [{"node_name": "pi_greenlight"}]
    state["usd_spent"] = 2.50

    pi.pi_acceptance(state, sdk, mcp, interrupt_fn)
    payload = interrupt_fn.captured_payloads[0]
    digest = payload["items"][0]
    assert digest["final_report_id"] == "rep_abc"
    assert digest["artifact_count"] == 2
    assert digest["interrupt_count"] == 1
    assert digest["usd_spent"] == 2.50


# ---------------------------------------------------------------------------
# Obs #15 — batch-review affordance
# ---------------------------------------------------------------------------


def test_pi_decision_select_does_not_batch_at_threshold_minus_one():
    # Threshold = 10; 10 items should NOT trigger batched mode (only >).
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": f"c{i}"} for i in range(10)
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn)
    assert update["batch_review_active"] is False
    assert update["interrupts"][0]["batch_review_used"] is False
    payload = interrupt_fn.captured_payloads[0]
    assert "batched" not in payload


def test_pi_decision_select_batches_above_threshold():
    # 11 items → batched, page_size = threshold (10).
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": f"c{i}"} for i in range(11)
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn)
    assert update["batch_review_active"] is True
    assert update["batch_review_payload_size"] == 11
    assert update["interrupts"][0]["batch_review_used"] is True
    payload = interrupt_fn.captured_payloads[0]
    assert payload["batched"] is True
    assert payload["page_size"] == 10
    assert payload["total_items"] == 11


def test_pi_greenlight_batches_at_15_items():
    # Confirmation Brief queue ballooning is unusual but possible if
    # multiple confirmation_brief invocations stack without consumption.
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "confirmation_brief", "context": f"c{i}"} for i in range(15)
    ]

    update = pi.pi_greenlight(state, sdk, mcp, interrupt_fn)
    assert update["interrupts"][0]["batch_review_used"] is True
    assert update["interrupts"][0]["payload_size"] == 15


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [pi.pi_greenlight, pi.pi_decision_select, pi.pi_acceptance],
)
def test_every_pi_node_records_a_single_interrupt(fn):
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt()
    state = _state()
    state["decisions_to_present"] = [{"source_node": "confirmation_brief", "context": "x"}]

    update = fn(state, sdk, mcp, interrupt_fn)
    assert len(update["interrupts"]) == 1


def test_pi_threshold_constant_is_ten():
    # Locked by the upfront-Backbrief design; obs #15 floor.
    assert pi.PI_BATCH_REVIEW_THRESHOLD == 10


# ---------------------------------------------------------------------------
# Phase 2.7 T3d — pi_decision_select copies proposed_actions → ratified_actions
# (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R; PI-ratified per jrn_01KRXP96THHEAKCGB0P0KGV7Y9)
# ---------------------------------------------------------------------------


def test_pi_decision_select_copies_proposed_to_ratified_on_accept():
    """When PI says 'accept', the state["proposed_actions"] list (populated
    by mission_execute) gets copied into state["ratified_actions"] so the
    downstream execute_ratified_actions node will iterate + dispatch them."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": "decision draft", "source_artifact": "jrn_x"},
    ]
    state["proposed_actions"] = [
        {"tool": "rka_update_note", "args": {"id": "jrn_target"}, "rationale": "r1"},
        {"tool": "rka_add_note", "args": {"content": "probe"}, "rationale": "r2"},
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn=interrupt_fn)

    assert update["ratified_actions"] == state["proposed_actions"]
    assert len(update["ratified_actions"]) == 2


def test_pi_decision_select_clears_ratified_on_reject():
    """On reject, no actions get ratified — the field is set to []
    explicitly so a prior workflow's value can't leak through."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="reject")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": "x", "source_artifact": "jrn_x"},
    ]
    state["proposed_actions"] = [
        {"tool": "rka_update_note", "args": {"id": "jrn_target"}, "rationale": "r"},
    ]

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn=interrupt_fn)

    assert update["ratified_actions"] == []


# ---------------------------------------------------------------------------
# Phase 2.9 T4 — pi_acceptance summary no longer leaks gate1 verdict text
# (mis_01KRY2KP0GGZY21BA4Z2R2S718; cosmetic anomaly from Phase 2.8)
# ---------------------------------------------------------------------------


def test_pi_acceptance_summary_does_not_leak_gate1_verdict():
    """Phase 2.9 T4: Phase 2.8 surfaced that `pi_acceptance.summary` was
    sourced from `state["brain_position"]` which (in the happy path) is
    gate1_validation's last write — the verdict text "APPROVED:" or
    "REDIRECTED:". This was misleading: described the gate1 verdict, not
    the mission outcome.

    Fix: `_compose_acceptance_summary(state)` builds a structured summary
    from counts + escalation signal; no longer reads brain_position."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    # Simulate the Phase 2.8 setup: gate1 wrote "APPROVED:" to brain_position.
    state["brain_position"] = "APPROVED:"
    state["final_report_id"] = "mis_target_01ABC"
    state["artifacts"] = [
        {"rka_id": "jrn_a", "entity_type": "journal", "node_name": "n1"},
        {"rka_id": "jrn_b", "entity_type": "journal", "node_name": "n2"},
    ]

    update = pi.pi_acceptance(state, sdk, mcp, interrupt_fn=interrupt_fn)

    # The payload presented to PI must NOT contain the gate1 verdict text.
    payload = interrupt_fn.captured_payloads[0]
    items = payload["items"]
    summary = items[0]["summary"]
    assert "APPROVED:" not in summary, (
        f"Phase 2.9 T4: pi_acceptance summary leaked gate1 verdict text "
        f"({summary!r}); should be a composed summary from counts."
    )
    # Sanity: the new composed summary mentions the actual signal.
    assert "mis_target_01ABC" in summary
    assert "2 artifacts" in summary


def test_pi_acceptance_summary_reflects_error_count_when_present():
    """T4 follow-up: when errors are present, the composed summary
    leads with the error count (matches Phase 2.5 Delta #14b's
    'divergence-as-headline' discipline at the report-submission layer
    — same principle applied to acceptance summary)."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["brain_position"] = "APPROVED:"  # legacy field; should NOT be used
    state["errors"] = [
        {"node_name": "mission_execute", "error_type": "test_error", "detail": "x"}
    ]
    state["artifacts"] = [{"rka_id": "jrn_a", "entity_type": "journal", "node_name": "n1"}]

    pi.pi_acceptance(state, sdk, mcp, interrupt_fn=interrupt_fn)

    payload = interrupt_fn.captured_payloads[0]
    summary = payload["items"][0]["summary"]
    assert "error" in summary.lower()
    assert "APPROVED:" not in summary


def test_pi_acceptance_summary_reflects_escalation_when_checkpoints_raised():
    """T4 follow-up: escalation path produces a summary that mentions
    the checkpoint(s), not the gate1 verdict."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["brain_position"] = "APPROVED:"  # legacy field; should NOT be used
    state["checkpoints"] = [
        {"chk_id": "chk_test", "type": "decision", "reason": "test"}
    ]

    pi.pi_acceptance(state, sdk, mcp, interrupt_fn=interrupt_fn)

    payload = interrupt_fn.captured_payloads[0]
    summary = payload["items"][0]["summary"]
    assert "escalat" in summary.lower() or "checkpoint" in summary.lower()
    assert "APPROVED:" not in summary


def test_pi_decision_select_empty_proposed_actions_passes_through_on_accept():
    """When mission_execute produced no proposed_actions (LLM emitted
    proposed_actions=[] explicitly, OR parse failed), the accept path
    still works — ratified_actions is just []."""
    sdk = FakeSDK()
    mcp = FakeMCP()
    interrupt_fn = FakeInterrupt(canned_response="accept")
    state = _state()
    state["decisions_to_present"] = [
        {"source_node": "decision_present", "context": "x", "source_artifact": "jrn_x"},
    ]
    # proposed_actions deliberately absent.

    update = pi.pi_decision_select(state, sdk, mcp, interrupt_fn=interrupt_fn)

    assert update["ratified_actions"] == []
