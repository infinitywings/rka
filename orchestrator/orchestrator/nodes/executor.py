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

from orchestrator.llm_client import (
    SDKClient,
    WRITE_TOOLS,
)
# Note: capability_of lookup is now inside `check_action_capability`
# (orchestrator/rka_enums.py) as of v2.6.0+agentic.6. The direct
# import here was removed when the inline capability check was lifted
# into the rka_enums vocabulary.
from orchestrator.mcp_client import CheckpointError, MCPClient
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
    check_action_capability,  # v2.6.0+agentic.6
    check_required_fields,  # Phase-X²' polish
    validate_action_args,  # Phase-X² polish
)
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
    "to PREPARE this run — they are not your work to re-do.\n\n"
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
    "`rka_*` names — the harness translates to "
    "`mcp__rka__rka_*`.\n"
    "  - To discover what's available without loading everything, use "
    "`rka_list_tools(category=..., query=..., tier=...)` — returns "
    "`{total_tools, filtered_count, categories: {...}}`. To inspect one "
    "tool's signature + docstring (active OR deferred) use "
    "`rka_help(name=\"rka_<name>\")`.\n"
    "  - The parent-side dispatcher in `execute_ratified_actions` "
    "handles all WRITE_TOOLS dispatch via REST and bypasses the MCP "
    "surface entirely — so your read-side calls are the primary place "
    "the navigator matters. Deferred read-side tools you commonly need "
    "during Backbrief drafting / mission_execute / report drafting: "
    "rka_get_mission, rka_get_journal, rka_get_decision_tree, "
    "rka_get_literature, rka_trace_provenance, rka_get_report. ALL of "
    "these require an `rka_load_tools` call first within the current "
    "SDK session.\n"
    "  - The always-on layer (rka_get_status / rka_get_context / "
    "rka_get_research_map / rka_get_pending_maintenance / "
    "rka_get_checkpoints / rka_search / rka_get) is fine for high-"
    "level orientation. The moment you need mission-scoped detail "
    "(task list, prior journal entries, decision lineage), call "
    "`rka_load_tools` for the specific deferred tools and then proceed.\n\n"
    # ── Phase-B (agentic) — Delta #19: enumerate the dispatcher's allowlist.
    # Empirical driver: Phase-A2 live test on the IoT-edge-LLM project surfaced
    # Brain repeatedly proposing tools outside WRITE_TOOLS (rka_present_decision,
    # rka_resolve_checkpoint, etc.). execute_ratified_actions correctly rejected
    # them, but the Brain didn't know the allowlist existed. This delta enumerates
    # it at the prompt layer so the Brain can self-constrain.
    # ────────────────────────────────────────────────────────────────────────────
    "Allowed write tools — your `proposed_actions[*].tool` MUST be one of: "
    + ", ".join(WRITE_TOOLS) + ". "
    "The parent-side `execute_ratified_actions` dispatcher rejects any tool "
    "outside this list with `ratified_action_tool_not_allowed` — your "
    "proposed work will be lost. NEVER propose `rka_present_decision`: "
    "`pi_decision_select` already presents to PI; use `rka_add_decision` to "
    "create the underlying record and let the orchestrator render it. "
    "NEVER propose lifecycle tools (`rka_resolve_checkpoint`, "
    "`rka_supersede_decision`, `rka_advance_rq`), session-routing tools "
    "(`rka_set_project`, `rka_list_projects`), hook-management tools, "
    "eviction sweeps, or any tool not in the allowlist above — they are "
    "out of scope for parent-side dispatch and the orchestrator rejects "
    "them. If your work requires a write tool outside the allowlist, "
    "escalate via `rka_submit_checkpoint` describing the gap; do not "
    "synthesize the work around an unavailable tool with placeholder "
    "values like `\"REQUIRES_PRIOR_OUTPUT\"` (the dispatcher cannot "
    "thread one action's return into another's args).\n\n"
    # Delta #20 — chain awareness. Phase-C added `{{PA-N.id}}` substitution
    # in execute_ratified_actions: actions can now reference earlier actions'
    # return values. Brain must use the canonical syntax, not literal
    # placeholder strings (which Phase-A2 live test demonstrated would
    # otherwise leak through unresolved).
    "Action chaining. `execute_ratified_actions` supports `{{PA-N.id}}` "
    "substitution: any string in a later action's `args` may reference an "
    "earlier action's returned id by 1-indexed position. Example: "
    '`{tool: "rka_add_decision", args: {...}}` followed by '
    '`{tool: "rka_add_note", args: {content: "...", '
    'related_decisions: ["{{PA-1.id}}"]}}` — the orchestrator substitutes '
    "PA-1's returned dec_… id before dispatching PA-2. Constraints: "
    "(a) only `.id` is supported (no `.timestamp` / `.entity_type` etc.); "
    "(b) references are 1-indexed; (c) forward references and self-references "
    "are errors and skip the offending action; (d) references to a prior "
    "action that failed (no id returned) yield an error. NEVER use literal "
    "placeholder strings like `\"REQUIRES_PA1_DECISION_ID\"` — they pass "
    "through unmodified to the dispatcher and the call fails at the RKA "
    "API boundary. If a chain you need can't be expressed in this syntax, "
    "escalate via `rka_submit_checkpoint` describing the structure.\n\n"
    # Phase-X² polish — enumerate valid RKA enum values. Empirical Run-5
    # surfaced Brain proposing `confidence='confirmed'` (HTTP 422) and
    # Executor inherits the same constraint set when it emits proposed_actions.
    "RKA write-tool field values (v2.6+). Every string field with a "
    "constrained value space must use one of the values below — "
    "out-of-enum values are rejected pre-dispatch by the orchestrator "
    "(`ratified_action_arg_invalid_enum_value`) AND at the RKA API "
    "(HTTP 422). For executor-authored journal entries use `source='executor'`.\n"
    "  - `confidence`: " + " | ".join(sorted(RKA_CONFIDENCES))
    + ". The value 'confirmed' is NOT valid — use 'verified' for "
    "cross-checked findings, 'tested' for empirically-probed findings.\n"
    "  - `importance`: " + " | ".join(sorted(RKA_IMPORTANCES)) + ".\n"
    "  - `source`: " + " | ".join(sorted(RKA_SOURCES))
    + ". For Executor-authored entries, use 'executor'.\n"
    "  - `type` (journal v2 canonical): "
    + " | ".join(sorted(RKA_JOURNAL_TYPES_V2_CANONICAL))
    + ". Legacy values silently normalized server-side but avoid in new writes.\n"
    "  - `status` (journal lifecycle): "
    + " | ".join(sorted(RKA_JOURNAL_STATUSES)) + ".\n"
    "  - `decided_by`: " + " | ".join(sorted(RKA_DECISION_DECIDED_BY)) + ".\n"
    "  - `kind` (decision): " + " | ".join(sorted(RKA_DECISION_KINDS))
    + ". 'research_question' is reserved for advanceable RQs.\n"
    "  - `status` (decision lifecycle): "
    + " | ".join(sorted(RKA_DECISION_STATUSES)) + ".\n"
    "  - `type` (checkpoint): " + " | ".join(sorted(RKA_CHECKPOINT_TYPES))
    + ". 'gate' for blocking go/no-go points; 'decision' for forks "
    "needing PI adjudication.\n"
    "  - `status` (mission): " + " | ".join(sorted(RKA_MISSION_STATUSES)) + ".\n\n"
    # Phase-X²' polish — canonical field NAMES per WRITE_TOOL.
    # Parallel insert with BRAIN_SYSTEM's Phase-X²' block. See the
    # design doc at orchestrator/docs/phase-x-prime-polish-design.md §5.3.
    "RKA write-tool canonical field names (Phase-X²' polish). The 9 "
    "WRITE_TOOLS use FIVE different vocabularies for the primary body "
    "field. Emit the canonical name below; rejection at the dispatcher "
    "is the `ratified_action_arg_missing_required_field` ErrorRecord.\n"
    "  - `rka_add_note`: `content` (required).\n"
    "  - `rka_add_decision`: `content` (required) + `related_journal: "
    "list[str]` (required) + `decided_by` + `phase`.\n"
    "  - `rka_create_mission`: `objective` (required) + "
    "`motivated_by_decision: str` + `acceptance_criteria: list[str]`.\n"
    "  - `rka_update_mission_status`: `id` (required) + `status`.\n"
    "  - `rka_submit_checkpoint`: `description` (required, NOT "
    "`content` — common Brain hallucination; the adapter tolerates "
    "`content`/`message`/`reason` as aliases since the Phase-X²' "
    "polish, but emit `description`) + `mission_id` + `type`.\n"
    "  - `rka_submit_report`: `summary` (required, NOT `content` — "
    "`content` is tolerated as alias) + `mission_id`.\n"
    "  - `rka_ingest_document`: `content` (required).\n"
    "  - `rka_update_note`: `id` (required, jrn-id).\n"
    "  - `rka_bulk_update`: `updates: list[dict]` (required).\n"
    "Common Brain hallucination — same shape as BRAIN_SYSTEM's callout: "
    "`content` is NOT canonical for rka_submit_checkpoint (use "
    "`description`) or rka_submit_report (use `summary`). The adapter "
    "tolerates `content` as an alias for both since the Phase-X²' "
    "polish, but emit the canonical name for audit-trail clarity.\n\n"
    # Phase D2 — built-in filesystem tools (Bash/Read/Write/Edit/Grep/Glob/
    # WebFetch/WebSearch) are granted to the subprocess for actual mission
    # work. The Phase-2.7 read-only-subprocess invariant is preserved at the
    # RKA layer (writes still flow through pi_decision_select → ratified
    # actions); built-in FS tools touch the PI's workspace, NOT RKA state.
    "Filesystem tools. Bash, Read, Write, Edit, Grep, Glob, WebFetch, "
    "WebSearch are available to you. Use them to actually perform mission "
    "work: read the workspace (PI's project files at HOST_WORKSPACE_ROOT, "
    "mounted at the same absolute path as on the host), probe `.env` for "
    "secrets your mission needs, run Python via `Bash` for analysis or "
    "library-version checks, write outputs to `{workspace_path}/results/` "
    "or wherever the mission's scope says. These tools operate on the "
    "PI's workspace, NOT on RKA state — they do NOT replace the "
    "`proposed_actions` ratification gate: any RKA write (rka_add_note, "
    "rka_add_decision, rka_submit_report, rka_update_*, etc.) MUST still "
    "go through `proposed_actions` so the PI can ratify. The split is: "
    "(a) Bash/Read/Write/Edit/Grep/Glob/WebFetch/WebSearch = filesystem "
    "actions, unratified, scoped to the PI's mounted workspace; (b) "
    "rka_* WRITE_TOOLS via proposed_actions = knowledge-base writes, "
    "ratified, scoped to RKA. NEVER call rka_add_* / rka_update_* / "
    "rka_submit_* directly from a subprocess tool call — that path is "
    "explicitly denied at the SDK level (WRITE_TOOLS are on "
    "`disallowed_tools`). Run Bash commands that read or analyze freely; "
    "be cautious about Bash that mutates the host shell environment, "
    "deletes files, or contacts external services — when in doubt, "
    "escalate via rka_submit_checkpoint.\n\n"
    # v2.6 absorption — RKA tool calls require project_id
    "RKA project scoping (v2.6+): every project-scoped rka_* tool you "
    "call (read or write) requires `project_id` as a kwarg-only "
    "parameter. The active project_id for this workflow is in your "
    "orchestrator state — when you call rka_get_mission / rka_get / "
    "rka_get_context / rka_search / etc., pass `project_id=\"<the "
    "project_id from your context>\"` explicitly. Omitting it raises "
    "`TypeError: rka_X() missing 1 required keyword-only argument: "
    "'project_id'`. Same rule applies to every action in your "
    "`proposed_actions` JSON: each action's `args` MUST include "
    "`project_id`. Without it, execute_ratified_actions raises a "
    "ratified_action_call_failed ErrorRecord and the EC8 guard escalates "
    "the whole run. The pre-v2.6 RKA_PROJECT env var passing was "
    "removed; do not rely on session defaults.\n\n"
    # Phase G — FS Actuator self-classification policy
    "FS Actuator policy (Bash / Write / Edit). Before calling Bash, Write, "
    "or Edit, classify the operation. Three categories:\n"
    " (i)  SCOPED — reads, or writes inside {workspace_path}, or Bash "
    "      that runs analysis/probe (`python …`, `ls`, `grep`, etc.). "
    "      Call the tool directly.\n"
    " (ii) RATIFY_REQUIRED — emit a `proposed_fs_actions` block instead "
    "      of calling the tool. The PI must ratify before the actuator "
    "      dispatches. Triggers:\n"
    "        * `rm -rf` (any), `git push`, `git reset --hard`, "
    "          `git clean -f`, `git rebase`, `git merge`\n"
    "        * `npm publish`, `pip install --system`, `docker rmi`, "
    "          `docker push`, `docker system prune`, `kubectl delete`\n"
    "        * `terraform apply` or `destroy`, `gcloud … delete`, "
    "          `aws … delete`, `systemctl stop/disable`, `crontab -r`\n"
    "        * any Write/Edit whose `file_path` escapes "
    "          `{workspace_path}` (e.g., `/etc/…`, `~/.aws/…`, sibling "
    "          project folders)\n"
    "        * redirects writing under `/etc/`\n"
    "(iii) DENIED — never executable, even with PI ratification. "
    "      `rm -rf /`, `rm -rf $HOME`, `sudo …`, `chmod 777`, "
    "      `mkfs.*`, `dd … of=/dev/sd*`, `curl | sh`, `wget | bash`, "
    "      fork-bombs. If a mission requires one of these, escalate "
    "      via `rka_submit_checkpoint` with the explicit reason; the "
    "      PI must rewrite the mission scope before any such operation "
    "      becomes possible.\n"
    "The `proposed_fs_actions` block has the same JSON shape as "
    "`proposed_actions` but the `tool` field is one of Bash/Write/Edit "
    "and `args` is the tool's native argument shape. Example: "
    "`{\"tool\": \"Bash\", \"args\": {\"command\": \"git push origin "
    "main\"}, \"rationale\": \"publishing T5 release per mission "
    "spec\"}`. Phase G2 will add a hook that intercepts your direct "
    "Bash/Write/Edit calls and reroutes ratify_required ones; until "
    "Phase G2 ships, YOU are the enforcement point.\n\n"
    # Phase E5 — WebFetch/WebSearch egress policy
    "Egress policy (WebFetch / WebSearch). These tools are granted but "
    "their use is observable in network logs and may carry workspace "
    "strings into third-party telemetry. Permitted uses: (a) fetching "
    "published documents (papers, RFCs, vendor docs, standards), (b) "
    "verifying a missioned claim against a primary source, (c) loading "
    "library docs when context7 lacks coverage, (d) downloading inputs "
    "the mission explicitly enumerates. FORBIDDEN: any URL whose host "
    "is segment.io, segment.com, amplitude.com, mixpanel.com, "
    "statsig.com, posthog.com, heap.io, or heapanalytics.com (these "
    "match the orchestrator's WEBHOOK_BLOCKLIST). FORBIDDEN: embedding "
    "workspace paths, project_ids, mission_ids, decision_ids, or "
    ".env-derived secrets in query parameters or path segments — every "
    "fetch URL is loggable. FORBIDDEN: POST or any mutation verb (these "
    "tools are GET-only by intent; if the mission needs a mutation, "
    "describe it in proposed_actions or escalate). When unsure prefer "
    "RKA tools, context7 docs, or escalation over web egress."
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


