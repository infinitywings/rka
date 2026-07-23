"""Runner segment + resume contract.

The Phase 2.4 v1 driver bug — returning "accept" for pi_greenlight,
which routes to escalation because graph.py checks `"approve" in response`
— is locked here at the runner contract level. The runner takes a typed
`action` (accept | reject | correct) and emits the type-correct token
internally; callers cannot supply a raw string that would mis-route.

The tests exercise the runner with a fake compiled-graph that records
inputs/resume tokens and emits scripted interrupts/terminals. The point
is to prove the contract surfaces, not to retest LangGraph itself.
"""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import (
    MissionNotFoundError,
    OrchestratorRunner,
    resume_token,
)


# ---------------------------------------------------------------------------
# resume_token — direct contract test
# ---------------------------------------------------------------------------


def test_resume_token_pi_greenlight_accept_returns_approve():
    # The exact bug from Phase 2.4 v1: callers expected "accept" to mean
    # "go ahead" for greenlight, but graph.py checks "approve in response".
    assert resume_token(interrupt_type="pi_greenlight", action="accept") == "approve"


def test_resume_token_pi_decision_select_accept_returns_accept():
    assert (
        resume_token(interrupt_type="pi_decision_select", action="accept") == "accept"
    )


def test_resume_token_pi_acceptance_accept_returns_accept():
    assert resume_token(interrupt_type="pi_acceptance", action="accept") == "accept"


def test_resume_token_reject_returns_literal_reject_for_all_types():
    for t in ("pi_greenlight", "pi_decision_select", "pi_acceptance"):
        assert resume_token(interrupt_type=t, action="reject") == "reject"


