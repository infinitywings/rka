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
    error_type: str  # "consensus_loop_exceeded" | "budget_exceeded" | "mcp_error" | "llm_call_timeout" | ...
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
    # Phase 2.9 (mis_01KRY2KP0GGZY21BA4Z2R2S718 T1): RKA project_id under
    # which the workflow is scoped. Populated at workflow start from
    # driver.py:--project-id. Threaded through `make_sdk(project_id=...)`
    # to propagate as McpStdioServerConfig.env["RKA_PROJECT"] to the
    # subprocess's `rka mcp` stdio child. Additive (TypedDict total=False);
    # pre-Phase-2.9 state shapes continue to work without it.
    project_id: str
    # Phase-X (Cross-Run Correction Channel) + Phase-X² (In-Run Redraft
    # Channel): per-run PI overrides. Two channels converge on this field:
    #
    #   {
    #     # Phase-X (cross-run; seeded at start_run_drive from
    #     # workflow_runs.run_overrides):
    #     "pi_instructions": "<optional PI text from orchestrator_run_start>",
    #     "prior_redirects": [
    #       {"workflow_thread_id": "...", "interrupt_id": "...",
    #        "responded_at": "...", "response_text": "..."},
    #       ...
    #     ],
    #     # Phase-X² (in-run; mutated by confirmation_brief_redraft when
    #     # the PI sends a 'correct' action at pi_greenlight — capped at
    #     # MAX_GREENLIGHT_REDRAFTS entries):
    #     "in_run_redirects": [
    #       {"responded_at": "...", "response_text": "<sanitized>"},
    #       ...
    #     ]
    #   }
    #
    # Read by Brain at _build_strategy_prompt (cross-run) AND
    # _build_confirmation_prompt (in-run, on redraft), prefixed under a
    # delimited "PI OVERRIDES" block at the top of the prompt. Empty
    # dict ({}) means "no overrides for this run" — the block is
    # suppressed. Additive (TypedDict total=False); pre-Phase-X state
    # shapes continue to work without it.
    run_overrides: dict

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
    # Phase-X² (In-Run Redraft Channel): per-thread counter incremented
    # by confirmation_brief_redraft each time the PI sends a 'correct'
    # action at pi_greenlight. Capped at MAX_GREENLIGHT_REDRAFTS (see
    # bottom of module) — on the (cap+1)th redraft the node emits a
    # real `greenlight_redraft_budget_exceeded` ErrorRecord and routes
    # to escalation_router (which now finds a genuine error and behaves
    # correctly). Last-write-wins scalar, initialized to 0 in
    # make_initial_state.
    greenlight_redrafts: int
    # v0.6.11 — sibling of greenlight_redrafts for the pi_decision_select
    # gate. Incremented by mission_redraft each time the PI sends a
    # 'correct' action at pi_decision_select. Capped at
    # MAX_DECISION_REDRAFTS; on the (cap+1)th the node emits a real
    # `decision_redraft_budget_exceeded` ErrorRecord and routes to
    # escalation_router. Last-write-wins scalar, init 0.
    decision_redrafts: int

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
    # Gap 2 — FS-action ratification surface (Phase G follow-through).
    # Mirror of proposed_actions / ratified_actions but for Bash/Write/Edit
    # operations the Brain or Executor wants to perform on the workspace
    # AFTER PI ratification (vs. unratified scoped_write operations that
    # the LLM may call directly via the Phase G2 hook). The Executor LLM
    # emits proposed_fs_actions when classify_fs_action returns
    # ratify_required; pi_decision_select packages them alongside
    # proposed_actions in the same payload; on accept,
    # execute_ratified_fs_actions dispatches via subprocess.run / Python
    # file IO from the parent process. PI cannot override DENY-tier
    # classifications — those are refused at dispatch time even if
    # somehow ratified.
    proposed_fs_actions: list[dict]
    ratified_fs_actions: list[dict]
    # Gap 3B — Brain's capability proposal. strategy_node parses
    # proposed_capabilities from its JSON reply; pi_greenlight on accept
    # copies them to allowed_capabilities (overriding any mission-set
    # value from Gap 3A). Empty list = no Brain proposal, allowlist
    # comes from mission spec.
    proposed_capabilities: list[str]
    # Phase 2.14 (agentic) — capability-scoped dispatch. When set to a
    # non-empty list of capability strings (e.g. ["record_knowledge",
    # "execution_gates"]), `execute_ratified_actions` rejects any tool
    # whose capability is NOT in this list with a
    # `ratified_action_capability_not_allowed` ErrorRecord. Empty or
    # missing = no restriction (the workflow may dispatch any tool in
    # WRITE_TOOLS). Set by mission-creation flow per the mission's
    # ratified scope.
    allowed_capabilities: list[str]

    # Phase D (agentic) — onboarding subgraph state.
    # `topic_metadata` is set by pi_onboarding_topic (a TopicMetadata
    # dict per orchestrator.manifest). `proposed_toolkit` is set by
    # research_toolkit_node — a list of ToolDecl dicts the Brain
    # proposes. `ratified_toolkit` is set on pi_toolkit_ratify accept.
    # All three live on the same TypedDict so the onboarding subgraph
    # shares state with the mission subgraph (lets a workflow_thread_id
    # straddle the boundary if onboarding triggers a mission).
    topic_metadata: dict
    proposed_toolkit: list[dict]
    ratified_toolkit: list[dict]

    # Phase O (agentic) — full project-onboarding workflow state.
    # O1-O2 inputs:
    project_slug: str
    workspace_path: str
    ingested_source_ids: list[str]   # journal IDs from pi_idea_capture
    polished_idea: dict              # PolishedIdea (O1: idea_polish output)
    scope_ratified: bool             # set by pi_scope_ratify
    # O2:
    deepresearch_complete: bool      # set by pi_research_complete resume
    # O3:
    hygiene_findings: list[dict]     # set by hygiene_pass
    claim_ids: list[str]             # set by claim_extraction
    # O4:
    ratified_plan_decision_id: str   # dec_… from pi_plan_ratify accept
    ratified_plan_journal_id: str    # jrn_… containing the plan JSON
    ratified_mission_ids: list[str]  # mis_… per milestone, auto-created
    # H:
    current_milestone_index: int     # 0-indexed position in ratified_mission_ids

    # Phase B (agentic) — orchestrator-level bootstrap state.
    # `bootstrap_intent` is set by pi_bootstrap_intent (free-form text
    # describing install state). `bootstrap_proposed_ids` is the catalog
    # entry-ids picked by propose_for_intent. `bootstrap_ratified_ids`
    # is the subset PI accepted at pi_bootstrap_ratify (set-identity:
    # non-empty iff PI accepted). `bootstrap_template_path` is the
    # absolute path of the .env.example the runner wrote for the PI to
    # fill in. `bootstrap_verify_results` is populated by the final
    # verify node so the runner can render the report.
    bootstrap_intent: str
    bootstrap_proposed_ids: list[str]
    bootstrap_ratified_ids: list[str]
    bootstrap_template_path: str
    bootstrap_verify_results: list[dict]

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
    project_id: str = "",
    allowed_capabilities: list[str] | None = None,
    run_overrides: dict | None = None,
) -> ResearchWorkflowState:
    """Construct the canonical initial state at workflow start.

    The graph entry node should call this once, then write the result via
    `state.update(...)`. Subsequent nodes read fields; reducers handle the
    append-only ones.

    Phase 2.9 T1: `project_id` is additive; defaults to empty string so
    pre-Phase-2.9 callers continue to work without modification. When set,
    it carries the RKA project context that scopes this workflow run.

    Gap 3A: `allowed_capabilities` lets the runner seed the workflow's
    capability allowlist from mission metadata (e.g., a mission whose
    spec carries `capabilities=["record_knowledge", "execution_gates"]`
    narrows the dispatcher accordingly). None / empty list = no
    restriction (pre-2.14 behavior).

    Phase-X: `run_overrides` carries per-run PI corrections (manual
    pi_instructions + auto-rehydrated prior_redirects). Seeded by the
    runner from workflow_runs.run_overrides at start_run_drive. Empty
    dict {} (default) means "no overrides for this run".
    """

    return ResearchWorkflowState(
        workflow_thread_id=workflow_thread_id,
        mission_id=mission_id,
        motivated_by_decision_id=motivated_by_decision_id,
        project_id=project_id,
        run_overrides=dict(run_overrides or {}),
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
        greenlight_redrafts=0,
        decision_redrafts=0,
        brain_position="",
        executor_position="",
        consensus_state="unresolved",
        decisions_to_present=[],
        batch_review_active=False,
        batch_review_payload_size=0,
        proposed_actions=[],
        ratified_actions=[],
        proposed_fs_actions=[],
        ratified_fs_actions=[],
        proposed_capabilities=[],
        allowed_capabilities=list(allowed_capabilities or []),
        # Phase D onboarding fields (additive; total=False on the
        # TypedDict means pre-Phase-D callers still construct valid
        # states without them, but the defaults are listed here for
        # clarity + audit-symmetry test passes).
        topic_metadata={},
        proposed_toolkit=[],
        ratified_toolkit=[],
        # Phase O fields (additive; total=False). All zeroed at start;
        # the onboarding subgraph populates them as it advances through
        # O1 → O2 → O3 → O4 → O5 → H.
        project_slug="",
        workspace_path="",
        ingested_source_ids=[],
        polished_idea={},
        scope_ratified=False,
        deepresearch_complete=False,
        hygiene_findings=[],
        claim_ids=[],
        ratified_plan_decision_id="",
        ratified_plan_journal_id="",
        ratified_mission_ids=[],
        current_milestone_index=0,
        # Phase B bootstrap fields (additive; total=False on the
        # TypedDict means pre-Phase-B callers still construct valid
        # states without them).
        bootstrap_intent="",
        bootstrap_proposed_ids=[],
        bootstrap_ratified_ids=[],
        bootstrap_template_path="",
        bootstrap_verify_results=[],
    )


