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

import re
from datetime import datetime, timezone

from orchestrator.llm_client import (
    SDK_TIMEOUT_DEFAULT_S,
    SDKClient,
    SDKTimeoutError,
    WRITE_TOOLS,
)
from orchestrator.mcp_client import MCPClient
from orchestrator.rka_enums import (
    RKA_CHECKPOINT_TYPES,
    RKA_CONFIDENCES,
    RKA_DECISION_DECIDED_BY,
    RKA_DECISION_KINDS,
    RKA_DECISION_STATUSES,
    RKA_IMPORTANCES,
    RKA_JOURNAL_STATUSES,
    RKA_JOURNAL_TYPES_V2_CANONICAL,
    RKA_MISSION_STATUSES,
    RKA_SOURCES,
)
from orchestrator.state import (
    MAX_GREENLIGHT_REDRAFTS,
    ArtifactRef,
    ErrorRecord,
    ResearchWorkflowState,
)

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
    "similarity makes future generalizations cheap.\n\n"
    # Phase D2 — built-in filesystem tools available to the subprocess
    "Available tools beyond RKA read-side MCP: you may call the built-in "
    "Read, Grep, Glob, WebFetch, and WebSearch tools to read host-side "
    "files in the PI's mounted workspace (HOST_WORKSPACE_ROOT) and to "
    "ground reasoning in source material. Bash, Write, and Edit are also "
    "available, but Brain work should remain READ-ONLY at the host FS "
    "layer — strategy decisions and journal/decision writes flow through "
    "`proposed_actions` for PI ratification, never through direct file "
    "mutations. Use the read tools liberally to verify claims before "
    "you propose; use the write/Bash tools only when the mission "
    "explicitly assigns a small probe (e.g., `python -c \"import X\"` "
    "to verify a dependency).\n\n"
    # v2.6 absorption — RKA tool calls require project_id
    "RKA project scoping (v2.6+): every project-scoped rka_* tool you "
    "call (read or write) requires `project_id` as a kwarg. The active "
    "project_id for this workflow is in the orchestrator state — when "
    "you call rka_get_status / rka_get_journal / rka_get_context / "
    "rka_search / etc., pass `project_id=\"<the project_id from your "
    "context>\"` explicitly. Omitting it raises `TypeError: rka_X() "
    "missing 1 required keyword-only argument: 'project_id'`. There is "
    "no longer an 'active project' default — by design. Same rule "
    "applies to any rka_* in your `proposed_actions` JSON: each action's "
    "`args` must include `project_id`. The pre-v2.6 RKA_PROJECT env var "
    "passing was removed; do not rely on session defaults.\n\n"
    # v2.8.0 (eval-v3) — report-scoped context assembly
    "## Report-scoped context (collect_report_context)\n"
    "When you need the knowledge relevant to a report, section, or themed "
    "question, prefer ONE rka_collect_report_context call (pass the prose "
    "description plus 3-5 short angle_queries) over many rka_get_context / "
    "rka_search calls. It unions multi-angle search seeds with provenance-weighted "
    "graph expansion and returns per-node inclusion provenance — measured 0.84 "
    "cohort recall in one call vs 0.32 for one-shot paragraph search.\n\n"
    # v2.6.3 — RKA navigator architecture (always-on + deferred tiers)
    "## Tool surface (v2.6.3+)\n"
    "RKA's MCP server uses a NAVIGATOR architecture. At startup only "
    "~12 always-on tools are advertised (rka_get_status, rka_get_context, "
    "rka_get_pending_maintenance, rka_get_checkpoints, rka_get_research_map, "
    "rka_search, rka_get, rka_add_note, rka_resolve_checkpoint, plus the "
    "three navigator tools rka_load_tools / rka_list_tools / rka_help). "
    "The other ~79 RKA tools are DEFERRED — they exist on the server but "
    "are hidden from the tool list until you register them.\n"
    "  - To access a deferred RKA tool, FIRST call "
    "`rka_load_tools(names=[\"rka_<name1>\", \"rka_<name2>\", ...])`. "
    "This registers the tools at runtime and fires "
    "`notifications/tools/list_changed`; the call is idempotent and "
    "returns `{loaded, already_active, unknown}`. Pass UNPREFIXED "
    "`rka_*` names (the harness translates).\n"
    "  - To discover what's available without loading everything, use "
    "`rka_list_tools(category=..., query=..., tier=...)` — returns "
    "`{total_tools, filtered_count, categories: {...}}`. To see the "
    "exact signature + docstring of one tool (active OR deferred), use "
    "`rka_help(name=\"rka_<name>\")`.\n"
    "  - Deferred tools you commonly need during strategy / "
    "Confirmation-Brief drafting / decision authoring: rka_add_decision, "
    "rka_create_mission, rka_get_journal, rka_get_mission, "
    "rka_get_decision_tree, rka_get_review_queue, rka_get_literature, "
    "rka_add_literature, rka_trace_provenance, rka_submit_checkpoint, "
    "rka_submit_report. ALL of these require an `rka_load_tools` call "
    "first within the current SDK session.\n"
    "  - The always-on layer is sufficient for read-only context loading "
    "(rka_get_status / rka_get_context / rka_get_research_map / "
    "rka_get_pending_maintenance / rka_get_checkpoints / rka_search / "
    "rka_get). Most planning workflows that culminate in `proposed_actions` "
    "with WRITES (rka_add_decision, rka_create_mission, etc.) MUST call "
    "`rka_load_tools` before proposing — otherwise the LLM call generating "
    "the proposal won't have read-side visibility into those tools' "
    "schemas and signatures.\n\n"
    # Phase-X² polish — allowed WRITE_TOOLS + forbidden lifecycle tools
    "Allowed write tools — your `proposed_actions[*].tool` MUST be one of: "
    + ", ".join(sorted(WRITE_TOOLS)) + ". The parent-side "
    "`execute_ratified_actions` dispatcher rejects any tool outside this "
    "list with `ratified_action_tool_not_allowed` — your proposed work "
    "will be lost. NEVER propose `rka_advance_rq` / `rka_resolve_checkpoint` "
    "/ `rka_supersede_decision` from inside the orchestrator: these are "
    "lifecycle-management tools documented for direct-Claude-as-Brain "
    "flows; the orchestrator's parent-side dispatcher does NOT allowlist "
    "them. Propose state changes through journal entries (`rka_add_note`) "
    "and decisions (`rka_add_decision`) only; let the PI close lifecycle "
    "gates manually via `rka_resolve_checkpoint` in their own RKA "
    "session. Also forbidden: `rka_present_decision` (the orchestrator's "
    "`pi_decision_select` already renders to PI; use `rka_add_decision` "
    "and let the orchestrator stage the rendering).\n\n"
    # v2.6.0+agentic.6 — workflow capability allowlist
    "Workflow capability allowlist (v2.6.0+agentic.6). Each ratified "
    "action's tool belongs to one of five capability buckets:\n"
    "  - `record_knowledge` — rka_add_note, rka_add_decision\n"
    "  - `update_knowledge` — rka_update_note, rka_bulk_update\n"
    "  - `mission_lifecycle` — rka_create_mission, rka_update_mission_status\n"
    "  - `execution_gates` — rka_submit_checkpoint, rka_submit_report\n"
    "  - `ingestion` — rka_ingest_document\n"
    "Each workflow segment runs with a ratified `allowed_capabilities` "
    "subset (e.g., a measure-development run typically holds "
    "`['record_knowledge', 'execution_gates']` so the Executor can write "
    "notes and submit deliverable gates, but NOT change mission "
    "lifecycle state — that's PI-actor scope). When the workflow "
    "allowed_capabilities is provided to your strategy context, "
    "SELF-PRUNE your `proposed_actions` to only include tools whose "
    "capability is in the allowlist. Common Brain hallucination — "
    "proposing `rka_update_mission_status(status='partial')` in an "
    "execution-segment workflow that holds only "
    "`['record_knowledge', 'execution_gates']`: the parent-side "
    "dispatcher rejects this pre-dispatch with "
    "`ratified_action_capability_not_allowed`, EC8 partial-dispatch "
    "routes the failure to a checkpoint, and the PI must complete the "
    "lifecycle write out-of-band — wasting a round-trip. Mission-"
    "lifecycle transitions are intentionally PI-actor scope (state "
    "transitions reshape the autonomy contract for future runs). If "
    "you believe a mission status transition is warranted, surface it "
    "as a checkpoint description or a journal-entry recommendation "
    "for the PI to action — do NOT propose `rka_update_mission_status` "
    "directly from an execution segment.\n\n"
    # Phase-X² polish — enumerate valid RKA enum values
    "RKA write-tool field values (v2.6+). When you propose an action, "
    "every string field with a constrained value space must use one of "
    "the values below — out-of-enum values are rejected pre-dispatch by "
    "the orchestrator (`ratified_action_arg_invalid_enum_value`) AND "
    "at the RKA API (HTTP 422), so the failure is loud + the write is "
    "lost.\n"
    "  - `confidence` (rka_add_note / rka_update_note): "
    + " | ".join(sorted(RKA_CONFIDENCES))
    + ". The value 'confirmed' is NOT valid (common Brain hallucination) — "
    "use 'verified' for findings that have been cross-checked, or "
    "'tested' for findings that have been empirically probed.\n"
    "  - `importance` (rka_add_note / rka_update_note): "
    + " | ".join(sorted(RKA_IMPORTANCES)) + ".\n"
    "  - `source` (rka_add_note / rka_update_note): "
    + " | ".join(sorted(RKA_SOURCES))
    + ". For Brain-authored notes, always use 'brain'.\n"
    "  - `type` (rka_add_note / rka_update_note) — v2 canonical: "
    + " | ".join(sorted(RKA_JOURNAL_TYPES_V2_CANONICAL))
    + ". Prefer these; legacy values (finding, insight, observation, ...) "
    "are silently normalized server-side for back-compat but should be "
    "avoided in new writes.\n"
    "  - `status` (rka_add_note / rka_update_note journal lifecycle): "
    + " | ".join(sorted(RKA_JOURNAL_STATUSES)) + ".\n"
    "  - `decided_by` (rka_add_decision / rka_update_decision): "
    + " | ".join(sorted(RKA_DECISION_DECIDED_BY))
    + ". When Brain authors the decision, use 'brain'.\n"
    "  - `kind` (rka_add_decision / rka_update_decision): "
    + " | ".join(sorted(RKA_DECISION_KINDS))
    + ". 'research_question' is reserved for advanceable RQs; don't use "
    "it casually — most decisions are 'decision' or 'design_choice'.\n"
    "  - `status` (rka_add_decision / rka_update_decision lifecycle): "
    + " | ".join(sorted(RKA_DECISION_STATUSES)) + ".\n"
    "  - `type` (rka_submit_checkpoint): "
    + " | ".join(sorted(RKA_CHECKPOINT_TYPES))
    + ". 'gate' for blocking go/no-go points; 'decision' for forks "
    "needing PI adjudication; 'clarification' for ambiguity surfaces; "
    "'inspection' for hands-off review.\n"
    "  - `status` (rka_create_mission / rka_update_mission_status): "
    + " | ".join(sorted(RKA_MISSION_STATUSES)) + ".\n\n"
    # Phase-X²' polish — canonical field NAMES per WRITE_TOOL.
    # Mirror of the enum-VALUE block above at the field-NAME layer.
    # Surfaced empirically on 2026-06-01: Brain emitted
    # `rka_submit_checkpoint(content=...)` instead of `description=...`
    # — the universal "content is the body field" pattern from
    # rka_add_note's worked example generalises incorrectly across
    # sibling write tools. Out-of-spec field names are rejected
    # pre-dispatch with `ratified_action_arg_missing_required_field`.
    "RKA write-tool canonical field names (Phase-X²' polish). The 9 "
    "WRITE_TOOLS use FIVE different vocabularies for the same semantic "
    "role (the primary body field). Emit the canonical name below for "
    "each tool — some accept aliases for backward compatibility, but "
    "the canonical name is preferred for clarity:\n"
    "  - `rka_add_note`: `content` (required) — the note body.\n"
    "  - `rka_add_decision`: emit `content` as the body field — the "
    "adapter then maps it to RKA's `question` field internally. Plus "
    "`related_journal: list[str]` (required) + `decided_by` + `phase`. "
    "Do NOT emit `question=` directly — the adapter does not accept "
    "that kwarg and would silently drop it via **kw absorption.\n"
    "  - `rka_create_mission`: `objective` (required) + "
    "`motivated_by_decision: str` (required, decision-id reference) + "
    "`acceptance_criteria: list[str]` (required).\n"
    "  - `rka_update_mission_status`: `id` (required, mission-id) + "
    "`status` (optional but typically set).\n"
    "  - `rka_submit_checkpoint`: `description` (required, the "
    "checkpoint body — NOT `content` — though the adapter tolerates "
    "`content`/`message`/`reason` as aliases since the Phase-X²' "
    "polish). Common Brain hallucination: emitting `content=` here. "
    "Canonical is `description`. Plus `mission_id` (required) + "
    "`type` (optional, defaults to 'decision').\n"
    "  - `rka_submit_report`: `summary` (required, the report body — "
    "NOT `content` — though `content` is tolerated as an alias) + "
    "`mission_id` (required).\n"
    "  - `rka_ingest_document`: `content` (required) — the document body.\n"
    "  - `rka_update_note`: `id` (required, jrn-id) + any subset of "
    "the rka_add_note kwargs to patch.\n"
    "  - `rka_bulk_update`: `updates: list[dict]` (required) — each "
    "dict has `entity_type`, `id`, `data`.\n"
    "Negative callout: `content` is NOT canonical for "
    "rka_submit_checkpoint or rka_submit_report (those want "
    "`description` and `summary` respectively). Common Brain "
    "hallucination — emit the canonical name even though the alias "
    "would also work; canonical-name clarity helps the audit trail.\n\n"
    # Phase G — FS Actuator self-classification policy
    "FS Actuator policy. Brain reasoning is host-FS-read-only by design: "
    "use Read, Grep, Glob, WebFetch, WebSearch freely; do NOT call Bash, "
    "Write, or Edit directly as Brain. If your reasoning ever needs an "
    "FS mutation (you want to inspect the side-effect of a probe, or "
    "draft a file the PI should review), put it in `proposed_fs_actions` "
    "alongside `proposed_actions` so the PI can ratify before any FS "
    "side effect lands. The Executor handles the actual mutation; "
    "Brain's role is to propose, not to execute. Phase G2 will add a "
    "hook that enforces this at the SDK layer; until then, your "
    "discipline IS the enforcement.\n\n"
    # Phase E5 — WebFetch/WebSearch egress policy
    "Egress policy (WebFetch / WebSearch). These tools reach the public "
    "internet from the daemon's network — every fetch is observable in "
    "logs and may carry workspace-derived strings (paths, IDs) into "
    "third-party telemetry pipelines. Use them only for: (a) retrieving "
    "published documents (papers, RFCs, standards bodies, vendor docs), "
    "(b) verifying a claim against a primary source, (c) loading library "
    "documentation when context7 lacks coverage. Never fetch from known "
    "telemetry / analytics endpoints (segment.io, segment.com, "
    "amplitude.com, mixpanel.com, statsig.com, posthog.com, heap.io / "
    "heapanalytics.com) — these are blocklisted at the notifications "
    "layer and any reference from your reasoning to them is a smell. "
    "Never craft a URL that embeds workspace paths, project_ids, or "
    "decision_ids as query parameters or path segments. Never POST. "
    "When in doubt prefer RKA tools or context7 over web egress; both "
    "are scoped and audited."
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
    "line is captured verbatim into the workflow state as your position.\n\n"
    # Gap 3B — Brain may propose a capability scope for this run.
    "CAPABILITY PROPOSAL (optional but recommended). You may include a "
    "fenced ```json block of the form `{\"capabilities\": [\"...\", ...]}` "
    "listing the SMALLEST set of write-capability buckets this run "
    "actually needs. Valid bucket names: record_knowledge, "
    "update_knowledge, mission_lifecycle, execution_gates, ingestion. "
    "Omit the block (or leave the list empty) to keep the full "
    "WRITE_TOOLS surface available. A hygiene/cleanup run might propose "
    "[\"record_knowledge\", \"update_knowledge\"]; a planning run might "
    "propose [\"record_knowledge\", \"mission_lifecycle\"]. The PI "
    "ratifies your proposal at pi_greenlight; on accept it becomes the "
    "workflow's allowed_capabilities and the dispatcher refuses any "
    "ratified action whose tool is outside the listed buckets. This is "
    "least-privilege scoping — narrow when you can."
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


