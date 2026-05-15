"""Brain nodes (6) — strategic synthesis, validation, presentation.

Each node is a sync function `(state, sdk, mcp) -> state_update_dict`.
LangGraph's `StateGraph` accepts plain callables; the topology in T7 wires
SDK + MCP via `functools.partial` (or a small closure).

The 6 Brain entry points map onto the Brain skill workflow:

  1. `strategy_node`        — session-start strategy synthesis
  2. `confirmation_brief`   — Brain → PI Confirmation Brief
  3. `decision_present`     — queue a decision for PI selection (T5 consumes)
  4. `cluster_review`       — `rka_review_cluster` integration
  5. `gate1_validation`     — accept/redirect Executor Backbrief
  6. `final_synthesis`      — mission-acceptance writeup at workflow end

All RKA writes are tagged with `workflow_thread_id` (via the MCPClient
auto-injection contract in `mcp_client.py`). Tests inject Fake clients.
"""

from __future__ import annotations

from datetime import datetime, timezone

from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.state import ArtifactRef, ResearchWorkflowState

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

BRAIN_SYSTEM = (
    "You are the Brain in an RKA-managed research project. Your job is "
    "strategic synthesis, decision interpretation, and oversight of the "
    "Executor's plans. Be terse, evidence-cited, and explicit about "
    "uncertainty."
)


