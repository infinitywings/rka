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
    "pi_extend_toolkit": "accept",          # set-identity (mid-mission extension; D6)
    # Phase O — project-onboarding workflow interrupts.
    "pi_idea_capture": "approve",           # free-form input gate; greenlight-class
    "pi_scope_ratify": "accept",            # TWO-TAP set-identity (polished idea)
    "pi_deepresearch_prompt": "accept",     # async-pause completion signal
    "pi_claims_review": "accept",           # TWO-TAP set-identity (claims)
    "pi_plan_ratify": "accept",             # TWO-TAP — THE plan-licensing contract gate
    "pi_phase_entry_ack": "approve",        # per-milestone go/no-go; greenlight-class
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
               "accept" for decision/acceptance)
    reject   → literal "reject"
    correct  → the PI's freeform redirection text verbatim. The graph's
               substring routing will treat anything without "approve" /
               "accept" as a redirect to escalation_router, which is the
               correct semantic for a correction.

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
        return response_text
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
        sdk_factory: Callable[[str], SDKClient],
        mcp_factory: Callable[[str, str], MCPClient],
        saver_factory: Callable[[str], Any],
        compile_factory: Optional[Callable[..., Any]] = None,
        onboarding_compile_factory: Optional[Callable[..., Any]] = None,
    ):
        self.store = store
        self._sdk_factory = sdk_factory
        self._mcp_factory = mcp_factory
        self._saver_factory = saver_factory
        self._compile_factory = compile_factory or graph_module.build_graph
        # Phase D5c: separate compile factory for the onboarding subgraph.
        # Lazy import to keep the runner module light when only mission
        # graphs are used.
        if onboarding_compile_factory is None:
            from orchestrator import onboarding_graph as _og
            self._onboarding_compile_factory = _og.build_onboarding_graph
        else:
            self._onboarding_compile_factory = onboarding_compile_factory

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
        """
        # We need an MCP client to load the mission spec before we have a
        # workflow_thread_id — but the client wants a thread_id to auto-tag
        # writes. Pre-create the run row to mint the id.
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
        initial = make_initial_state(
            workflow_thread_id=thread_id,
            mission_id=mission_id,
            motivated_by_decision_id=motivated_by,
            project_id=project_id,
        )

        sdk = self._sdk_factory(project_id)
        saver = self._saver_factory(thread_id)
        compiled = self._compile_factory(sdk=sdk, mcp=mcp, checkpointer=saver)
        return self._execute_segment(thread_id, compiled, initial)

    # Interrupt types that belong to the onboarding subgraph. When the
    # runner is responding to one of these, it must use
    # `_onboarding_compile_factory` rather than the mission
    # `_compile_factory`. Sourced from parked_store.py InterruptType
    # literal — keep in sync if new onboarding types are added.
    _ONBOARDING_INTERRUPT_TYPES: frozenset[str] = frozenset(
        {
            # Phase D — tool-setup subgraph (now nested under Phase O as O5).
            "pi_onboarding_topic",
            "pi_toolkit_ratify",
            "pi_credentials_ready",
            "pi_extend_toolkit",
            # Phase O — project-onboarding workflow.
            "pi_idea_capture",
            "pi_scope_ratify",
            "pi_deepresearch_prompt",
            "pi_claims_review",
            "pi_plan_ratify",
            "pi_phase_entry_ack",
        }
    )

    def respond(
        self,
        *,
        interrupt_id: str,
        action: ResponseAction,
        response_text: Optional[str] = None,
    ) -> SegmentOutcome:
        """Mark the interrupt as answered, resume the graph with the
        type-correct token, and return the next segment's outcome.

        Raises ValueError if the interrupt is missing or already
        answered/cancelled. The `action` argument enforces the
        Phase-2.4 v1 contract: callers can't supply a raw string, so
        they can't accidentally route a greenlight accept to escalation.
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

        # Atomic: mark answered (in store), THEN resume graph. The store
        # write is the durable record of the PI's decision; the graph
        # resume is the consequence.
        self.store.answer_interrupt(
            interrupt_id=interrupt_id,
            response_action=action,
            response_text=token,
        )

        run = self.store.get_run(parked["workflow_thread_id"])
        assert run is not None
        # Flip run status back to 'running' for the duration of this segment.
        self.store.update_run(run["workflow_thread_id"], status="running")

        mcp = self._mcp_factory(run["workflow_thread_id"], run["project_id"])
        sdk = self._sdk_factory(run["project_id"])
        saver = self._saver_factory(run["workflow_thread_id"])
        # Phase D5c: route to the onboarding compile factory when the
        # interrupt belongs to the onboarding subgraph. Otherwise use the
        # mission compile factory.
        if parked["interrupt_type"] in self._ONBOARDING_INTERRUPT_TYPES:
            factory = self._onboarding_compile_factory
        else:
            factory = self._compile_factory
        compiled = factory(sdk=sdk, mcp=mcp, checkpointer=saver)
        return self._execute_segment(
            run["workflow_thread_id"], compiled, Command(resume=token)
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
        """
        # Mint a workflow_runs row. mission_id is the project_id during
        # onboarding (the parked_interrupts.mission_id NOT NULL constraint
        # forces us to put SOMETHING; using project_id is the natural
        # choice and lets `orchestrator_inbox?workflow_thread_id=...`
        # surface onboarding interrupts uniformly).
        thread_id = self.store.create_run(
            mission_id=project_id,  # placeholder; onboarding isn't mission-scoped
            project_id=project_id,
            workflow_thread_id=workflow_thread_id,
        )

        mcp = self._mcp_factory(thread_id, project_id)
        sdk = self._sdk_factory(project_id)
        saver = self._saver_factory(thread_id)
        compiled = self._onboarding_compile_factory(
            sdk=sdk, mcp=mcp, checkpointer=saver
        )

        # Initial state: minimal — onboarding nodes read project_id and
        # build up topic_metadata / proposed_toolkit / etc. as they go.
        initial = {
            "workflow_thread_id": thread_id,
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
        return self._execute_segment(thread_id, compiled, initial)

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