def test_resume_token_correct_prefixes_response_text_with_redirect_sentinel():
    """Phase D2 (post-review): action='correct' now prepends REDIRECT_SENTINEL
    so the routing functions can short-circuit on it before running the
    substring approve/accept check. Closes the substring-smuggling class bug
    where a PI correction like "I cannot approve" would route to accept."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL, is_redirect_token

    text = "redirect to plan B with these changes"
    out = resume_token(
        interrupt_type="pi_greenlight", action="correct", response_text=text
    )
    assert out == REDIRECT_SENTINEL + text
    assert is_redirect_token(out)
    # The original text is preserved as a suffix so the escalation_router
    # node can still read the PI's actual correction.
    assert out.endswith(text)


def test_resume_token_correct_requires_non_empty_text():
    with pytest.raises(ValueError, match="non-empty response_text"):
        resume_token(
            interrupt_type="pi_greenlight", action="correct", response_text=""
        )
    with pytest.raises(ValueError, match="non-empty response_text"):
        resume_token(
            interrupt_type="pi_greenlight", action="correct", response_text="   "
        )


def test_resume_token_rejects_unknown_interrupt_type():
    with pytest.raises(ValueError, match="unknown interrupt_type"):
        resume_token(interrupt_type="pi_bogus", action="accept")


def test_resume_token_rejects_unknown_action():
    with pytest.raises(ValueError, match="unknown action"):
        resume_token(interrupt_type="pi_greenlight", action="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Runner integration with a fake compiled graph
# ---------------------------------------------------------------------------


class _FakeInterrupt:
    """Mimics langgraph.types.Interrupt — only needs `.value`."""

    def __init__(self, value: Any):
        self.value = value


class _ScriptedGraph:
    """A 'compiled' graph that pops a scripted output per invoke() call.

    Records the (input_or_command, config) pairs so the test can assert the
    runner passed the right resume token.
    """

    def __init__(self, outputs: list[dict]):
        self.outputs = list(outputs)
        self.invocations: list[tuple[Any, dict]] = []

    def invoke(self, input_or_command: Any, config: dict) -> dict:
        self.invocations.append((input_or_command, config))
        if not self.outputs:
            raise AssertionError("ScriptedGraph: ran out of outputs")
        return self.outputs.pop(0)


class _FakeMCP:
    """Stub MCP client. Only `rka_get_mission` is exercised by the runner."""

    def __init__(self, mission: dict | None = None):
        self.mission = mission or {
            "id": "mis_test",
            "motivated_by_decision": "dec_test",
            "objective": "test mission",
        }

    def rka_get_mission(self, id: str | None = None) -> dict:
        if id != self.mission["id"]:
            return {}
        return self.mission


def _make_runner(
    store: ParkedStore,
    scripted: _ScriptedGraph,
    mission: dict | None = None,
) -> OrchestratorRunner:
    return OrchestratorRunner(
        store=store,
        sdk_factory=lambda project_id, _ws="": object(),
        mcp_factory=lambda thread_id, project_id: _FakeMCP(mission=mission),
        saver_factory=lambda thread_id: None,
        compile_factory=lambda **kwargs: scripted,
    )


@pytest.fixture
def store():
    s = ParkedStore(":memory:")
    yield s
    s.close()


def test_start_run_parks_first_interrupt(store: ParkedStore):
    scripted = _ScriptedGraph(
        [
            {
                "current_node": "pi_greenlight",
                "usd_spent": 0.12,
                "__interrupt__": [
                    _FakeInterrupt(
                        value={
                            "type": "pi_greenlight",
                            "title": "Approve brief?",
                            "items": [{"x": 1}],
                            "total_items": 1,
                        }
                    )
                ],
            }
        ]
    )
    runner = _make_runner(store, scripted)
    out = runner.start_run(
        mission_id="mis_test",
        project_id="prj_test",
    )
    assert out.parked_interrupt_id is not None
    assert out.parked_interrupt_type == "pi_greenlight"
    assert out.current_node == "pi_greenlight"
    assert out.usd_spent == 0.12
    parked = store.get_interrupt(out.parked_interrupt_id)
    assert parked["status"] == "pending"
    assert parked["payload"]["title"] == "Approve brief?"
    assert store.get_run(out.workflow_thread_id)["status"] == "awaiting_pi"


def test_start_run_terminal_complete(store: ParkedStore):
    scripted = _ScriptedGraph(
        [
            {
                "current_node": "pi_acceptance",
                "terminal_state": "complete",
                "final_report_id": "jrn_final",
                "usd_spent": 0.55,
            }
        ]
    )
    runner = _make_runner(store, scripted)
    out = runner.start_run(mission_id="mis_test", project_id="prj_test")
    assert out.terminal_state == "complete"
    assert out.final_report_id == "jrn_final"
    run = store.get_run(out.workflow_thread_id)
    assert run["status"] == "complete"
    assert run["final_report_id"] == "jrn_final"


def test_start_run_raises_mission_not_found(store: ParkedStore):
    scripted = _ScriptedGraph([])  # never invoked
    runner = _make_runner(store, scripted, mission={"id": "mis_other"})
    with pytest.raises(MissionNotFoundError):
        runner.start_run(mission_id="mis_missing", project_id="prj_test")


def test_respond_accept_pi_greenlight_resumes_with_approve_token(
    store: ParkedStore,
):
    """The Phase-2.4 v1 regression — locked here.

    If `accept` action on `pi_greenlight` resumed with the literal string
    "accept", the graph would route `"approve" in "accept"` = False →
    escalation_router → skip 7 nodes → no pi_decision_select. This test
    asserts the runner emits "approve" instead, preserving the happy path.
    """
    # Segment 1: park a pi_greenlight interrupt.
    seg1_output = {
        "current_node": "pi_greenlight",
        "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_greenlight", "items": [], "total_items": 0})
        ],
    }
    # Segment 2: resume, run to a terminal so the test can complete.
    seg2_output = {
        "current_node": "pi_acceptance",
        "terminal_state": "complete",
    }
    scripted = _ScriptedGraph([seg1_output, seg2_output])
    runner = _make_runner(store, scripted)

    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    out = runner.respond(
        interrupt_id=start.parked_interrupt_id, action="accept"
    )
    assert out.terminal_state == "complete"

    # Verify the resume token: scripted.invocations[1] is the resume call.
    assert len(scripted.invocations) == 2
    resume_input, _cfg = scripted.invocations[1]
    # Command(resume="approve") — extract the resume value.
    assert getattr(resume_input, "resume", None) == "approve"


def test_respond_accept_pi_decision_select_resumes_with_accept_token(
    store: ParkedStore,
):
    seg1 = {
        "current_node": "pi_decision_select",
        "__interrupt__": [
            _FakeInterrupt(
                value={"type": "pi_decision_select", "items": [], "total_items": 0}
            )
        ],
    }
    seg2 = {"terminal_state": "complete"}
    scripted = _ScriptedGraph([seg1, seg2])
    runner = _make_runner(store, scripted)
    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    runner.respond(interrupt_id=start.parked_interrupt_id, action="accept")
    resume_input, _ = scripted.invocations[1]
    assert resume_input.resume == "accept"


def test_respond_reject_resumes_with_literal_reject(store: ParkedStore):
    seg1 = {
        "current_node": "pi_greenlight",
        "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_greenlight", "items": [], "total_items": 0})
        ],
    }
    seg2 = {"terminal_state": "escalated"}
    scripted = _ScriptedGraph([seg1, seg2])
    runner = _make_runner(store, scripted)
    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    out = runner.respond(interrupt_id=start.parked_interrupt_id, action="reject")
    assert out.terminal_state == "escalated"
    resume_input, _ = scripted.invocations[1]
    assert resume_input.resume == "reject"


def test_respond_correct_resumes_with_freeform_text(store: ParkedStore):
    seg1 = {
        "current_node": "pi_decision_select",
        "__interrupt__": [
            _FakeInterrupt(
                value={"type": "pi_decision_select", "items": [], "total_items": 0}
            )
        ],
    }
    seg2 = {"terminal_state": "escalated"}
    scripted = _ScriptedGraph([seg1, seg2])
    runner = _make_runner(store, scripted)
    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    correction = "use option C instead, and re-run cluster_review first"
    runner.respond(
        interrupt_id=start.parked_interrupt_id,
        action="correct",
        response_text=correction,
    )
    resume_input, _ = scripted.invocations[1]
    # Phase D2 (post-review): action='correct' prepends REDIRECT_SENTINEL.
    # The graph routes on the sentinel before reading the substring.
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    assert resume_input.resume == REDIRECT_SENTINEL + correction


def test_respond_rejects_double_answer(store: ParkedStore):
    seg1 = {
        "current_node": "pi_greenlight",
        "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_greenlight", "items": [], "total_items": 0})
        ],
    }
    seg2 = {"terminal_state": "complete"}
    scripted = _ScriptedGraph([seg1, seg2])
    runner = _make_runner(store, scripted)
    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    runner.respond(interrupt_id=start.parked_interrupt_id, action="accept")
    with pytest.raises(ValueError, match="already in status"):
        runner.respond(interrupt_id=start.parked_interrupt_id, action="accept")


def test_respond_unknown_interrupt_id_raises(store: ParkedStore):
    runner = _make_runner(store, _ScriptedGraph([]))
    with pytest.raises(ValueError, match="not found"):
        runner.respond(interrupt_id="int_bogus", action="accept")


def test_segment_chain_two_interrupts(store: ParkedStore):
    """Verify the runner correctly handles back-to-back interrupts:
    start → park greenlight → respond accept → park decision_select →
    respond accept → terminal."""
    seg1 = {
        "current_node": "pi_greenlight",
        "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_greenlight", "items": [], "total_items": 0})
        ],
    }
    seg2 = {
        "current_node": "pi_decision_select",
        "__interrupt__": [
            _FakeInterrupt(
                value={"type": "pi_decision_select", "items": [{"x": 1}], "total_items": 1}
            )
        ],
    }
    seg3 = {"terminal_state": "complete", "final_report_id": "jrn_final"}
    scripted = _ScriptedGraph([seg1, seg2, seg3])
    runner = _make_runner(store, scripted)

    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    assert start.parked_interrupt_type == "pi_greenlight"

    second = runner.respond(
        interrupt_id=start.parked_interrupt_id, action="accept"
    )
    assert second.parked_interrupt_type == "pi_decision_select"

    final = runner.respond(
        interrupt_id=second.parked_interrupt_id, action="accept"
    )
    assert final.terminal_state == "complete"
    assert final.final_report_id == "jrn_final"

    # Resume tokens, in order:
    tokens = [scripted.invocations[i][0].resume for i in (1, 2)]
    assert tokens == ["approve", "accept"]


def test_cancel_marks_pending_cancelled(store: ParkedStore):
    seg1 = {
        "current_node": "pi_greenlight",
        "__interrupt__": [
            _FakeInterrupt(value={"type": "pi_greenlight", "items": [], "total_items": 0})
        ],
    }
    scripted = _ScriptedGraph([seg1])
    runner = _make_runner(store, scripted)
    start = runner.start_run(mission_id="mis_test", project_id="prj_test")
    count = runner.cancel(start.workflow_thread_id)
    assert count == 1
    run = store.get_run(start.workflow_thread_id)
    assert run["status"] == "cancelled"


def test_graph_exception_marks_run_failed(store: ParkedStore):
    class _BrokenGraph:
        def invoke(self, *a, **kw):
            raise RuntimeError("simulated SDK failure")

    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda p, _ws="": object(),
        mcp_factory=lambda t, p: _FakeMCP(),
        saver_factory=lambda t: None,
        compile_factory=lambda **kw: _BrokenGraph(),
    )
    out = runner.start_run(mission_id="mis_test", project_id="prj_test")
    assert out.terminal_state == "failed"
    run = store.get_run(out.workflow_thread_id)
    assert run["status"] == "failed"
    assert "simulated SDK failure" in (run.get("last_error") or "")


# ---------------------------------------------------------------------------
# Phase-D5a — onboarding interrupt response-token contracts
# ---------------------------------------------------------------------------


def test_resume_token_pi_onboarding_topic_accept_returns_approve():
    """pi_onboarding_topic is greenlight-class — accept emits 'approve'
    (caller MUST NOT supply a raw string)."""
    assert resume_token(
        interrupt_type="pi_onboarding_topic", action="accept"
    ) == "approve"


def test_resume_token_pi_toolkit_ratify_accept_returns_accept():
    """pi_toolkit_ratify is set-identity ratification — like
    pi_decision_select — so accept emits 'accept'."""
    assert resume_token(
        interrupt_type="pi_toolkit_ratify", action="accept"
    ) == "accept"


def test_resume_token_pi_credentials_ready_accept_returns_accept():
    assert resume_token(
        interrupt_type="pi_credentials_ready", action="accept"
    ) == "accept"


def test_resume_token_pi_extend_toolkit_is_no_longer_registered():
    """Phase E3 cleanup: pi_extend_toolkit was a half-built D6 placeholder
    registered in _ACCEPT_TOKEN_BY_TYPE / _ONBOARDING_INTERRUPT_TYPES /
    parked_store.InterruptType but never had a node or graph wiring.
    Removed to prevent the registry from drifting from the running graph.
    When D6 ships, re-add with full wiring in one PR."""
    with pytest.raises(ValueError, match="unknown interrupt_type"):
        resume_token(interrupt_type="pi_extend_toolkit", action="accept")


def test_resume_token_onboarding_reject_returns_literal_reject():
    for t in (
        "pi_onboarding_topic",
        "pi_toolkit_ratify",
        "pi_credentials_ready",
    ):
        assert resume_token(interrupt_type=t, action="reject") == "reject"


def test_resume_token_onboarding_correct_prefixes_redirect_sentinel():
    """Phase D2: onboarding interrupts also get REDIRECT_SENTINEL on
    action='correct' — same sentinel contract as the mission graph, so the
    onboarding routing helpers can short-circuit before substring match."""
    from orchestrator.response_tokens import REDIRECT_SENTINEL

    text = "use these tools instead: rka, context7 only"
    out = resume_token(
        interrupt_type="pi_toolkit_ratify", action="correct", response_text=text
    )
    assert out == REDIRECT_SENTINEL + text


# ---------------------------------------------------------------------------
# Phase D2 (post-review) — REDIRECT_SENTINEL routing tests
#
# Closes the substring-routing-smuggling class bug surfaced by the
# code review: a PI correction text containing the words "approve" or
# "accept" must NOT route through the accept branch.
# ---------------------------------------------------------------------------


def test_redirect_sentinel_makes_is_redirect_token_true():
    from orchestrator.response_tokens import REDIRECT_SENTINEL, is_redirect_token

    assert is_redirect_token(REDIRECT_SENTINEL + "anything")
    assert is_redirect_token(REDIRECT_SENTINEL + "I cannot approve this")
    # Bare accept/approve tokens (action='accept' path) do NOT carry sentinel
    assert not is_redirect_token("approve")
    assert not is_redirect_token("accept")
    assert not is_redirect_token("reject")
    assert not is_redirect_token("")
    assert not is_redirect_token(None)
    # Case-insensitive (graph._latest_interrupt_response lowercases first)
    assert is_redirect_token((REDIRECT_SENTINEL + "x").lower())
    # Leading whitespace tolerated
    assert is_redirect_token("  " + REDIRECT_SENTINEL + "x")


def test_route_after_pi_greenlight_short_circuits_on_redirect_sentinel():
    """Phase-X² + Phase D2.1: substring-smuggling guard still fires
    FIRST, AND the new destination is the in-run redraft node (not
    escalation_router, which was the pre-Phase-X² dead-end).

    PI correction "I cannot approve" — REDIRECT_SENTINEL-prefixed at
    the runner layer — must (a) NOT match the 'approve' substring →
    backbrief_draft (smuggling), AND (b) route to
    confirmation_brief_redraft so Brain redrafts the brief
    incorporating the PI's correction. Pre-Phase-X² this routed to
    escalation_router (the bug); the loopback is the fix."""
    from orchestrator.graph import _route_after_pi_greenlight
    from orchestrator.response_tokens import REDIRECT_SENTINEL

    # Adversarial: correction text contains "approve" verbatim
    state = {
        "interrupts": [
            {"response": REDIRECT_SENTINEL + "I cannot approve this — redo"}
        ]
    }
    assert (
        _route_after_pi_greenlight(state) == "confirmation_brief_redraft"
    )

    # Plain accept path still routes to backbrief_draft
    state_accept = {"interrupts": [{"response": "approve"}]}
    assert _route_after_pi_greenlight(state_accept) == "backbrief_draft"

    # Plain reject path (no sentinel, no 'approve' substring) still
    # escalates — preserving the genuine hard-reject semantic.
    state_reject = {"interrupts": [{"response": "reject this brief"}]}
    assert _route_after_pi_greenlight(state_reject) == "escalation_router"


def test_route_after_pi_decision_short_circuits_on_redirect_sentinel():
    """Adversarial: PI correction "do not accept this — redo the plan"
    must NOT route through execute_ratified_actions (which would dispatch
    the WRITE_TOOLS the PI is rejecting). v0.6.11 — a `correct` now routes
    to the in-run redraft node (mission_redraft) rather than dead-ending at
    escalation_router; the sentinel guard still prevents the "accept"
    substring from smuggling through to execute_ratified_actions."""
    from orchestrator.graph import _route_after_pi_decision
    from orchestrator.response_tokens import REDIRECT_SENTINEL

    state = {
        "interrupts": [
            {"response": REDIRECT_SENTINEL + "do not accept this — redo"}
        ]
    }
    route = _route_after_pi_decision(state)
    assert route == "mission_redraft"
    assert route != "execute_ratified_actions"

    state_accept = {"interrupts": [{"response": "accept"}]}
    assert _route_after_pi_decision(state_accept) == "execute_ratified_actions"


def test_route_after_credentials_ready_short_circuits_on_redirect_sentinel():
    from orchestrator.onboarding_graph import _route_after_credentials_ready
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    from langgraph.graph import END

    state = {
        "interrupts": [
            {"response": REDIRECT_SENTINEL + "accept the manifest but fix typos"}
        ]
    }
    assert _route_after_credentials_ready(state) == END

    state_accept = {"interrupts": [{"response": "accept"}]}
    assert _route_after_credentials_ready(state_accept) == "finalize"


def test_route_after_fill_ack_short_circuits_on_redirect_sentinel():
    from orchestrator.phase_b_graph import _route_after_fill_ack
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    from langgraph.graph import END

    state = {
        "interrupts": [
            {
                "node_name": "pi_bootstrap_fill_ack",
                "response": REDIRECT_SENTINEL + "approve once you reconfirm",
            }
        ]
    }
    assert _route_after_fill_ack(state) == END

    state_accept = {
        "interrupts": [
            {"node_name": "pi_bootstrap_fill_ack", "response": "accept"}
        ]
    }
    assert _route_after_fill_ack(state_accept) == "bootstrap_verify"


# ---------------------------------------------------------------------------
# budget_usd -> state["cap_usd"] threading (daemon gold; completes cap_usd channel)
# ---------------------------------------------------------------------------


def test_start_run_threads_budget_usd_to_cap_usd(store: ParkedStore):
    """Regression (2026-06-15): orchestrator_run_start(budget_usd=...) was a
    NO-OP for the runtime cap — start_run_drive never threaded the run's
    budget_usd into state['cap_usd'], so budget_check used DEFAULT_BUDGET_USD
    (5.0) and an expensive run escalated before the pivot. The run's budget_usd
    must reach the budget_check cap."""
    scripted = _ScriptedGraph(
        [{"current_node": "pi_acceptance", "terminal_state": "complete", "usd_spent": 0.1}]
    )
    runner = _make_runner(store, scripted)
    runner.start_run(mission_id="mis_test", project_id="prj_test", budget_usd=42.0)
    initial = scripted.invocations[0][0]
    assert initial["cap_usd"] == 42.0


def test_start_run_default_cap_usd_when_budget_unset(store: ParkedStore):
    """Default budget_usd (5.0) flows to cap_usd — prior behavior preserved."""
    scripted = _ScriptedGraph(
        [{"current_node": "pi_acceptance", "terminal_state": "complete", "usd_spent": 0.1}]
    )
    runner = _make_runner(store, scripted)
    runner.start_run(mission_id="mis_test", project_id="prj_test")
    initial = scripted.invocations[0][0]
    assert initial["cap_usd"] == 5.0