def _accrue_cost(state: ResearchWorkflowState, sdk: SDKClient) -> float:
    """Phase E4: return `state["usd_spent"] + sdk.last_call_cost_usd`.

    Mirror of brain._accrue_cost — see there for full semantics. Each
    Executor node that calls `sdk.complete()` returns the accumulated
    cost via `"usd_spent": _accrue_cost(state, sdk)` so the workflow's
    running total reflects every LLM call.
    """
    prev = float(state.get("usd_spent", 0.0) or 0.0)
    delta = float(getattr(sdk, "last_call_cost_usd", 0.0) or 0.0)
    return prev + delta


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
        "usd_spent": _accrue_cost(state, sdk),
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
        "usd_spent": _accrue_cost(state, sdk),
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
    # Phase-A2 (agentic): WRITE_TOOLS expansion to unblock Brain proposals
    # that landed in pi_decision_select for the IoT-edge-LLM mission.
    "rka_update_mission_status": "mission",
    "rka_ingest_document": "journal",
}


# ---------------------------------------------------------------------------
# Phase-C (agentic) — chain substitution in ratified actions
# ---------------------------------------------------------------------------

# `{{PA-N.id}}` references action N's (1-indexed) return value (the rka_id
# the dispatched WRITE_TOOL returned). Only `.id` is supported in Phase-C;
# future versions can add `.entity_type` / `.timestamp` etc. as needed.
# Empirical driver: the Phase-A2 IoT-edge-LLM live test showed Brain wanting
# to chain a `rka_resolve_checkpoint` (creating a decision_id) into a
# subsequent `rka_present_decision(decision_id=<that>)` — and using a
# literal placeholder string `'REQUIRES_PA1_DECISION_ID'` because there
# was no way to express the dependency. This closes that.
_CHAIN_REF_PATTERN = re.compile(r"\{\{PA-(\d+)\.([a-zA-Z_]+)\}\}")
_SUPPORTED_CHAIN_FIELDS: frozenset[str] = frozenset({"id"})


