"""Tests for orchestrator/parked_store.py.

Covers the CRUD contract on `workflow_runs` + `parked_interrupts`. Uses
in-memory sqlite (`":memory:"`) — schema is initialized idempotently on
ParkedStore construction.
"""

from __future__ import annotations

import pytest

from orchestrator.parked_store import ParkedStore


@pytest.fixture
def store() -> ParkedStore:
    s = ParkedStore(":memory:")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# workflow_runs
# ---------------------------------------------------------------------------


def test_create_run_returns_thread_id_and_persists(store: ParkedStore):
    thread_id = store.create_run(
        mission_id="mis_test_001", project_id="prj_test", budget_usd=3.5
    )
    assert thread_id.startswith("thr_")
    row = store.get_run(thread_id)
    assert row is not None
    assert row["mission_id"] == "mis_test_001"
    assert row["project_id"] == "prj_test"
    assert row["budget_usd"] == 3.5
    assert row["status"] == "running"


def test_create_run_honors_explicit_thread_id(store: ParkedStore):
    thread_id = store.create_run(
        mission_id="mis_test_002",
        project_id="prj_test",
        workflow_thread_id="thr_explicit",
    )
    assert thread_id == "thr_explicit"
    row = store.get_run("thr_explicit")
    assert row is not None


def test_update_run_patches_columns_and_bumps_updated_at(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    before = store.get_run(tid)["updated_at"]
    # Force timestamp granularity (strftime is second-precision).
    import time
    time.sleep(1.01)
    store.update_run(tid, status="complete", current_node="pi_acceptance")
    after = store.get_run(tid)
    assert after["status"] == "complete"
    assert after["current_node"] == "pi_acceptance"
    assert after["updated_at"] > before


def test_update_run_rejects_unknown_columns(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    with pytest.raises(ValueError, match="unknown columns"):
        store.update_run(tid, bogus_column="x")


def test_list_runs_filters_by_status_and_orders_desc(store: ParkedStore):
    import time
    store.create_run(mission_id="m1", project_id="p")
    time.sleep(1.01)
    t2 = store.create_run(mission_id="m2", project_id="p")
    time.sleep(1.01)
    store.create_run(mission_id="m3", project_id="p")
    all_runs = store.list_runs()
    # Pre-update_run ordering: newest-created first.
    assert [r["mission_id"] for r in all_runs] == ["m3", "m2", "m1"]
    # update_run bumps updated_at, so m2 should now lead.
    time.sleep(1.01)
    store.update_run(t2, status="complete")
    all_runs = store.list_runs()
    assert [r["mission_id"] for r in all_runs] == ["m2", "m3", "m1"]
    running = store.list_runs(status="running")
    assert {r["mission_id"] for r in running} == {"m1", "m3"}


# ---------------------------------------------------------------------------
# parked_interrupts
# ---------------------------------------------------------------------------


def test_park_interrupt_inserts_pending_and_flips_run_to_awaiting_pi(
    store: ParkedStore,
):
    tid = store.create_run(mission_id="m", project_id="p")
    payload = {"type": "pi_greenlight", "items": [{"x": 1}], "total_items": 1}
    iid = store.park_interrupt(
        workflow_thread_id=tid,
        mission_id="m",
        interrupt_type="pi_greenlight",
        payload=payload,
    )
    assert iid.startswith("int_")
    row = store.get_interrupt(iid)
    assert row["status"] == "pending"
    assert row["interrupt_type"] == "pi_greenlight"
    assert row["payload"] == payload
    assert store.get_run(tid)["status"] == "awaiting_pi"


def test_list_pending_interrupts_orders_oldest_first(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    import time
    i1 = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={"k": 1},
    )
    time.sleep(1.01)
    i2 = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={"k": 2},
    )
    pending = store.list_pending_interrupts()
    assert [r["interrupt_id"] for r in pending] == [i1, i2]


def test_list_pending_interrupts_filters_by_thread(store: ParkedStore):
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
    out = store.list_pending_interrupts(workflow_thread_id=t1)
    assert len(out) == 1
    assert out[0]["mission_id"] == "m1"


def test_answer_interrupt_marks_answered_and_records_action(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    updated = store.answer_interrupt(
        interrupt_id=iid, response_action="accept", response_text="accept"
    )
    assert updated["status"] == "answered"
    assert updated["response_action"] == "accept"
    assert updated["response_text"] == "accept"
    assert updated["responded_at"] is not None


def test_answer_interrupt_rejects_double_answer(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    iid = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    store.answer_interrupt(
        interrupt_id=iid, response_action="accept", response_text="approve"
    )
    with pytest.raises(ValueError, match="already in status"):
        store.answer_interrupt(
            interrupt_id=iid, response_action="accept", response_text="approve"
        )


def test_answer_interrupt_raises_for_unknown_id(store: ParkedStore):
    with pytest.raises(ValueError, match="not found"):
        store.answer_interrupt(
            interrupt_id="int_bogus", response_action="accept",
            response_text="approve",
        )


def test_cancel_run_marks_pending_interrupts_cancelled(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    count = store.cancel_run(tid)
    assert count == 2
    assert store.get_run(tid)["status"] == "cancelled"
    assert store.list_pending_interrupts(workflow_thread_id=tid) == []


def test_cancel_run_leaves_answered_interrupts_alone(store: ParkedStore):
    tid = store.create_run(mission_id="m", project_id="p")
    iid_answered = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_greenlight", payload={},
    )
    store.answer_interrupt(
        interrupt_id=iid_answered, response_action="accept",
        response_text="approve",
    )
    iid_pending = store.park_interrupt(
        workflow_thread_id=tid, mission_id="m",
        interrupt_type="pi_decision_select", payload={},
    )
    count = store.cancel_run(tid)
    assert count == 1
    # The already-answered interrupt stays answered.
    assert store.get_interrupt(iid_answered)["status"] == "answered"
    assert store.get_interrupt(iid_pending)["status"] == "cancelled"
