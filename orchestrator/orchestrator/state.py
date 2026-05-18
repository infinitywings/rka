"""ResearchWorkflowState — LangGraph state schema for the Phase 1 orchestrator.

The state is a `TypedDict` with `total=False` (every field is optional at any
checkpoint). Append-only collections use `Annotated[list[T], operator.add]`
so LangGraph's checkpointer merges concurrent node-writes by concatenation
instead of overwriting. Scalars use last-write-wins (default).

Three-storage discipline:

  - **RKA SQLite** owns domain truth (decisions, missions, journals).
  - **LangGraph SqliteSaver** owns workflow position (which node ran).
  - **This state dict** owns transient per-run context. Persistence happens
    via the SqliteSaver checkpointer — not by writing state values back to
    RKA. RKA writes go through `mcp_client` and are tagged with
    `workflow_thread_id` so they can be traced back to the run.

The schema must be stable across T3-T6 implementation: every node reads
fields documented here and writes only the documented surface. T11 audit
checks that no node writes undocumented keys.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

# ---------------------------------------------------------------------------
# Workflow phase enumeration
# ---------------------------------------------------------------------------

WorkflowPhase = Literal[
    "init",
    "brain_strategy",
    "brain_confirmation",
    "executor_backbrief",
    "executor_mission",
    "executor_report",
    "brain_review",
    "pi_greenlight",
    "pi_decision",
    "pi_acceptance",
    "complete",
    "escalated",
    "failed",
]
"""Every legal value of `state["current_phase"]`. The graph topology in
T7 will validate that the routing transitions land on one of these."""

ConsensusState = Literal["agreed", "disagree", "unresolved"]
"""Brain ⇄ Executor consensus result. `unresolved` means the loop is
still running; `disagree` after `MAX_LOOP_DEPTH` triggers escalation."""

TerminalState = Literal["complete", "escalated", "failed"]
"""Terminal state set by the final node before the workflow exits."""

# ---------------------------------------------------------------------------
# Sub-record shapes
# ---------------------------------------------------------------------------


class ArtifactRef(TypedDict, total=False):
    """One RKA entity created during the run, tagged with the producing node."""

    rka_id: str  # jrn_…, dec_…, mis_…, clm_…, chk_…
    entity_type: str  # "journal" | "decision" | "mission" | "claim" | "checkpoint"
    node_name: str  # which orchestrator node produced it
    timestamp: str  # ISO 8601 UTC


class InterruptRecord(TypedDict, total=False):
    """One PI `interrupt()` event — captures payload size for obs #15."""

    node_name: str  # pi_greenlight | pi_decision_select | pi_acceptance
    payload_size: int  # # items presented (for batch-review affordance)
    response: str  # serialized PI response (option chosen / verbatim input)
    timestamp: str  # ISO 8601 UTC
    batch_review_used: bool  # True if this interrupt presented a batched view


class CheckpointRecord(TypedDict, total=False):
    """One `rka_submit_checkpoint` outcome surfaced from the wrapper."""

    chk_id: str
    type: Literal["decision", "clarification"]
    reason: str
    resolved: bool


class ErrorRecord(TypedDict, total=False):
    """One escalation-class failure (caught + routed, not a Python exception)."""

    node_name: str
    error_type: str  # "consensus_loop_exceeded" | "budget_exceeded" | "mcp_error" | ...
    detail: str
    timestamp: str


class NotificationRecord(TypedDict, total=False):
    """One PI notification sent by the T8 daemon — bell, osascript, or webhook."""

    channel: Literal["bell", "osascript", "webhook"]
    message: str
    timestamp: str
    delivered: bool


# ---------------------------------------------------------------------------
# Top-level state
# ---------------------------------------------------------------------------