class _ChainResolutionError(Exception):
    """Raised by _substitute_chain_refs when a reference is invalid.

    The message names the specific failure mode (forward ref, missing
    prior result, unsupported field) so the ErrorRecord is diagnostic.
    """


def _substitute_chain_refs(
    value: Any,
    *,
    current_index: int,  # 1-indexed
    previous_results: dict[int, str],
    total_actions: int,
) -> Any:
    """Recursively walk `value` and replace `{{PA-N.field}}` references.

    Returns the substituted value (same shape as input — dict/list/str
    preserved). Raises _ChainResolutionError if any reference is invalid
    (forward ref, self ref, out-of-range, unsupported field, or refers
    to a prior action that failed and produced no id).

    The reference syntax exists only inside string args (and recurses
    into nested dicts/lists). Non-string scalars (int/float/bool/None)
    pass through unchanged.
    """
    if isinstance(value, str):
        # Fast path: no `{{` present → unchanged.
        if "{{" not in value:
            return value

        def _replace(match: re.Match) -> str:
            n_str, field = match.group(1), match.group(2)
            n = int(n_str)
            if field not in _SUPPORTED_CHAIN_FIELDS:
                raise _ChainResolutionError(
                    f"unsupported chain field {field!r} in {{{{PA-{n}.{field}}}}} — "
                    f"only {sorted(_SUPPORTED_CHAIN_FIELDS)} supported in Phase-C"
                )
            if n < 1 or n > total_actions:
                raise _ChainResolutionError(
                    f"chain reference PA-{n} out of range "
                    f"(1..{total_actions} for this proposed_actions list)"
                )
            if n >= current_index:
                raise _ChainResolutionError(
                    f"chain reference PA-{n} is forward-ref or self-ref "
                    f"from action PA-{current_index} — only prior actions "
                    f"may be referenced"
                )
            if n not in previous_results:
                raise _ChainResolutionError(
                    f"chain reference PA-{n}.{field} cannot resolve: "
                    f"PA-{n} either failed or produced no id"
                )
            return previous_results[n]

        return _CHAIN_REF_PATTERN.sub(_replace, value)

    if isinstance(value, dict):
        return {
            k: _substitute_chain_refs(
                v,
                current_index=current_index,
                previous_results=previous_results,
                total_actions=total_actions,
            )
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [
            _substitute_chain_refs(
                item,
                current_index=current_index,
                previous_results=previous_results,
                total_actions=total_actions,
            )
            for item in value
        ]

    return value


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

    Phase-C (agentic) — chain substitution. Before dispatching each
    action, walks `args` recursively and substitutes any
    `{{PA-N.id}}` references (1-indexed) with the rka_id returned by
    the corresponding prior proposed_action. Forward references,
    self-references, and references to failed actions yield an
    ErrorRecord and skip the offending action without aborting the
    rest of the chain.

    Phase 2.14 (agentic) — capability-aware dispatch. Each ratified
    tool's capability is read from `llm_client.TOOL_CAPABILITIES`. If
    `state["allowed_capabilities"]` is set (a non-empty list of
    capability strings), tools whose capability is NOT in that list are
    rejected with a `ratified_action_capability_not_allowed`
    ErrorRecord. When the field is absent or empty, all capabilities
    are allowed (pre-2.14 behavior preserved).

    A no-op when `state["ratified_actions"]` is empty (rejected, escaped,
    or never populated). This means the node sits unconditionally between
    `pi_decision_select` and `final_synthesis` in the graph without
    requiring routing logic to skip it.
    """
    # Phase 2.14: capability allowlist. Empty / missing → no restriction.
    # A malformed value (e.g., a plain string instead of list-of-strings)
    # is treated as missing AND surfaces a one-shot ErrorRecord so the
    # workflow operator sees the typo instead of silently losing the
    # capability restriction.
    raw_caps = state.get("allowed_capabilities")
    new_artifacts: list[ArtifactRef] = []
    new_errors: list[ErrorRecord] = []
    if raw_caps is None or raw_caps == [] or raw_caps == ():
        allowed_caps: set[str] = set()
    elif isinstance(raw_caps, (list, tuple, set)) and all(
        isinstance(c, str) for c in raw_caps
    ):
        allowed_caps = {c for c in raw_caps}
    else:
        allowed_caps = set()
        new_errors.append(
            _make_error(
                "execute_ratified_actions",
                "ratified_action_capability_allowlist_malformed",
                (
                    f"state['allowed_capabilities']={raw_caps!r} is not a "
                    f"list of capability strings; ignored. Pre-2.14 "
                    f"behavior (no restriction) applies. Fix the workflow "
                    f"that populated this field."
                ),
            )
        )
    actions = state.get("ratified_actions", []) or []
    # 1-indexed map of action-position → returned rka_id; populated as we
    # dispatch successfully. Phase-C chain substitution consults this.
    previous_results: dict[int, str] = {}

    for idx, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_shape_error",
                    f"PA-{idx}: action is not a dict (got {type(action).__name__})",
                )
            )
            continue

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}

        # Defense in depth: only the WRITE_TOOLS registry (now derived
        # from TOOL_CAPABILITIES per Phase 2.14) is callable.
        if tool not in WRITE_TOOLS:
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_tool_not_allowed",
                    (
                        f"PA-{idx}: tool {tool!r} is not in WRITE_TOOLS "
                        f"registry — the executor LLM proposed an action "
                        f"the orchestrator refuses to execute. "
                        f"Phase 2.7 Option C invariant."
                    ),
                )
            )
            continue

        # v2.6.0+agentic.6 — Phase 2.14 capability-scoped restriction
        # via the unified rka_enums.check_action_capability helper.
        # Lifted from an inline block (functionally identical) so the
        # check composes alongside validate_action_args + check_required_fields
        # and is independently unit-testable. Error type name preserved
        # for journal-grep consumer compatibility.
        capability_errors = check_action_capability(tool, allowed_caps)
        if capability_errors:
            for reason in capability_errors:
                new_errors.append(
                    _make_error(
                        "execute_ratified_actions",
                        "ratified_action_capability_not_allowed",
                        f"PA-{idx}: {reason}",
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
                        f"PA-{idx}: tool {tool!r} is in WRITE_TOOLS but "
                        f"MCPClient has no method by that name. Protocol "
                        f"drift; surface."
                    ),
                )
            )
            continue

        if not isinstance(args, dict):
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_args_shape_error",
                    f"PA-{idx}: args for {tool!r} is not a dict",
                )
            )
            continue

        # Phase-C: resolve any `{{PA-N.id}}` placeholders in args.
        try:
            resolved_args = _substitute_chain_refs(
                args,
                current_index=idx,
                previous_results=previous_results,
                total_actions=len(actions),
            )
        except _ChainResolutionError as e:
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_chain_resolution_failed",
                    f"PA-{idx}: tool={tool!r} chain-ref error: {e}",
                )
            )
            continue

        # Phase-X² polish — pre-dispatch enum validation. Run-5 PA-2
        # failed with HTTP 422 because Brain proposed
        # `confidence='confirmed'` (not in RKA's enum). Catch the
        # equivalent failure modes here BEFORE the network round-trip:
        # short-circuits the EC8 escalation path on known-bad enum
        # values, and produces a clearer ErrorRecord (with the
        # offending field + value + expected set) than the
        # downstream 422-reason enrichment can. Validation runs AFTER
        # chain substitution so `{{PA-N.id}}`-resolved values are
        # checked. Open-world tolerance: unknown tools and unknown
        # args produce no violations (the upstream WRITE_TOOLS check
        # already refuses unknown tools).
        enum_violations = validate_action_args(tool, resolved_args)
        if enum_violations:
            detail_parts = [
                f"{arg}={value!r} not in {sorted(expected)!r}"
                for arg, value, expected in enum_violations
            ]
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_arg_invalid_enum_value",
                    (
                        f"PA-{idx}: tool={tool!r} invalid enum value(s): "
                        + "; ".join(detail_parts)
                        + " — rejected pre-dispatch to short-circuit the "
                        "HTTP 422 round-trip."
                    ),
                )
            )
            continue

        # Phase-X²' polish — pre-dispatch required-field validation.
        # The 2026-06-01 hyperscaler-auditing PA-2 failure surfaced
        # this gap: Brain emitted `rka_submit_checkpoint(content=...)`
        # instead of `description=...`. The enum validator returned
        # empty (no enum violations); the adapter at mcp_client.py:574
        # then raised ValueError at dispatch time and EC8 escalated
        # to a failure checkpoint. The required-field validator
        # closes this at the same dispatcher seam as the enum check:
        # alias-set-of-sets semantics so legitimate `message=`-only
        # or `reason=`-only calls still satisfy the body-field set
        # for rka_submit_checkpoint. Layered after the enum check so
        # an action with BOTH a wrong enum value AND a missing
        # required field surfaces the enum error first (more
        # actionable for Brain).
        missing_fields = check_required_fields(tool, resolved_args)
        if missing_fields:
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_arg_missing_required_field",
                    (
                        f"PA-{idx}: tool={tool!r} missing required "
                        f"field(s): " + "; ".join(missing_fields)
                        + " — rejected pre-dispatch to short-circuit "
                        "the adapter-layer ValueError or REST 422."
                    ),
                )
            )
            continue

        # Phase E6 — project_id consistency guard + dispatcher-layer
        # auto-injection. The orchestrator's RestMCPClient already injects
        # `self.project_id` into every REST call's query params (see
        # `RestMCPClient._params()`), so the per-action `project_id` kwarg
        # would be redundant at best and contradictory at worst. Behavior:
        #   (a) if the LLM passed a `project_id` that doesn't match the
        #       workflow's `state["project_id"]`, raise a
        #       cross_project_write_attempted ErrorRecord and skip — the
        #       Brain/Executor must never authorize writes against a
        #       different project than the one the PI ratified.
        #   (b) otherwise, strip `project_id` from resolved_args before
        #       dispatch. The client adds it back at the REST layer with
        #       the correct, workflow-bound value. This makes per-action
        #       project_id LLM-omittable (prompts still encourage it,
        #       but a forgotten kwarg no longer fails methods whose
        #       signatures don't accept **kw, e.g. rka_add_decision).
        workflow_project_id = (state.get("project_id") or "").strip()
        if "project_id" in resolved_args:
            proposed_pid = (resolved_args.get("project_id") or "").strip()
            if (
                workflow_project_id
                and proposed_pid
                and proposed_pid != workflow_project_id
            ):
                new_errors.append(
                    _make_error(
                        "execute_ratified_actions",
                        "cross_project_write_attempted",
                        (
                            f"PA-{idx}: tool={tool!r} action proposed "
                            f"project_id={proposed_pid!r} but the workflow "
                            f"is bound to project_id={workflow_project_id!r}. "
                            f"Cross-project writes are forbidden — escalate "
                            f"to PI if you need to write to a different "
                            f"project."
                        ),
                    )
                )
                continue
            # Drop project_id from args; RestMCPClient will re-inject the
            # workflow-bound value at the REST layer via `_params()`.
            resolved_args = {k: v for k, v in resolved_args.items() if k != "project_id"}

        try:
            rka_id = method(**resolved_args)
        except Exception as e:  # noqa: BLE001 — surface all failures as ErrorRecord
            # Phase-X² polish — belt-and-suspenders: if the failure was a
            # CheckpointError with a structured `mcp_response`, append
            # it to the detail so the ErrorRecord carries the full body
            # even if the upstream RestMCPClient 422 enrichment misses
            # an edge case. The reason string itself already carries
            # the field-name summary for Pydantic 422s; this dumps the
            # full parsed body for programmatic inspection downstream.
            detail = (
                f"PA-{idx}: tool={tool!r} "
                f"args_keys={sorted(resolved_args.keys())!r} exc={e!r}"
            )
            if isinstance(e, CheckpointError) and getattr(e, "mcp_response", None):
                detail += f" mcp_response={e.mcp_response!r}"
            new_errors.append(
                _make_error(
                    "execute_ratified_actions",
                    "ratified_action_call_failed",
                    detail,
                )
            )
            continue

        # Record success for downstream chain references.
        if rka_id:
            previous_results[idx] = rka_id

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
# Gap 2 — execute_ratified_fs_actions: parent-process FS dispatch
# ---------------------------------------------------------------------------
#
# Mirror of execute_ratified_actions but for Bash/Write/Edit operations.
# Brain/Executor emits `proposed_fs_actions` when classify_fs_action
# returns ratify_required (the SDK hook denied the direct call);
# pi_decision_select packages them alongside proposed_actions in the
# same payload; PI accept copies them to `ratified_fs_actions`; this
# dispatcher runs them from the parent process.
#
# DOUBLE-CLASSIFY invariant: classify_fs_action runs AGAIN on each
# action at dispatch time. PI cannot override DENY-tier even if they
# somehow accepted one — those are refused and surface a
# `ratified_fs_action_denied_at_dispatch` ErrorRecord. This is the
# "PI shouldn't override deny" insurance policy.


def _resolve_workspace_path_from_state(state: ResearchWorkflowState) -> str:
    """Pick the workspace root for FS dispatch + double-classify.

    Priority: state["workspace_path"] (set by Phase O onboarding) →
    HOST_WORKSPACE_ROOT env var → empty string. Empty workspace_path
    is acceptable but skips escape detection in classify_fs_action,
    which is why the double-classify is critical at dispatch time
    (DENY-tier bash patterns still enforce).
    """
    explicit = (state.get("workspace_path") or "").strip()
    if explicit:
        return explicit
    import os as _os

    return _os.environ.get("HOST_WORKSPACE_ROOT", "").strip()


def execute_ratified_fs_actions(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Gap 2 — parent-process dispatch of PI-ratified FS actions.

    Iterates `state["ratified_fs_actions"]` and runs each via Python's
    subprocess.run() (for Bash) or direct file IO (for Write/Edit).
    A no-op when the list is empty — the topology can wire this node
    unconditionally between pi_decision_select and final_synthesis,
    parallel to execute_ratified_actions.

    Defense layers per action:
      1. Action shape validation (must be dict with tool + args)
      2. Tool must be in FS_ACTUATOR_MUTATING_TOOLS
      3. classify_fs_action() runs AGAIN at dispatch — PI cannot
         override DENY-tier; ratify_required actions are allowed at
         this point (PI ratified them, that's the whole point); only
         deny/unknown produces a refusal.
      4. Bash runs with timeout=300s, cwd=workspace_path, captures
         stdout/stderr to an ArtifactRef. Exit code != 0 → ErrorRecord.
      5. Write/Edit go through pathlib with size cap (10 MB) to
         prevent runaway writes.
    """
    import subprocess  # noqa: PLC0415 — local import to avoid top-level overhead
    from pathlib import Path

    from orchestrator import fs_actuator

    actions = state.get("ratified_fs_actions", []) or []
    new_artifacts: list[ArtifactRef] = []
    new_errors: list[ErrorRecord] = []

    workspace_path = _resolve_workspace_path_from_state(state)

    for idx, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            new_errors.append(
                _make_error(
                    "execute_ratified_fs_actions",
                    "ratified_fs_action_shape_error",
                    f"FA-{idx}: action is not a dict (got {type(action).__name__})",
                )
            )
            continue

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}

        if tool not in fs_actuator.FS_ACTUATOR_MUTATING_TOOLS:
            new_errors.append(
                _make_error(
                    "execute_ratified_fs_actions",
                    "ratified_fs_action_tool_not_allowed",
                    (
                        f"FA-{idx}: tool {tool!r} is not Bash/Write/Edit. "
                        f"Read-side tools don't need ratification and "
                        f"should never appear in proposed_fs_actions."
                    ),
                )
            )
            continue

        if not isinstance(args, dict):
            new_errors.append(
                _make_error(
                    "execute_ratified_fs_actions",
                    "ratified_fs_action_args_shape_error",
                    f"FA-{idx}: args for {tool!r} is not a dict",
                )
            )
            continue

        # CRITICAL: re-classify at dispatch. PI cannot override DENY.
        cls, rationale = fs_actuator.classify_fs_action(
            {"tool": tool, "args": args},
            workspace_path=workspace_path,
        )
        if cls == "deny":
            new_errors.append(
                _make_error(
                    "execute_ratified_fs_actions",
                    "ratified_fs_action_denied_at_dispatch",
                    (
                        f"FA-{idx}: tool={tool!r} classified as DENY at "
                        f"dispatch ({rationale}). PI ratification does not "
                        f"override the DENY tier. This operation has no "
                        f"safe execution path; the mission must be rewritten."
                    ),
                )
            )
            continue
        # cls in {read, scoped_write, ratify_required} — all proceed:
        # read shouldn't happen (validated above) but is safe;
        # scoped_write is fine; ratify_required is precisely the case
        # PI authorized us to dispatch.

        try:
            rka_id = _dispatch_fs_action(tool, args, workspace_path, subprocess, Path)
        except _FSDispatchError as e:
            new_errors.append(
                _make_error(
                    "execute_ratified_fs_actions",
                    e.error_type,
                    f"FA-{idx}: tool={tool!r} {e.message}",
                )
            )
            continue
        except Exception as e:  # noqa: BLE001 — surface unexpected as ErrorRecord
            new_errors.append(
                _make_error(
                    "execute_ratified_fs_actions",
                    "ratified_fs_action_call_failed",
                    f"FA-{idx}: tool={tool!r} unexpected error: {e!r}",
                )
            )
            continue

        new_artifacts.append(
            {
                "rka_id": rka_id or "",
                "entity_type": "fs_action",
                "node_name": "execute_ratified_fs_actions",
                "timestamp": _now_iso(),
            }
        )

    update: dict = {
        "current_phase": "executor_mission",
        "current_node": "execute_ratified_fs_actions",
    }
    if new_artifacts:
        update["artifacts"] = new_artifacts
    if new_errors:
        update["errors"] = new_errors
    return update