# Canonical phase set for runtime validation. Built from the Literal so the
# two stay in sync (mypy enforces; T11 audit cross-checks).
ALL_PHASES: frozenset[str] = frozenset(WorkflowPhase.__args__)  # type: ignore[attr-defined]
ALL_CONSENSUS_STATES: frozenset[str] = frozenset(ConsensusState.__args__)  # type: ignore[attr-defined]
ALL_TERMINAL_STATES: frozenset[str] = frozenset(TerminalState.__args__)  # type: ignore[attr-defined]


# Phase-X² — bound on the in-run pi_greenlight redirect loop. After this
# many `correct` actions in a single workflow_thread_id,
# confirmation_brief_redraft emits a real ErrorRecord and routes to
# escalation_router instead of looping again. Closes the unbounded-cycle
# risk that CLAUDE.md previously flagged as a deferred follow-up
# ('loop_iterations declared but never written').
MAX_GREENLIGHT_REDRAFTS: int = 3

# v0.6.11 — bound on the pi_decision_select in-run redraft loop. On the
# (cap+1)th 'correct' at the decision gate, mission_redraft emits a real
# `decision_redraft_budget_exceeded` ErrorRecord and escalates so the PI
# adjudicates rather than looping unbounded.
MAX_DECISION_REDRAFTS: int = 3