class ResearchWorkflowState(TypedDict, total=False):
    """Phase 1 workflow state. All fields optional (total=False) so partial
    node-updates merge cleanly through the checkpointer.

    **Identity + RKA linkage**

    - `workflow_thread_id` — UUID-flavored tag attached to every RKA write
      so artifacts produced during this run can be located via
      `rka_get_journal(tags=[workflow_thread_id])`. Mirrors the v2.3.5
      Affordance F convention.
    - `mission_id` — `mis_…` ID being executed.
    - `motivated_by_decision_id` — `dec_…` providing the why.

    **Position**

    - `current_phase` — see `WorkflowPhase`.
    - `current_node` — last node that wrote state (resume hint).
    - `next_node_override` — explicit routing target; takes precedence over
      the default edge if set.

    **Brain ⇄ Executor synthesis**

    - `brain_strategy` — Brain's most recent strategy summary text.
    - `executor_backbrief` — Executor's most recent Backbrief text.
    - `gate1_verdict` — "approved" | "redirected" | None (Brain's Gate 1 result).

    **Append-only collections** (each merged via `operator.add` reducer)

    - `artifacts`        — list of `ArtifactRef`
    - `interrupts`       — list of `InterruptRecord`
    - `checkpoints`      — list of `CheckpointRecord`
    - `errors`           — list of `ErrorRecord`
    - `notifications`    — list of `NotificationRecord`

    **Budget tracking** (last-write-wins scalars)

    - `usd_spent` — running cost in USD.
    - `loop_iterations` — number of Brain⇄Executor disagreement cycles.

    **Consensus tracking**

    - `brain_position` — Brain's current position summary.
    - `executor_position` — Executor's current position summary.
    - `consensus_state` — see `ConsensusState`.

    **Decision-presentation queue**

    - `decisions_to_present` — list of dicts staged for `pi_decision_select`.
      Each dict has shape `{title, options: [...], context}`.

    **Batch-review (rehearsal obs #15)**

    - `batch_review_active` — currently presenting a batched view to PI.
    - `batch_review_payload_size` — # items in the current batch.

    **Termination**

    - `terminal_state` — set once by the final node before exit.
    - `final_report_id` — `rep_…` ID emitted by `executor.submit_report`.
    """

    # Identity / RKA linkage
    workflow_thread_id: str
    mission_id: str
    motivated_by_decision_id: str

    # Position
    current_phase: WorkflowPhase
    current_node: str
    next_node_override: str

    # Brain ⇄ Executor synthesis
    brain_strategy: str
    executor_backbrief: str
    gate1_verdict: Literal["approved", "redirected"]

    # Append-only collections
    artifacts: Annotated[list[ArtifactRef], operator.add]
    interrupts: Annotated[list[InterruptRecord], operator.add]
    checkpoints: Annotated[list[CheckpointRecord], operator.add]
    errors: Annotated[list[ErrorRecord], operator.add]
    notifications: Annotated[list[NotificationRecord], operator.add]

    # Budget
    usd_spent: float
    loop_iterations: int

    # Consensus
    brain_position: str
    executor_position: str
    consensus_state: ConsensusState

    # Decision queue
    decisions_to_present: list[dict]

    # Batch-review (obs #15)
    batch_review_active: bool
    batch_review_payload_size: int

    # Phase 2.7 (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R T3) — ratification-gated
    # action execution. `mission_execute` writes proposed_actions (parsed
    # from the LLM's structured JSON output block); `pi_decision_select`
    # copies the ratified subset to ratified_actions on "accept";
    # `executor.execute_ratified_actions` iterates ratified_actions and
    # calls write-side mcp methods from the parent process. Both are
    # last-write-wins scalars (not append-only) — only one node writes
    # each in a single workflow pass.
    proposed_actions: list[dict]
    ratified_actions: list[dict]

    # Termination
    terminal_state: TerminalState
    final_report_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_initial_state(
    *,
    workflow_thread_id: str,
    mission_id: str,
    motivated_by_decision_id: str,
) -> ResearchWorkflowState:
    """Construct the canonical initial state at workflow start.

    The graph entry node should call this once, then write the result via
    `state.update(...)`. Subsequent nodes read fields; reducers handle the
    append-only ones.
    """

    return ResearchWorkflowState(
        workflow_thread_id=workflow_thread_id,
        mission_id=mission_id,
        motivated_by_decision_id=motivated_by_decision_id,
        current_phase="init",
        current_node="",
        next_node_override="",
        brain_strategy="",
        executor_backbrief="",
        artifacts=[],
        interrupts=[],
        checkpoints=[],
        errors=[],
        notifications=[],
        usd_spent=0.0,
        loop_iterations=0,
        brain_position="",
        executor_position="",
        consensus_state="unresolved",
        decisions_to_present=[],
        batch_review_active=False,
        batch_review_payload_size=0,
        proposed_actions=[],
        ratified_actions=[],
    )


# Canonical phase set for runtime validation. Built from the Literal so the
# two stay in sync (mypy enforces; T11 audit cross-checks).
ALL_PHASES: frozenset[str] = frozenset(WorkflowPhase.__args__)  # type: ignore[attr-defined]
ALL_CONSENSUS_STATES: frozenset[str] = frozenset(ConsensusState.__args__)  # type: ignore[attr-defined]
ALL_TERMINAL_STATES: frozenset[str] = frozenset(TerminalState.__args__)  # type: ignore[attr-defined]
