"""End-to-end integration test — synthesized PI workflow.

Walks the entire stack: FastAPI HTTP surface → OrchestratorRunner →
ParkedStore → fake compiled-graph that simulates a real Brain ⇄ PI ⇄
Executor session. The graph fake emits structured payloads matching
what `pi.py` produces in production and records the resume tokens it
gets back from the runner — so any regression in the response-token
contract surfaces here too, but exercised through the full HTTP layer.

Three scripted scenarios:

  1. **Golden path** — start → pi_greenlight (accept) →
     pi_decision_select (accept) → pi_acceptance (accept) → complete.
     Verifies the three different accept tokens land correctly.
  2. **Correction loop** — start → pi_greenlight (correct with text) →
     verifies the freeform text reached the graph verbatim.
  3. **Cancel** — start → pi_greenlight (parked) → DELETE /runs/{id} →
     verifies cancellation cleans up pending interrupts.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner
from orchestrator.server import create_app


# ---------------------------------------------------------------------------
# Test doubles — same shape as runner unit tests, but used through HTTP.
# ---------------------------------------------------------------------------


class _Interrupt:
    def __init__(self, value: Any):
        self.value = value


class _ProductionShapeFake:
    """Fake graph that emits payloads matching pi.py's production output."""

    def __init__(self):
        self.invocations: list[tuple[Any, dict]] = []
        # Track which interrupt to emit next.
        self._step = 0

    def invoke(self, input_or_command: Any, config: dict) -> dict:
        self.invocations.append((input_or_command, config))
        # Step 0: initial invocation → park pi_greenlight.
        # Step 1: after pi_greenlight accept → park pi_decision_select.
        # Step 2: after pi_decision_select accept → run through
        #         execute_ratified_actions → park pi_acceptance.
        # Step 3: after pi_acceptance accept → terminal complete.
        step = self._step
        self._step += 1

        if step == 0:
            return {
                "current_node": "pi_greenlight",
                "usd_spent": 0.05,
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_greenlight",
                            "title": "PI approval — Confirmation Brief",
                            "items": [
                                {
                                    "title": "Mission test_X — Backbrief",
                                    "objective": "Test the synthesized workflow",
                                    "approach": "End-to-end pipeline verification",
                                    "source_node": "confirmation_brief",
                                }
                            ],
                            "total_items": 1,
                        }
                    )
                ],
            }
        if step == 1:
            return {
                "current_node": "pi_decision_select",
                "usd_spent": 0.20,
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_decision_select",
                            "title": "PI selection — choose decision option",
                            "items": [
                                {
                                    "content": "Add note documenting outcome",
                                    "context": "rka_add_note proposal",
                                    "source_node": "decision_present",
                                    "source_artifact": "jrn_test_1",
                                },
                                {
                                    "content": "Record decision linking to research map",
                                    "context": "rka_add_decision proposal",
                                    "source_node": "decision_present",
                                    "source_artifact": "dec_test_1",
                                },
                            ],
                            "total_items": 2,
                        }
                    )
                ],
            }
        if step == 2:
            return {
                "current_node": "pi_acceptance",
                "usd_spent": 0.45,
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_acceptance",
                            "title": "PI acceptance — final mission review",
                            "items": [
                                {
                                    "final_report_id": "jrn_final_test",
                                    "artifact_count": 5,
                                    "interrupt_count": 2,
                                    "error_count": 0,
                                    "checkpoint_count": 0,
                                    "usd_spent": 0.45,
                                    "summary": "Mission complete; 5 artifacts produced.",
                                }
                            ],
                            "total_items": 1,
                        }
                    )
                ],
            }
        # Step 3: terminal.
        return {
            "current_node": "pi_acceptance",
            "terminal_state": "complete",
            "final_report_id": "jrn_final_test",
            "usd_spent": 0.45,
        }


class _FakeMCP:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def rka_get_mission(self, id: str | None = None) -> dict:
        self.calls.append(("rka_get_mission", {"id": id}))
        return {
            "id": id,
            "objective": "synthesized test mission",
            "motivated_by_decision": "dec_synth_root",
        }


@pytest.fixture
def stack():
    """Wire the full stack with a production-shape fake graph."""
    store = ParkedStore(":memory:")
    fake_graph = _ProductionShapeFake()
    mcp = _FakeMCP()
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda project_id: object(),  # graph never calls SDK
        mcp_factory=lambda tid, pid: mcp,
        saver_factory=lambda tid: None,
        compile_factory=lambda **kwargs: fake_graph,
    )
    app = create_app(store=store, runner=runner)
    client = TestClient(app)
    with client:
        yield client, store, runner, fake_graph, mcp
    store.close()


# ---------------------------------------------------------------------------
# Scenario 1: golden path — three interrupts, all accepted
# ---------------------------------------------------------------------------


