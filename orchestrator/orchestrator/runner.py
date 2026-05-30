"""OrchestratorRunner — drives the LangGraph workflow segment-by-segment.

A "segment" is one stretch of graph execution between either:
  - the START → first interrupt, OR
  - a Command(resume=...) → next interrupt, OR
  - a Command(resume=...) → terminal (END).

Each `start_run()` or `respond()` call executes one segment. The graph
uses LangGraph's native `interrupt()` so the thread genuinely suspends
(SqliteSaver holds position); the runner is stateless w.r.t. paused
threads — every segment is independent.

The Phase-2.4 v1 regression (driver returned "accept" for pi_greenlight,
which routes to escalation because graph.py checks `"approve" in response`)
is closed here at the contract level: `resume_token()` maps
`(interrupt_type, action)` to the right substring-token, and callers must
pick `action: accept | reject | correct` instead of supplying a raw
string. This makes the routing-mismatch bug impossible from the API
surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from langgraph.types import Command

from orchestrator import graph as graph_module
from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.parked_store import ParkedStore, ResponseAction
from orchestrator.response_tokens import REDIRECT_SENTINEL, is_redirect_token
from orchestrator.state import make_initial_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response-token contract — Phase 2.4 v1 regression locked here
# ---------------------------------------------------------------------------

_ACCEPT_TOKEN_BY_TYPE: dict[str, str] = {
    # Mission-level interrupts (Phase A).
    "pi_greenlight": "approve",
    "pi_decision_select": "accept",
    "pi_acceptance": "accept",
    # Onboarding-subgraph interrupts (Phase D5a).
    "pi_onboarding_topic": "approve",       # input gate; greenlight-class
    "pi_toolkit_ratify": "accept",          # set-identity ratification (mirrors pi_decision_select)
    "pi_credentials_ready": "accept",       # "I'm done editing .env" signal
    # Phase E3 cleanup: `pi_extend_toolkit` removed from accept-token map.
    # The type was registered here, in _ONBOARDING_INTERRUPT_TYPES, and in
    # parked_store.InterruptType but never had a node or graph wiring — a
    # half-built D6 feature. If/when D6 ships, re-add the entry alongside
    # the node and graph edges in one PR (not three separate registrations).
    # Phase O — project-onboarding workflow interrupts.
    "pi_idea_capture": "approve",           # free-form input gate; greenlight-class
    "pi_scope_ratify": "accept",            # TWO-TAP set-identity (polished idea)
    "pi_deepresearch_prompt": "accept",     # async-pause completion signal
    "pi_claims_review": "accept",           # TWO-TAP set-identity (claims)
    "pi_plan_ratify": "accept",             # TWO-TAP — THE plan-licensing contract gate
    "pi_phase_entry_ack": "approve",        # per-milestone go/no-go; greenlight-class
    # Phase B — orchestrator-level credential bootstrap interrupts.
    "pi_bootstrap_intent": "approve",       # free-form intent gate; greenlight-class
    "pi_bootstrap_ratify": "accept",        # set-identity (ratified_ids non-empty iff accept)
    "pi_bootstrap_fill_ack": "accept",      # "I'm done editing orchestrator/.env" signal
}
"""The substring the graph's routing function looks for to take the
'continue' branch at each PI interrupt. Sourced from graph.py:

  - _route_after_pi_greenlight: 'approve' in response → backbrief_draft
  - _route_after_pi_decision:   'accept'  in response → execute_ratified_actions
  - pi_acceptance node:         'accept'  in response → terminal=complete
  - pi_toolkit_ratify node:     'accept'  → ratified_toolkit = proposed_toolkit
  - pi_onboarding_topic node:   'approve' → research_toolkit_node fires next
  - pi_credentials_ready node:  'accept'  → credential_validator probes the .env

