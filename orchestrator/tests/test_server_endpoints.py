"""FastAPI endpoint contracts.

These tests pin the HTTP surface the MCP server consumes. They use a
fake runner that records calls + emits scripted outcomes — the runner
itself is covered separately in test_runner_resume.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import MissionNotFoundError, SegmentOutcome
from orchestrator.server import create_app


class _FakeRunner:
    """Spec-compatible with OrchestratorRunner but scripted."""

    def __init__(self, store: ParkedStore):
        self.store = store
        self.start_calls: list[dict] = []
        self.respond_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self._next_outcome: SegmentOutcome | None = None
        self._next_exception: Exception | None = None

    def script_outcome(self, outcome: SegmentOutcome) -> None:
        self._next_outcome = outcome
        self._next_exception = None

    def script_exception(self, exc: Exception) -> None:
        self._next_exception = exc
        self._next_outcome = None

    def _consume(self) -> SegmentOutcome:
        if self._next_exception is not None:
            exc = self._next_exception
            self._next_exception = None
            raise exc
        if self._next_outcome is None:
            raise AssertionError("no scripted outcome")
        out = self._next_outcome
        self._next_outcome = None
        return out

    def start_run(self, **kwargs) -> SegmentOutcome:
        self.start_calls.append(kwargs)
        # Side-effect: create the workflow_runs row so /runs/{id} returns it.
        self.store.create_run(
            mission_id=kwargs["mission_id"],
            project_id=kwargs["project_id"],
            budget_usd=kwargs.get("budget_usd", 5.0),
            workflow_thread_id=kwargs.get("workflow_thread_id"),
        )
        return self._consume()

    def respond(self, **kwargs) -> SegmentOutcome:
        self.respond_calls.append(kwargs)
        return self._consume()

    def cancel(self, workflow_thread_id: str) -> int:
        self.cancel_calls.append(workflow_thread_id)
        return self.store.cancel_run(workflow_thread_id)


@pytest.fixture
def setup():
    store = ParkedStore(":memory:")
    runner = _FakeRunner(store)
    app = create_app(store=store, runner=runner)
    client = TestClient(app)
    # FastAPI lifespan runs on context entry.
    with client:
        yield client, store, runner
    store.close()


def test_health_returns_ok(setup):
    client, _, _ = setup
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_post_runs_returns_outcome(setup):
    client, store, runner = setup
    runner.script_outcome(
        SegmentOutcome(
            workflow_thread_id="thr_x",
            parked_interrupt_id="int_p1",
            parked_interrupt_type="pi_greenlight",
            current_node="pi_greenlight",
            usd_spent=0.5,
        )
    )
    r = client.post(
        "/runs",
        json={
            "mission_id": "mis_test",
            "project_id": "prj_test",
            "budget_usd": 2.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parked_interrupt_id"] == "int_p1"
    assert body["parked_interrupt_type"] == "pi_greenlight"
    assert runner.start_calls == [
        {
            "mission_id": "mis_test",
            "project_id": "prj_test",
            "budget_usd": 2.0,
            "workflow_thread_id": None,
        }
    ]


def test_post_runs_404_on_missing_mission(setup):
    client, _, runner = setup
    runner.script_exception(MissionNotFoundError("mission mis_x not found"))
    r = client.post(
        "/runs", json={"mission_id": "mis_x", "project_id": "prj_test"}
    )
    assert r.status_code == 404
    assert "mis_x" in r.json()["detail"]


def test_get_runs_lists_all(setup):
    client, store, runner = setup
    store.create_run(mission_id="m1", project_id="p")
    store.create_run(mission_id="m2", project_id="p")
    r = client.get("/runs")
    assert r.status_code == 200
    missions = sorted(row["mission_id"] for row in r.json())
    assert missions == ["m1", "m2"]


def test_get_runs_filters_by_status(setup):
    client, store, _ = setup
    t1 = store.create_run(mission_id="m1", project_id="p")
    store.create_run(mission_id="m2", project_id="p")
    store.update_run(t1, status="complete")
    r = client.get("/runs?status=running")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["mission_id"] == "m2"


def test_get_run_404_unknown(setup):
    client, _, _ = setup
    r = client.get("/runs/thr_bogus")
    assert r.status_code == 404


def test_delete_run_cancels(setup):
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    r = client.delete(f"/runs/{tid}")
    assert r.status_code == 200
    assert r.json()["cancelled_interrupts"] == 1
    assert store.get_run(tid)["status"] == "cancelled"


def test_delete_run_404_unknown(setup):
    client, _, _ = setup
    r = client.delete("/runs/thr_bogus")
    assert r.status_code == 404


def test_inbox_lists_pending_interrupts(setup):
    client, store, _ = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight",
        payload={"type": "pi_greenlight", "title": "approve?", "items": []},
    )
    r = client.get("/inbox")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["interrupt_id"] == iid
    assert body[0]["payload"]["title"] == "approve?"


def test_inbox_filters_by_workflow_thread_id(setup):
    client, store, _ = setup
    t1 = store.create_run(mission_id="m1", project_id="p")
    t2 = store.create_run(mission_id="m2", project_id="p")
    store.park_interrupt(
        workflow_thread_id=t1, mission_id="m1",
        interrupt_type="pi_greenlight", payload={},
    )
    store.park_interrupt(
        workflow_thread_id=t2, mission_id="m2",
        interrupt_type="pi_greenlight", payload={},
    )
    r = client.get(f"/inbox?workflow_thread_id={t1}")
    assert len(r.json()) == 1
    assert r.json()[0]["mission_id"] == "m1"


def test_accept_invokes_runner_with_action_accept(setup):
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    runner.script_outcome(
        SegmentOutcome(workflow_thread_id=tid, terminal_state="complete")
    )
    r = client.post(f"/inbox/{iid}/accept")
    assert r.status_code == 200
    assert r.json()["terminal_state"] == "complete"
    assert runner.respond_calls == [
        {"interrupt_id": iid, "action": "accept", "response_text": None}
    ]


def test_reject_passes_reason_through_response_text(setup):
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    runner.script_outcome(
        SegmentOutcome(workflow_thread_id=tid, terminal_state="escalated")
    )
    r = client.post(f"/inbox/{iid}/reject", json={"reason": "wrong scope"})
    assert r.status_code == 200
    assert runner.respond_calls == [
        {"interrupt_id": iid, "action": "reject", "response_text": "wrong scope"}
    ]


def test_correct_passes_text(setup):
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    runner.script_outcome(
        SegmentOutcome(workflow_thread_id=tid, terminal_state="escalated")
    )
    r = client.post(
        f"/inbox/{iid}/correct", json={"response_text": "use plan C"}
    )
    assert r.status_code == 200
    assert runner.respond_calls == [
        {
            "interrupt_id": iid,
            "action": "correct",
            "response_text": "use plan C",
        }
    ]


def test_correct_rejects_empty_response_text(setup):
    client, _, _ = setup
    r = client.post(
        "/inbox/int_x/correct", json={"response_text": ""}
    )
    # pydantic min_length=1 → 422.
    assert r.status_code == 422


def test_respond_404_when_interrupt_missing(setup):
    client, _, runner = setup
    runner.script_exception(ValueError("interrupt int_x not found"))
    r = client.post("/inbox/int_x/accept")
    assert r.status_code == 404


def test_respond_409_when_already_answered(setup):
    client, _, runner = setup
    runner.script_exception(
        ValueError("interrupt int_x already in status='answered'")
    )
    r = client.post("/inbox/int_x/accept")
    assert r.status_code == 409