def _sdk_timeout_error_state(
    *,
    node_name: str,
    current_phase: str,
    timeout_s: float,
    exc: SDKTimeoutError,
) -> dict:
    """Phase S4 — build the standard ErrorRecord + escalation routing for a
    per-call LLM timeout.

    The returned state update is shaped identically to the cap-exceeded
    pattern used by `confirmation_brief_redraft` (real ErrorRecord +
    `next_node_override='escalation_router'`) so the escalation_router
    sees a classified error rather than synthesizing an unclassified
    one. `error_type='llm_call_timeout'` is the canonical label.
    """
    err: ErrorRecord = {
        "node_name": node_name,
        "error_type": "llm_call_timeout",
        "detail": (
            f"sdk.complete() exceeded {timeout_s:.0f}s budget in "
            f"{node_name}: {exc}"
        ),
        "timestamp": _now_iso(),
    }
    return {
        "current_phase": current_phase,
        "current_node": node_name,
        "next_node_override": "escalation_router",
        "errors": [err],
    }


def _accrue_cost(state: ResearchWorkflowState, sdk: SDKClient) -> float:
    """Phase E4: return `state["usd_spent"] + sdk.last_call_cost_usd`.

    Every Brain/Executor node that calls `sdk.complete()` should include
    `"usd_spent": _accrue_cost(state, sdk)` in its return dict so the
    workflow's running total reflects the cost of the just-completed LLM
    call. The `last_call_cost_usd` is reset by complete() at the start
    of every invocation and populated from the SDK's ResultMessage; for
    fakes that don't emit a result message, the default 0.0 is a safe
    no-op.
    """
    prev = float(state.get("usd_spent", 0.0) or 0.0)
    delta = float(getattr(sdk, "last_call_cost_usd", 0.0) or 0.0)
    return prev + delta


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


