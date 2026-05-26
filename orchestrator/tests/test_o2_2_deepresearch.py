"""Phase O, O2.2 — pi_deepresearch_prompt (async-pause) tests.

Covers:
  - Payload shape: prompt, project_id, async_pause flag, tag_to_query, floor
  - Accept path with sufficient literature → deepresearch_complete=True, no warning
  - Accept path with insufficient literature → soft-warning notification emitted
  - Reject path → deepresearch_complete=False, no MCP query
  - InterruptRecord shape
  - MCP query failure is tolerated (no exception bubbles up)
  - Async-pause regression: state survives a process restart via SqliteSaver
    (the parked interrupt persists across ParkedStore close/reopen)
  - parked_store accepts pi_deepresearch_prompt type
  - runner _ACCEPT_TOKEN_BY_TYPE maps pi_deepresearch_prompt → 'accept'
  - runner _ONBOARDING_INTERRUPT_TYPES contains pi_deepresearch_prompt
  - graph.ONBOARDING_NODE_NAMES contains pi_deepresearch_prompt
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import graph
from orchestrator.nodes import pi
from orchestrator.parked_store import ParkedStore
from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE, OrchestratorRunner

from tests._fakes import FakeMCP, FakeSDK


# ---------------------------------------------------------------------------
# Payload + accept/reject behavior
# ---------------------------------------------------------------------------


def test_pi_deepresearch_prompt_payload_shape():
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "accept"

    pi.pi_deepresearch_prompt(
        {"project_id": "prj_test_01", "current_phase": "init"},
        FakeSDK(),
        FakeMCP(),
        fake_interrupt,
    )
    p = captured["payload"]
    assert p["type"] == "pi_deepresearch_prompt"
    assert "async" in p["title"].lower() or "deep research" in p["title"].lower()
    assert p["async_pause"] is True
    assert p["project_id"] == "prj_test_01"
    assert p["tag_to_query"] == ["prj_test_01", "literature"]
    assert p["minimum_paper_floor"] == 5
    # Prompt should mention rka_enrich_doi and rka_add_literature.
    assert "rka_enrich_doi" in p["prompt"]
    assert "rka_add_literature" in p["prompt"]
    # Prompt substitutes the project_id.
    assert "prj_test_01" in p["prompt"]


def test_pi_deepresearch_accept_with_sufficient_literature_no_warning():
    """≥ 5 literature entries → deepresearch_complete=True, no warning."""
    mcp = FakeMCP()
    mcp.journal_response = [
        {"id": f"jrn_lit_{i:02d}", "tags": ["prj_test", "literature"]}
        for i in range(7)
    ]
    out = pi.pi_deepresearch_prompt(
        {"project_id": "prj_test"},
        FakeSDK(),
        mcp,
        lambda _p: "accept",
    )
    assert out["deepresearch_complete"] is True
    assert "notifications" not in out


def test_pi_deepresearch_accept_with_insufficient_literature_emits_warning():
    """< 5 literature → deepresearch_complete=True, soft warning notification."""
    mcp = FakeMCP()
    mcp.journal_response = [
        {"id": "jrn_lit_01", "tags": ["prj_test", "literature"]},
        {"id": "jrn_lit_02", "tags": ["prj_test", "literature"]},
    ]
    out = pi.pi_deepresearch_prompt(
        {"project_id": "prj_test"},
        FakeSDK(),
        mcp,
        lambda _p: "accept",
    )
    assert out["deepresearch_complete"] is True
    assert "notifications" in out
    notif = out["notifications"][0]
    assert notif["channel"] == "bell"
    assert "soft floor" in notif["message"]
    assert "2 literature" in notif["message"]
    assert notif["delivered"] is False


def test_pi_deepresearch_accept_with_zero_literature_emits_warning():
    """Edge case: PI hit accept without ingesting any papers."""
    out = pi.pi_deepresearch_prompt(
        {"project_id": "prj_test"},
        FakeSDK(),
        FakeMCP(),  # empty journal_response
        lambda _p: "accept",
    )
    assert out["deepresearch_complete"] is True
    assert "0 literature" in out["notifications"][0]["message"]


def test_pi_deepresearch_reject_skips_literature_query():
    """Reject → deepresearch_complete=False, MCP not queried for count."""
    mcp = FakeMCP()
    out = pi.pi_deepresearch_prompt(
        {"project_id": "prj_test"},
        FakeSDK(),
        mcp,
        lambda _p: "reject",
    )
    assert out["deepresearch_complete"] is False
    # No rka_get_journal call (no count needed on reject).
    assert not any(c["op"] == "rka_get_journal" for c in mcp.calls)
    assert "notifications" not in out


def test_pi_deepresearch_records_interrupt():
    out = pi.pi_deepresearch_prompt(
        {"project_id": "prj_test"},
        FakeSDK(),
        FakeMCP(),
        lambda _p: "accept",
    )
    assert len(out["interrupts"]) == 1
    rec = out["interrupts"][0]
    assert rec["node_name"] == "pi_deepresearch_prompt"
    assert rec["response"] == "accept"


def test_pi_deepresearch_tolerates_mcp_failure_on_accept():
    """If RKA is unreachable during the literature count, deepresearch
    should still mark complete (the PI's accept is the durable signal)
    and emit the soft warning (count=0 by fallback)."""

    class _RaisingMCP(FakeMCP):
        def rka_get_journal(self, **_kw):
            raise RuntimeError("RKA unreachable")

    out = pi.pi_deepresearch_prompt(
        {"project_id": "prj_test"},
        FakeSDK(),
        _RaisingMCP(),
        lambda _p: "accept",
    )
    assert out["deepresearch_complete"] is True
    # MCP failure means count = 0, so the warning fires.
    assert "notifications" in out


# ---------------------------------------------------------------------------
# Async-pause regression: state survives a ParkedStore close/reopen
# ---------------------------------------------------------------------------


def test_async_pause_parked_state_survives_store_restart(tmp_path):
    """The Phase O design relies on the PI being able to close Claude
    Desktop and come back hours/days later. The parked-interrupt row
    must persist across a ParkedStore close and a fresh-process open
    against the same DB file. This regression test simulates the
    long-pause + restart by closing the store and re-opening it.
    """
    db_path = str(tmp_path / "parked.db")
    store = ParkedStore(db_path)
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    interrupt_id = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_deepresearch_prompt",
        payload={
            "type": "pi_deepresearch_prompt",
            "title": "async test",
            "project_id": "prj_x",
        },
    )
    # Verify pending.
    assert store.get_interrupt(interrupt_id)["status"] == "pending"
    store.close()

    # Simulate process restart hours later — fresh ParkedStore against
    # the same DB file.
    store2 = ParkedStore(db_path)
    parked = store2.get_interrupt(interrupt_id)
    assert parked is not None
    assert parked["status"] == "pending"
    assert parked["interrupt_type"] == "pi_deepresearch_prompt"
    assert parked["payload"]["project_id"] == "prj_x"
    # Run state recoverable too.
    run = store2.get_run(thread_id)
    assert run["status"] == "awaiting_pi"
    store2.close()


# ---------------------------------------------------------------------------
# Schema + registry wiring
# ---------------------------------------------------------------------------


def test_parked_store_accepts_pi_deepresearch_prompt():
    store = ParkedStore(":memory:")
    thread_id = store.create_run(mission_id="prj_x", project_id="prj_x")
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="prj_x",
        interrupt_type="pi_deepresearch_prompt",
        payload={"type": "pi_deepresearch_prompt", "title": "x"},
    )
    assert iid.startswith("int_")
    store.close()


def test_runner_accept_token_for_deepresearch_is_accept():
    assert _ACCEPT_TOKEN_BY_TYPE["pi_deepresearch_prompt"] == "accept"


def test_runner_recognizes_pi_deepresearch_as_onboarding():
    assert "pi_deepresearch_prompt" in OrchestratorRunner._ONBOARDING_INTERRUPT_TYPES


def test_graph_onboarding_node_names_include_pi_deepresearch_prompt():
    assert "pi_deepresearch_prompt" in graph.ONBOARDING_NODE_NAMES
