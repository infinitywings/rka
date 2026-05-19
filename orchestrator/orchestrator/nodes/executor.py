"""Executor nodes (4) — Backbrief drafting, mission execution, report submission,
ratification-gated action execution.

  - `backbrief_draft`            — produces the upfront Backbrief journal entry
  - `mission_execute`            — performs the mission work + emits structured
                                   `proposed_actions` JSON for PI ratification
  - `submit_report`              — synthesizes and submits the final mission report
  - `execute_ratified_actions`   — Phase 2.7 T3e: iterates `state["ratified_actions"]`
                                   and calls write-side MCP methods from the parent
                                   process (subprocess is read-only per T2)

Like the Brain nodes, each is a sync `(state, sdk, mcp) -> dict` function.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from orchestrator.llm_client import SDKClient, WRITE_TOOLS
from orchestrator.mcp_client import MCPClient
from orchestrator.state import ArtifactRef, ErrorRecord, ResearchWorkflowState

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM = (
    "You are the Executor in an RKA-managed research project. Your job "
    "is to implement missions: produce Backbriefs, run experiments, "
    "modify code, and submit structured reports with provenance. Defer "
    "strategic decisions to the Brain. When in doubt, escalate via "
    "checkpoint rather than guessing.\n\n"
    # ── Phase 2.5 deltas folded per dec_01KRVHZ4P3F1GXE75RRAQX3BTP
    # (mis_01KRVJ240VXH7NQ0PMSHXHK888). Runtime-relevant disciplines only;
    # architectural patterns already enforced in orchestrator source are
    # SKIPPED-PYTHON with code-path references in skill-prompt-deltas.md.
    # ────────────────────────────────────────────────────────────────────
    # Delta #1 — Version-drift re-verification
    "Backbrief — Confirm Your Plan. For every library version pin in your "
    "Backbrief, capture the current PyPI `info.version` and the last-"
    "release date for the pinned major. Flag any pin where the line has "
    "been silent more than 6 months. Pinning to abandoned majors is a "
    "worse failure mode than tracking current stable — re-verify "
    "Backbrief assumptions about library versions older than 6 months "
    "BEFORE they harden into mission pins.\n\n"
    # Delta #8 — Defensive missing-required-field paths
    "Guardrails. Inside an orchestrator workflow, prefer appending an "
    "ErrorRecord over raising — the topology has a defined escalation "
    "path (`escalation_router`); raising bypasses it and loses the "
    "workflow checkpointer's recovery affordance. `submit_report` with a "
    "missing `mission_id` appends an error and returns rather than "
    "raising, so the PI can be notified via `pi_acceptance` with the "
    "partial state.\n\n"
    # Delta #14b — Metric divergence-as-headline (Report Submission)
    "Report Submission. When the expected and observed values of a "
    "measured metric diverge during a run, lead the report (and any "
    "related journal notes or PI notifications) with the divergence — "
    "not the raw numbers. Use the form 'expected X, observed Y — Z% off' "
    "in the first sentence. Burying divergence inside a metrics table "
    "delays PI awareness; the metric matters because the divergence "
    "matters.\n\n"
    # Delta #17 — Affordance G surface re-exposed
    "Repo-specific procedures. 422 from the RKA REST API is an integrity "
    "error, not a transient failure. Affordance G surfaces knowledge-pack-"
    "integrity violations (orphaned references, missing transitive "
    "provenance) as structured HTTP 422 responses. The orchestrator's "
    "`RestMCPClient._request` maps these to `CheckpointError` and routes "
    "via `escalation_router`. Do NOT retry — it's a strategic problem "
    "that needs PI input, not a network retry.\n\n"
    # ── Phase 2.7 (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R T3; PI-ratified at T1 mid-mission
    # gate per jrn_01KRXP96THHEAKCGB0P0KGV7Y9). Option C requires the executor LLM
    # to emit a structured proposed_actions block so the orchestrator can route
    # write-side MCP calls through pi_decision_select ratification before commit.
    # ────────────────────────────────────────────────────────────────────────────
    "Action proposals. When mission_execute runs, end your reply with a "
    "structured JSON block under the key `proposed_actions`: a list of "
    '`{"tool": str, "args": dict, "rationale": str}` objects naming write-side '
    "RKA MCP methods you propose to call. The orchestrator parses this block "
    "and surfaces it to PI via `pi_decision_select` before any write commits — "
    "you do NOT call write tools directly. If planning concludes no action is "
    "needed, emit `proposed_actions: []` explicitly — never omit the block. "
    "Malformed JSON falls back to empty proposed_actions + ErrorRecord per the "
    "conservative-malformed-input default.\n\n"
    # ── Phase 2.11 (mis_01KRYT62XQK5NK3BY7G9BGRAPS T2; Brain-ratified scope per
    # dec_01KRYT1GCP5N9CJZ2YE2N3BTBH Option A). Closes Phase 2.10 Finding 1: brain
    # `mission_execute` LLM misframed wrapper-vs-target — interpreted the Phase 2.10
    # wrapper mission's T0-T7 task structure (from the Backbrief) as the work to
    # execute, emitting a single rka_submit_report stub instead of 3× rka_update_note
    # for the target mission's 3 cross-reference items. This delta locks the
    # distinction at the prompt layer so future runs don't re-encounter the gap.
    # ────────────────────────────────────────────────────────────────────────────
    "Wrapper-vs-target distinction. When `mission_execute` runs, your "
    "work-target is the `mission_id` field in the workflow state, NOT the "
    "wrapper mission whose Backbrief you may be reading. If the Backbrief "
    "outlines T0-T7 plan structure (pre-flight, debt discharge, driver "
    "invocation, keystone test, narrative, commits, mission report), that is "
    "wrapper scaffolding the orchestrator already executes via graph topology — "
    "your job is to execute against the target mission's actual tasks (typically "
    "cross-reference work, content extraction, decision linkage, etc.). Read "
    "the target mission via `rka_get_mission(mission_id_in_state)` before "
    "planning `proposed_actions`; ground every action item in the target "
    "mission's task list, not the wrapper's planning structure. A wrapper "
    "Backbrief's T1-T7 are framework metadata describing what the PI/Brain did "
    "to PREPARE this run — they are not your work to re-do."
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


def _format_mission_body(mission: dict | None, *, task_char_cap: int = 240) -> str:
    """Render a mission's body fields into a compact prompt section.

    Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T5): backbrief_draft needs to
    SEE the mission body in the LLM prompt — same data-flow fix applied to
    `brain.strategy_node` + `brain.confirmation_brief` in T4. Duplicated
    here rather than imported across orchestrator nodes so each node module
    remains self-contained against a single-responsibility helper surface;
    if a third call site appears, lift into a shared `nodes/_prompts.py`.
    """
    if not mission or not isinstance(mission, dict):
        return "(mission body unavailable)"

    objective = (mission.get("objective") or "").strip()
    acceptance = (mission.get("acceptance_criteria") or "").strip()
    scope = (mission.get("scope_boundaries") or "").strip()
    tasks = mission.get("tasks") or []

    lines: list[str] = []
    if objective:
        lines.append(f"Objective: {objective}")
    if tasks:
        lines.append(f"Tasks ({len(tasks)}):")
        for i, t in enumerate(tasks, 1):
            desc = (t.get("description") if isinstance(t, dict) else str(t)) or ""
            status = (t.get("status") if isinstance(t, dict) else "") or "pending"
            if len(desc) > task_char_cap:
                desc = desc[: task_char_cap - 1] + "…"
            lines.append(f"  {i}. [{status}] {desc}")
    if acceptance:
        lines.append(f"Acceptance criteria:\n{acceptance}")
    if scope:
        lines.append(f"Scope boundaries:\n{scope}")

    return "\n".join(lines) if lines else "(mission body empty)"


# ---------------------------------------------------------------------------
# 1. backbrief_draft — produces the upfront Backbrief journal entry
# ---------------------------------------------------------------------------


def _build_backbrief_prompt(
    state: ResearchWorkflowState, mission: dict | None
) -> str:
    return (
        "Draft an upfront Backbrief for the mission. Cover:\n"
        "  1. Plan summary (numbered steps).\n"
        "  2. Acceptance-criteria interpretation (per the mission spec).\n"
        "  3. Assumptions (numbered A1, A2, …; explicit and falsifiable).\n"
        "  4. Risks (numbered R1, R2, …; with mitigations).\n"
        "  5. Approach (files touched, test method, invariants preserved).\n\n"
        f"Mission: {state.get('mission_id', '(unset)')}\n"
        f"Motivated-by decision: {state.get('motivated_by_decision_id', '(unset)')}\n"
        f"Mission body:\n{_format_mission_body(mission)}\n\n"
        f"Brain's strategy context:\n{state.get('brain_strategy', '(empty)')}\n"
    )


def backbrief_draft(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    mission_id = state.get("mission_id")
    # Phase 2.5 T5: same data-flow fix as brain.strategy_node — fetch the
    # mission body so the upfront Backbrief is grounded in objective/tasks/AC.
    mission = mcp.rka_get_mission(id=mission_id) if mission_id else None
    prompt = _build_backbrief_prompt(state, mission)
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
        f"Gate 1 verdict: {state.get('gate1_verdict', '(pending)')}\n\n"
        "End your reply with a structured JSON block per the EXECUTOR_SYSTEM "
        "'Action proposals' directive: `{\"proposed_actions\": [{...}, ...]}` "
        "naming the write-side RKA MCP methods you propose to call (e.g., "
        '`rka_update_note` with `id` + `related_decisions`). Emit '
        "`proposed_actions: []` if no action is required. The orchestrator "
        "routes these through `pi_decision_select` for PI ratification "
        "before any write commits."
    )


# ---------------------------------------------------------------------------
# Phase 2.7 T3c — structured-output extraction for proposed_actions
# ---------------------------------------------------------------------------


# Fenced ```json ... ``` block carrying a proposed_actions object. The
# LLM may emit either fenced OR bare-trailing JSON; the parser accepts both.
_PROPOSED_ACTIONS_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL
)


def _extract_last_balanced_object(text: str) -> str | None:
    """Find the LAST balanced `{...}` substring in `text` by brace-counting.

    Walks backwards from the rightmost `}` to find the matching `{` that
    balances brace depth. Returns the substring or None. This is robust
    to nested objects/arrays that a single-level regex would miss.
    """
    if not text:
        return None
    last_close = text.rfind("}")
    if last_close < 0:
        return None
    depth = 0
    for i in range(last_close, -1, -1):
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                return text[i : last_close + 1]
    return None


def _parse_proposed_actions(
    text: str,
) -> tuple[list[dict], ErrorRecord | None]:
    """Extract the `proposed_actions` list from an LLM reply.

    Returns `(actions, error_record)`. On a successful parse, `actions` is
    the list and `error_record` is None. On any failure (no JSON block,
    malformed JSON, missing key, wrong shape), `actions` is `[]` and
    `error_record` is a populated ErrorRecord per Phase 2.5 Delta #7's
    conservative-malformed-input default.

    Robust to multi-level nesting: tries fenced ```json``` blocks first,
    then falls back to the last balanced `{...}` substring (brace-counted,
    not regex-matched).
    """
    if not text:
        return [], _make_error(
            "mission_execute",
            "proposed_actions_parse_failure",
            "empty LLM reply; no JSON to parse",
        )

    candidates: list[str] = []
    fenced = list(_PROPOSED_ACTIONS_FENCE_RE.finditer(text))
    if fenced:
        candidates.append(fenced[-1].group(1))
    trailing = _extract_last_balanced_object(text)
    if trailing:
        candidates.append(trailing)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        actions = parsed.get("proposed_actions")
        if actions is None:
            continue
        if not isinstance(actions, list):
            return [], _make_error(
                "mission_execute",
                "proposed_actions_parse_failure",
                f"proposed_actions is not a list (got {type(actions).__name__})",
            )
        # Validate each action shape.
        valid: list[dict] = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            if "tool" not in a or "args" not in a:
                continue
            if not isinstance(a.get("args"), dict):
                continue
            valid.append({"tool": a["tool"], "args": a["args"], "rationale": a.get("rationale", "")})
        return valid, None

    return [], _make_error(
        "mission_execute",
        "proposed_actions_parse_failure",
        "no valid JSON object with proposed_actions key found in reply",
    )


def _make_error(node_name: str, error_type: str, detail: str) -> ErrorRecord:
    return {
        "node_name": node_name,
        "error_type": error_type,
        "detail": detail,
        "timestamp": _now_iso(),
    }


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

    # Phase 2.7 T3c: extract structured proposed_actions from the LLM reply.
    proposed_actions, parse_error = _parse_proposed_actions(work_log)

    update: dict = {
        "current_phase": "executor_mission",
        "current_node": "mission_execute",
        "executor_position": _summarize_position(work_log),
        "artifacts": [_artifact(note_id, "journal", "mission_execute")],
        "proposed_actions": proposed_actions,
    }
    if parse_error is not None:
        update["errors"] = [parse_error]
    return update


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


# ---------------------------------------------------------------------------
# 4. execute_ratified_actions — Phase 2.7 T3e
# ---------------------------------------------------------------------------


# Map a WRITE_TOOL name to the entity_type the resulting RKA id implies.
# Used to populate ArtifactRef.entity_type so the audit trail records what
# kind of entity each ratified action produced. Centralized here (vs the
# orchestrator/mcp_client.py prefix-conventions) because this is the only
# node that needs the mapping.
_WRITE_TOOL_ENTITY_TYPES: dict[str, str] = {
    "rka_add_note": "journal",
    "rka_add_decision": "decision",
    "rka_submit_checkpoint": "checkpoint",
    "rka_submit_report": "report",
    "rka_create_mission": "mission",
    "rka_update_note": "journal",
    # Phase 2.13 T2 (mis_01KRYZMEAT01SMNNXQXS3JRC4W): rka_bulk_update can
    # update note/decision/literature in one call; "bulk" labels the
    # artifact so the run-artifact JSON ledger surfaces the fanout
    # cleanly. Per-entity provenance is recoverable from the bulk
    # summary string stored in ArtifactRef.rka_id.
    "rka_bulk_update": "bulk",
}


def execute_ratified_actions(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Phase 2.7 T3e — parent-process execution of PI-ratified write actions.

    Iterates `state["ratified_actions"]` (populated by `pi_decision_select`
    when the PI ratifies the brain-drafted decision packet, which now
    carries `mission_execute`'s structured `proposed_actions`). For each
    action, validates the `tool` name is in `WRITE_TOOLS` (defense in
    depth against any LLM that bypasses the subprocess disallowlist) and
    dispatches via `getattr(mcp, tool)(**args)`. Successful calls produce
    `ArtifactRef`s; failures produce `ErrorRecord`s — both append-only
    per the state schema's reducer convention.

    A no-op when `state["ratified_actions"]` is empty (rejected, escaped,
    or never populated). This means the node sits unconditionally between
    `pi_decision_select` and `final_synthesis` in the graph without
    requiring routing logic to skip it.
    """
    actions = state.get("ratified_actions", []) or []
    new_artifacts: list[ArtifactRef] = []
    new_errors: list[ErrorRecord] = []

    for action in actions:
        if not isinstance(action, dict):
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_shape_error",
                    f"action is not a dict (got {type(action).__name__})",
                )
            )
            continue

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}

        # Defense in depth: only the static WRITE_TOOLS registry is callable.
        if tool not in WRITE_TOOLS:
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_tool_not_allowed",
                    (
                        f"tool {tool!r} is not in WRITE_TOOLS registry — "
                        f"the executor LLM proposed an action the orchestrator "
                        f"refuses to execute. Phase 2.7 Option C invariant."
                    ),
                )
            )
            continue

        method = getattr(mcp, tool, None)
        if method is None:
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_method_missing",
                    (
                        f"tool {tool!r} is in WRITE_TOOLS but MCPClient has "
                        f"no method by that name. Protocol drift; surface."
                    ),
                )
            )
            continue

        if not isinstance(args, dict):
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_args_shape_error",
                    f"args for {tool!r} is not a dict",
                )
            )
            continue

        try:
            rka_id = method(**args)
        except Exception as e:  # noqa: BLE001 — surface all failures as ErrorRecord
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_call_failed",
                    f"tool={tool!r} args_keys={sorted(args.keys())!r} exc={e!r}",
                )
            )
            continue

        new_artifacts.append(
            {
                "rka_id": rka_id or "",
                "entity_type": _WRITE_TOOL_ENTITY_TYPES.get(tool, "unknown"),
                "node_name": "execute_ratified_actions",
                "timestamp": _now_iso(),
            }
        )

    update: dict = {
        "current_phase": "executor_mission",
        "current_node": "execute_ratified_actions",
    }
    if new_artifacts:
        update["artifacts"] = new_artifacts
    if new_errors:
        update["errors"] = new_errors
    return update


# ---------------------------------------------------------------------------
# 5. submit_report — mission acceptance writeup via rka_submit_report
# ---------------------------------------------------------------------------


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