_PI_OVERRIDES_OPEN = "--- BEGIN PI OVERRIDES (highest priority) ---"
_PI_OVERRIDES_CLOSE = "--- END PI OVERRIDES ---"

# Adversarial-review H2 — runner.commit_response stores
# `REDIRECT_SENTINEL + text` in parked_interrupts.response_text for
# action="correct" so the routing layer recognizes the redirect on
# resume. When we rehydrate that text into Brain's prompt we strip the
# sentinel — Brain doesn't need to see the internal routing token, and
# leaving it in confuses the "treat as PI directive" framing. Imported
# here rather than at module top to avoid a circular import (brain ↔
# orchestrator.response_tokens is fine but kept colocated for clarity).
from orchestrator.response_tokens import REDIRECT_SENTINEL, is_redirect_token


# H1 hardening (Phase-X² adversarial review wrhahen1y) — Unicode dash
# equivalents that an LLM may semantically equate with the ASCII
# triple-hyphen fence. Normalized to ASCII U+002D before the
# fence-defang substring check so the case-insensitive +
# variance-tolerant match catches em-dash / en-dash / box-drawing /
# horizontal-bar variants that would otherwise pass through the
# original `if literal in s` check untouched.
_UNICODE_DASH_PATTERN = re.compile(
    r"[‐‑‒–—―−─━﹘﹣－]"
)

