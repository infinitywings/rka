"""Phase D2.6 — async-resume watchdog tests.

Covers the four module-level helpers (`_WatchdogProbe`,
`_capture_probe`, `_probe_advanced`, `_cache_sync`) and the
`_background_segment` integration (probe-and-retry around the
async-resume drive coroutine). Plus runner-side hardening for the
post-invoke inspection's non-dict / missing-terminal-state cases.

Reference: workflow `wqicgntwi` synthesis (root cause: bg thread
blocked mid `compiled.invoke()` on SDK subprocess pipe wait). The
watchdog catches the silent-return failure mode by snapshotting four
structural signals before and after the drive coroutine and emitting
a single bounded retry on detected no-advance.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orchestrator.parked_store import ParkedStore
from orchestrator.runner import OrchestratorRunner, SegmentOutcome
from orchestrator.server import (
    _WatchdogProbe,
    _cache_sync,
    _capture_probe,
    _probe_advanced,
    _read_live_probe_fields,
    create_app,
)


# ---------------------------------------------------------------
# Helper-level unit tests — _WatchdogProbe / _probe_advanced /
# _cache_sync / _read_live_probe_fields
# ---------------------------------------------------------------


def _make_probe(
    *,
    status: Optional[str] = "running",
    checkpoint_id: Optional[str] = None,
    pending: frozenset = frozenset(),
    terminal_state: Optional[str] = None,
    live_current_node: Optional[str] = None,
    live_usd_spent: float = 0.0,
    cached_current_node: Optional[str] = None,
    cached_usd_spent: float = 0.0,
) -> _WatchdogProbe:
    return _WatchdogProbe(
        status=status,
        checkpoint_id=checkpoint_id,
        pending_interrupt_ids=pending,
        terminal_state=terminal_state,
        live_current_node=live_current_node,
        live_usd_spent=live_usd_spent,
        cached_current_node=cached_current_node,
        cached_usd_spent=cached_usd_spent,
    )


def test_probe_advanced_status_change_detected() -> None:
    before = _make_probe(status="running")
    after = _make_probe(status="awaiting_pi")
    assert _probe_advanced(before, after) is True


def test_probe_advanced_terminal_state_set_detected() -> None:
    before = _make_probe(terminal_state=None)
    after = _make_probe(status="complete", terminal_state="complete")
    assert _probe_advanced(before, after) is True


def test_probe_advanced_checkpoint_id_change_detected() -> None:
    before = _make_probe(checkpoint_id="ckpt-1")
    after = _make_probe(checkpoint_id="ckpt-2")
    assert _probe_advanced(before, after) is True


def test_probe_advanced_pending_set_identity_change_detected() -> None:
    # Same cardinality, different identity — park-then-answer race.
    before = _make_probe(pending=frozenset({"int_A"}))
    after = _make_probe(pending=frozenset({"int_B"}))
    assert _probe_advanced(before, after) is True


def test_probe_advanced_no_advance_when_all_signals_unchanged() -> None:
    # The empirical 2026-06-01 stall pattern: status still 'running',
    # checkpoint_id unchanged (None == None), no interrupts, no
    # terminal_state. This MUST return False or the watchdog won't fire.
    before = _make_probe(
        status="running",
        checkpoint_id="ckpt-1",
        pending=frozenset(),
        terminal_state=None,
    )
    after = _make_probe(
        status="running",
        checkpoint_id="ckpt-1",
        pending=frozenset(),
        terminal_state=None,
    )
    assert _probe_advanced(before, after) is False


def test_probe_advanced_tolerates_none_checkpoint_id() -> None:
    # Saver-path-None or fresh-thread case: both probes have ckpt_id=None.
    # Must NOT spuriously claim advance (None != None would be wrong).
    before = _make_probe(checkpoint_id=None)
    after = _make_probe(checkpoint_id=None)
    assert _probe_advanced(before, after) is False


def test_probe_advanced_after_checkpoint_None_is_not_advance() -> None:
    # If the checkpoint disappeared between probes (unusual but possible
    # under saver-rotation), we should NOT treat None-after as an advance.
    before = _make_probe(checkpoint_id="ckpt-1")
    after = _make_probe(checkpoint_id=None)
    assert _probe_advanced(before, after) is False


def test_probe_advanced_fresh_saver_first_checkpoint_is_advance() -> None:
    """Fresh-thread case: no checkpoint yet → first checkpoint appears.
    The disjunction MUST fire (signal 3 — checkpoint_id changed from
    None to a non-None value).
    """
    before = _make_probe(checkpoint_id=None)
    after = _make_probe(checkpoint_id="ckpt-1")
    assert _probe_advanced(before, after) is True


def test_probe_advanced_status_already_non_running_stays_false() -> None:
    """Adversarial review MEDIUM #1 — _probe_advanced disjunct 1
    previously checked only `after.status != 'running'`, which would
    false-positive when before.status was already non-'running' (e.g.,
    a bg task scheduled over an already-parked run). Tightened to
    require a transition AWAY from 'running'.
    """
    before = _make_probe(status="awaiting_pi")
    after = _make_probe(status="awaiting_pi")
    # All four signals unchanged → False.
    assert _probe_advanced(before, after) is False
    # Even if after.status differs but neither was 'running'.
    before2 = _make_probe(status="complete")
    after2 = _make_probe(status="failed")
    assert _probe_advanced(before2, after2) is False


# ---------------------------------------------------------------
# _capture_probe — reads workflow_runs + parked_interrupts + live
# ---------------------------------------------------------------


def test_capture_probe_reads_workflow_runs_status_and_cached_fields() -> None:
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m1", project_id="p1")
        store.update_run(tid, current_node="brain_strategy", usd_spent=0.12)
        probe = _capture_probe(store, saver_path=None, workflow_thread_id=tid)
        assert probe.status == "running"
        assert probe.cached_current_node == "brain_strategy"
        assert probe.cached_usd_spent == pytest.approx(0.12)
        assert probe.terminal_state is None
        # No saver_path → live fields are degraded.
        assert probe.checkpoint_id is None
        assert probe.live_current_node is None
        assert probe.live_usd_spent == 0.0
    finally:
        store.close()


def test_capture_probe_collects_pending_interrupt_ids() -> None:
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m1", project_id="p1")
        iid_a = store.park_interrupt(
            workflow_thread_id=tid, mission_id="m1",
            interrupt_type="pi_greenlight", payload={},
        )
        iid_b = store.park_interrupt(
            workflow_thread_id=tid, mission_id="m1",
            interrupt_type="pi_decision_select", payload={},
        )
        probe = _capture_probe(store, saver_path=None, workflow_thread_id=tid)
        assert probe.pending_interrupt_ids == frozenset({iid_a, iid_b})
    finally:
        store.close()


def test_capture_probe_graceful_when_thread_missing() -> None:
    # Fresh store, unknown thread id — must not raise.
    store = ParkedStore(":memory:")
    try:
        probe = _capture_probe(
            store, saver_path=None, workflow_thread_id="thr_bogus"
        )
        assert probe.status is None
        assert probe.pending_interrupt_ids == frozenset()
        assert probe.checkpoint_id is None
    finally:
        store.close()


def test_read_live_probe_fields_returns_none_for_missing_saver() -> None:
    assert _read_live_probe_fields("thr_x", saver_path=None) == (None, None, 0.0)
    assert _read_live_probe_fields("thr_x", saver_path="/nope/nope.db") == (
        None,
        None,
        0.0,
    )


def test_read_live_probe_fields_returns_live_values_from_real_saver(
    tmp_path: Path,
) -> None:
    """Hot path coverage — open a real SqliteSaver, persist a tuple
    with channel_values containing current_node + usd_spent, then
    verify _read_live_probe_fields extracts them. Closes the gap where
    only the graceful-degrade branches were tested.
    """
    from orchestrator import graph as graph_module

    saver_path = str(tmp_path / "saver.sqlite")
    saver = graph_module.open_checkpointer(saver_path)
    config = {"configurable": {"thread_id": "thr_live", "checkpoint_ns": ""}}
    saver.put(
        config,
        checkpoint={
            "id": "ckpt-real-1",
            "channel_values": {
                "current_node": "brain_strategy",
                "usd_spent": 0.37,
            },
            "channel_versions": {},
            "versions_seen": {},
            "ts": "2026-06-01T00:00:00Z",
        },
        metadata={},
        new_versions={},
    )

    ckpt_id, live_node, live_usd = _read_live_probe_fields(
        "thr_live", saver_path
    )
    assert ckpt_id == "ckpt-real-1"
    assert live_node == "brain_strategy"
    assert live_usd == pytest.approx(0.37)


def test_capture_probe_swallows_get_run_exception() -> None:
    """Defensive coverage — _capture_probe's get_run try/except branch.
    If the cache read raises (e.g., transient sqlite lock contention),
    the probe degrades to status=None rather than failing the watchdog.
    """
    mock_store = MagicMock()
    mock_store.get_run.side_effect = sqlite3.OperationalError("database is locked")
    mock_store.list_pending_interrupts.return_value = []
    probe = _capture_probe(mock_store, saver_path=None, workflow_thread_id="thr_x")
    assert probe.status is None
    assert probe.cached_current_node is None
    assert probe.cached_usd_spent == 0.0
    assert probe.pending_interrupt_ids == frozenset()


def test_capture_probe_swallows_list_pending_interrupts_exception() -> None:
    """Same as above but for the parked_interrupts query — fault in
    one read does not leak into the other.
    """
    mock_store = MagicMock()
    mock_store.get_run.return_value = {"status": "running", "current_node": "n1", "usd_spent": 0.0}
    mock_store.list_pending_interrupts.side_effect = sqlite3.OperationalError(
        "table parked_interrupts is locked"
    )
    probe = _capture_probe(mock_store, saver_path=None, workflow_thread_id="thr_x")
    assert probe.status == "running"
    assert probe.cached_current_node == "n1"
    assert probe.pending_interrupt_ids == frozenset()


def test_cache_sync_swallows_update_run_exception() -> None:
    """_cache_sync is best-effort: a sqlite OperationalError during
    update_run must NOT propagate out of the watchdog's drive loop.
    Coverage of the swallow branch at server.py.
    """
    mock_store = MagicMock()
    mock_store.get_run.return_value = {
        "status": "running",
        "current_node": "cached",
        "usd_spent": 0.0,
    }
    mock_store.update_run.side_effect = sqlite3.OperationalError(
        "database is locked"
    )
    probe = _make_probe(
        live_current_node="fresh",
        live_usd_spent=0.5,
        cached_current_node="cached",
        cached_usd_spent=0.0,
    )
    # Must not raise.
    _cache_sync(mock_store, "thr_x", probe)


# ---------------------------------------------------------------
# _cache_sync — pushes live values into workflow_runs cache row
# ---------------------------------------------------------------


def test_cache_sync_writes_current_node_when_live_differs() -> None:
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        store.update_run(tid, current_node="stale_node", usd_spent=0.05)
        probe = _make_probe(
            live_current_node="fresh_node",
            live_usd_spent=0.20,
            cached_current_node="stale_node",
            cached_usd_spent=0.05,
        )
        _cache_sync(store, tid, probe)
        run = store.get_run(tid)
        assert run["current_node"] == "fresh_node"
        assert run["usd_spent"] == pytest.approx(0.20)
    finally:
        store.close()


def test_cache_sync_noop_when_in_sync() -> None:
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        store.update_run(tid, current_node="node1", usd_spent=0.10)
        probe = _make_probe(
            live_current_node="node1",
            live_usd_spent=0.10,
            cached_current_node="node1",
            cached_usd_spent=0.10,
        )
        before_ts = store.get_run(tid)["updated_at"]
        _cache_sync(store, tid, probe)
        after_ts = store.get_run(tid)["updated_at"]
        # No write should have happened, but updated_at could still tick
        # if update_run was called with no fields (it isn't here). Best
        # assertion: the row's values are unchanged.
        run = store.get_run(tid)
        assert run["current_node"] == "node1"
        assert run["usd_spent"] == pytest.approx(0.10)
    finally:
        store.close()


def test_cache_sync_noop_when_no_live_signal() -> None:
    # Saver-path-None case: live_* are all default. No write.
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        store.update_run(tid, current_node="cached_node", usd_spent=0.30)
        probe = _make_probe(
            live_current_node=None,
            live_usd_spent=0.0,
            cached_current_node="cached_node",
            cached_usd_spent=0.30,
        )
        _cache_sync(store, tid, probe)
        run = store.get_run(tid)
        assert run["current_node"] == "cached_node"
        assert run["usd_spent"] == pytest.approx(0.30)
    finally:
        store.close()


def test_cache_sync_never_decrements_usd_spent() -> None:
    # Stale checkpoint read or saver rotation — live appears lower than
    # cached. Never overwrite — usd_spent is monotonic.
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        store.update_run(tid, usd_spent=0.50)
        probe = _make_probe(
            live_current_node=None,
            live_usd_spent=0.10,  # lower than cached
            cached_current_node=None,
            cached_usd_spent=0.50,
        )
        _cache_sync(store, tid, probe)
        run = store.get_run(tid)
        assert run["usd_spent"] == pytest.approx(0.50)
    finally:
        store.close()


# ---------------------------------------------------------------
# Integration tests — _background_segment with watchdog wiring
# ---------------------------------------------------------------


class _WatchdogFakeRunner:
    """Test double for OrchestratorRunner async-resume paths.

    Lets each test configure resume_segment / start_run_drive /
    start_onboarding_drive / start_phase_b_drive behaviour: advance,
    stall, raise. Counts calls so watchdog single-retry can be verified.
    """

    def __init__(self, store: ParkedStore) -> None:
        self.store = store
        self._resume_behaviors: list[str] = []
        self._start_run_behaviors: list[str] = []
        self._start_onboarding_behaviors: list[str] = []
        self._start_phase_b_behaviors: list[str] = []
        # Tracks each call's behavior in order.
        self.resume_calls: list[str] = []
        self.start_run_drive_calls: list[str] = []
        self.start_onboarding_drive_calls: list[str] = []
        self.start_phase_b_drive_calls: list[str] = []
        # Optional side-effect to run inside resume_segment before the
        # behavior fires — used to exercise the cancel-during-retry
        # race (test simulates a DELETE /runs/{id} mid-stall).
        self._resume_side_effect = None

    def script_resume(self, *behaviors: str) -> None:
        self._resume_behaviors = list(behaviors)

    def script_start_run_drive(self, *behaviors: str) -> None:
        self._start_run_behaviors = list(behaviors)

    def script_start_onboarding_drive(self, *behaviors: str) -> None:
        self._start_onboarding_behaviors = list(behaviors)

    def script_start_phase_b_drive(self, *behaviors: str) -> None:
        self._start_phase_b_behaviors = list(behaviors)

    def set_resume_side_effect(self, callback) -> None:
        self._resume_side_effect = callback

    # ---- /runs path ----

    def start_run(self, **kwargs) -> SegmentOutcome:
        self.store.create_run(
            mission_id=kwargs["mission_id"],
            project_id=kwargs["project_id"],
            workflow_thread_id=kwargs.get("workflow_thread_id"),
        )
        return SegmentOutcome(workflow_thread_id="thr_x", terminal_state="complete")

    def start_run_commit(self, **kwargs) -> dict:
        tid = kwargs.get("workflow_thread_id") or "thr_start_test"
        self.store.create_run(
            mission_id=kwargs["mission_id"],
            project_id=kwargs["project_id"],
            workflow_thread_id=tid,
        )
        return {
            "workflow_thread_id": tid,
            "mission_id": kwargs["mission_id"],
            "project_id": kwargs["project_id"],
            "motivated_by_decision_id": "dec_test",
        }

    def start_run_drive(self, **kwargs) -> SegmentOutcome:
        tid = kwargs["workflow_thread_id"]
        return self._consume_start_behavior(
            tid, self._start_run_behaviors, self.start_run_drive_calls,
            "start_run_drive",
        )

    def start_onboarding_commit(self, **kwargs) -> dict:
        tid = kwargs.get("workflow_thread_id") or "thr_onb_test"
        self.store.create_run(
            mission_id="_onboarding_",
            project_id=kwargs["project_id"],
            workflow_thread_id=tid,
        )
        return {
            "workflow_thread_id": tid,
            "project_id": kwargs["project_id"],
        }

    def start_onboarding_drive(self, **kwargs) -> SegmentOutcome:
        tid = kwargs["workflow_thread_id"]
        return self._consume_start_behavior(
            tid, self._start_onboarding_behaviors,
            self.start_onboarding_drive_calls, "start_onboarding_drive",
        )

    def start_phase_b_commit(self, **kwargs) -> dict:
        tid = kwargs.get("workflow_thread_id") or "thr_phb_test"
        self.store.create_run(
            mission_id="_bootstrap_",
            project_id="",
            workflow_thread_id=tid,
        )
        return {"workflow_thread_id": tid}

    def start_phase_b_drive(self, **kwargs) -> SegmentOutcome:
        tid = kwargs["workflow_thread_id"]
        return self._consume_start_behavior(
            tid, self._start_phase_b_behaviors,
            self.start_phase_b_drive_calls, "start_phase_b_drive",
        )

    def _consume_start_behavior(
        self, tid: str, behaviors: list, calls: list, name: str
    ) -> SegmentOutcome:
        if not behaviors:
            raise AssertionError(
                f"{name} called but only {len(calls)} behaviors scripted"
            )
        behavior = behaviors.pop(0)
        calls.append(behavior)
        if behavior == "advance":
            self.store.park_interrupt(
                workflow_thread_id=tid,
                mission_id=self.store.get_run(tid)["mission_id"],
                interrupt_type="pi_greenlight",
                payload={},
            )
            return SegmentOutcome(workflow_thread_id=tid, parked_interrupt_id="int_x")
        if behavior == "stall":
            return SegmentOutcome(workflow_thread_id=tid, terminal_state="complete")
        if behavior == "raise":
            raise RuntimeError(f"simulated crash inside {name}")
        raise AssertionError(f"unknown behavior {behavior!r}")

    # ---- async-resume path used by /inbox tests ----

    def commit_response(self, **kwargs) -> dict:
        parked = self.store.get_interrupt(kwargs["interrupt_id"])
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
        thread_id = kwargs["workflow_thread_id"]
        if not self._resume_behaviors:
            raise AssertionError(
                f"resume_segment called {len(self.resume_calls) + 1}x but only "
                f"{len(self.resume_calls)} behaviors scripted"
            )
        behavior = self._resume_behaviors.pop(0)
        self.resume_calls.append(behavior)
        if behavior == "advance":
            self.store.park_interrupt(
                workflow_thread_id=thread_id,
                mission_id="m1",
                interrupt_type="pi_greenlight",
                payload={},
            )
            return SegmentOutcome(
                workflow_thread_id=thread_id,
                parked_interrupt_id="int_after_resume",
                parked_interrupt_type="pi_greenlight",
            )
        if behavior == "stall":
            # Do nothing — status stays 'running', no parked interrupt,
            # no checkpoint progress. Mimics the SDK pipe-wait deadlock.
            return SegmentOutcome(
                workflow_thread_id=thread_id, terminal_state="complete"
            )
        if behavior == "raise":
            raise RuntimeError("simulated crash inside resume_segment")
        raise AssertionError(f"unknown behavior {behavior!r}")

    def respond(self, **kwargs):  # pragma: no cover - sync path unused by these tests
        raise AssertionError("respond() should not be called on async-resume tests")

    def cancel(self, workflow_thread_id: str) -> int:
        return self.store.cancel_run(workflow_thread_id)


@pytest.fixture
def watchdog_setup():
    store = ParkedStore(":memory:")
    runner = _WatchdogFakeRunner(store)
    # Stash a saver_path that doesn't exist; _read_live_probe_fields
    # degrades gracefully → checkpoint_id stays None throughout.
    app = create_app(store=store, runner=runner, enforce_mount_safety=False)
    client = TestClient(app)
    with client:
        yield client, store, runner
    store.close()


def _park_an_interrupt(store: ParkedStore) -> tuple[str, str]:
    tid = store.create_run(mission_id="m1", project_id="p1")
    iid = store.park_interrupt(
        workflow_thread_id=tid,
        mission_id="m1",
        interrupt_type="pi_greenlight",
        payload={"type": "pi_greenlight"},
    )
    return tid, iid


def _wait_for_bg_segments(client: TestClient, timeout: float = 2.0) -> None:
    """Drive the event loop until the registered bg_segments set drains.

    The watchdog runs in a background asyncio task; tests need to wait for
    completion before asserting last_error / status changes.
    """
    loop = client.app.state.bg_segments
    async def _drain():
        deadline = asyncio.get_event_loop().time() + timeout
        while loop and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
    # asgi TestClient drives lifespan; we just use asyncio.run.
    asyncio.run(_drain())


def test_watchdog_happy_path_no_retry(watchdog_setup) -> None:
    """resume_segment advances on first call → no retry, no escalation."""
    client, store, runner = watchdog_setup
    tid, iid = _park_an_interrupt(store)
    runner.script_resume("advance")

    r = client.post(
        f"/inbox/{iid}/accept",
        json={"response_text": "ok"},
        params={"wait_segment": "false"},
    )
    assert r.status_code == 200
    _wait_for_bg_segments(client)

    assert runner.resume_calls == ["advance"]
    run = store.get_run(tid)
    # First-call advance parked a new interrupt → status flipped to
    # awaiting_pi by park_interrupt.
    assert run["status"] == "awaiting_pi"
    assert run["last_error"] is None


def test_watchdog_transient_stall_recovered(watchdog_setup) -> None:
    """Stall on call 1, advance on retry → success, no escalation."""
    client, store, runner = watchdog_setup
    tid, iid = _park_an_interrupt(store)
    runner.script_resume("stall", "advance")

    r = client.post(
        f"/inbox/{iid}/accept",
        json={"response_text": "ok"},
        params={"wait_segment": "false"},
    )
    assert r.status_code == 200
    _wait_for_bg_segments(client)

    assert runner.resume_calls == ["stall", "advance"]
    run = store.get_run(tid)
    assert run["status"] == "awaiting_pi"
    assert run["last_error"] is None


def test_watchdog_deterministic_stall_escalates(watchdog_setup) -> None:
    """Stall on call 1 AND retry → escalation to status='failed'."""
    client, store, runner = watchdog_setup
    tid, iid = _park_an_interrupt(store)
    runner.script_resume("stall", "stall")

    r = client.post(
        f"/inbox/{iid}/accept",
        json={"response_text": "ok"},
        params={"wait_segment": "false"},
    )
    assert r.status_code == 200
    _wait_for_bg_segments(client)

    assert runner.resume_calls == ["stall", "stall"]
    run = store.get_run(tid)
    assert run["status"] == "failed"
    assert run["last_error"] is not None
    assert "watchdog" in run["last_error"]
    assert "did not advance" in run["last_error"].lower() or "without advancing" in run["last_error"]


def test_watchdog_does_not_retry_when_exception_raised(watchdog_setup) -> None:
    """Exception on call 1 → existing exception path (no retry)."""
    client, store, runner = watchdog_setup
    tid, iid = _park_an_interrupt(store)
    runner.script_resume("raise")  # only one behavior — retry would AssertionError

    r = client.post(
        f"/inbox/{iid}/accept",
        json={"response_text": "ok"},
        params={"wait_segment": "false"},
    )
    assert r.status_code == 200
    _wait_for_bg_segments(client)

    assert runner.resume_calls == ["raise"]
    run = store.get_run(tid)
    assert run["status"] == "failed"
    assert "simulated crash" in run["last_error"]
    # Crucially, NOT a watchdog message — the standard exception path.
    assert "watchdog retry" not in run["last_error"]


def test_watchdog_set_identity_catches_park_then_answer_race() -> None:
    """If interrupt set IDENTITY changes (same count, different IDs),
    that counts as advance even when status / checkpoint look unchanged.
    """
    before = _make_probe(
        status="running",
        checkpoint_id="ckpt-1",
        pending=frozenset({"int_A"}),
    )
    after = _make_probe(
        status="running",
        checkpoint_id="ckpt-1",
        pending=frozenset({"int_B"}),
    )
    assert _probe_advanced(before, after) is True


# ---------------------------------------------------------------
# Runner-side hardening tests — _execute_segment defensive paths
# ---------------------------------------------------------------


class _FakeCompiledNonDict:
    def invoke(self, *args, **kwargs):
        return "not a dict"


class _FakeCompiledMissingTerminalState:
    def invoke(self, *args, **kwargs):
        # No __interrupt__, no terminal_state — the LangGraph internal
        # early-return shape.
        return {"current_node": "stuck_node", "usd_spent": 0.1}


class _FakeCompiledUnexpectedTerminalState:
    def invoke(self, *args, **kwargs):
        return {"terminal_state": "borked"}


def _make_runner_with_store() -> tuple[OrchestratorRunner, ParkedStore]:
    store = ParkedStore(":memory:")
    runner = OrchestratorRunner(
        store=store,
        sdk_factory=lambda *a, **k: None,
        mcp_factory=lambda *a, **k: None,
        saver_factory=lambda *a, **k: None,
    )
    return runner, store


def test_runner_explicit_failure_on_non_dict_output() -> None:
    """Non-dict output → status='failed' + last_error mentions non-dict.
    Previously fell through to terminal branch and AttributeError'd silently.
    """
    runner, store = _make_runner_with_store()
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        outcome = runner._execute_segment(tid, _FakeCompiledNonDict(), {})
        assert outcome.terminal_state == "failed"
        run = store.get_run(tid)
        assert run["status"] == "failed"
        assert "non-dict" in run["last_error"]
    finally:
        store.close()


def test_runner_missing_terminal_state_defaults_to_complete_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dict output with neither __interrupt__ nor terminal_state — the
    LangGraph internal early-return class for legitimate END nodes
    (Phase B bootstrap, onboarding subgraph, Phase O project onboarding).
    The runner now defaults to 'complete' (back-compat for END nodes
    that don't explicitly set terminal_state) but logs a warning so
    operators still see the empirical class. The Phase D2.6 watchdog
    catches the silent-stall failure mode authoritatively at the
    bg-task layer via checkpoint-id progress.
    """
    runner, store = _make_runner_with_store()
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        with caplog.at_level("WARNING", logger="orchestrator.runner"):
            outcome = runner._execute_segment(
                tid, _FakeCompiledMissingTerminalState(), {}
            )
        assert outcome.terminal_state == "complete"
        run = store.get_run(tid)
        assert run["status"] == "complete"
        # Warning must mention the missing terminal_state and that the
        # watchdog covers the silent-stall class.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "without terminal_state" in r.message for r in warnings
        ), warnings
        assert any(
            "watchdog" in r.message.lower() for r in warnings
        ), warnings
    finally:
        store.close()