class _FSDispatchError(Exception):
    """Internal: bubble a typed failure up to execute_ratified_fs_actions."""

    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


_BASH_TIMEOUT_SECONDS = 300
_MAX_WRITE_BYTES = 10 * 1024 * 1024  # 10 MB cap


def _bash_has_backgrounding(cmd: str) -> bool:
    """Detect a backgrounding operator (`&`) in the bash command.

    Adversarial-review #1: a backgrounded child detaches from the
    parent shell, surviving subprocess.run timeout and clean exit.
    Quick AST check; fall back to a careful regex that ignores `&&`
    and `&` inside single/double-quoted strings.
    """
    try:
        import bashlex
        trees = bashlex.parse(cmd)
        return any(_ast_node_contains_backgrounding(t) for t in trees)
    except Exception:  # noqa: BLE001
        pass
    # Regex fallback: strip quoted regions, then look for a lone `&`.
    import re as _re
    stripped = _re.sub(r"'[^']*'", "", cmd)
    stripped = _re.sub(r'"[^"]*"', "", stripped)
    # `&&` is logical AND, not backgrounding. Look for unaccompanied `&`.
    return bool(_re.search(r"(?<![&|])&(?![&])", stripped))


def _ast_node_contains_backgrounding(node) -> bool:
    """Recursively check for an OperatorNode with op '&'."""
    kind = getattr(node, "kind", "")
    if kind == "operator" and getattr(node, "op", None) == "&":
        return True
    for attr in ("parts", "list"):
        children = getattr(node, attr, None) or []
        for c in children:
            if _ast_node_contains_backgrounding(c):
                return True
    return False


