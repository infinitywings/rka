"""Utility nodes (3) — budget, consensus, and escalation routing.

  - `budget_check`        — abort/escalate on $ cap or loop bound
  - `consensus_check`     — detect Brain⇄Executor disagreement → escalate
  - `escalation_router`   — submit checkpoint + route to PI handoff

These nodes do no LLM work; they're pure state inspection + RKA write.
Signature is `(state, sdk, mcp)` for parity with Brain/Executor — `sdk`
is unused but kept so the T7 topology binds all 9 the same way.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from orchestrator.budgets import DEFAULT_BUDGET_USD, MAX_LOOP_DEPTH
from orchestrator.llm_client import SDKClient  # noqa: F401 (signature parity)
from orchestrator.mcp_client import MCPClient
from orchestrator.state import (
    CheckpointRecord,
    ErrorRecord,
    ResearchWorkflowState,
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(node: str, error_type: str, detail: str) -> ErrorRecord:
    return {
        "node_name": node,
        "error_type": error_type,
        "detail": detail,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# 1. budget_check
# ---------------------------------------------------------------------------


def budget_check(
    state: ResearchWorkflowState,
    sdk: Any = None,
    mcp: Any = None,
    *,
    cap_usd: float = DEFAULT_BUDGET_USD,
) -> dict:
    """Verify the run is within its $ cap and loop-depth bound.

    On breach, appends an error record and sets
    `next_node_override="escalation_router"` so the topology routes to
    checkpoint creation.
    """
    spent = float(state.get("usd_spent", 0.0))
    loops = int(state.get("loop_iterations", 0))

    # A per-run `cap_usd` seeded into state OVERRIDES the constant default.
    # The hardcoded DEFAULT_BUDGET_USD (5.0) is calibrated for cheap models;
    # an expensive model (e.g. Opus 4.8, which ships ~50 tool schemas every
    # turn at ~$1/node + a multi-turn mission_execute experiment loop) blows
    # it after a handful of nodes — escalating the run BEFORE it reaches the
    # decision/pivot stage. Making the cap state-configurable lets a caller
    # (the runner or the eval driver) size it to the model without editing a
    # global constant. Empirically surfaced driving Opus 4.8 (2026-06-15):
    # usd_spent=5.18 >= cap=5.0 fired at budget_check after mission_execute,
    # starving the pi_decision_select pivot gate.
    state_cap = state.get("cap_usd")
    effective_cap = float(state_cap) if state_cap else cap_usd

    if spent >= effective_cap:
        return {
            "current_node": "budget_check",
            "next_node_override": "escalation_router",
            "errors": [
                _error(
                    "budget_check",
                    "budget_exceeded",
                    f"usd_spent={spent} >= cap={effective_cap}",
                )
            ],
        }
    if loops >= MAX_LOOP_DEPTH:
        return {
            "current_node": "budget_check",
            "next_node_override": "escalation_router",
            "errors": [
                _error(
                    "budget_check",
                    "loop_bound_exceeded",
                    f"loop_iterations={loops} >= max={MAX_LOOP_DEPTH}",
                )
            ],
        }

    return {"current_node": "budget_check"}


# ---------------------------------------------------------------------------
# 2. consensus_check — Brain ⇄ Executor agreement gate
# ---------------------------------------------------------------------------


def consensus_check(
    state: ResearchWorkflowState,
    sdk: Any = None,
    mcp: Any = None,
) -> dict:
    """Compare Brain and Executor positions; promote `consensus_state`.

    Phase 1 heuristic — no LLM call:
      - if both positions empty → unresolved
      - if Brain explicitly says APPROVED in Gate 1 → agreed
      - if loop_iterations >= MAX_LOOP_DEPTH and not yet agreed → disagree
        + escalation hint via `next_node_override`
      - otherwise → unresolved (loop continues)
    """
    brain_pos = (state.get("brain_position") or "").strip()
    exec_pos = (state.get("executor_position") or "").strip()
    gate_verdict = state.get("gate1_verdict") or ""
    loops = int(state.get("loop_iterations", 0))

    # Phase E4: increment loop_iterations on each consensus_check pass
    # so MAX_LOOP_DEPTH actually bounds Brain⇄Executor disagreement
    # loops. Pre-Phase-E4 this was missing — the counter stayed at 0
    # forever and the cap check below was dead code.
    #
    # Phase E4 adversarial-review hardening (HIGH #6): increment ONLY on
    # `unresolved` / `disagree` outcomes so legitimate non-disagreement
    # re-entries (e.g., a graph topology that visits consensus_check on
    # a successful Brain APPROVED path more than once across a long
    # mission) don't burn the budget. `agreed` exits and empty-position
    # exits both leave the counter alone.
    next_loops_unresolved = loops + 1

    if not brain_pos and not exec_pos:
        # No positions yet — workflow hasn't reached Brain ⇄ Executor
        # synthesis. Do not consume the loop budget.
        return {
            "current_node": "consensus_check",
            "consensus_state": "unresolved",
        }

    if gate_verdict == "approved":
        # Brain has APPROVED in Gate 1 — no disagreement to bound.
        # Do not consume the loop budget.
        return {
            "current_node": "consensus_check",
            "consensus_state": "agreed",
        }

    if loops >= MAX_LOOP_DEPTH:
        return {
            "current_node": "consensus_check",
            "consensus_state": "disagree",
            "next_node_override": "escalation_router",
            "errors": [
                _error(
                    "consensus_check",
                    "consensus_loop_exceeded",
                    f"Brain⇄Executor unresolved after {loops} loops; "
                    f"brain_position={brain_pos[:80]!r}; "
                    f"executor_position={exec_pos[:80]!r}",
                )
            ],
            "loop_iterations": next_loops_unresolved,
        }

    return {
        "current_node": "consensus_check",
        "consensus_state": "unresolved",
        "loop_iterations": next_loops_unresolved,
    }


# ---------------------------------------------------------------------------
# 3. escalation_router — submit checkpoint + route to PI
# ---------------------------------------------------------------------------


def _classify_checkpoint_type(error_type: str) -> str:
    """Map an error_type to a checkpoint type per the executor protocol.

    `decision` for must-escalate triggers (budget breach, consensus loop
    exceeded, assumption invalidation). `clarification` for ambiguity-
    class events. Defaults to `decision` when uncertain — conservative.
    """
    if error_type in {
        "budget_exceeded",
        "loop_bound_exceeded",
        "consensus_loop_exceeded",
        "assumption_invalidation",
        "scope_expansion_required",
        "contradictory_results",
    }:
        return "decision"
    if error_type in {"ambiguous_acceptance", "missing_context", "unexpected_complexity"}:
        return "clarification"
    return "decision"


def escalation_router(
    state: ResearchWorkflowState,
    sdk: Any = None,
    mcp: MCPClient | None = None,
) -> dict:
    """Submit a checkpoint capturing the latest failure and route to PI.

    Reads the most recent ErrorRecord in `state["errors"]`. If there is
    none, escalates with a generic "unclassified" reason rather than
    silently no-op'ing.
    """
    errors = state.get("errors", [])
    latest = errors[-1] if errors else _error(
        "escalation_router",
        "unclassified",
        "No prior error found in state['errors'].",
    )
    chk_type = _classify_checkpoint_type(latest.get("error_type", "unclassified"))
    reason = (
        f"[{latest.get('node_name')}] {latest.get('error_type')}: "
        f"{latest.get('detail', '')}"
    )

    chk_id = ""
    if mcp is not None:
        chk_id = mcp.rka_submit_checkpoint(
            reason=reason,
            type=chk_type,
            related_mission=state.get("mission_id"),
        )

    record: CheckpointRecord = {
        "chk_id": chk_id or "chk_pending",
        "type": chk_type,  # type: ignore[typeddict-item]
        "reason": reason,
        "resolved": False,
    }
    return {
        "current_node": "escalation_router",
        "current_phase": "escalated",
        # Route to pi_acceptance so the PI sees the escalation + run digest
        # and decides whether to accept the partial state or fail-the-run.
        "next_node_override": "pi_acceptance",
        "checkpoints": [record],
    }
