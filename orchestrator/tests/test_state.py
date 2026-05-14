"""Unit tests for the workflow state schema (T2).

These verify:

  - Reducer semantics for the 5 append-only collections.
  - `make_initial_state` produces a valid baseline.
  - Phase / consensus / terminal Literal enumerations match the documented
    surface and stay closed (i.e. no accidental string leaks).
  - Sub-record `TypedDict`s accept their documented fields.
  - LangGraph-style state-merge mechanics work end-to-end against the schema.

T11 will expand to ≥50 unit tests; this file is the seed.
"""

from __future__ import annotations

import operator
import typing
from typing import get_args, get_type_hints

import pytest

from orchestrator import state as state_mod
from orchestrator.state import (
    ALL_CONSENSUS_STATES,
    ALL_PHASES,
    ALL_TERMINAL_STATES,
    ArtifactRef,
    CheckpointRecord,
    ConsensusState,
    ErrorRecord,
    InterruptRecord,
    NotificationRecord,
    ResearchWorkflowState,
    TerminalState,
    WorkflowPhase,
    make_initial_state,
)


# ---------------------------------------------------------------------------
# `make_initial_state` baseline
# ---------------------------------------------------------------------------


def test_initial_state_carries_identity_fields():
    s = make_initial_state(
        workflow_thread_id="thr_abc",
        mission_id="mis_xyz",
        motivated_by_decision_id="dec_123",
    )
    assert s["workflow_thread_id"] == "thr_abc"
    assert s["mission_id"] == "mis_xyz"
    assert s["motivated_by_decision_id"] == "dec_123"


def test_initial_state_starts_in_init_phase():
    s = make_initial_state(
        workflow_thread_id="t", mission_id="m", motivated_by_decision_id="d"
    )
    assert s["current_phase"] == "init"
    assert s["consensus_state"] == "unresolved"


def test_initial_state_collections_are_empty_lists():
    s = make_initial_state(
        workflow_thread_id="t", mission_id="m", motivated_by_decision_id="d"
    )
    assert s["artifacts"] == []
    assert s["interrupts"] == []
    assert s["checkpoints"] == []
    assert s["errors"] == []
    assert s["notifications"] == []


def test_initial_state_budget_starts_at_zero():
    s = make_initial_state(
        workflow_thread_id="t", mission_id="m", motivated_by_decision_id="d"
    )
    assert s["usd_spent"] == 0.0
    assert s["loop_iterations"] == 0


def test_initial_state_batch_review_starts_inactive():
    # Obs #15: batch-review only activates when the payload crosses
    # PI_BATCH_REVIEW_THRESHOLD. Baseline = inactive.
    s = make_initial_state(
        workflow_thread_id="t", mission_id="m", motivated_by_decision_id="d"
    )
    assert s["batch_review_active"] is False
    assert s["batch_review_payload_size"] == 0


# ---------------------------------------------------------------------------
# Phase / consensus / terminal enumerations
# ---------------------------------------------------------------------------


def test_workflow_phase_enumerates_thirteen_values():
    # Decision spec specifies the phase set; locking the count prevents
    # silent enum drift between state.py and the topology in T7.
    assert len(ALL_PHASES) == 13


def test_workflow_phase_includes_required_pi_phases():
    # Three PI interaction nodes (T5) → three PI phases.
    assert "pi_greenlight" in ALL_PHASES
    assert "pi_decision" in ALL_PHASES
    assert "pi_acceptance" in ALL_PHASES


def test_workflow_phase_includes_three_terminal_phases():
    assert {"complete", "escalated", "failed"} <= ALL_PHASES


def test_consensus_state_has_three_legal_values():
    assert ALL_CONSENSUS_STATES == {"agreed", "disagree", "unresolved"}


def test_terminal_state_matches_terminal_phases():
    # The terminal-phase set in `WorkflowPhase` and the standalone
    # `TerminalState` literal must agree, or routing bugs become silent.
    assert ALL_TERMINAL_STATES == {"complete", "escalated", "failed"}
    assert ALL_TERMINAL_STATES <= ALL_PHASES


# ---------------------------------------------------------------------------
# Reducer semantics — append-only collections
# ---------------------------------------------------------------------------


def _reducer_for(state_class, field: str):
    """Pull the `operator.add`-style reducer off an Annotated field."""
    hints = get_type_hints(state_class, include_extras=True)
    annotated_type = hints[field]
    metadata = annotated_type.__metadata__
    assert metadata, f"{field} should be Annotated[..., reducer]"
    return metadata[0]


@pytest.mark.parametrize(
    "field",
    ["artifacts", "interrupts", "checkpoints", "errors", "notifications"],
)
def test_append_only_fields_use_operator_add_reducer(field):
    reducer = _reducer_for(ResearchWorkflowState, field)
    assert reducer is operator.add, (
        f"{field}'s reducer must be `operator.add` so concurrent node "
        f"updates concatenate rather than overwrite."
    )