# Markdown-heading injection vector — if PI prose contains a line-start
# `## IN-RUN PI REDIRECT` (or any markdown heading mentioning a known
# sub-section label), the LLM may semantically treat it as a new
# section header inside the PI-overrides block, smuggling a fake
# "newer" correction past the structural framing. Defang by replacing
# the markdown heading marker (`#+` or setext underline) with a benign
# bullet so the section-label text survives but the structural cue is
# removed.
_SECTION_LABELS = (
    "PI INSTRUCTIONS",
    "PRIOR-RUN PI REDIRECTS",
    "IN-RUN PI REDIRECT",
)
_MARKDOWN_HEADING_INJECTION_PATTERN = re.compile(
    r"(?im)^(\s*)(#+\s*)("
    + "|".join(re.escape(lbl) for lbl in _SECTION_LABELS)
    + r")"
)


def _sanitize_override_text(text: str) -> str:
    """Strip the REDIRECT_SENTINEL routing prefix and silently neutralize
    any fence-shaped delimiter or sub-section-heading occurrences in a
    PI/redirect-supplied text body before it lands in Brain's prompt.

    Three adversarial-review fixes:
      H1 — a PI text containing the literal `--- END PI OVERRIDES ---`
           (or any visually-equivalent dash variant, case mutation, or
           markdown-heading shape that mentions a known sub-section
           label) would close the override block early and let
           post-fence text appear to Brain as if it had exited the
           PI-directive scope. Hardened (workflow wrhahen1y) against:
             - ASCII triple-hyphen + variants (4-hyphen, extra whitespace)
             - Unicode dash equivalents (em-dash, en-dash, horizontal-bar,
               box-drawing, mathematical minus, fullwidth)
             - Case mutations (`--- end pi overrides ---`)
             - Markdown-heading injection (`## IN-RUN PI REDIRECT`)
           Defang by inserting a zero-width-ish separator inside the
           delimiter / replacing the heading marker with a bullet so
           the literal match no longer fires.
      H2 — answer_interrupt stores `REDIRECT_SENTINEL + body` for
           action="correct". We strip leading sentinels (a `while`
           loop catches a hypothetical double-prefix from a
           composition bug) so Brain sees clean prose.
    """
    if not isinstance(text, str):
        return ""
    s = text

    # H2 — strip leading REDIRECT_SENTINEL(s) defensively in a loop.
    # Production runner.commit_response only prepends once, but a
    # future composition error (re-wrapping for re-route) shouldn't
    # leak the routing token into Brain's prompt.
    while True:
        stripped = s.lstrip()
        if not stripped.upper().startswith(REDIRECT_SENTINEL):
            break
        s = stripped[len(REDIRECT_SENTINEL):]

    # H1 — defang ANY fence-shaped close-delimiter occurrence. The
    # detection is:
    #   1. Normalize Unicode-dash variants to ASCII U+002D in a
    #      WORKING COPY (we still surface the original text to the
    #      LLM with the original characters — only the detection is
    #      ASCII-normalized).
    #   2. Use a case-insensitive regex over the normalized copy to
    #      find every fence span (≥2 dashes + label + ≥2 dashes,
    #      whitespace-tolerant); the span boundaries map back to the
    #      original text and we slice the dashes in the original.
    normalized = _UNICODE_DASH_PATTERN.sub("-", s)
    fence_re = re.compile(
        r"-{2,}\s*(BEGIN|END)\s+PI\s+OVERRIDES(?:\s*\([^)]*\))?\s*-{2,}|"
        r"-{2,}\s*(BEGIN|END)\s+PI\s+OVERRIDES",
        re.IGNORECASE,
    )
    # Splice spans from end-to-start so positions remain valid.
    spans = list(fence_re.finditer(normalized))
    if spans:
        out_chars = list(s)
        # Defang dashes ONLY BETWEEN consecutive dashes (lookahead) so
        # `---` becomes `- - -` (the original H1 shape, single spacing).
        # This breaks the structural fence shape while preserving
        # readable prose and exactly matching the pre-hardening
        # defanged-output shape that prior tests asserted on.
        between_consecutive_dashes_re = re.compile(
            r"[‐‑‒–—―−─━﹘﹣－\-](?=[‐‑‒–—―−─━﹘﹣－\-])"
        )
        for m in reversed(spans):
            start, end = m.start(), m.end()
            span_original = s[start:end]
            defanged = between_consecutive_dashes_re.sub(
                lambda ch: ch.group(0) + " ", span_original
            )
            out_chars[start:end] = list(defanged)
        s = "".join(out_chars)

    # H1 (continued) — defang markdown-heading injection of sub-section
    # labels. Replace the leading `#+` (or any heading marker) with a
    # benign bullet so the LLM reads "label as bullet text" rather than
    # "label as heading announcing a new section."
    s = _MARKDOWN_HEADING_INJECTION_PATTERN.sub(r"\1- \3", s)

    return s