Any other content routes to escalation_router (greenlight, decision) or
terminal=escalated (acceptance). Reject and correct paths both fall here
on purpose.
"""


def resume_token(
    *,
    interrupt_type: str,
    action: ResponseAction,
    response_text: Optional[str] = None,
) -> str:
    """Map (interrupt_type, action) to the resume string handed to the graph.

    accept   → the type-specific accept token ("approve" for greenlight,
               "accept" for decision/acceptance). Bare literal, no prefix.
    reject   → literal "reject".
    correct  → the PI's freeform redirection text, **prefixed with
               REDIRECT_SENTINEL**. The graph's routing functions
               (graph._route_after_pi_*, onboarding_graph._route_*, etc.)
               and node-side is_accept checks (nodes/pi.py) detect the
               sentinel and route to escalation/redirect regardless of
               whether the PI's text contains the words "approve" or
               "accept" — closes the substring-smuggling class bug.

    Raises ValueError on invalid action or unknown interrupt_type.
    """
    if interrupt_type not in _ACCEPT_TOKEN_BY_TYPE:
        raise ValueError(f"unknown interrupt_type {interrupt_type!r}")
    if action == "accept":
        return _ACCEPT_TOKEN_BY_TYPE[interrupt_type]
    if action == "reject":
        return "reject"
    if action == "correct":
        if not response_text or not response_text.strip():
            raise ValueError("correct action requires non-empty response_text")
        return REDIRECT_SENTINEL + response_text
    raise ValueError(f"unknown action {action!r}")


# ---------------------------------------------------------------------------
# Segment outcome
# ---------------------------------------------------------------------------


@dataclass
class SegmentOutcome:
    """One segment's result. Exactly one of `parked_interrupt_id` or
    `terminal_state` is populated."""

    workflow_thread_id: str
    parked_interrupt_id: Optional[str] = None
    parked_interrupt_type: Optional[str] = None
    terminal_state: Optional[Literal["complete", "escalated", "failed"]] = None
    current_node: Optional[str] = None
    usd_spent: float = 0.0
    final_report_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class MissionNotFoundError(Exception):
    """Raised when the requested mission_id can't be loaded from RKA."""


