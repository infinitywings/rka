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

    # Phase D2 (post-review) — split respond into commit + resume so the
    # FastAPI async-resume path can background the segment. FakeRunner
    # mirrors the same shape so tests against wait_segment=false hit a
    # spec-compatible runner.
    def commit_response(self, **kwargs) -> dict:
        self.respond_calls.append({**kwargs, "_phase": "commit"})
        # Look up the interrupt to derive interrupt_type for the ack dict.
        parked = self.store.get_interrupt(kwargs["interrupt_id"])
        if parked is None:
            raise ValueError(f"interrupt {kwargs['interrupt_id']!r} not found")
        if parked["status"] != "pending":
            raise ValueError(
                f"interrupt {kwargs['interrupt_id']!r} already in status="
                f"{parked['status']!r}"
            )
        # Mark answered + run running, same as real runner.commit_response.
        run = self.store.get_run(parked["workflow_thread_id"])
        self.store.answer_interrupt(
            interrupt_id=kwargs["interrupt_id"],
            response_action=kwargs["action"],
            response_text=kwargs.get("response_text") or kwargs["action"],
        )
        self.store.update_run(run["workflow_thread_id"], status="running")
        return {
            "workflow_thread_id": run["workflow_thread_id"],
            "project_id": run["project_id"],
            "interrupt_type": parked["interrupt_type"],
            "interrupt_id": kwargs["interrupt_id"],
            "token": kwargs.get("response_text") or kwargs["action"],
        }

    def resume_segment(self, **kwargs) -> SegmentOutcome:
        self.respond_calls.append({**kwargs, "_phase": "resume"})
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


# ---------------------------------------------------------------------------
# Phase D2 (post-review) — wait_segment=false async-resume path
#
# The MCP-stdio binary always calls with ?wait_segment=false; the entire
# production code path from MCP client to graph resume runs through this
# branch. The synchronous branch above remains for legacy callers + tests.
# ---------------------------------------------------------------------------


def test_accept_wait_segment_false_returns_resuming_shape(setup):
    """Async-resume path: HTTP returns immediately after answer commit;
    the actual graph segment runs as a background task."""
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    # Script the outcome the background task will see (segment finishes
    # quickly under the fake runner).
    runner.script_outcome(
        SegmentOutcome(workflow_thread_id=tid, terminal_state="complete")
    )

    r = client.post(f"/inbox/{iid}/accept?wait_segment=false")
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_thread_id"] == tid
    assert body["answered_interrupt_id"] == iid
    assert body["answered_interrupt_type"] == "pi_decision_select"
    assert body["status"] == "resuming"
    assert body["wait_segment"] is False
    # Legacy SegmentOutcome keys must NOT be present in the resuming response.
    assert "terminal_state" not in body
    assert "parked_interrupt_id" not in body


