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
    "uncertainty.\n\n"
    # ── Phase 2.5 deltas folded per dec_01KRVHZ4P3F1GXE75RRAQX3BTP
    # (mis_01KRVJ240VXH7NQ0PMSHXHK888). Runtime-relevant disciplines only;
    # architectural patterns already enforced in orchestrator source are
    # SKIPPED-PYTHON with code-path references in skill-prompt-deltas.md.
    # ────────────────────────────────────────────────────────────────────
    # Delta #2 — Mid-mission Backbrief gate at structural milestones
    "Gate cadence. For missions longer than ~5 tasks, identify the "
    "foundation-locking task and gate-ratify the Backbrief before downstream "
    "work proceeds. Re-verify upfront-Backbrief assumptions against any "
    "empirical evidence the foundation work surfaced — a mid-mission gate "
    "is cheap insurance against compounded misalignment.\n\n"
    # Delta #7 — Conservative malformed-input defaults
    "Output parsing. When parsing structured outputs from your own LLM "
    "calls, default to the conservative branch if parsing fails — for "
    "verdicts, that means redirect, not approve. A malformed reply that "
    "lacks the expected token must not be treated as an implicit "
    "go-ahead.\n\n"
    # Delta #14a — Metric divergence-as-headline (Status reporting)
    "Status reporting. When the expected and observed values of a measured "
    "metric diverge, lead the next status update (report, journal note, or "
    "PI notification) with the divergence — not the raw numbers. Use the "
    "form 'expected X, observed Y — Z% off' in the first sentence. Burying "
    "divergence inside a metrics table delays PI awareness; the metric "
    "matters because the divergence matters.\n\n"
    # Delta #15 — PI batch-review affordance
    "PI interactions. When queueing more than ~10 decisions for a single "
    "PI interrupt, prefer auto-paginating the payload (`batched=True`, "
    "`page_size=N`, `total_items=N`) so the PI can review in batches "
    "instead of a single fatigue-inducing blob. For lower-volume manual "
    "flows, still split into 3-5 item chunks. Record "
    "`batch_review_used=True` on the resulting interrupt for analytics "
    "on whether the affordance fired correctly.\n\n"
    # Delta #16 — Affordance F propagation (workflow_thread_id mirror)
    "Affordances. The `workflow_thread_id` tag is structurally identical to "
    "the v2.3.5 `motivated-by-explained` suppression tag: a deterministic "
    "value written on every artifact during a context, used to scope "
    "retrospective queries. Treat workflow-membership tagging as the same "
    "affordance pattern applied to workflow-scoped retrieval — naming the "
    "similarity makes future generalizations cheap."
)


# Per-node system-prompt format requirements (v2.5.3+agentic-rc1 → final
# transition; Phase 2.1 mis_01KRSTZVCTFGF91QZXTYK7ZGDD T1). Phase 1 PilotSDK
# returned hardcoded strings that satisfied downstream parsers; real Claude
# returns free-form prose. These per-call system-prompt extensions instruct
# Claude to start replies with the exact tokens the parsers expect, so the
# existing prefix parsers continue to work (option (a) from the resolved
# checkpoint chk_01KRSTFD7203NWAR8MYD91KSFV; defer tool-use option (b) to
# a hypothetical Phase 2.2 if (a) proves insufficient).

_GATE1_FORMAT = (
    "\n\nFORMAT REQUIREMENT (mechanical parsing — must follow exactly):\n"
    "Begin your reply with the verdict token on line 1, column 1: either "
    "`APPROVED:` (uppercase, colon-suffixed) or `REDIRECTED:` (same). "
    "Follow with one paragraph of rationale on subsequent lines. The first "
    "line is parsed by string match — anything else there breaks the gate."
)

_POSITION_FORMAT = (
    "\n\nFORMAT REQUIREMENT: begin your reply with a one-line position "
    "summary (≤200 chars) on line 1. Detail on subsequent lines. The first "
    "line is captured verbatim into the workflow state as your position."
)