class OrchestratorRunner:
    """Glue between the LangGraph workflow and the parked-interrupt store.

    Factories are injected so production wires real SDK + MCP + on-disk
    SqliteSaver, while tests inject fakes. All three are called per
    workflow_thread_id; the runner does not cache instances.

    `compile_factory` builds the compiled graph from (sdk, mcp,
    checkpointer). Test fakes can return a pre-built compiled object that
    ignores the args, but production should call `graph_module.build_graph`.
    """

    def __init__(
        self,
        *,
        store: ParkedStore,
        sdk_factory: Callable[[str, str], SDKClient],
        mcp_factory: Callable[[str, str], MCPClient],
        saver_factory: Callable[[str], Any],
        compile_factory: Optional[Callable[..., Any]] = None,
        onboarding_compile_factory: Optional[Callable[..., Any]] = None,
        phase_o_compile_factory: Optional[Callable[..., Any]] = None,
        phase_b_compile_factory: Optional[Callable[..., Any]] = None,
    ):
        self.store = store
        self._sdk_factory = sdk_factory
        self._mcp_factory = mcp_factory
        self._saver_factory = saver_factory
        self._compile_factory = compile_factory or graph_module.build_graph
        # Phase D5c: separate compile factory for the (tool-setup)
        # onboarding subgraph. Lazy import to keep the runner module
        # light when only mission graphs are used.
        if onboarding_compile_factory is None:
            from orchestrator import onboarding_graph as _og
            self._onboarding_compile_factory = _og.build_onboarding_graph
        else:
            self._onboarding_compile_factory = onboarding_compile_factory
        # Phase O: separate compile factory for the full
        # project-onboarding workflow (idea → plan → mission queue).
        if phase_o_compile_factory is None:
            from orchestrator import phase_o_graph as _pog
            self._phase_o_compile_factory = _pog.build_phase_o_graph
        else:
            self._phase_o_compile_factory = phase_o_compile_factory
        # Phase B: separate compile factory for the orchestrator-level
        # credential bootstrap. Lazy import (only loaded when bootstrap
        # is invoked or a Phase B interrupt is resumed).
        if phase_b_compile_factory is None:
            from orchestrator import phase_b_graph as _pbg
            self._phase_b_compile_factory = _pbg.build_phase_b_graph
        else:
            self._phase_b_compile_factory = phase_b_compile_factory

    # ---- internal helpers ----

    def _resolve_workspace_path(self, project_id: str) -> str:
        """Gap 1 fix — look up the per-project workspace_path so the SDK
        factory can pass it to make_sdk(workspace_path=...) for the
        Phase G2 can_use_tool hook.

        Returns the workspace_path persisted in `project_workspaces`
        (written at onboarding via ParkedStore.set_project_workspace).
        Returns empty string when no per-project workspace is recorded —
        the hook then falls through to HOST_WORKSPACE_ROOT. Empty
        project_id (Phase B bootstrap, etc.) also returns empty.
        """
        if not project_id:
            return ""
        try:
            return self.store.get_project_workspace(project_id) or ""
        except Exception:  # noqa: BLE001
            # Defensive: a missing project_workspaces row shouldn't crash
            # the runner — degrade to HOST_WORKSPACE_ROOT fallback.
            return ""

    def _require_workspace_or_raise(self, project_id: str) -> str:
        """Adversarial-review #8: for mission flows (non-empty
        project_id), refuse to start the run if the project has not
        been onboarded — i.e., no `project_workspaces` row. Without
        that row, the SDK falls back to HOST_WORKSPACE_ROOT (the broad
        projects-parent), which lets Edit/Write touch sibling projects.
        """
        if not project_id:
            return ""
        workspace = self._resolve_workspace_path(project_id)
        if not workspace:
            raise MissionNotFoundError(
                f"project {project_id!r} has no registered workspace_path. "
                f"Run `/orchestrator-onboard {project_id}` first so the "
                f"per-project workspace is recorded and FS scope can be "
                f"correctly bounded."
            )
        return workspace

    # ---- public API ----

    def start_run(
        self,
        *,
        mission_id: str,
        project_id: str,
        budget_usd: float = 5.0,
        workflow_thread_id: Optional[str] = None,
    ) -> SegmentOutcome:
        """Create a workflow_runs row, load the mission spec, and invoke
        the graph from START. Returns when the graph parks at an
        interrupt or hits a terminal state.

        Synchronous composition of `start_run_commit` + `start_run_drive`.
        FastAPI's async-resume path on `/runs` calls the two halves
        separately so the HTTP caller can get a fast ack while the first
        segment (Brain strategy_node + confirmation_brief — typically 2
        LLM calls = ~minutes) runs as a background task. The legacy sync
        path is kept for tests and any caller that explicitly passes
        `?wait_segment=true`.
        """
        ack = self.start_run_commit(
            mission_id=mission_id,
            project_id=project_id,
            budget_usd=budget_usd,
            workflow_thread_id=workflow_thread_id,
        )
        return self.start_run_drive(
            workflow_thread_id=ack["workflow_thread_id"],
            project_id=ack["project_id"],
            mission_id=ack["mission_id"],
            motivated_by_decision_id=ack["motivated_by_decision_id"],
            allowed_capabilities=ack.get("allowed_capabilities"),
        )

    def start_run_commit(
        self,
        *,
        mission_id: str,
        project_id: str,
        budget_usd: float = 5.0,
        workflow_thread_id: Optional[str] = None,
    ) -> dict:
        """Phase 1 of start_run: mint workflow_runs row, validate the
        mission exists by loading its spec. Does NOT invoke the graph.

        Returns the handoff dict the caller hands to `start_run_drive` to
        run the first segment — typically on a background task so the
        HTTP caller gets `{workflow_thread_id, status: "starting"}`
        immediately and polls `/inbox` for the first parked interrupt.

        Raises MissionNotFoundError if the mission can't be loaded (same
        contract as `start_run`).
        """
        thread_id = self.store.create_run(
            mission_id=mission_id,
            project_id=project_id,
            budget_usd=budget_usd,
            workflow_thread_id=workflow_thread_id,
        )

        mcp = self._mcp_factory(thread_id, project_id)
        try:
            mission = mcp.rka_get_mission(id=mission_id)
        except Exception as e:  # noqa: BLE001
            self.store.update_run(
                thread_id, status="failed", last_error=f"mission load failed: {e}"
            )
            raise MissionNotFoundError(
                f"failed to load mission {mission_id}: {e}"
            ) from e

        if not mission or not mission.get("id"):
            self.store.update_run(
                thread_id, status="failed", last_error="mission not found"
            )
            raise MissionNotFoundError(
                f"mission {mission_id!r} not found in project {project_id!r}"
            )

        motivated_by = (
            mission.get("motivated_by_decision")
            or mission.get("motivated_by_decision_id")
            or ""
        )
        # Gap 3A — capability allowlist from mission metadata. A mission
        # spec may carry `capabilities=["record_knowledge", ...]` to scope
        # its dispatcher surface to a subset of WRITE_TOOLS buckets.
        # Missing field or empty list → no restriction (pre-2.14 behavior).
        # Defensive: ignore non-list values; the dispatcher's
        # ratified_action_capability_allowlist_malformed guard would catch
        # them downstream but the runner can keep the state cleaner by
        # filtering here.
        raw_caps = mission.get("capabilities")
        if isinstance(raw_caps, list) and all(isinstance(c, str) for c in raw_caps):
            allowed_caps: list[str] = list(raw_caps)
        else:
            allowed_caps = []
        return {
            "workflow_thread_id": thread_id,
            "project_id": project_id,
            "mission_id": mission_id,
            "motivated_by_decision_id": motivated_by,
            "allowed_capabilities": allowed_caps,
        }

    def start_run_drive(
        self,
        *,
        workflow_thread_id: str,
        project_id: str,
        mission_id: str,
        motivated_by_decision_id: str,
        allowed_capabilities: list[str] | None = None,
    ) -> SegmentOutcome:
        """Phase 2 of start_run: build SDK + saver + compiled graph and
        drive until the first interrupt or terminal.

        Independent of `start_run_commit` so the FastAPI layer can
        background this on a worker thread while the HTTP client gets
        the workflow_thread_id ack immediately. Brain's strategy_node +
        confirmation_brief LLM calls in this segment can take minutes —
        the same async-resume rationale as `resume_segment`.

        Gap 3A — `allowed_capabilities` seeds the workflow's capability
        allowlist from the mission spec (populated by `start_run_commit`
        from `mission.capabilities`). None/empty = no restriction.
        """
        initial = make_initial_state(
            workflow_thread_id=workflow_thread_id,
            mission_id=mission_id,
            motivated_by_decision_id=motivated_by_decision_id,
            project_id=project_id,
            allowed_capabilities=allowed_capabilities,
        )
        # Gap 1 fix: per-project workspace_path threads into make_sdk so the
        # Phase G2 can_use_tool hook can scope FS escape detection to THIS
        # project's workspace rather than the broader HOST_WORKSPACE_ROOT.
        workspace_path = self._resolve_workspace_path(project_id)
        mcp = self._mcp_factory(workflow_thread_id, project_id)
        sdk = self._sdk_factory(project_id, workspace_path)
        saver = self._saver_factory(workflow_thread_id)
        compiled = self._compile_factory(sdk=sdk, mcp=mcp, checkpointer=saver)
        return self._execute_segment(workflow_thread_id, compiled, initial)

    # Interrupt types that belong to the onboarding subgraph. When the
    # runner is responding to one of these, it must use
    # `_onboarding_compile_factory` rather than the mission
    # `_compile_factory`. Sourced from parked_store.py InterruptType
    # literal — keep in sync if new onboarding types are added.
    _ONBOARDING_INTERRUPT_TYPES: frozenset[str] = frozenset(
        {
            # Phase D — tool-setup subgraph (also runnable standalone).
            "pi_onboarding_topic",
            "pi_toolkit_ratify",
            "pi_credentials_ready",
            # Phase E3 cleanup: pi_extend_toolkit removed (was half-built D6
            # placeholder; no node + no graph wiring shipped).
        }
    )
    """Interrupt types whose response resumes via the Phase D tool-setup
    compile factory (onboarding_graph.build_onboarding_graph)."""

    _PHASE_O_INTERRUPT_TYPES: frozenset[str] = frozenset(
        {
            "pi_idea_capture",
            "pi_scope_ratify",
            "pi_deepresearch_prompt",
            "pi_claims_review",
            "pi_plan_ratify",
            "pi_phase_entry_ack",
        }
    )
    """Interrupt types whose response resumes via the Phase O
    project-onboarding compile factory (phase_o_graph.build_phase_o_graph).
    These represent the full idea → plan → mission-queue workflow,
    distinct from Phase D's tool-setup subgraph."""

    _PHASE_B_INTERRUPT_TYPES: frozenset[str] = frozenset(
        {
            "pi_bootstrap_intent",
            "pi_bootstrap_ratify",
            "pi_bootstrap_fill_ack",
        }
    )
    """Interrupt types whose response resumes via the Phase B bootstrap
    compile factory (phase_b_graph.build_phase_b_graph). Orchestrator-
    level credential setup (orchestrator/.env), distinct from Phase D's
    per-project credential setup."""

    def respond(
        self,
        *,
        interrupt_id: str,
        action: ResponseAction,
        response_text: Optional[str] = None,
    ) -> SegmentOutcome:
        """Mark the interrupt as answered, resume the graph with the
        type-correct token, and return the next segment's outcome.

        Synchronous composition of `commit_response` + `resume_segment` —
        used by the legacy synchronous endpoint path and by tests. The
        FastAPI server's async-resume path calls the two halves
        separately so the HTTP call returns immediately after the
        answer is committed, with the graph segment driven on a
        background task (long LLM segments otherwise blow past any
        reasonable client timeout).

        Raises ValueError if the interrupt is missing or already
        answered/cancelled. The `action` argument enforces the
        Phase-2.4 v1 contract: callers can't supply a raw string, so
        they can't accidentally route a greenlight accept to escalation.
        """
        ack = self.commit_response(
            interrupt_id=interrupt_id,
            action=action,
            response_text=response_text,
        )
        return self.resume_segment(
            workflow_thread_id=ack["workflow_thread_id"],
            interrupt_type=ack["interrupt_type"],
            token=ack["token"],
            project_id=ack["project_id"],
        )

    def commit_response(
        self,
        *,
        interrupt_id: str,
        action: ResponseAction,
        response_text: Optional[str] = None,
    ) -> dict:
        """Phase 1 of respond: commit the PI's answer to the store and
        flip the run to 'running'. Does NOT drive the graph segment.

        Returns the handoff dict the caller hands to `resume_segment` to
        run the graph forward — typically on a background task so the
        HTTP call that committed the answer can return immediately.

        Raises ValueError on missing / already-answered interrupt
        (same contract as `respond`).
        """
        parked = self.store.get_interrupt(interrupt_id)
        if parked is None:
            raise ValueError(f"interrupt {interrupt_id!r} not found")
        if parked["status"] != "pending":
            raise ValueError(
                f"interrupt {interrupt_id!r} already in status="
                f"{parked['status']!r}"
            )

        token = resume_token(
            interrupt_type=parked["interrupt_type"],
            action=action,
            response_text=response_text,
        )

        # The store write is the durable record of the PI's decision;
        # the graph resume is the consequence and may take minutes.
        self.store.answer_interrupt(
            interrupt_id=interrupt_id,
            response_action=action,
            response_text=token,
        )

        run = self.store.get_run(parked["workflow_thread_id"])
        assert run is not None
        # Flip run status back to 'running' for the duration of this segment.
        self.store.update_run(run["workflow_thread_id"], status="running")

        return {
            "workflow_thread_id": run["workflow_thread_id"],
            "project_id": run["project_id"],
            "interrupt_type": parked["interrupt_type"],
            "interrupt_id": interrupt_id,
            "token": token,
        }

    def resume_segment(
        self,
        *,
        workflow_thread_id: str,
        interrupt_type: str,
        token: str,
        project_id: str,
    ) -> SegmentOutcome:
        """Phase 2 of respond: drive the graph forward until the next
        interrupt or terminal state.

        Independent of `commit_response` so the FastAPI layer can
        background this on a worker thread while the HTTP client gets
        an immediate ack — long LLM segments otherwise exceed any
        reasonable client timeout and the client sees an empty timeout
        error even though the server completes successfully.
        """
        workspace_path = self._resolve_workspace_path(project_id)
        mcp = self._mcp_factory(workflow_thread_id, project_id)
        sdk = self._sdk_factory(project_id, workspace_path)
        saver = self._saver_factory(workflow_thread_id)
        # Phase D5c / Phase O: pick the compile factory by interrupt
        # type.  Phase D tool-setup interrupts → onboarding subgraph;
        # Phase O workflow interrupts → phase_o subgraph; everything
        # else → mission graph (Phase A).
        if interrupt_type in self._PHASE_O_INTERRUPT_TYPES:
            factory = self._phase_o_compile_factory
        elif interrupt_type in self._PHASE_B_INTERRUPT_TYPES:
            factory = self._phase_b_compile_factory
        elif interrupt_type in self._ONBOARDING_INTERRUPT_TYPES:
            factory = self._onboarding_compile_factory
        else:
            factory = self._compile_factory
        compiled = factory(sdk=sdk, mcp=mcp, checkpointer=saver)
        return self._execute_segment(
            workflow_thread_id, compiled, Command(resume=token)
        )

    # ---- Phase D5c: onboarding subgraph entrypoint ----

    def start_onboarding(
        self,
        *,
        project_id: str,
        workflow_thread_id: Optional[str] = None,
    ) -> SegmentOutcome:
        """Kick off the onboarding subgraph for a project.

        Unlike start_run (which requires a mission_id), onboarding is
        project-scoped — no mission is loaded. The store still gets a
        workflow_runs row so the parked-interrupt machinery works the
        same way (parked interrupts reference workflow_thread_id +
        mission_id, so we use the project_id as the placeholder
        mission_id for now — the runner-level state.mission_id is
        unused during onboarding).

        Synchronous composition of start_onboarding_commit +
        start_onboarding_drive. FastAPI's async-resume path on /onboard
        calls the two halves separately so the first segment (Brain
        topic-elicitation prompt) doesn't block the HTTP caller.
        """
        ack = self.start_onboarding_commit(
            project_id=project_id, workflow_thread_id=workflow_thread_id,
        )
        return self.start_onboarding_drive(
            workflow_thread_id=ack["workflow_thread_id"],
            project_id=ack["project_id"],
        )

    def start_onboarding_commit(
        self,
        *,
        project_id: str,
        workflow_thread_id: Optional[str] = None,
    ) -> dict:
        """Phase 1 of start_onboarding: mint workflow_runs row. Does not
        invoke the graph. Returns the handoff dict for start_onboarding_drive."""
        thread_id = self.store.create_run(
            mission_id=project_id,  # placeholder; onboarding isn't mission-scoped
            project_id=project_id,
            workflow_thread_id=workflow_thread_id,
        )
        return {
            "workflow_thread_id": thread_id,
            "project_id": project_id,
        }

    def start_onboarding_drive(
        self,
        *,
        workflow_thread_id: str,
        project_id: str,
    ) -> SegmentOutcome:
        """Phase 2 of start_onboarding: build factories + invoke the
        onboarding subgraph until the first interrupt or terminal."""
        workspace_path = self._resolve_workspace_path(project_id)
        mcp = self._mcp_factory(workflow_thread_id, project_id)
        sdk = self._sdk_factory(project_id, workspace_path)
        saver = self._saver_factory(workflow_thread_id)
        compiled = self._onboarding_compile_factory(
            sdk=sdk, mcp=mcp, checkpointer=saver
        )

        # Initial state: minimal — onboarding nodes read project_id and
        # build up topic_metadata / proposed_toolkit / etc. as they go.
        initial = {
            "workflow_thread_id": workflow_thread_id,
            "mission_id": project_id,
            "project_id": project_id,
            "motivated_by_decision_id": "",
            "current_phase": "init",
            "current_node": "",
            "next_node_override": "",
            "brain_strategy": "",
            "executor_backbrief": "",
            "artifacts": [],
            "interrupts": [],
            "checkpoints": [],
            "errors": [],
            "notifications": [],
            "usd_spent": 0.0,
            "loop_iterations": 0,
            "brain_position": "",
            "executor_position": "",
            "consensus_state": "unresolved",
            "decisions_to_present": [],
            "batch_review_active": False,
            "batch_review_payload_size": 0,
            "proposed_actions": [],
            "ratified_actions": [],
            "topic_metadata": {},
            "proposed_toolkit": [],
            "ratified_toolkit": [],
        }
        return self._execute_segment(workflow_thread_id, compiled, initial)

    # ---- Phase O: full project-onboarding workflow entrypoint ----

    def start_phase_o(
        self,
        *,
        project_id: str,
        workflow_thread_id: Optional[str] = None,
    ) -> SegmentOutcome:
        """Kick off the Phase O full project-onboarding workflow.

        Project-scoped (no mission_id) like start_onboarding, but uses
        the Phase O compile factory which threads idea → polish →
        scope ratify → workspace → deep research → hygiene → claim
        extraction → plan synthesis → plan ratify → Phase H entry.

        The workflow parks at the first PI interrupt
        (pi_idea_capture); PI's response resumes via respond() with
        the parked-interrupt classification routing back to this
        compile factory.
        """
        thread_id = self.store.create_run(
            mission_id=project_id,  # placeholder; Phase O isn't mission-scoped
            project_id=project_id,
            workflow_thread_id=workflow_thread_id,
        )

        workspace_path = self._resolve_workspace_path(project_id)
        mcp = self._mcp_factory(thread_id, project_id)
        sdk = self._sdk_factory(project_id, workspace_path)
        saver = self._saver_factory(thread_id)
        compiled = self._phase_o_compile_factory(
            sdk=sdk, mcp=mcp, checkpointer=saver
        )

        initial = make_initial_state(
            workflow_thread_id=thread_id,
            mission_id=project_id,  # placeholder
            motivated_by_decision_id="",
            project_id=project_id,
        )
        return self._execute_segment(thread_id, compiled, initial)

    # ---- Phase B: orchestrator-level credential bootstrap entrypoint ----

    def start_phase_b(
        self,
        *,
        workflow_thread_id: Optional[str] = None,
    ) -> SegmentOutcome:
        """Kick off the Phase B bootstrap subgraph.

        Unlike start_phase_o, Phase B is *not* project-scoped — it
        configures the orchestrator daemon's own credentials. We still
        need a workflow_runs row (so the parked-interrupt machinery
        works) so we use the sentinel string "_bootstrap_" as both
        the placeholder mission_id and project_id. The runner-level
        state.project_id stays empty during bootstrap.

        Synchronous composition of start_phase_b_commit +
        start_phase_b_drive. FastAPI's async-resume path on /bootstrap
        calls the two halves separately so the first segment doesn't
        block the HTTP caller.
        """
        ack = self.start_phase_b_commit(workflow_thread_id=workflow_thread_id)
        return self.start_phase_b_drive(
            workflow_thread_id=ack["workflow_thread_id"]
        )

    def start_phase_b_commit(
        self,
        *,
        workflow_thread_id: Optional[str] = None,
    ) -> dict:
        """Phase 1 of start_phase_b: mint workflow_runs row.
        Does not invoke the graph."""
        thread_id = self.store.create_run(
            mission_id="_bootstrap_",  # sentinel; bootstrap isn't mission-scoped
            project_id="_bootstrap_",  # sentinel; bootstrap isn't project-scoped
            workflow_thread_id=workflow_thread_id,
        )
        return {"workflow_thread_id": thread_id}

    def start_phase_b_drive(
        self,
        *,
        workflow_thread_id: str,
    ) -> SegmentOutcome:
        """Phase 2 of start_phase_b: build factories + invoke the Phase B
        subgraph until the first interrupt or terminal."""
        # Phase B is project-independent (orchestrator-level bootstrap),
        # so workspace_path is empty — the hook will fall through to
        # HOST_WORKSPACE_ROOT, which is correct for daemon-level work.
        mcp = self._mcp_factory(workflow_thread_id, "")
        sdk = self._sdk_factory("", "")
        saver = self._saver_factory(workflow_thread_id)
        compiled = self._phase_b_compile_factory(
            sdk=sdk, mcp=mcp, checkpointer=saver
        )
        initial = make_initial_state(
            workflow_thread_id=workflow_thread_id,
            mission_id="_bootstrap_",
            motivated_by_decision_id="",
            project_id="",
        )
        return self._execute_segment(workflow_thread_id, compiled, initial)

    def cancel(self, workflow_thread_id: str) -> int:
        """Cancel a run. Returns count of pending interrupts marked cancelled."""
        return self.store.cancel_run(workflow_thread_id)

    # ---- internal ----

    def _execute_segment(
        self, thread_id: str, compiled: Any, command_or_input: Any
    ) -> SegmentOutcome:
        cfg = {"configurable": {"thread_id": thread_id}}
        try:
            output = compiled.invoke(command_or_input, config=cfg)
        except Exception as e:  # noqa: BLE001
            logger.exception("graph invocation failed for thread %s", thread_id)
            self.store.update_run(
                thread_id, status="failed", last_error=str(e)[:500]
            )
            return SegmentOutcome(
                workflow_thread_id=thread_id, terminal_state="failed"
            )

        # Inspect for interrupt vs terminal.
        interrupts = output.get("__interrupt__") if isinstance(output, dict) else None
        if interrupts:
            first = interrupts[0]
            payload = dict(first.value) if isinstance(first.value, dict) else {"raw": first.value}
            interrupt_type = payload.get("type", "")
            iid = self.store.park_interrupt(
                workflow_thread_id=thread_id,
                mission_id=output.get("mission_id") or self.store.get_run(thread_id)["mission_id"],
                interrupt_type=interrupt_type,
                payload=payload,
            )
            self.store.update_run(
                thread_id,
                current_node=output.get("current_node"),
                usd_spent=float(output.get("usd_spent", 0.0) or 0.0),
            )
            return SegmentOutcome(
                workflow_thread_id=thread_id,
                parked_interrupt_id=iid,
                parked_interrupt_type=interrupt_type,
                current_node=output.get("current_node"),
                usd_spent=float(output.get("usd_spent", 0.0) or 0.0),
            )

        # Terminal.
        terminal = output.get("terminal_state") or "complete"
        if terminal not in ("complete", "escalated", "failed"):
            terminal = "complete"
        self.store.update_run(
            thread_id,
            status=terminal,
            terminal_state=terminal,
            final_report_id=output.get("final_report_id"),
            current_node=output.get("current_node"),
            usd_spent=float(output.get("usd_spent", 0.0) or 0.0),
        )
        return SegmentOutcome(
            workflow_thread_id=thread_id,
            terminal_state=terminal,
            current_node=output.get("current_node"),
            usd_spent=float(output.get("usd_spent", 0.0) or 0.0),
            final_report_id=output.get("final_report_id"),
        )