def _resolve_safe_target(
    target: str, workspace_path: str, path_cls, *, allow_missing: bool
):
    """Adversarial-review #2: resolve the path (collapsing `..` AND
    symlinks) and confirm it lies inside workspace_path. Refuses
    silent-escape via symlinks like `/ws/proj/link → /etc/passwd`.

    `allow_missing=True` for Write (target may not exist yet); we
    resolve the PARENT and append the basename, then verify the
    resolved path is still inside workspace_path. `allow_missing=False`
    for Edit (target must exist; resolve via `.resolve(strict=True)`).
    """
    from orchestrator import fs_actuator
    p = path_cls(target)

    if allow_missing and not p.exists():
        parent = p.parent
        # Walk up until we find an existing ancestor; resolve that,
        # then re-append the missing tail.
        existing = parent
        tail: list[str] = [p.name]
        while not existing.exists() and str(existing) != str(existing.parent):
            tail.insert(0, existing.name)
            existing = existing.parent
        if not existing.exists():
            raise _FSDispatchError(
                "ratified_fs_action_bad_path",
                f"Write target {target!r} resolves to a non-existent ancestor",
            )
        resolved = existing.resolve(strict=True)
        for t in tail:
            resolved = resolved / t
    else:
        if not p.exists():
            raise _FSDispatchError(
                "ratified_fs_action_target_missing",
                f"Edit target {target!r} does not exist",
            )
        try:
            resolved = p.resolve(strict=True)
        except OSError as e:
            raise _FSDispatchError(
                "ratified_fs_action_bad_path",
                f"target {target!r} cannot be resolved: {e}",
            )

    # workspace_path must be non-empty in production — Gap 2 dispatcher
    # already guards. Defensive double-check.
    if not workspace_path:
        raise _FSDispatchError(
            "ratified_fs_action_missing_workspace",
            "Write/Edit dispatch requires state['workspace_path']",
        )

    if fs_actuator.is_workspace_escape(str(resolved), workspace_path):
        raise _FSDispatchError(
            "ratified_fs_action_symlink_escape",
            f"resolved path {str(resolved)!r} escapes workspace "
            f"{workspace_path!r} after symlink resolution",
        )
    return resolved