def test_runner_normalises_unexpected_terminal_state_to_complete() -> None:
    """Unexpected (non-complete/escalated/failed) terminal_state value —
    we still tolerate but normalise to 'complete' rather than silently
    accepting an unknown status. Back-compat preserved.
    """
    runner, store = _make_runner_with_store()
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        outcome = runner._execute_segment(
            tid, _FakeCompiledUnexpectedTerminalState(), {}
        )
        assert outcome.terminal_state == "complete"
        run = store.get_run(tid)
        assert run["status"] == "complete"
    finally:
        store.close()


# ---------------------------------------------------------------
# Adversarial-review-derived tests — terminal_safe guards,
# start-path watchdog firing, last_error truncation, cache_sync
# after retry, None-output runner path
# ---------------------------------------------------------------


def test_update_run_terminal_safe_rejects_overwrite_of_cancelled() -> None:
    """Phase D2.6 — `terminal_safe=True` on parked_store.update_run
    refuses to overwrite a run that's already in a terminal status.
    Symmetric with the Phase D2.1 cancel_run guard.
    """
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        store.cancel_run(tid)
        assert store.get_run(tid)["status"] == "cancelled"
        # Without terminal_safe: would overwrite (legacy behaviour).
        # With terminal_safe=True: refuses, returns 0 rows updated.
        rows = store.update_run(
            tid, terminal_safe=True,
            status="failed", last_error="watchdog says failed",
        )
        assert rows == 0
        assert store.get_run(tid)["status"] == "cancelled"
        # Without the guard, the same call WOULD overwrite — pin that
        # as the (legacy / non-watchdog) baseline.
        rows2 = store.update_run(
            tid, status="failed", last_error="legacy overwrite",
        )
        assert rows2 == 1
        assert store.get_run(tid)["status"] == "failed"
    finally:
        store.close()


