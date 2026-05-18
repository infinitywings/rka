"""PI interaction nodes (3) — `interrupt()` points for human input.

Each PI node halts the workflow via the injected `interrupt_fn` callable,
which in production is `langgraph.types.interrupt`. The function returns
whatever the PI provides as the resume payload.

Per rehearsal observation #15 (labeler-UX-scaling-friction), when the
payload presented to PI exceeds `PI_BATCH_REVIEW_THRESHOLD` items, the
node wraps it in a batched view and records `batch_review_used=True`
on the resulting `InterruptRecord`. T11 audit asserts this contract.

  - `pi_greenlight`       — Confirmation Brief approval (after brain_confirmation)
  - `pi_decision_select`  — choose between Brain-drafted options
  - `pi_acceptance`       — final mission acceptance review
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from orchestrator.llm_client import SDKClient  # noqa: F401  (kept for signature parity)
from orchestrator.mcp_client import MCPClient
from orchestrator.state import InterruptRecord, ResearchWorkflowState

PI_BATCH_REVIEW_THRESHOLD: int = 10
"""When a PI interrupt payload exceeds this many items, render a batched
view (page_size = threshold). Obs #15 mitigation."""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_interrupt_payload(
    *,
    node_name: str,
    items: list[Any],
    title: str,
) -> tuple[dict, bool]:
    """Construct the payload the topology will hand to `interrupt_fn`.

    Returns `(payload, batch_review_used)`. When `len(items)` exceeds
    `PI_BATCH_REVIEW_THRESHOLD`, the payload carries pagination metadata
    so the UI can render a paged review.
    """
    batch_review_used = len(items) > PI_BATCH_REVIEW_THRESHOLD
    payload: dict[str, Any] = {
        "type": node_name,
        "title": title,
        "items": items,
        "total_items": len(items),
    }
    if batch_review_used:
        payload["batched"] = True
        payload["page_size"] = PI_BATCH_REVIEW_THRESHOLD
    return payload, batch_review_used


def _record_interrupt(
    *,
    node_name: str,
    payload_size: int,
    response: Any,
    batch_review_used: bool,
) -> InterruptRecord:
    return {
        "node_name": node_name,
        "payload_size": payload_size,
        "response": str(response),
        "timestamp": _now_iso(),
        "batch_review_used": batch_review_used,
    }


# ---------------------------------------------------------------------------
# 1. pi_greenlight — Confirmation Brief approval
# ---------------------------------------------------------------------------