def _now_iso() -> str:
    """Current UTC timestamp in ISO-8601 with `Z` suffix."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact(rka_id: str, entity_type: str, node_name: str) -> ArtifactRef:
    return {
        "rka_id": rka_id,
        "entity_type": entity_type,
        "node_name": node_name,
        "timestamp": _now_iso(),
    }


def _summarize_position(text: str, *, max_chars: int = 280) -> str:
    """Trim a long Brain output to a single-line position summary.

    Used to populate `state["brain_position"]` for the consensus_check
    utility node in T6. Truncation is naïve (first N chars + ellipsis);
    Phase 2 can swap in an LLM-extracted summary.
    """
    first_line = text.strip().split("\n", 1)[0]
    if len(first_line) <= max_chars:
        return first_line
    return first_line[: max_chars - 1] + "…"


# ---------------------------------------------------------------------------
# 1. strategy_node
# ---------------------------------------------------------------------------


def _build_strategy_prompt(state: ResearchWorkflowState, context: dict, status: dict) -> str:
    return (
        "Session-start strategy synthesis.\n\n"
        f"Project status:\n{status}\n\n"
        f"Relevant prior context:\n{context}\n\n"
        f"Current mission: {state.get('mission_id', '(none)')}\n"
        f"Motivated by decision: {state.get('motivated_by_decision_id', '(none)')}\n\n"
        "Produce a short strategy outline: what this run should do, in what "
        "order, with what evidence checks. Cite RKA IDs you reference."
    )


def strategy_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    context = mcp.rka_get_context(topic=state.get("mission_id", ""))
    status = mcp.rka_get_status()
    prompt = _build_strategy_prompt(state, context, status)
    strategy_text = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)

    note_id = mcp.rka_add_note(
        content=strategy_text,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["brain-strategy"],
        importance="high",
    )

    return {
        "current_phase": "brain_strategy",
        "current_node": "strategy_node",
        "brain_strategy": strategy_text,
        "brain_position": _summarize_position(strategy_text),
        "artifacts": [_artifact(note_id, "journal", "strategy_node")],
    }


# ---------------------------------------------------------------------------
# 2. confirmation_brief
# ---------------------------------------------------------------------------


def _build_confirmation_prompt(state: ResearchWorkflowState) -> str:
    return (
        "Produce a Confirmation Brief for the PI summarizing:\n"
        "  1. What this workflow run will attempt.\n"
        "  2. Key assumptions the PI should validate.\n"
        "  3. The decision points where PI input will be requested.\n"
        "  4. Estimated budget envelope.\n\n"
        f"Strategy so far:\n{state.get('brain_strategy', '(empty)')}\n"
    )


def confirmation_brief(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    prompt = _build_confirmation_prompt(state)
    brief_text = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)

    note_id = mcp.rka_add_note(
        content=brief_text,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["confirmation-brief"],
        confidence="hypothesis",
        importance="high",
    )

    return {
        "current_phase": "brain_confirmation",
        "current_node": "confirmation_brief",
        "artifacts": [_artifact(note_id, "journal", "confirmation_brief")],
        # Queue this for the upcoming pi_greenlight interrupt — payload is
        # the brief text itself, presented for PI accept/redirect.
        "decisions_to_present": [
            {
                "title": "Confirmation Brief",
                "options": ["approve", "redirect"],
                "context": brief_text,
                "source_node": "confirmation_brief",
                "source_artifact": note_id,
            }
        ],
    }


# ---------------------------------------------------------------------------
# 3. decision_present — queue a structured decision for PI selection
# ---------------------------------------------------------------------------


def _build_decision_prompt(state: ResearchWorkflowState) -> str:
    return (
        "Draft a decision packet for PI selection. Provide:\n"
        "  - The question being decided.\n"
        "  - 2-4 options with trade-offs.\n"
        "  - The Brain's recommendation (option index + 1-sentence reason).\n\n"
        f"Current strategy:\n{state.get('brain_strategy', '(empty)')}\n"
        f"Executor's most recent position:\n{state.get('executor_position', '(empty)')}\n"
    )


def decision_present(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    prompt = _build_decision_prompt(state)
    decision_draft = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)

    # Draft is journaled (not yet a decision — decision creation happens
    # after PI selects an option, in pi_decision_select → finalization).
    note_id = mcp.rka_add_note(
        content=decision_draft,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["decision-draft"],
        importance="high",
    )

    return {
        "current_phase": "brain_review",
        "current_node": "decision_present",
        "artifacts": [_artifact(note_id, "journal", "decision_present")],
        "decisions_to_present": [
            {
                "title": "Brain-drafted decision",
                "options": ["accept", "modify", "reject"],
                "context": decision_draft,
                "source_node": "decision_present",
                "source_artifact": note_id,
            }
        ],
    }


# ---------------------------------------------------------------------------
# 4. cluster_review — `rka_review_cluster` integration
# ---------------------------------------------------------------------------


def _build_cluster_review_prompt(state: ResearchWorkflowState, research_map: dict) -> str:
    return (
        "Review the current research map for evidence-cluster issues — "
        "contradictions, freshness gaps, unassigned claims, or missing "
        "provenance edges. Identify the 1-3 highest-leverage clusters to "
        "address next.\n\n"
        f"Research map:\n{research_map}\n"
    )


def cluster_review(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    research_map = mcp.rka_get_research_map()
    prompt = _build_cluster_review_prompt(state, research_map)
    review_text = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)

    note_id = mcp.rka_add_note(
        content=review_text,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["cluster-review"],
        importance="normal",
    )

    return {
        "current_phase": "brain_review",
        "current_node": "cluster_review",
        "artifacts": [_artifact(note_id, "journal", "cluster_review")],
    }


# ---------------------------------------------------------------------------
# 5. gate1_validation — accept or redirect the Executor's Backbrief
# ---------------------------------------------------------------------------


def _build_gate1_prompt(state: ResearchWorkflowState) -> str:
    return (
        "Gate 1 plan validation. Evaluate the Executor's Backbrief against:\n"
        "  - Mission acceptance criteria coverage.\n"
        "  - Assumption explicitness (each labeled A1, A2, …).\n"
        "  - Risk register completeness.\n"
        "  - Bookkeeper-invariant safety where applicable.\n\n"
        "Emit a verdict on the FIRST LINE: APPROVED or REDIRECTED.\n"
        "Follow with a one-paragraph rationale.\n\n"
        f"Executor Backbrief:\n{state.get('executor_backbrief', '(empty)')}\n"
    )


def _parse_gate1_verdict(text: str) -> str:
    """Pull `approved` / `redirected` off the first line of the verdict."""
    first = text.strip().split("\n", 1)[0].upper()
    if "APPROVED" in first:
        return "approved"
    return "redirected"


def gate1_validation(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    prompt = _build_gate1_prompt(state)
    verdict_text = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)
    verdict = _parse_gate1_verdict(verdict_text)

    note_id = mcp.rka_add_note(
        content=verdict_text,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["gate1", f"verdict-{verdict}"],
        importance="high",
    )

    return {
        "current_phase": "brain_review",
        "current_node": "gate1_validation",
        "gate1_verdict": verdict,
        "brain_position": _summarize_position(verdict_text),
        "artifacts": [_artifact(note_id, "journal", "gate1_validation")],
    }


# ---------------------------------------------------------------------------
# 6. final_synthesis — mission-acceptance writeup
# ---------------------------------------------------------------------------


def _build_final_synthesis_prompt(state: ResearchWorkflowState) -> str:
    artifact_summary = "\n".join(
        f"  - {a.get('rka_id')} ({a.get('entity_type')}, by {a.get('node_name')})"
        for a in state.get("artifacts", [])
    )
    return (
        "Final mission synthesis. Produce a 5-section writeup:\n"
        "  1. What this run achieved (mapped to acceptance criteria).\n"
        "  2. Key evidence + RKA IDs.\n"
        "  3. Decisions resolved or surfaced.\n"
        "  4. Anomalies + open questions.\n"
        "  5. Recommended next missions.\n\n"
        f"Artifacts produced this run:\n{artifact_summary or '  (none)'}\n"
        f"Executor reports observed:\n"
        f"  - errors: {len(state.get('errors', []))}\n"
        f"  - checkpoints: {len(state.get('checkpoints', []))}\n"
        f"  - PI interrupts: {len(state.get('interrupts', []))}\n"
    )


def final_synthesis(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    prompt = _build_final_synthesis_prompt(state)
    synthesis_text = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)

    # Journal the synthesis, then surface as a mission report.
    note_id = mcp.rka_add_note(
        content=synthesis_text,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["final-synthesis"],
        confidence="tested",
        importance="critical",
    )

    return {
        "current_phase": "complete",
        "current_node": "final_synthesis",
        "terminal_state": "complete",
        "artifacts": [_artifact(note_id, "journal", "final_synthesis")],
    }