def test_update_run_terminal_safe_allows_running_state() -> None:
    """terminal_safe=True still permits writes when the run is
    actively 'running' (i.e., the intended pre-terminal state)."""
    store = ParkedStore(":memory:")
    try:
        tid = store.create_run(mission_id="m", project_id="p")
        # Default status from create_run is 'running'.
        rows = store.update_run(
            tid, terminal_safe=True,
            status="failed", last_error="legit failure",
        )
        assert rows == 1
        assert store.get_run(tid)["status"] == "failed"
    finally:
        store.close()


def test_watchdog_escalation_does_not_overwrite_cancelled(watchdog_setup) -> None:
    """If a cancel races with the watchdog's escalation (deterministic
    stall path), terminal_safe=True ensures the cancel wins. The
    watchdog escalation does NOT clobber status='cancelled' back to
    'failed'."""
    client, store, runner = watchdog_setup
    tid, iid = _park_an_interrupt(store)
    # Script: stall, then a side-effect that cancels the run while
    # stalling. This simulates a PI DELETE /runs/{id} landing during
    # the watchdog's retry await.
    runner.script_resume("stall", "stall")

    # Pre-cancel the run BEFORE the retry's escalation fires by patching
    # the retry's pre-update probe path. Simpler: cancel mid-stall via
    # a side-effect on the second resume_segment call.
    original_resume = runner.resume_segment
    cancel_armed = {"done": False}

    def resume_with_cancel_after(**kwargs):
        # On the SECOND resume_segment call (the retry), cancel the run
        # AFTER the stall returns but BEFORE the post-retry probe.
        # The escalation UPDATE then must NOT overwrite cancelled.
        out = original_resume(**kwargs)
        if not cancel_armed["done"] and len(runner.resume_calls) == 2:
            cancel_armed["done"] = True
            store.cancel_run(kwargs["workflow_thread_id"])
        return out

    runner.resume_segment = resume_with_cancel_after

    r = client.post(
        f"/inbox/{iid}/accept",
        json={"response_text": "ok"},
        params={"wait_segment": "false"},
    )
    assert r.status_code == 200
    _wait_for_bg_segments(client)

    # The cancel must win — terminal_safe guard on the escalation UPDATE.
    run = store.get_run(tid)
    assert run["status"] == "cancelled", (
        f"watchdog escalation overwrote cancellation; status={run['status']}, "
        f"last_error={run['last_error']!r}"
    )