def _brain_system(format_hint: str = "") -> str:
    """Compose the Brain system prompt with an optional per-node format hint."""
    return BRAIN_SYSTEM + format_hint


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


def _format_mission_body(mission: dict | None, *, task_char_cap: int = 240) -> str:
    """Render a mission's body fields into a compact prompt section.

    Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T4): the autonomous brain_node
    + confirmation_brief + backbrief_draft need to SEE the mission body in
    the LLM prompt — Phase 2.4 confirmed empirically that without it, the
    brain produces SKELETON Backbriefs and gate1 correctly REDIRECTs (the
    PilotSDK fixture happened to mask the gap with canned responses).

    Format is keys-and-values with mild truncation on long task descriptions
    so a 15-task mission doesn't blow the context budget. Returns
    "(mission body unavailable)" if the fetch returned None or empty.
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
# 1. strategy_node
# ---------------------------------------------------------------------------


def _build_strategy_prompt(
    state: ResearchWorkflowState,
    context: dict,
    status: dict,
    mission: dict | None,
) -> str:
    return (
        "Session-start strategy synthesis.\n\n"
        f"Project status:\n{status}\n\n"
        f"Relevant prior context:\n{context}\n\n"
        f"Current mission: {state.get('mission_id', '(none)')}\n"
        f"Motivated by decision: {state.get('motivated_by_decision_id', '(none)')}\n\n"
        f"Mission body:\n{_format_mission_body(mission)}\n\n"
        "Produce a short strategy outline: what this run should do, in what "
        "order, with what evidence checks. Cite RKA IDs you reference."
    )


def strategy_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    mission_id = state.get("mission_id")
    # Phase 2.5 (mis_01KRVJ240VXH7NQ0PMSHXHK888 T4): without the mission body
    # the LLM can't produce a substantive strategy — Phase 2.4 retry confirmed
    # this empirically (skeleton Backbrief → gate1 REDIRECT). Fetch up front
    # and feed into _build_strategy_prompt.
    mission = mcp.rka_get_mission(id=mission_id) if mission_id else None
    context = mcp.rka_get_context(topic=mission_id or "")
    status = mcp.rka_get_status()
    prompt = _build_strategy_prompt(state, context, status, mission)
    # _POSITION_FORMAT ensures real Claude's reply begins with a one-line
    # position summary (consumed by _summarize_position below). Phase 1's
    # PilotSDK happened to satisfy this naturally; real Claude needs the hint.
    strategy_text = sdk.complete(prompt=prompt, system=_brain_system(_POSITION_FORMAT))

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


def _build_confirmation_prompt(
    state: ResearchWorkflowState, mission: dict | None
) -> str:
    return (
        "Produce a Confirmation Brief for the PI summarizing:\n"
        "  1. What this workflow run will attempt.\n"
        "  2. Key assumptions the PI should validate.\n"
        "  3. The decision points where PI input will be requested.\n"
        "  4. Estimated budget envelope.\n\n"
        f"Strategy so far:\n{state.get('brain_strategy', '(empty)')}\n\n"
        f"Mission body:\n{_format_mission_body(mission)}\n"
    )


def confirmation_brief(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    mission_id = state.get("mission_id")
    # Phase 2.5 T4: same data-flow fix as strategy_node — feed the mission
    # body so the Confirmation Brief is grounded in objective/tasks/AC.
    mission = mcp.rka_get_mission(id=mission_id) if mission_id else None
    prompt = _build_confirmation_prompt(state, mission)
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
    # _GATE1_FORMAT enforces the APPROVED:/REDIRECTED: first-line token
    # that _parse_gate1_verdict relies on. Phase 1's PilotSDK returned the
    # token verbatim; real Claude needs the explicit format requirement so
    # the verdict isn't mis-parsed as "redirected" and routed to
    # escalation_router (the v2.5.3+agentic-rc1 cascade failure).
    verdict_text = sdk.complete(prompt=prompt, system=_brain_system(_GATE1_FORMAT))
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