def pi_greenlight(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    pending = state.get("decisions_to_present", [])
    items = [d for d in pending if d.get("source_node") == "confirmation_brief"]

    payload, batched = _build_interrupt_payload(
        node_name="pi_greenlight",
        items=items,
        title="PI approval — Confirmation Brief",
    )
    pi_response = interrupt_fn(payload)

    remaining = [d for d in pending if d.get("source_node") != "confirmation_brief"]
    return {
        "current_phase": "pi_greenlight",
        "current_node": "pi_greenlight",
        "decisions_to_present": remaining,
        "batch_review_active": batched,
        "batch_review_payload_size": len(items),
        "interrupts": [
            _record_interrupt(
                node_name="pi_greenlight",
                payload_size=len(items),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }


# ---------------------------------------------------------------------------
# 2. pi_decision_select — pick a Brain-drafted decision
# ---------------------------------------------------------------------------


def pi_decision_select(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    pending = state.get("decisions_to_present", [])
    items = [d for d in pending if d.get("source_node") == "decision_present"]

    payload, batched = _build_interrupt_payload(
        node_name="pi_decision_select",
        items=items,
        title="PI selection — choose decision option",
    )
    pi_response = interrupt_fn(payload)

    # If PI selected "accept" or "modify", record a decision in RKA.
    artifacts: list[dict] = []
    response_text = str(pi_response).lower()
    is_accept = "accept" in response_text
    if items and is_accept:
        first_item = items[0]
        rka_id = mcp.rka_add_decision(
            content=first_item.get("context", ""),
            related_journal=[first_item.get("source_artifact", "")],
            tags=["pi-accepted"],
        )
        artifacts.append(
            {
                "rka_id": rka_id,
                "entity_type": "decision",
                "node_name": "pi_decision_select",
                "timestamp": _now_iso(),
            }
        )

    # Phase 2.7 T3d: ratification gates write-side action execution. On
    # "accept", copy state["proposed_actions"] into ratified_actions so the
    # downstream `executor.execute_ratified_actions` node will execute them
    # from the parent process. On reject/escape, explicitly clear so a
    # prior workflow's proposed_actions can't leak through.
    ratified = list(state.get("proposed_actions", []) or []) if is_accept else []

    remaining = [d for d in pending if d.get("source_node") != "decision_present"]
    update = {
        "current_phase": "pi_decision",
        "current_node": "pi_decision_select",
        "decisions_to_present": remaining,
        "batch_review_active": batched,
        "batch_review_payload_size": len(items),
        "ratified_actions": ratified,
        "interrupts": [
            _record_interrupt(
                node_name="pi_decision_select",
                payload_size=len(items),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }
    if artifacts:
        update["artifacts"] = artifacts
    return update


# ---------------------------------------------------------------------------
# 3. pi_acceptance — final mission acceptance review
# ---------------------------------------------------------------------------


def _compose_acceptance_summary(state: ResearchWorkflowState) -> str:
    """Build a structured one-line summary for the pi_acceptance payload.

    Phase 2.9 T4 (mis_01KRY2KP0GGZY21BA4Z2R2S718): Phase 2.8 close-out
    surfaced a cosmetic anomaly — `pi_acceptance` summary was sourced
    from `state["brain_position"]` which carries the LAST brain-position
    write, which (in the happy path) is `gate1_validation`'s verdict
    text ("APPROVED:" / "REDIRECTED:"). Misleading: the summary
    described the gate1 verdict, not the mission outcome.

    Replacement is a composed summary based on counts + escalation
    signal: clear, accurate, no leak. Falls back to a static placeholder
    when state has no signal to summarize.
    """
    artifact_count = len(state.get("artifacts", []))
    error_count = len(state.get("errors", []))
    checkpoint_count = len(state.get("checkpoints", []))
    final_report_id = state.get("final_report_id")

    if error_count > 0:
        return (
            f"Mission ended with {error_count} error(s); "
            f"{artifact_count} artifacts produced; "
            f"{checkpoint_count} checkpoint(s) raised."
        )
    if checkpoint_count > 0:
        return (
            f"Mission escalated via {checkpoint_count} checkpoint(s); "
            f"{artifact_count} artifacts produced; see checkpoint detail."
        )
    if final_report_id:
        return (
            f"Mission complete; final_report_id={final_report_id}; "
            f"{artifact_count} artifacts produced."
        )
    return (
        f"Workflow complete; {artifact_count} artifacts produced; "
        f"see report for details."
    )


def pi_acceptance(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    # Acceptance payload is the run's complete state digest:
    # final_report_id + accumulated artifacts + interrupts + errors.
    # Phase 2.9 T4: summary now composed from counts (no longer leaks
    # gate1 verdict text via brain_position).
    items = [
        {
            "final_report_id": state.get("final_report_id"),
            "artifact_count": len(state.get("artifacts", [])),
            "interrupt_count": len(state.get("interrupts", [])),
            "error_count": len(state.get("errors", [])),
            "checkpoint_count": len(state.get("checkpoints", [])),
            "usd_spent": state.get("usd_spent", 0.0),
            "summary": _compose_acceptance_summary(state),
        }
    ]

    payload, batched = _build_interrupt_payload(
        node_name="pi_acceptance",
        items=items,
        title="PI acceptance — final mission review",
    )
    pi_response = interrupt_fn(payload)

    response_text = str(pi_response).lower()
    if "accept" in response_text:
        terminal: str = "complete"
    else:
        terminal = "escalated"

    return {
        "current_phase": "pi_acceptance",
        "current_node": "pi_acceptance",
        "terminal_state": terminal,
        "batch_review_active": batched,
        "batch_review_payload_size": len(items),
        "interrupts": [
            _record_interrupt(
                node_name="pi_acceptance",
                payload_size=len(items),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }
