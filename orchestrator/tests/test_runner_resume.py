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


def test_resume_token_correct_returns_response_text_verbatim():
    text = "redirect to plan B with these changes"
    out = resume_token(
        interrupt_type="pi_greenlight", action="correct", response_text=text
    )
    assert out == text


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
        sdk_factory=lambda project_id: object(),
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
    assert resume_input.resume == correction


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
        sdk_factory=lambda p: object(),
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


def test_resume_token_pi_extend_toolkit_accept_returns_accept():
    """pi_extend_toolkit (Phase D6) is set-identity ratification of a
    mid-stream tool extension. Same token semantics as pi_toolkit_ratify."""
    assert resume_token(
        interrupt_type="pi_extend_toolkit", action="accept"
    ) == "accept"


def test_resume_token_onboarding_reject_returns_literal_reject():
    for t in (
        "pi_onboarding_topic",
        "pi_toolkit_ratify",
        "pi_credentials_ready",
        "pi_extend_toolkit",
    ):
        assert resume_token(interrupt_type=t, action="reject") == "reject"


def test_resume_token_onboarding_correct_returns_freeform_text():
    text = "use these tools instead: rka, context7 only"
    out = resume_token(
        interrupt_type="pi_toolkit_ratify", action="correct", response_text=text
    )
    assert out == text