def test_watchdog_truncates_last_error_to_500_chars(watchdog_setup) -> None:
    """The Phase D2.6 escalation last_error is `[:500]`-capped. Pin it
    so a future refactor that drops the cap doesn't leak unbounded
    error text into PI surfaces."""
    client, store, runner = watchdog_setup
    tid, iid = _park_an_interrupt(store)

    # Use the exception path — last_error includes repr(e), so a long
    # exception message stress-tests the truncation.
    long_msg = "x" * 5000

    def raise_with_long_message(**kwargs):
        runner.resume_calls.append("raise")
        raise RuntimeError(long_msg)

    runner.resume_segment = raise_with_long_message

    r = client.post(
        f"/inbox/{iid}/accept",
        json={"response_text": "ok"},
        params={"wait_segment": "false"},
    )
    assert r.status_code == 200
    _wait_for_bg_segments(client)

    run = store.get_run(tid)
    assert run["status"] == "failed"
    assert len(run["last_error"]) <= 500


def test_watchdog_fires_on_start_run_drive_stall() -> None:
    """The shared _background_segment helper is also wired into /runs
    `wait_segment=false`. A stall on the first start_run_drive must
    trigger the same probe-and-retry. Covers the gap where only the
    /inbox/{id}/accept path was integration-tested.
    """
    store = ParkedStore(":memory:")
    runner = _WatchdogFakeRunner(store)
    app = create_app(store=store, runner=runner, enforce_mount_safety=False)
    client = TestClient(app)
    try:
        with client:
            runner.script_start_run_drive("stall", "advance")
            r = client.post(
                "/runs",
                json={
                    "mission_id": "mis_test", "project_id": "prj_test",
                    "workflow_thread_id": "thr_start_test",
                },
                params={"wait_segment": "false"},
            )
            assert r.status_code == 200
            _wait_for_bg_segments(client)

            assert runner.start_run_drive_calls == ["stall", "advance"]
            run = store.get_run("thr_start_test")
            assert run["status"] == "awaiting_pi"
            assert run["last_error"] is None
    finally:
        store.close()