def test_correct_wait_segment_false_returns_resuming_shape(setup):
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    runner.script_outcome(
        SegmentOutcome(workflow_thread_id=tid, terminal_state="escalated")
    )

    r = client.post(
        f"/inbox/{iid}/correct?wait_segment=false",
        json={"response_text": "redo with stricter consensus"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resuming"
    assert r.json()["answered_interrupt_type"] == "pi_greenlight"


def test_reject_wait_segment_false_returns_resuming_shape(setup):
    client, store, runner = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    runner.script_outcome(
        SegmentOutcome(workflow_thread_id=tid, terminal_state="escalated")
    )

    r = client.post(
        f"/inbox/{iid}/reject?wait_segment=false",
        json={"reason": "wrong scope"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resuming"


def test_wait_segment_false_returns_409_when_already_answered(setup):
    """The async path must still surface the 'already answered' 409 from
    commit_response — the failure mode the synchronous path tested in
    test_respond_409_when_already_answered."""
    client, store, _ = setup
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    # First answer commits.
    store.answer_interrupt(
        interrupt_id=iid, response_action="accept", response_text="accept"
    )
    # Second attempt → 409.
    r = client.post(f"/inbox/{iid}/accept?wait_segment=false")
    assert r.status_code == 409


def test_wait_segment_false_returns_404_when_interrupt_missing(setup):
    client, _, _ = setup
    r = client.post("/inbox/int_does_not_exist/accept?wait_segment=false")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Phase D2.1 — wait_segment=false async-START path on /runs, /onboard, /bootstrap
#
# Same architectural rationale as wait_segment=false on /inbox/*/{accept,...}:
# the first segment of a fresh run (Brain strategy + confirmation_brief) is
# a multi-LLM-call chunk that exceeds any reasonable HTTP timeout.
# ---------------------------------------------------------------------------


def test_post_runs_wait_segment_false_returns_starting_shape(setup):
    """Async-start path: HTTP returns immediately after the run row is
    committed + the mission spec is loaded (404 on missing mission still
    works). The graph segment runs as a background task."""
    client, store, runner = setup

    # FakeRunner needs commit + drive methods to satisfy the new code path.
    # Provide minimal stubs.
    def _commit(**kwargs):
        return {
            "workflow_thread_id": "thr_async_start",
            "project_id": kwargs["project_id"],
            "mission_id": kwargs["mission_id"],
            "motivated_by_decision_id": "",
        }

    def _drive(**kwargs):
        # Mimic real runner: park an interrupt + flip status.
        return SegmentOutcome(
            workflow_thread_id=kwargs["workflow_thread_id"],
            parked_interrupt_id="int_first",
            parked_interrupt_type="pi_greenlight",
        )

    runner.start_run_commit = _commit
    runner.start_run_drive = _drive
    # FakeRunner also needs a workflow_runs row for /runs/{id} to return it.
    store.create_run(
        mission_id="m", project_id="p",
        workflow_thread_id="thr_async_start",
    )

    r = client.post(
        "/runs?wait_segment=false",
        json={
            "mission_id": "m",
            "project_id": "p",
            "budget_usd": 5.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_thread_id"] == "thr_async_start"
    assert body["status"] == "starting"
    assert body["wait_segment"] is False
    assert body["mission_id"] == "m"
    assert body["project_id"] == "p"
    # Legacy SegmentOutcome keys must NOT be present.
    assert "terminal_state" not in body
    assert "parked_interrupt_id" not in body


def test_post_runs_wait_segment_false_404_on_missing_mission(setup):
    """The async path still surfaces MissionNotFoundError as 404 from
    the synchronous commit phase — the failure is fast (rka_get_mission
    HTTP call) and shouldn't be hidden behind a background task."""
    client, _, runner = setup

    def _commit(**kwargs):
        raise MissionNotFoundError(f"mission {kwargs['mission_id']!r} not found")

    runner.start_run_commit = _commit

    r = client.post(
        "/runs?wait_segment=false",
        json={"mission_id": "mis_missing", "project_id": "p"},
    )
    assert r.status_code == 404
    assert "mis_missing" in r.json()["detail"]


def test_post_onboard_wait_segment_false_returns_starting_shape(setup):
    client, store, runner = setup

    def _commit(**kwargs):
        return {
            "workflow_thread_id": "thr_onboard",
            "project_id": kwargs["project_id"],
        }

    def _drive(**kwargs):
        return SegmentOutcome(
            workflow_thread_id=kwargs["workflow_thread_id"],
            parked_interrupt_id="int_topic",
            parked_interrupt_type="pi_onboarding_topic",
        )

    runner.start_onboarding_commit = _commit
    runner.start_onboarding_drive = _drive
    store.create_run(
        mission_id="p", project_id="p", workflow_thread_id="thr_onboard",
    )

    r = client.post(
        "/onboard?wait_segment=false", json={"project_id": "p"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_thread_id"] == "thr_onboard"
    assert body["status"] == "starting"
    assert body["wait_segment"] is False


def test_post_bootstrap_wait_segment_false_returns_starting_shape(setup):
    client, store, runner = setup

    def _commit(**kwargs):
        return {"workflow_thread_id": "thr_boot"}

    def _drive(**kwargs):
        return SegmentOutcome(
            workflow_thread_id=kwargs["workflow_thread_id"],
            parked_interrupt_id="int_boot",
            parked_interrupt_type="pi_bootstrap_intent",
        )

    runner.start_phase_b_commit = _commit
    runner.start_phase_b_drive = _drive
    store.create_run(
        mission_id="_bootstrap_", project_id="_bootstrap_",
        workflow_thread_id="thr_boot",
    )

    r = client.post("/bootstrap?wait_segment=false", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_thread_id"] == "thr_boot"
    assert body["status"] == "starting"
    assert body["wait_segment"] is False