def test_golden_path_three_accepts_to_terminal(stack):
    client, store, runner, fake_graph, mcp = stack

    # Step 1: kick off a workflow.
    r = client.post(
        "/runs",
        json={"mission_id": "mis_synth", "project_id": "prj_synth"},
    )
    assert r.status_code == 200
    start = r.json()
    thread_id = start["workflow_thread_id"]
    int1_id = start["parked_interrupt_id"]
    assert start["parked_interrupt_type"] == "pi_greenlight"
    assert start["current_node"] == "pi_greenlight"

    # The mission was fetched once via MCP.
    assert mcp.calls == [("rka_get_mission", {"id": "mis_synth"})]

    # Step 2: inbox shows the parked interrupt with the structured payload.
    r = client.get(f"/inbox?workflow_thread_id={thread_id}")
    assert r.status_code == 200
    inbox = r.json()
    assert len(inbox) == 1
    payload = inbox[0]["payload"]
    assert payload["type"] == "pi_greenlight"
    assert payload["items"][0]["objective"] == "Test the synthesized workflow"

    # Step 3: PI accepts the greenlight. Server MUST emit "approve" (not "accept").
    r = client.post(f"/inbox/{int1_id}/accept")
    assert r.status_code == 200
    seg2 = r.json()
    assert seg2["parked_interrupt_type"] == "pi_decision_select"
    int2_id = seg2["parked_interrupt_id"]

    # Verify the resume token sent to the graph:
    resume_input1, _ = fake_graph.invocations[1]
    assert resume_input1.resume == "approve", (
        "pi_greenlight accept must resume with 'approve' or graph routes to "
        "escalation — Phase 2.4 v1 regression!"
    )

    # Step 4: PI accepts the decision_select (privileged ratification).
    r = client.post(f"/inbox/{int2_id}/accept")
    assert r.status_code == 200
    seg3 = r.json()
    assert seg3["parked_interrupt_type"] == "pi_acceptance"
    int3_id = seg3["parked_interrupt_id"]
    resume_input2, _ = fake_graph.invocations[2]
    assert resume_input2.resume == "accept"

    # Step 5: PI accepts the final acceptance.
    r = client.post(f"/inbox/{int3_id}/accept")
    assert r.status_code == 200
    final = r.json()
    assert final["terminal_state"] == "complete"
    assert final["final_report_id"] == "jrn_final_test"
    resume_input3, _ = fake_graph.invocations[3]
    assert resume_input3.resume == "accept"

    # The run record now reflects completion.
    r = client.get(f"/runs/{thread_id}")
    assert r.json()["status"] == "complete"
    assert r.json()["final_report_id"] == "jrn_final_test"
    assert r.json()["terminal_state"] == "complete"

    # All three interrupts are now answered (not pending).
    assert store.list_pending_interrupts() == []
    for iid in (int1_id, int2_id, int3_id):
        assert store.get_interrupt(iid)["status"] == "answered"


# ---------------------------------------------------------------------------
# Scenario 2: correction loop — freeform text round-trips
# ---------------------------------------------------------------------------


def test_correction_passes_freeform_text_to_graph(stack):
    client, store, runner, fake_graph, mcp = stack
    r = client.post(
        "/runs", json={"mission_id": "mis_synth", "project_id": "prj_synth"}
    )
    int_id = r.json()["parked_interrupt_id"]

    correction = "use option B and re-run gate1 with a stricter consensus threshold"
    r = client.post(
        f"/inbox/{int_id}/correct",
        json={"response_text": correction},
    )
    assert r.status_code == 200

    resume_input, _ = fake_graph.invocations[1]
    # Phase D2: action='correct' prepends REDIRECT_SENTINEL so substring
    # routing can't smuggle a PI correction containing "approve"/"accept"
    # into the accept branch.
    from orchestrator.response_tokens import REDIRECT_SENTINEL
    assert resume_input.resume == REDIRECT_SENTINEL + correction

    # Empty corrections rejected by pydantic before reaching the graph.
    r = client.post(f"/inbox/int_bogus/correct", json={"response_text": ""})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Scenario 3: cancel a run with a parked interrupt
# ---------------------------------------------------------------------------


def test_cancel_run_marks_pending_cancelled(stack):
    client, store, runner, fake_graph, mcp = stack
    r = client.post(
        "/runs", json={"mission_id": "mis_synth", "project_id": "prj_synth"}
    )
    thread_id = r.json()["workflow_thread_id"]
    int_id = r.json()["parked_interrupt_id"]

    # Cancel.
    r = client.delete(f"/runs/{thread_id}")
    assert r.status_code == 200
    assert r.json()["cancelled_interrupts"] == 1

    # The interrupt is no longer pending.
    r = client.get(f"/inbox?workflow_thread_id={thread_id}")
    assert r.json() == []

    # The run row is cancelled.
    r = client.get(f"/runs/{thread_id}")
    assert r.json()["status"] == "cancelled"

    # Responding to a cancelled interrupt fails cleanly.
    r = client.post(f"/inbox/{int_id}/accept")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Scenario 4: reject routes to escalation, not silent accept
# ---------------------------------------------------------------------------


class _RejectShapeFake:
    """Variant: after rejection, graph terminates as escalated."""

    def __init__(self):
        self.invocations: list[tuple[Any, dict]] = []
        self._step = 0

    def invoke(self, input_or_command: Any, config: dict) -> dict:
        self.invocations.append((input_or_command, config))
        step = self._step
        self._step += 1
        if step == 0:
            return {
                "current_node": "pi_greenlight",
                "__interrupt__": [
                    _Interrupt(
                        value={
                            "type": "pi_greenlight",
                            "title": "Approve?",
                            "items": [{"x": 1}],
                            "total_items": 1,
                        }
                    )
                ],
            }
        return {"current_node": "pi_acceptance", "terminal_state": "escalated"}


def test_reject_emits_literal_reject_to_graph():
    store = ParkedStore(":memory:")
    fake = _RejectShapeFake()
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda p: object(),
        mcp_factory=lambda t, p: _FakeMCP(),
        saver_factory=lambda t: None,
        compile_factory=lambda **kw: fake,
    )
    app = create_app(store=store, runner=runner)
    with TestClient(app) as client:
        r = client.post(
            "/runs", json={"mission_id": "mis_synth", "project_id": "prj_synth"}
        )
        int_id = r.json()["parked_interrupt_id"]
        r = client.post(
            f"/inbox/{int_id}/reject", json={"reason": "wrong scope"}
        )
        assert r.status_code == 200
        assert r.json()["terminal_state"] == "escalated"
        resume_input, _ = fake.invocations[1]
        assert resume_input.resume == "reject"
    store.close()