def test_watchdog_fires_on_start_onboarding_drive_stall() -> None:
    """Same as above for the /onboard async-start path."""
    store = ParkedStore(":memory:")
    runner = _WatchdogFakeRunner(store)
    app = create_app(store=store, runner=runner, enforce_mount_safety=False)
    client = TestClient(app)
    try:
        with client:
            runner.script_start_onboarding_drive("stall", "advance")
            r = client.post(
                "/onboard",
                json={
                    "project_id": "prj_onb",
                    "workflow_thread_id": "thr_onb_test",
                },
                params={"wait_segment": "false"},
            )
            assert r.status_code == 200
            _wait_for_bg_segments(client)

            assert runner.start_onboarding_drive_calls == ["stall", "advance"]
            run = store.get_run("thr_onb_test")
            assert run["status"] == "awaiting_pi"
    finally:
        store.close()


def test_watchdog_fires_on_start_phase_b_drive_stall() -> None:
    """Same as above for the /bootstrap async-start path."""
    store = ParkedStore(":memory:")
    runner = _WatchdogFakeRunner(store)
    app = create_app(store=store, runner=runner, enforce_mount_safety=False)
    client = TestClient(app)
    try:
        with client:
            runner.script_start_phase_b_drive("stall", "advance")
            r = client.post(
                "/bootstrap",
                json={"workflow_thread_id": "thr_phb_test"},
                params={"wait_segment": "false"},
            )
            assert r.status_code == 200
            _wait_for_bg_segments(client)

            assert runner.start_phase_b_drive_calls == ["stall", "advance"]
            run = store.get_run("thr_phb_test")
            assert run["status"] == "awaiting_pi"
    finally:
        store.close()


def test_runner_explicit_failure_on_none_output() -> None:
    """compiled.invoke() returning None lands on the same non-dict
    path as other non-dict shapes. last_error mentions the type
    so operators know what they got."""
    runner, store = _make_runner_with_store()

    class _NoneCompiled:
        def invoke(self, *a, **kw):
            return None

    try:
        tid = store.create_run(mission_id="m", project_id="p")
        outcome = runner._execute_segment(tid, _NoneCompiled(), {})
        assert outcome.terminal_state == "failed"
        run = store.get_run(tid)
        assert run["status"] == "failed"
        assert "NoneType" in run["last_error"] or "non-dict" in run["last_error"]
    finally:
        store.close()