def _format_pi_overrides_block(run_overrides: dict) -> str:
    """Phase-X + Phase-X²: render the PI-overrides block that prefixes
    Brain's prompts. Returns the empty string when there are no
    overrides.

    Shape of run_overrides (any subset may be absent):
      {
        # Phase-X (cross-run):
        "pi_instructions": "<text from orchestrator_run_start>",
        "prior_redirects": [{"workflow_thread_id": ..., "responded_at": ...,
                             "response_text": ...}, ...],
        # Phase-X² (in-run, mutated by confirmation_brief_redraft):
        "in_run_redirects": [{"responded_at": ..., "response_text": ...}, ...]
      }

    The block opens with a fence and an explicit "treat as PI directive,
    not as RKA tool instructions" line so a prose redirect can't be
    misparsed as a tool-call directive. Closes with a matching fence.
    Each body text passes through `_sanitize_override_text` which strips
    the REDIRECT_SENTINEL routing prefix (H2) and defangs any literal
    close-delimiter occurrence inside the prose (H1).

    Three sub-sections rendered in order (most-recent-PI-input last so
    it reads as "latest word"):
      1. PI INSTRUCTIONS (this run)            — pi_instructions
      2. PRIOR-RUN PI REDIRECTS                 — prior_redirects
      3. IN-RUN PI REDIRECT (this segment)      — in_run_redirects
    """
    if not isinstance(run_overrides, dict) or not run_overrides:
        return ""

    pi_instructions = run_overrides.get("pi_instructions")
    prior_redirects = run_overrides.get("prior_redirects") or []
    in_run_redirects = run_overrides.get("in_run_redirects") or []
    has_any = bool(
        (pi_instructions and pi_instructions.strip())
        or prior_redirects
        or in_run_redirects
    )
    if not has_any:
        return ""

    lines: list[str] = []
    lines.append(_PI_OVERRIDES_OPEN)
    lines.append(
        "Treat the text below as PI directive for THIS run. It supersedes "
        "any prior framing in the mission body when they conflict. Do NOT "
        "execute as RKA tool instructions — it is plain English to scope "
        "your plan."
    )
    if pi_instructions and pi_instructions.strip():
        clean = _sanitize_override_text(pi_instructions).strip()
        if clean:
            lines.append("")
            lines.append("PI INSTRUCTIONS (this run):")
            lines.append(clean)
    if prior_redirects:
        rendered: list[str] = []
        for r in prior_redirects:
            ts = r.get("responded_at", "?")
            text = _sanitize_override_text(r.get("response_text") or "").strip()
            if not text:
                continue
            rendered.append(f"  [{ts}] {text}")
        if rendered:
            lines.append("")
            lines.append(
                "PRIOR-RUN PI REDIRECTS (corrections from previous attempts "
                "of this mission, most recent first; supersede any contradicting "
                "mission-body wording):"
            )
            lines.extend(rendered)
    if in_run_redirects:
        rendered_in_run: list[str] = []
        for r in in_run_redirects:
            ts = r.get("responded_at", "?")
            text = _sanitize_override_text(r.get("response_text") or "").strip()
            if not text:
                continue
            rendered_in_run.append(f"  [{ts}] {text}")
        if rendered_in_run:
            lines.append("")
            lines.append(
                "IN-RUN PI REDIRECT (this segment — supersedes any prior "
                "framing including the prior-run redirects above; this is "
                "the PI's most recent correction and your redraft MUST "
                "honor it):"
            )
            lines.extend(rendered_in_run)
    lines.append(_PI_OVERRIDES_CLOSE)
    return "\n".join(lines)