def test_artifacts_reducer_concatenates():
    reducer = _reducer_for(ResearchWorkflowState, "artifacts")
    a1: ArtifactRef = {"rka_id": "jrn_a", "entity_type": "journal", "node_name": "n1"}
    a2: ArtifactRef = {"rka_id": "dec_b", "entity_type": "decision", "node_name": "n2"}
    a3: ArtifactRef = {"rka_id": "mis_c", "entity_type": "mission", "node_name": "n3"}
    assert reducer([a1], [a2, a3]) == [a1, a2, a3]


def test_interrupts_reducer_concatenates_in_order():
    reducer = _reducer_for(ResearchWorkflowState, "interrupts")
    i1: InterruptRecord = {"node_name": "pi_greenlight", "payload_size": 1}
    i2: InterruptRecord = {"node_name": "pi_decision_select", "payload_size": 8}
    combined = reducer([i1], [i2])
    assert combined[0]["node_name"] == "pi_greenlight"
    assert combined[1]["node_name"] == "pi_decision_select"


def test_errors_reducer_preserves_failure_history():
    reducer = _reducer_for(ResearchWorkflowState, "errors")
    e1: ErrorRecord = {"node_name": "consensus_check", "error_type": "consensus_loop_exceeded"}
    e2: ErrorRecord = {"node_name": "budget_check", "error_type": "budget_exceeded"}
    assert reducer([e1], [e2]) == [e1, e2]
    # Empty + non-empty still works.
    assert reducer([], [e1]) == [e1]
    assert reducer([e1], []) == [e1]


def test_notifications_reducer_concatenates():
    reducer = _reducer_for(ResearchWorkflowState, "notifications")
    n1: NotificationRecord = {"channel": "bell", "message": "PI needed"}
    n2: NotificationRecord = {"channel": "osascript", "message": "PI needed"}
    assert reducer([], [n1, n2]) == [n1, n2]


def test_checkpoints_reducer_concatenates():
    reducer = _reducer_for(ResearchWorkflowState, "checkpoints")
    c1: CheckpointRecord = {"chk_id": "chk_1", "type": "decision", "reason": "x", "resolved": False}
    c2: CheckpointRecord = {"chk_id": "chk_2", "type": "clarification", "reason": "y", "resolved": True}
    assert reducer([c1], [c2]) == [c1, c2]


# ---------------------------------------------------------------------------
# Sub-record shape validation
# ---------------------------------------------------------------------------


def test_artifact_ref_accepts_known_rka_prefixes():
    # The schema doesn't validate prefixes at runtime (TypedDict is structural),
    # but the documented surface should support all canonical RKA IDs.
    for prefix in ("jrn_", "dec_", "mis_", "clm_", "chk_", "ecl_", "lit_"):
        rec: ArtifactRef = {"rka_id": f"{prefix}abc", "entity_type": prefix.strip("_"), "node_name": "n"}
        assert rec["rka_id"].startswith(prefix)


def test_interrupt_record_captures_batch_review_metadata():
    # Obs #15: a batched PI presentation must record both the size and the
    # flag so post-run analytics can see whether the affordance fired.
    rec: InterruptRecord = {
        "node_name": "pi_decision_select",
        "payload_size": 15,
        "response": "option-3",
        "timestamp": "2026-05-14T10:00:00Z",
        "batch_review_used": True,
    }
    assert rec["batch_review_used"] is True
    assert rec["payload_size"] == 15


# ---------------------------------------------------------------------------
# Scalar last-write-wins semantics (LangGraph default)
# ---------------------------------------------------------------------------


def test_scalar_fields_lack_reducer_metadata():
    # Scalars use LangGraph's default last-write-wins. Verifying they are
    # NOT annotated with a reducer guards against accidentally adding one
    # (which would break budget tracking).
    hints = get_type_hints(ResearchWorkflowState, include_extras=True)
    for scalar_field in (
        "usd_spent",
        "loop_iterations",
        "current_phase",
        "consensus_state",
        "workflow_thread_id",
        "mission_id",
    ):
        t = hints[scalar_field]
        assert not hasattr(t, "__metadata__"), (
            f"{scalar_field} should NOT have an Annotated reducer; "
            f"scalars use last-write-wins."
        )


# ---------------------------------------------------------------------------
# State module exports — guards against accidental rename
# ---------------------------------------------------------------------------


def test_state_module_exposes_canonical_names():
    expected = {
        "ResearchWorkflowState",
        "WorkflowPhase",
        "ConsensusState",
        "TerminalState",
        "ArtifactRef",
        "InterruptRecord",
        "CheckpointRecord",
        "ErrorRecord",
        "NotificationRecord",
        "make_initial_state",
        "ALL_PHASES",
        "ALL_CONSENSUS_STATES",
        "ALL_TERMINAL_STATES",
    }
    actual = {n for n in dir(state_mod) if not n.startswith("_")}
    missing = expected - actual
    assert not missing, f"state module is missing: {missing}"