def _safe_read_text(p):
    """Read a file with O_NOFOLLOW so a symlink swap between resolution
    and read is refused at the kernel level."""
    import os as _os
    fd = _os.open(str(p), _os.O_RDONLY | _os.O_NOFOLLOW)
    try:
        # Use fdopen to leverage UnicodeDecodeError as a real text-check
        with _os.fdopen(fd, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        raise _FSDispatchError(
            "ratified_fs_action_bad_path",
            f"O_NOFOLLOW read failed (path may have become a symlink): {e}",
        )


def _safe_write_text(p, content: str) -> None:
    """Write a file with O_NOFOLLOW + O_TRUNC. If the path became a
    symlink after resolution (TOCTOU), the kernel refuses with ELOOP."""
    import os as _os
    flags = _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC | _os.O_NOFOLLOW
    try:
        fd = _os.open(str(p), flags, 0o644)
    except OSError as e:
        raise _FSDispatchError(
            "ratified_fs_action_bad_path",
            f"O_NOFOLLOW write open failed: {e}",
        )
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        raise _FSDispatchError(
            "ratified_fs_action_write_failed",
            f"write failed: {e}",
        )


def _dispatch_fs_action(
    tool: str, args: dict, workspace_path: str, subprocess_mod, path_cls
) -> str:
    """Execute a single Gap 2 FS action. Returns a synthetic ID (a
    deterministic-ish short string identifying the action; mostly
    cosmetic in the artifact record). Raises `_FSDispatchError` on
    typed failures.
    """
    if tool == "Bash":
        cmd = args.get("command", "")
        if not isinstance(cmd, str) or not cmd.strip():
            raise _FSDispatchError(
                "ratified_fs_action_bad_command", "Bash command empty/non-string"
            )
        # Adversarial-review #6: refuse Bash dispatch when no workspace
        # is set. Empty workspace_path would make cwd default to the
        # daemon's /app — which holds the orchestrator's source tree
        # under Gap 5's non-root user setup. We never want PI-ratified
        # shell commands running against /app.
        if not workspace_path:
            raise _FSDispatchError(
                "ratified_fs_action_missing_workspace",
                "Bash dispatch requires state['workspace_path']; refusing to "
                "default to daemon cwd. Project must be onboarded first.",
            )
        # Adversarial-review #1: reject backgrounding operators in the
        # bash command. `cmd &` would fork a child that survives the
        # subprocess.run timeout and clean exit, and the dispatcher
        # would record success even though the LLM smuggled a
        # long-running process. No legitimate ratified mission step
        # needs fire-and-forget — escalate via rka_submit_checkpoint
        # if the mission genuinely needs background work.
        if _bash_has_backgrounding(cmd):
            raise _FSDispatchError(
                "ratified_fs_action_backgrounded",
                "Bash command contains a backgrounding operator (&). "
                "Ratified mission steps must complete synchronously.",
            )
        try:
            # Adversarial-review #1: start_new_session=True puts the
            # bash child in its own process group. On timeout/exit
            # we can kill the entire group (`os.killpg`) so any
            # grandchildren the LLM spawned are reaped too.
            result = subprocess_mod.run(
                cmd,
                shell=True,
                cwd=workspace_path,
                timeout=_BASH_TIMEOUT_SECONDS,
                capture_output=True,
                text=True,
                start_new_session=True,
            )
        except subprocess_mod.TimeoutExpired as e:
            # Kill the whole process group; the TimeoutExpired's pid
            # field gives us the immediate child, and start_new_session
            # made it the group leader.
            import os as _os
            import signal as _signal
            try:
                if e.cmd and hasattr(e, "pid"):
                    _os.killpg(e.pid, _signal.SIGKILL)
            except (ProcessLookupError, AttributeError, OSError):
                pass
            raise _FSDispatchError(
                "ratified_fs_action_timeout",
                f"Bash exceeded {_BASH_TIMEOUT_SECONDS}s timeout",
            )
        if result.returncode != 0:
            raise _FSDispatchError(
                "ratified_fs_action_bash_nonzero_exit",
                (
                    f"Bash exit={result.returncode} stderr="
                    f"{result.stderr[:500]!r}"
                ),
            )
        return f"bash:{hash(cmd) & 0xFFFFFF:06x}"

    if tool == "Write":
        target = args.get("file_path") or args.get("path")
        content = args.get("content", "")
        if not isinstance(target, str) or not target:
            raise _FSDispatchError(
                "ratified_fs_action_bad_path", "Write file_path empty/non-string"
            )
        if not isinstance(content, str):
            raise _FSDispatchError(
                "ratified_fs_action_bad_content", "Write content must be string"
            )
        if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
            raise _FSDispatchError(
                "ratified_fs_action_too_large",
                f"Write exceeds {_MAX_WRITE_BYTES} bytes",
            )
        p = _resolve_safe_target(target, workspace_path, path_cls, allow_missing=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Adversarial-review #2: use O_NOFOLLOW to refuse following
        # symlinks at the open call. Even if the symlink was placed
        # between classify-time and write-time (TOCTOU), the kernel
        # rejects it.
        _safe_write_text(p, content)
        return f"write:{target}"

    if tool == "Edit":
        target = args.get("file_path") or args.get("path")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not isinstance(target, str) or not target:
            raise _FSDispatchError(
                "ratified_fs_action_bad_path", "Edit file_path empty/non-string"
            )
        p = _resolve_safe_target(target, workspace_path, path_cls, allow_missing=False)
        try:
            # O_NOFOLLOW on read also — if target became a symlink after
            # the workspace-bound resolution, refuse.
            current = _safe_read_text(p)
        except UnicodeDecodeError:
            raise _FSDispatchError(
                "ratified_fs_action_not_text",
                f"Edit target {target!r} is not UTF-8 text",
            )
        if old_string and old_string not in current:
            raise _FSDispatchError(
                "ratified_fs_action_edit_old_string_not_found",
                f"Edit old_string not found in {target!r}",
            )
        updated = (
            current.replace(old_string, new_string, 1) if old_string else new_string
        )
        if len(updated.encode("utf-8")) > _MAX_WRITE_BYTES:
            raise _FSDispatchError(
                "ratified_fs_action_too_large",
                f"Edit result exceeds {_MAX_WRITE_BYTES} bytes",
            )
        _safe_write_text(p, updated)
        return f"edit:{target}"

    # Unreachable per FS_ACTUATOR_MUTATING_TOOLS guard upstream.
    raise _FSDispatchError(
        "ratified_fs_action_unknown_tool", f"unhandled tool {tool!r}"
    )


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
        "usd_spent": _accrue_cost(state, sdk),
    }