def _build_strategy_prompt(
    state: ResearchWorkflowState,
    context: dict,
    status: dict,
    mission: dict | None,
) -> str:
    override_block = _format_pi_overrides_block(state.get("run_overrides", {}))
    prefix = (override_block + "\n\n") if override_block else ""
    return (
        prefix
        + "Session-start strategy synthesis.\n\n"
        + f"Project status:\n{status}\n\n"
        + f"Relevant prior context:\n{context}\n\n"
        + f"Current mission: {state.get('mission_id', '(none)')}\n"
        + f"Motivated by decision: {state.get('motivated_by_decision_id', '(none)')}\n\n"
        + f"Mission body:\n{_format_mission_body(mission)}\n\n"
        + "Produce a short strategy outline: what this run should do, in what "
        + "order, with what evidence checks. Cite RKA IDs you reference."
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
    try:
        strategy_text = sdk.complete(
            prompt=prompt,
            system=_brain_system(_POSITION_FORMAT),
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )
    except SDKTimeoutError as exc:
        return _sdk_timeout_error_state(
            node_name="strategy_node",
            current_phase="brain_strategy",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
            exc=exc,
        )

    note_id = mcp.rka_add_note(
        content=strategy_text,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["brain-strategy"],
        importance="high",
    )

    # Gap 3B — parse Brain's optional `proposed_capabilities` block from
    # the strategy reply. Brain may include a ```json fenced block of
    # the form {"capabilities": ["record_knowledge", ...]} to declare
    # the narrowest set of capability buckets this mission needs.
    # pi_greenlight uses this to populate allowed_capabilities on accept.
    proposed_caps = _parse_proposed_capabilities(strategy_text)

    update: dict = {
        "current_phase": "brain_strategy",
        "current_node": "strategy_node",
        "brain_strategy": strategy_text,
        "brain_position": _summarize_position(strategy_text),
        "artifacts": [_artifact(note_id, "journal", "strategy_node")],
        "usd_spent": _accrue_cost(state, sdk),
    }
    if proposed_caps:
        update["proposed_capabilities"] = proposed_caps
    return update


_KNOWN_CAPABILITIES: frozenset[str] = frozenset({
    "record_knowledge",
    "update_knowledge",
    "mission_lifecycle",
    "execution_gates",
    "ingestion",
})


def _parse_proposed_capabilities(reply: str) -> list[str]:
    """Gap 3B — extract a ```json {"capabilities": [...]} block from
    Brain's strategy reply if present. Returns [] when:
      - no fenced block present
      - block isn't JSON
      - top-level isn't an object
      - "capabilities" key missing or non-list
      - all entries are unknown capability names
    The filter to _KNOWN_CAPABILITIES drops typos rather than passing
    them through; dispatcher's malformed-allowlist guard would catch
    them anyway, but Brain-side filtering keeps state cleaner.

    Adversarial-review #7: the legacy contract conflates "no block"
    with "block had only unknown names". Use
    `_parse_proposed_capabilities_with_provenance` to distinguish
    them when the caller needs to log a Brain-prompt regression
    explicitly. This helper preserves the legacy []-on-anything-bad
    shape for backward compat.
    """
    parsed, _provenance = _parse_proposed_capabilities_with_provenance(reply)
    return parsed


def _parse_proposed_capabilities_with_provenance(
    reply: str,
) -> tuple[list[str], str]:
    """Gap 3B + adversarial-review #7: returns `(valid_capabilities,
    provenance)` where provenance is one of:
      - "absent"      — no fenced JSON block was present at all
      - "non_json"    — block present but didn't parse as JSON
      - "non_object"  — JSON wasn't an object
      - "no_key"      — object lacked the "capabilities" key
      - "non_list"    — "capabilities" key wasn't a list
      - "all_filtered" — list non-empty but all entries unknown/non-str
      - "valid"       — at least one valid capability extracted

    Callers can surface the provenance on a journal/log entry so a
    Brain prompt regression (proposing valid-sounding but unknown
    capability names) is visible instead of silently identical to a
    no-proposal case.
    """
    import json
    import re

    match = re.search(r"```json\s*\n(.+?)\n```", reply or "", re.DOTALL | re.IGNORECASE)
    if not match:
        return ([], "absent")
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ([], "non_json")
    if not isinstance(parsed, dict):
        return ([], "non_object")
    if "capabilities" not in parsed:
        return ([], "no_key")
    raw = parsed.get("capabilities")
    if not isinstance(raw, list):
        return ([], "non_list")
    valid = [c for c in raw if isinstance(c, str) and c in _KNOWN_CAPABILITIES]
    # De-dupe preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in valid:
        if c not in seen:
            seen.add(c)
            out.append(c)
    if raw and not out:
        # Brain proposed entries but none survived filtering — a
        # contract-shape regression worth flagging.
        return ([], "all_filtered")
    return (out, "valid" if out else "no_key")


# ---------------------------------------------------------------------------
# 2. confirmation_brief
# ---------------------------------------------------------------------------


def _build_confirmation_prompt(
    state: ResearchWorkflowState, mission: dict | None
) -> str:
    # Phase-X² (In-Run Redraft Channel): when confirmation_brief is
    # re-entered via the pi_greenlight redirect loop-back,
    # confirmation_brief_redraft has already appended the sanitized
    # redirect text to state['run_overrides']['in_run_redirects'].
    # Prefixing _format_pi_overrides_block here makes the redirect
    # visible to the Brain LLM redrafting the brief — symmetric with
    # _build_strategy_prompt. On a fresh (first-time) brief
    # generation, run_overrides typically has only Phase-X cross-run
    # content (or nothing), and the same formatter handles that case.
    override_block = _format_pi_overrides_block(state.get("run_overrides", {}))
    prefix = (override_block + "\n\n") if override_block else ""
    return (
        prefix
        + "Produce a Confirmation Brief for the PI summarizing:\n"
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
    try:
        brief_text = sdk.complete(
            prompt=prompt, system=BRAIN_SYSTEM, timeout_s=SDK_TIMEOUT_DEFAULT_S
        )
    except SDKTimeoutError as exc:
        return _sdk_timeout_error_state(
            node_name="confirmation_brief",
            current_phase="brain_confirmation",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
            exc=exc,
        )

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
        "usd_spent": _accrue_cost(state, sdk),
    }


# ---------------------------------------------------------------------------
# 2b. confirmation_brief_redraft — Phase-X² in-run redirect channel
# ---------------------------------------------------------------------------
#
# Routing: pi_greenlight on a `correct` action returns a sentinel-prefixed
# token; `_route_after_pi_greenlight` routes that branch HERE instead of
# to `escalation_router`. This node owns the redraft policy in one
# place:
#
#   1. Locate the latest pi_greenlight redirect in state['interrupts'].
#   2. Sanitize via _sanitize_override_text (H1 delimiter-defang + H2
#      sentinel-strip), reusing the Phase-X formatter so the in-run
#      and cross-run paths share identical prompt-injection defenses.
#   3. Append the sanitized text to state['run_overrides']['in_run_redirects']
#      (capped at MAX_GREENLIGHT_REDRAFTS entries; oldest drop first).
#   4. Increment state['greenlight_redrafts'].
#   5. On budget cap, emit a real ErrorRecord (`greenlight_redraft_budget_exceeded`)
#      and set next_node_override='escalation_router' so the escalation
#      flows from a genuine error, not a synthetic 'unclassified'.
#
# No LLM call here — pure state mutation, cheap. The downstream
# `confirmation_brief` does the redraft LLM work; its prompt builder
# (`_build_confirmation_prompt`) already prefixes
# `_format_pi_overrides_block(state['run_overrides'])` so the redirect
# text reaches Brain on the next pass.


def _latest_greenlight_redirect_record(
    state: ResearchWorkflowState,
) -> dict | None:
    """Scan state['interrupts'] reversed for the most recent
    pi_greenlight record whose response is a REDIRECT_SENTINEL-prefixed
    token. Returns the record dict, or None if no such entry exists.

    Filtering by node_name='pi_greenlight' is load-bearing: the
    `interrupts` list is shared across pi_greenlight / pi_decision_select
    / pi_acceptance writes, and a redirect at a sibling gate must NOT
    leak into the redraft loop's source-of-truth.
    """
    interrupts = state.get("interrupts", []) or []
    for record in reversed(interrupts):
        if not isinstance(record, dict):
            continue
        if record.get("node_name") != "pi_greenlight":
            continue
        response = str(record.get("response", ""))
        if is_redirect_token(response):
            return record
    return None


def confirmation_brief_redraft(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Phase-X² entry point for the in-run pi_greenlight redirect loop.

    See header comment block for the full responsibility list. This
    function is a pure state mutator — it does NOT call the LLM. The
    downstream `confirmation_brief` reads the updated
    `state['run_overrides']` via `_build_confirmation_prompt` and
    pays the redraft cost there.

    `sdk` is unused but kept in the signature for binding symmetry with
    other Brain nodes (matches `_bind` contract in graph.py).
    """
    current_count = int(state.get("greenlight_redrafts", 0) or 0)
    existing_overrides = dict(state.get("run_overrides") or {})

    # Locate the redirect that triggered this redraft.
    record = _latest_greenlight_redirect_record(state)
    if record is None:
        # Defensive: route helper should have prevented this, but if we
        # arrive without a redirect to consume, escalate via a real
        # error rather than silently looping.
        err: ErrorRecord = {
            "node_name": "confirmation_brief_redraft",
            "error_type": "greenlight_redirect_text_missing",
            "detail": (
                "Routed to redraft but no pi_greenlight redirect record "
                "found in state['interrupts']."
            ),
            "timestamp": _now_iso(),
        }
        return {
            "current_phase": "brain_confirmation",
            "current_node": "confirmation_brief_redraft",
            "next_node_override": "escalation_router",
            "errors": [err],
        }

    sanitized = _sanitize_override_text(record.get("response") or "").strip()
    if not sanitized:
        # Sentinel-only / empty redirect text — escalate with a real
        # error rather than rerunning Brain with no new guidance.
        err = {
            "node_name": "confirmation_brief_redraft",
            "error_type": "greenlight_redirect_text_empty",
            "detail": (
                "PI redirect at pi_greenlight had no usable text after "
                "REDIRECT_SENTINEL strip + delimiter defang."
            ),
            "timestamp": _now_iso(),
        }
        return {
            "current_phase": "brain_confirmation",
            "current_node": "confirmation_brief_redraft",
            "next_node_override": "escalation_router",
            "errors": [err],
        }

    next_count = current_count + 1
    if next_count > MAX_GREENLIGHT_REDRAFTS:
        # Bounded loop: emit a real ErrorRecord so escalation_router
        # picks it up legitimately (no synthetic 'unclassified').
        err = {
            "node_name": "confirmation_brief_redraft",
            "error_type": "greenlight_redraft_budget_exceeded",
            "detail": (
                f"PI requested redraft #{next_count} at pi_greenlight; "
                f"cap is {MAX_GREENLIGHT_REDRAFTS}. Routing to "
                "escalation_router so the PI can adjudicate."
            ),
            "timestamp": _now_iso(),
        }
        return {
            "current_phase": "brain_confirmation",
            "current_node": "confirmation_brief_redraft",
            "next_node_override": "escalation_router",
            "errors": [err],
        }

    # Happy path: append the sanitized redirect to run_overrides and
    # let the downstream confirmation_brief produce a fresh brief.
    in_run = list(existing_overrides.get("in_run_redirects") or [])
    in_run.append({
        "responded_at": record.get("timestamp", _now_iso()),
        "response_text": sanitized,
    })
    # Cap the list at MAX_GREENLIGHT_REDRAFTS entries (drop oldest).
    if len(in_run) > MAX_GREENLIGHT_REDRAFTS:
        in_run = in_run[-MAX_GREENLIGHT_REDRAFTS:]
    new_overrides = {**existing_overrides, "in_run_redirects": in_run}

    return {
        "current_phase": "brain_confirmation",
        "current_node": "confirmation_brief_redraft",
        # Clear any stale next_node_override (e.g. from a prior
        # budget_check pass) so the happy-path route helper sees a
        # clean state.
        "next_node_override": "",
        "run_overrides": new_overrides,
        "greenlight_redrafts": next_count,
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


def _render_proposed_actions_packet(proposed_actions: list[dict]) -> str:
    """Phase 2.11 T1 (mis_01KRYT62XQK5NK3BY7G9BGRAPS) — render the
    `state["proposed_actions"]` list as a PI-facing decision packet body.

    Each action is displayed by identity (tool, args, rationale) so PI can
    verify the set before ratifying. No LLM intermediation — the packet
    structure is mechanical so the proposed_actions PI sees ARE exactly
    what `pi_decision_select` will copy to `ratified_actions` on accept.
    Restores EC8 set-identity verifiability (which Phase 2.10 found
    broken: PI saw a brain-generated strategic meta-decision instead of
    the actual actions).
    """
    n = len(proposed_actions)
    lines: list[str] = [
        f"# Brain proposes {n} action(s) for PI ratification",
        "",
        "PI must verify the set below; on `accept`, these actions are copied "
        "to `ratified_actions` for parent-process dispatch via "
        "`execute_ratified_actions`. EC8 set-identity: ratified == proposed.",
        "",
        "## Proposed actions",
    ]
    for i, action in enumerate(proposed_actions, 1):
        tool = action.get("tool", "<missing>")
        args = action.get("args", {})
        rationale = action.get("rationale", "(no rationale)")
        lines.append("")
        lines.append(f"### {i}. `{tool}`")
        lines.append("")
        lines.append(f"**args**: `{args}`")
        lines.append("")
        lines.append(f"**rationale**: {rationale}")
    return "\n".join(lines)


def _decision_present_from_proposed_actions(
    state: ResearchWorkflowState,
    mcp: MCPClient,
    proposed_actions: list[dict],
) -> dict:
    """Phase 2.11 T1 early-bypass path. No brain LLM call; build the
    decision packet directly from structured `state["proposed_actions"]`."""
    n = len(proposed_actions)
    packet_content = _render_proposed_actions_packet(proposed_actions)

    note_id = mcp.rka_add_note(
        content=packet_content,
        type="note",
        source="brain",
        related_mission=state.get("mission_id"),
        tags=["decision-draft", "proposed-actions-set"],
        importance="high",
    )

    return {
        "current_phase": "brain_review",
        "current_node": "decision_present",
        "artifacts": [_artifact(note_id, "journal", "decision_present")],
        "decisions_to_present": [
            {
                "title": f"Brain proposes {n} action(s) — ratify the set?",
                "options": ["accept", "modify", "reject"],
                "context": packet_content,
                "source_node": "decision_present",
                "source_artifact": note_id,
                # Structured view of the actions for PI UI / driver
                # rendering. The driver's `interactive_interrupt` will JSON-
                # dump this so PI sees the actions by identity, not just as
                # markdown in `context`.
                "proposed_actions": list(proposed_actions),
                "summary": (
                    f"Brain proposes {n} action item(s); ratify the set or "
                    f"surface objections (EC8: ratified must equal proposed)"
                ),
            }
        ],
    }


def decision_present(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    # Phase 2.11 T1 (mis_01KRYT62XQK5NK3BY7G9BGRAPS) — early-bypass when
    # the workflow has structured `proposed_actions` to ratify. Phase 2.10
    # surfaced that decision_present's strategic-meta-decision LLM call was
    # decoupled from `state["proposed_actions"]`: PI saw a brain-generated
    # A/B/C/D strategic question, NOT the actual writes the orchestrator
    # would dispatch on accept. EC8 set-identity (Brain explicitly relied on
    # it) was unverifiable by PI. The fix: when proposed_actions is non-empty,
    # build the PI-facing packet directly from the structured data with no
    # LLM intermediation. Strategic-meta-decision path preserved as the
    # fall-through for empty proposed_actions (existing workflow shapes
    # where the brain needs to surface an open strategic question).
    proposed_actions = list(state.get("proposed_actions") or [])
    if proposed_actions:
        return _decision_present_from_proposed_actions(state, mcp, proposed_actions)

    # Fall-through: existing strategic-meta-decision flow (Phase 2.7 design).
    prompt = _build_decision_prompt(state)
    try:
        decision_draft = sdk.complete(
            prompt=prompt, system=BRAIN_SYSTEM, timeout_s=SDK_TIMEOUT_DEFAULT_S
        )
    except SDKTimeoutError as exc:
        return _sdk_timeout_error_state(
            node_name="decision_present",
            current_phase="brain_review",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
            exc=exc,
        )

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
        "usd_spent": _accrue_cost(state, sdk),
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
    try:
        review_text = sdk.complete(
            prompt=prompt, system=BRAIN_SYSTEM, timeout_s=SDK_TIMEOUT_DEFAULT_S
        )
    except SDKTimeoutError as exc:
        return _sdk_timeout_error_state(
            node_name="cluster_review",
            current_phase="brain_review",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
            exc=exc,
        )

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
        "usd_spent": _accrue_cost(state, sdk),
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
    try:
        verdict_text = sdk.complete(
            prompt=prompt,
            system=_brain_system(_GATE1_FORMAT),
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )
    except SDKTimeoutError as exc:
        return _sdk_timeout_error_state(
            node_name="gate1_validation",
            current_phase="brain_review",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
            exc=exc,
        )
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
        "usd_spent": _accrue_cost(state, sdk),
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
    try:
        synthesis_text = sdk.complete(
            prompt=prompt, system=BRAIN_SYSTEM, timeout_s=SDK_TIMEOUT_DEFAULT_S
        )
    except SDKTimeoutError as exc:
        return _sdk_timeout_error_state(
            node_name="final_synthesis",
            current_phase="brain_synthesis",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
            exc=exc,
        )

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
        "usd_spent": _accrue_cost(state, sdk),
    }
