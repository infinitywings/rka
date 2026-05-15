"""Executor nodes (3) — Backbrief drafting, mission execution, report submission.

  - `backbrief_draft`   — produces the upfront Backbrief journal entry
  - `mission_execute`   — performs the mission work + records artifacts
  - `submit_report`     — synthesizes and submits the final mission report

Like the Brain nodes, each is a sync `(state, sdk, mcp) -> dict` function.
"""

from __future__ import annotations

from datetime import datetime, timezone

from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.state import ArtifactRef, ResearchWorkflowState

EXECUTOR_SYSTEM = (
    "You are the Executor in an RKA-managed research project. Your job "
    "is to implement missions: produce Backbriefs, run experiments, "
    "modify code, and submit structured reports with provenance. Defer "
    "strategic decisions to the Brain. When in doubt, escalate via "
    "checkpoint rather than guessing."
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact(rka_id: str, entity_type: str, node_name: str) -> ArtifactRef:
    return {
        "rka_id": rka_id,
        "entity_type": entity_type,
        "node_name": node_name,
        "timestamp": _now_iso(),
    }


def _summarize_position(text: str, *, max_chars: int = 280) -> str:
    first_line = text.strip().split("\n", 1)[0]
    return first_line if len(first_line) <= max_chars else first_line[: max_chars - 1] + "…"


# ---------------------------------------------------------------------------
# 1. backbrief_draft — produces the upfront Backbrief journal entry
# ---------------------------------------------------------------------------


def _build_backbrief_prompt(state: ResearchWorkflowState) -> str:
    return (
        "Draft an upfront Backbrief for the mission. Cover:\n"
        "  1. Plan summary (numbered steps).\n"
        "  2. Acceptance-criteria interpretation (per the mission spec).\n"
        "  3. Assumptions (numbered A1, A2, …; explicit and falsifiable).\n"
        "  4. Risks (numbered R1, R2, …; with mitigations).\n"
        "  5. Approach (files touched, test method, invariants preserved).\n\n"
        f"Mission: {state.get('mission_id', '(unset)')}\n"
        f"Motivated-by decision: {state.get('motivated_by_decision_id', '(unset)')}\n"
        f"Brain's strategy context:\n{state.get('brain_strategy', '(empty)')}\n"
    )


def backbrief_draft(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    prompt = _build_backbrief_prompt(state)
    backbrief_text = sdk.complete(prompt=prompt, system=EXECUTOR_SYSTEM)

    note_id = mcp.rka_add_note(
        content=backbrief_text,
        type="note",
        source="executor",
        related_mission=state.get("mission_id"),
        tags=["backbrief", "upfront"],
        confidence="hypothesis",
        importance="high",
    )

    return {
        "current_phase": "executor_backbrief",
        "current_node": "backbrief_draft",
        "executor_backbrief": backbrief_text,
        "executor_position": _summarize_position(backbrief_text),
        "artifacts": [_artifact(note_id, "journal", "backbrief_draft")],
    }


# ---------------------------------------------------------------------------
# 2. mission_execute — perform the work
# ---------------------------------------------------------------------------


def _build_mission_execute_prompt(state: ResearchWorkflowState) -> str:
    return (
        "Execute the mission per the approved Backbrief. Produce a structured "
        "report of work performed, including:\n"
        "  - Files modified (paths + summary).\n"
        "  - Tests added or changed.\n"
        "  - Anomalies encountered.\n"
        "  - Any assumption invalidation (escalate if found).\n\n"
        f"Approved Backbrief:\n{state.get('executor_backbrief', '(empty)')}\n"
        f"Gate 1 verdict: {state.get('gate1_verdict', '(pending)')}\n"
    )


def mission_execute(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    # Defensive: if Gate 1 redirected, this node shouldn't have been reached.
    # We still run (LangGraph topology owns control flow), but mark phase
    # accordingly so the router in T6 can pick it up.
    prompt = _build_mission_execute_prompt(state)
    work_log = sdk.complete(prompt=prompt, system=EXECUTOR_SYSTEM)

    note_id = mcp.rka_add_note(
        content=work_log,
        type="log",
        source="executor",
        related_mission=state.get("mission_id"),
        tags=["mission-execution"],
        importance="normal",
    )

    return {
        "current_phase": "executor_mission",
        "current_node": "mission_execute",
        "executor_position": _summarize_position(work_log),
        "artifacts": [_artifact(note_id, "journal", "mission_execute")],
    }


# ---------------------------------------------------------------------------
# 3. submit_report — mission acceptance writeup via rka_submit_report
# ---------------------------------------------------------------------------


def _build_report_prompt(state: ResearchWorkflowState) -> str:
    artifact_lines = "\n".join(
        f"  - {a.get('rka_id')} ({a.get('entity_type')}) — by {a.get('node_name')}"
        for a in state.get("artifacts", [])
    ) or "  (no artifacts)"
    return (
        "Compose the mission report. Sections required:\n"
        "  1. summary — one paragraph.\n"
        "  2. findings — bulleted list.\n"
        "  3. anomalies — bulleted list (empty if none).\n"
        "  4. questions — bulleted list (empty if none).\n"
        "  5. codebase_state — what changed and what is now true.\n"
        "  6. recommended_next — bulleted list of follow-ups.\n\n"
        f"Artifacts produced this run:\n{artifact_lines}\n\n"
        f"Work log:\n{state.get('executor_position', '(empty)')}\n"
    )


def submit_report(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    prompt = _build_report_prompt(state)
    report_text = sdk.complete(prompt=prompt, system=EXECUTOR_SYSTEM)

    mission_id = state.get("mission_id")
    # `mission_id` is required by rka_submit_report. If absent (shouldn't
    # happen mid-workflow), surface as an error record rather than crashing.
    if not mission_id:
        return {
            "current_phase": "executor_report",
            "current_node": "submit_report",
            "errors": [
                {
                    "node_name": "submit_report",
                    "error_type": "missing_mission_id",
                    "detail": "state['mission_id'] absent; cannot call rka_submit_report",
                    "timestamp": _now_iso(),
                }
            ],
        }

    report_id = mcp.rka_submit_report(
        content=report_text,
        related_mission=mission_id,
        summary=_summarize_position(report_text, max_chars=400),
    )

    return {
        "current_phase": "executor_report",
        "current_node": "submit_report",
        "final_report_id": report_id,
        "artifacts": [_artifact(report_id, "report", "submit_report")],
    }
