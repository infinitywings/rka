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

import json
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


# ---------------------------------------------------------------------------
# Phase O O1.1 — pi_idea_capture (free-form project description + ingestion)
# ---------------------------------------------------------------------------


_PI_IDEA_CAPTURE_PROMPT = (
    "Describe the research project — paste text, summarize attached docs, "
    "or drop diagrams (you'll summarize them next).\n\n"
    "For each document / diagram / URL you want to bring in to RKA:\n"
    "  1. Read or view it (in Claude Desktop's chat).\n"
    "  2. Summarize in 2-3 sentences.\n"
    "  3. Extract concrete claims as bullets.\n"
    "  4. Call rka_add_note(content=<summary+claims>, source='pi', "
    "type='note', tags=['<project_id>', 'ingested-source']) — substitute "
    "the project's prj_… ID where shown.\n\n"
    "When all sources are ingested AND you've described the project, "
    "accept this interrupt. orchestrator_correct lets you carry the full "
    "project description in the response_text; orchestrator_accept alone "
    "means 'I used the chat session to describe + ingest — no extra text "
    "to forward'. Either path advances."
)


def pi_idea_capture(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """First Phase O PI interrupt — free-form project description.

    The PI Claude session renders the prompt as guidance and packages
    the response as either:
      - orchestrator_correct(response_text=<idea>) — the description
        text comes back as the resume token,
      - orchestrator_accept() — the resume token is "approve"
        (greenlight-class), meaning "I used the chat in-band; no extra
        text to forward".

    Either way, after the interrupt the node:
      1. Records the PI's response_text on brain_position so idea_polish
         (O1.2) can read it as the polished-idea source material.
      2. Refreshes state["ingested_source_ids"] by re-querying RKA — the
         PI may have called rka_add_note one or more times during the
         pause to ingest sources, and the polished-idea node needs the
         updated set.

    Low-stakes (no TWO-TAP): ratification happens at pi_scope_ratify
    in O1.3 after Brain polishes the idea into structured form.
    """
    project_id = state.get("project_id", "")

    payload = {
        "type": "pi_idea_capture",
        "title": "PI idea capture — describe the project + ingest sources",
        "prompt": _PI_IDEA_CAPTURE_PROMPT.replace("<project_id>", project_id or "<project_id>"),
        "project_id": project_id,
        "items": [],
        "total_items": 0,
    }
    pi_response = interrupt_fn(payload)
    response_str = str(pi_response or "")

    # Re-query for any 'ingested-source' journals the PI added during
    # the pause. (capture_idea_node pre-loaded what was there at parking
    # time; the PI typically adds more between then and now.)
    refreshed_ids: list[str] = []
    if project_id:
        try:
            result = mcp.rka_get_journal(
                tags=[project_id, "ingested-source"], limit=200
            )
        except Exception:  # noqa: BLE001
            result = None
        entries = (
            result if isinstance(result, list)
            else (result or {}).get("entries") or (result or {}).get("results") or []
        )
        for e in entries:
            if isinstance(e, dict):
                eid = e.get("id") or e.get("rka_id") or e.get("jrn_id")
                if eid:
                    refreshed_ids.append(str(eid))

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "pi_idea_capture",
        "ingested_source_ids": refreshed_ids,
        "interrupts": [
            _record_interrupt(
                node_name="pi_idea_capture",
                payload_size=0,
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }
    # Stash the PI's free-form description on brain_position so the
    # downstream idea_polish node can read it as the polished-idea
    # source material. When PI just hit accept (response is the
    # greenlight token "approve"), leave brain_position empty —
    # idea_polish then falls back entirely on the journal contents
    # already ingested via rka_add_note.
    if response_str and response_str.strip().lower() not in {"approve", "accept", "reject"}:
        update["brain_position"] = response_str[:5000]

    return update


# ---------------------------------------------------------------------------
# Phase O O1.3 — pi_scope_ratify (TWO-TAP ratification of the polished idea)
# ---------------------------------------------------------------------------


def _render_polished_idea_markdown(p: dict) -> str:
    """Pretty-print the PolishedIdea dict as markdown sections for the
    PI to read at ratification time. Tolerant of missing/empty fields
    (renders "(unspecified)" rather than raising)."""
    if not isinstance(p, dict):
        return "(no polished idea on state)"

    def _field(key: str, fallback: str = "(unspecified)") -> str:
        v = p.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            return fallback
        return str(v).strip()

    sections = [
        "## Research question",
        _field("research_question"),
        "",
        "## Motivation",
        _field("motivation"),
        "",
        "## Scope",
        _field("scope"),
        "",
        "## Novelty hypothesis",
        _field("novelty_hypothesis"),
        "",
        f"**Target venue:** {_field('target_venue', '(none specified)')}",
        "",
    ]
    assumptions = p.get("open_assumptions") or []
    if assumptions:
        sections.append("## Open assumptions")
        for a in assumptions:
            if a:
                sections.append(f"  - {a}")
        sections.append("")
    sources = p.get("ingested_sources") or []
    if sources:
        sections.append("## Backed by ingested sources")
        for s in sources:
            if s:
                sections.append(f"  - {s}")
        sections.append("")
    return "\n".join(sections).rstrip()


def pi_scope_ratify(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Phase O O1.3 — TWO-TAP ratification of the polished idea (O1.2 output).

    Set-identity pattern (mirrors pi_decision_select / pi_toolkit_ratify):
    on accept, ``state["scope_ratified"] = True``; on reject/correct,
    cleared to False so the routing fn loops back to capture_idea.

    Payload carries:
      - The PolishedIdea dict on ``items[0]`` so Claude-the-assistant
        can render its fields individually + structure the TWO-TAP
        ask.
      - A pre-rendered markdown blob (``rendered_markdown``) for
        skills/UIs that prefer the bake-out.
      - Type-level TWO-TAP signal (``two_tap_required = true``,
        ``two_tap_label = "Confirm scope locks the project's framing"``)
        so the skill's rendering rules can present the second
        confirmation tap. The orchestrator-pi skill enforces the
        TWO-TAP at presentation time; the Python node does not.

    PI's resume token:
      - 'accept'  → scope_ratified = True; advance to O2
      - 'reject'  → scope_ratified = False; loop back to capture_idea
      - <freeform text> (correct) → scope_ratified = False; the text
        is the redirection feedback for the next idea_polish pass.
    """
    polished = state.get("polished_idea") or {}

    payload, batched = _build_interrupt_payload(
        node_name="pi_scope_ratify",
        items=[polished] if polished else [],
        title="PI ratification — polished idea (TWO-TAP)",
    )
    payload["rendered_markdown"] = _render_polished_idea_markdown(polished)
    payload["two_tap_required"] = True
    payload["two_tap_label"] = (
        "Confirm the polished scope locks the project's framing. You "
        "can still extend in later phases, but this is the foundation."
    )

    pi_response = interrupt_fn(payload)
    response_text = str(pi_response or "").lower()
    is_accept = "accept" in response_text

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "pi_scope_ratify",
        "scope_ratified": is_accept,
        "batch_review_active": batched,
        "batch_review_payload_size": len(payload.get("items") or []),
        "interrupts": [
            _record_interrupt(
                node_name="pi_scope_ratify",
                payload_size=1 if polished else 0,
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }

    # When PI provides freeform correction (i.e., not accept and not the
    # bare "reject" token), stash the verbatim redirection on
    # brain_position so the next idea_polish pass reads it as
    # corrective feedback. On a bare reject, leave brain_position alone.
    if not is_accept and response_text and response_text != "reject":
        update["brain_position"] = str(pi_response)[:5000]

    return update


# ---------------------------------------------------------------------------
# Phase O O2.2 — pi_deepresearch_prompt (async-pause for SOTA literature scan)
# ---------------------------------------------------------------------------


_DEEPRESEARCH_MIN_PAPER_FLOOR: int = 5
"""Soft floor on # papers PI should ingest before proceeding to hygiene.
Below this, the workflow proceeds but stashes a soft-warning note on
state (renderable by the orchestrator-pi skill for the next phase)."""


_DEEPRESEARCH_PROMPT_TEMPLATE = (
    "Time to bring in SOTA literature + related work. The orchestrator "
    "parks here indefinitely — close Claude Desktop now, come back in "
    "an hour or a week. Accept when you're done.\n\n"
    "Workflow (in Claude Desktop):\n"
    "  1. Use Deep Research / web search / Semantic Scholar / arxiv "
    "     to scan the literature for this project's RQ.\n"
    "  2. For each useful paper, call rka_enrich_doi(doi=...) OR "
    "     rka_add_literature(title=..., source='deep-research', "
    "     tags=['{project_id}', 'literature']). The orchestrator "
    "     discovers what you added by querying tags on resume.\n"
    "  3. For broader insights / framing notes, use rka_add_note "
    "     (source='pi', tags=['{project_id}', 'deep-research-finding']).\n\n"
    "Recommended floor: at least {floor} papers. The orchestrator will "
    "warn but proceed below that. Reject if you want to abandon the "
    "project here."
)


def pi_deepresearch_prompt(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Phase O O2.2 — async-pause interrupt for Deep Research literature scan.

    The interrupt parks indefinitely (LangGraph SqliteSaver durability).
    The PI works in Claude Desktop's chat (Deep Research, web search,
    Semantic Scholar MCP, arxiv MCP) and ingests papers via
    rka_enrich_doi / rka_add_literature with the project's literature
    tag. The orchestrator does NOT actively poll — it simply waits for
    the resume.

    On resume (accept):
      - Queries RKA for ``[project_id, 'literature']``-tagged journals.
      - Writes state["deepresearch_complete"] = True.
      - If the count is below the soft floor, emits a soft-warning
        notification (not an error; the workflow continues).

    On reject:
      - Writes state["deepresearch_complete"] = False so the routing
        function can short-circuit to a terminal abandonment.

    Acceptance token: "accept" (per runner _ACCEPT_TOKEN_BY_TYPE).
    """
    project_id = state.get("project_id", "")
    payload = {
        "type": "pi_deepresearch_prompt",
        "title": "PI deep research — async pause for literature scan",
        "prompt": _DEEPRESEARCH_PROMPT_TEMPLATE.format(
            project_id=project_id or "<project_id>",
            floor=_DEEPRESEARCH_MIN_PAPER_FLOOR,
        ),
        "project_id": project_id,
        "minimum_paper_floor": _DEEPRESEARCH_MIN_PAPER_FLOOR,
        "tag_to_query": [project_id, "literature"] if project_id else ["literature"],
        "async_pause": True,  # signal to the skill: PI may walk away
        "items": [],
        "total_items": 0,
    }
    pi_response = interrupt_fn(payload)
    response_text = str(pi_response or "").lower()
    is_accept = "accept" in response_text

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "pi_deepresearch_prompt",
        "deepresearch_complete": is_accept,
        "interrupts": [
            _record_interrupt(
                node_name="pi_deepresearch_prompt",
                payload_size=0,
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }

    if not is_accept:
        return update

    # Count literature on accept; emit soft-warning notification if low.
    literature_count = 0
    if project_id:
        try:
            result = mcp.rka_get_journal(
                tags=[project_id, "literature"], limit=500
            )
        except Exception:  # noqa: BLE001
            result = None
        if isinstance(result, list):
            literature_count = len(result)
        elif isinstance(result, dict):
            entries = result.get("entries") or result.get("results") or []
            literature_count = len(entries) if isinstance(entries, list) else 0

    if literature_count < _DEEPRESEARCH_MIN_PAPER_FLOOR:
        update["notifications"] = [
            {
                "channel": "bell",
                "message": (
                    f"Deep research advanced with {literature_count} literature "
                    f"entries (soft floor is {_DEEPRESEARCH_MIN_PAPER_FLOOR}). "
                    f"PI can return to O2 later to ingest more before O4 plan "
                    f"synthesis if desired."
                ),
                "timestamp": _now_iso(),
                "delivered": False,
            }
        ]

    return update


# ---------------------------------------------------------------------------
# Phase O O3.2 — pi_claims_review (TWO-TAP ratification of extracted claims)
# ---------------------------------------------------------------------------


_CLAIMS_REVIEW_PREVIEW_FLOOR: int = 10
"""Soft floor for inline claim rendering. Above this the payload
relies on batch_review for paging — same convention as pi_greenlight /
pi_decision_select payloads."""


def _fetch_claims_for_review(
    mcp: MCPClient, *, claim_ids: list[str]
) -> list[dict]:
    """Best-effort fetch of claim entities so the interrupt payload
    can render content + provenance per claim rather than just IDs.

    Tries rka_list_claims with no filters (returns all claims; we
    filter to the IDs) and falls back to one rka_get per ID if the
    list path is unavailable.
    """
    if not claim_ids:
        return []
    wanted = set(claim_ids)
    fetched: list[dict] = []
    try:
        result = mcp.rka_list_claims(limit=200)
        if isinstance(result, list):
            for c in result:
                if isinstance(c, dict):
                    cid = c.get("id") or c.get("clm_id")
                    if cid and str(cid) in wanted:
                        fetched.append(c)
    except Exception:  # noqa: BLE001
        pass
    if fetched:
        return fetched
    # Fallback: per-ID rka_get.
    for cid in claim_ids:
        try:
            entity = mcp.rka_get(cid)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(entity, dict):
            fetched.append(entity)
    return fetched


def pi_claims_review(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Phase O O3.2 — TWO-TAP ratification of the extracted claims.

    Claims are the provenance backbone of the plan that follows at O4,
    so PI must explicitly ratify them before plan synthesis runs.
    Mirrors the set-identity ratification pattern of pi_scope_ratify /
    pi_toolkit_ratify: on accept the workflow proceeds; on reject /
    correct the workflow loops back to claim_extraction.

    Payload carries:
      - items[]              — full claim dicts (when fetchable) so
                               Claude-the-assistant can render each
                               with claim_type + content + confidence
                               + provenance (source_entry_id).
      - claim_ids            — the raw ID list for skills that just
                               surface counts.
      - two_tap_required     — True; second tap label warns this
                               claim set becomes plan provenance.
    """
    claim_ids = list(state.get("claim_ids") or [])
    claims = _fetch_claims_for_review(mcp, claim_ids=claim_ids)

    payload, batched = _build_interrupt_payload(
        node_name="pi_claims_review",
        items=claims or [{"id": cid} for cid in claim_ids],
        title="PI ratification — extracted claims (TWO-TAP)",
    )
    payload["claim_ids"] = claim_ids
    payload["two_tap_required"] = True
    payload["two_tap_label"] = (
        f"Confirm the {len(claim_ids)} extracted claim(s) become the "
        "provenance for plan synthesis. Reject or correct to re-run "
        "claim extraction (e.g., to drop or refine specific claims "
        "first via rka_review_claims)."
    )

    pi_response = interrupt_fn(payload)
    response_text = str(pi_response or "").lower()
    is_accept = "accept" in response_text

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "pi_claims_review",
        "batch_review_active": batched,
        "batch_review_payload_size": len(payload.get("items") or []),
        "interrupts": [
            _record_interrupt(
                node_name="pi_claims_review",
                payload_size=len(claim_ids),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }
    # On reject/correct, clear claim_ids so the next claim_extraction
    # pass re-populates from scratch. (Set-identity convention.)
    if not is_accept:
        update["claim_ids"] = []
        if response_text and response_text != "reject":
            # Freeform correction → stash on brain_position so
            # claim_extraction sees the redirection guidance.
            update["brain_position"] = str(pi_response)[:5000]

    return update


# ---------------------------------------------------------------------------
# Phase O O4.2 — pi_plan_ratify (TWO-TAP — THE contract gate for autonomy)
# ---------------------------------------------------------------------------


def _render_research_plan_markdown(plan: dict | None) -> str:
    """Render the ratified-plan-draft as PI-facing markdown for the
    TWO-TAP ratification interrupt.

    Tolerant of missing/empty sections — surfaces '(none)' rather than
    raising so the renderer is safe to invoke on a malformed plan
    (lets the PI see what Brain emitted even when fields are off).
    """
    if not isinstance(plan, dict):
        return "(no plan on state)"

    def _field(key: str, fallback: str = "(unspecified)") -> str:
        v = plan.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            return fallback
        return str(v).strip()

    sections: list[str] = []

    sections.append("## Refined research question")
    sections.append(_field("refined_research_question"))
    sections.append("")

    hypotheses = plan.get("hypotheses") or []
    sections.append(f"## Hypotheses ({len(hypotheses)})")
    if not hypotheses:
        sections.append("(none)")
    else:
        for i, h in enumerate(hypotheses, 1):
            if not isinstance(h, dict):
                continue
            sections.append(
                f"{i}. **{h.get('statement', '(missing)')}** "
                f"— falsifier: {h.get('falsifier', '(missing)')} "
                f"[confidence: {h.get('confidence', '?')}]"
            )
    sections.append("")

    variables = plan.get("variables") or []
    sections.append(f"## Variables ({len(variables)})")
    if not variables:
        sections.append("(none)")
    else:
        sections.append("| name | kind | description | measurement |")
        sections.append("|---|---|---|---|")
        for v in variables:
            if not isinstance(v, dict):
                continue
            sections.append(
                f"| {v.get('name', '?')} | {v.get('kind', '?')} | "
                f"{v.get('description', '')[:80]} | {v.get('measurement') or '—'} |"
            )
    sections.append("")

    sections.append("## Experimental matrix")
    sections.append(_field("experimental_matrix"))
    sections.append("")

    gaps = plan.get("literature_gaps") or []
    if gaps:
        sections.append("## Literature gaps")
        for g in gaps:
            sections.append(f"  - {g}")
        sections.append("")

    milestones = plan.get("milestones") or []
    total_cost = sum(
        float(m.get("estimated_llm_cost_usd") or 0)
        for m in milestones if isinstance(m, dict)
    )
    total_wall = sum(
        int(m.get("estimated_wall_clock_min") or 0)
        for m in milestones if isinstance(m, dict)
    )
    sections.append(
        f"## Mission queue ({len(milestones)} milestones — "
        f"total estimated cost ${total_cost:.2f}, "
        f"total ETA {total_wall} min)"
    )
    if milestones:
        sections.append("| milestone_id | phase | objective | depends_on | cost | wall-clock |")
        sections.append("|---|---|---|---|---|---|")
        for m in milestones:
            if not isinstance(m, dict):
                continue
            sections.append(
                f"| {m.get('milestone_id', '?')} | {m.get('phase', '?')} | "
                f"{(m.get('objective') or '')[:60]} | "
                f"{m.get('depends_on_milestone') or '—'} | "
                f"${float(m.get('estimated_llm_cost_usd') or 0):.2f} | "
                f"{int(m.get('estimated_wall_clock_min') or 0)}m |"
            )
    else:
        sections.append("(none)")
    sections.append("")

    risks = plan.get("open_risks") or []
    if risks:
        sections.append("## Open risks")
        for r in risks:
            sections.append(f"  - {r}")
        sections.append("")

    return "\n".join(sections).rstrip()


def _topo_sort_milestones(milestones: list[dict]) -> list[dict]:
    """Topological order so a milestone's dependency is created before
    it. Stable: respects the original order for milestones with no
    inter-dependencies. Cycles fall through with the cycle members
    appended at the end (validated upstream — should never happen for
    a ratified plan, but we don't crash either way)."""
    by_id = {m.get("milestone_id"): m for m in milestones if isinstance(m, dict)}
    out: list[dict] = []
    visited: set[str] = set()

    def visit(mid: str, on_stack: set[str]):
        if mid in visited or mid not in by_id or mid in on_stack:
            return
        m = by_id[mid]
        dep = m.get("depends_on_milestone")
        if dep:
            visit(dep, on_stack | {mid})
        visited.add(mid)
        out.append(m)

    for m in milestones:
        if isinstance(m, dict) and m.get("milestone_id"):
            visit(m["milestone_id"], set())
    # Append any milestones not reached (cycles / dangling refs).
    for m in milestones:
        if isinstance(m, dict) and m.get("milestone_id") not in visited:
            out.append(m)
    return out


def _materialize_milestone_chain(
    *,
    mcp: MCPClient,
    decision_id: str,
    plan: dict,
    project_id: str,
) -> tuple[list[str], list[dict]]:
    """For each milestone in the plan, call rka_create_mission in topo
    order and remember the (m_NN → mis_…) mapping so dependencies
    resolve to real mission IDs.

    Returns (mission_ids, errors).
    """
    milestones = plan.get("milestones") or []
    ordered = _topo_sort_milestones(milestones)
    plan_to_mission: dict[str, str] = {}
    created_ids: list[str] = []
    errors: list[dict] = []

    for m in ordered:
        mid = m.get("milestone_id") or ""
        depends_plan = m.get("depends_on_milestone")
        depends_mission = plan_to_mission.get(depends_plan) if depends_plan else None
        try:
            mission_id = mcp.rka_create_mission(
                objective=m.get("objective") or f"Milestone {mid}",
                motivated_by_decision=decision_id,
                acceptance_criteria=[m.get("acceptance_criteria") or ""],
                phase=m.get("phase"),
                scope_boundaries=m.get("scope_boundaries"),
                depends_on=depends_mission,
                tags=[project_id, "phase-o-milestone", mid] if project_id else [],
            )
        except Exception as e:  # noqa: BLE001
            errors.append(
                {
                    "node_name": "pi_plan_ratify",
                    "error_type": "pi_plan_ratify_mission_create_failed",
                    "detail": (
                        f"rka_create_mission failed for milestone {mid}: "
                        f"{type(e).__name__}: {str(e)[:200]}"
                    ),
                    "timestamp": _now_iso(),
                }
            )
            continue
        if mission_id:
            plan_to_mission[mid] = mission_id
            created_ids.append(mission_id)
    return created_ids, errors


def pi_plan_ratify(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Phase O O4.2 — TWO-TAP ratification of the ResearchPlan + auto-create missions.

    THE contract gate of Phase O. On accept:
      1. Write a decision (rka_add_decision) recording PI ratified the
         plan, related_journal = [plan_journal_id].
      2. For each milestone (in topo order), call rka_create_mission
         with the milestone's objective + acceptance_criteria +
         scope_boundaries + phase, plus depends_on (mis_…) resolved
         from the m_NN → mis_… mapping built as we go.
      3. Re-tag the plan journal from 'ratified-plan-draft' →
         'ratified-plan' so downstream queries find the ratified
         version, not the draft.
      4. State writes:
           ratified_plan_decision_id = dec_…
           ratified_mission_ids      = [mis_…, mis_…, ...]
           current_milestone_index   = 0 (Phase H reads this)

    On reject/correct:
      - No decision written, no missions created, no retag.
      - ratified_plan_decision_id stays empty (signals abandonment).
      - On correct, brain_position carries the verbatim redirection
        so a re-synthesis loop has the feedback.

    Payload includes the full plan dict (items[0]) AND a pre-rendered
    markdown blob (rendered_markdown) so the orchestrator-pi skill can
    decide how to present.

    TWO-TAP enforcement is the skill's responsibility (Python only
    declares the requirement via two_tap_required=True + two_tap_label).
    """
    project_id = state.get("project_id", "")
    plan_journal_id = state.get("ratified_plan_journal_id", "")

    # Fetch the plan JSON from the journal (preferred) — falls back to
    # state.polished_idea only if the journal is missing.
    plan: dict = {}
    if plan_journal_id:
        try:
            entry = mcp.rka_get(plan_journal_id)
            if isinstance(entry, dict):
                content = entry.get("content") or ""
                if content.strip():
                    try:
                        plan = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        plan = {}
        except Exception:  # noqa: BLE001
            plan = {}

    payload, batched = _build_interrupt_payload(
        node_name="pi_plan_ratify",
        items=[plan] if plan else [],
        title="PI ratification — research plan (TWO-TAP — licenses autonomy)",
    )
    payload["rendered_markdown"] = _render_research_plan_markdown(plan)
    payload["two_tap_required"] = True
    milestones = plan.get("milestones") or []
    total_cost = sum(
        float(m.get("estimated_llm_cost_usd") or 0)
        for m in milestones if isinstance(m, dict)
    )
    total_wall = sum(
        int(m.get("estimated_wall_clock_min") or 0)
        for m in milestones if isinstance(m, dict)
    )
    payload["two_tap_label"] = (
        f"**Authorize the orchestrator to dispatch this {len(milestones)}-milestone "
        f"mission queue with estimated total cost ${total_cost:.2f} and "
        f"ETA {total_wall} min? Per-phase acknowledgment will still apply "
        f"for each milestone.**"
    )
    payload["total_estimated_cost_usd"] = total_cost
    payload["total_estimated_wall_clock_min"] = total_wall
    payload["plan_journal_id"] = plan_journal_id

    pi_response = interrupt_fn(payload)
    response_text = str(pi_response or "").lower()
    is_accept = "accept" in response_text

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "pi_plan_ratify",
        "batch_review_active": batched,
        "batch_review_payload_size": len(payload.get("items") or []),
        "interrupts": [
            _record_interrupt(
                node_name="pi_plan_ratify",
                payload_size=len(milestones),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }

    if not is_accept:
        # Reject / correct path.
        if response_text and response_text != "reject":
            update["brain_position"] = str(pi_response)[:5000]
        return update

    # Accept path: write the ratification decision + materialize missions.
    if not plan:
        # PI accepted but the plan is missing/unparsable. Defensive
        # error path (should never happen if O4.1 succeeded).
        update["errors"] = [
            {
                "node_name": "pi_plan_ratify",
                "error_type": "pi_plan_ratify_no_plan",
                "detail": (
                    "PI accepted ratification but no plan content could "
                    "be loaded from the journal — aborting auto-mission "
                    "creation to avoid corrupting RKA state."
                ),
                "timestamp": _now_iso(),
            }
        ]
        return update

    errors: list[dict] = []
    try:
        decision_id = mcp.rka_add_decision(
            content=f"Ratified Phase O research plan for project {project_id}.",
            related_journal=[plan_journal_id] if plan_journal_id else [],
            tags=[project_id, "ratified-plan"] if project_id else ["ratified-plan"],
        )
    except Exception as e:  # noqa: BLE001
        decision_id = ""
        errors.append(
            {
                "node_name": "pi_plan_ratify",
                "error_type": "pi_plan_ratify_decision_write_failed",
                "detail": f"rka_add_decision raised: {type(e).__name__}: {str(e)[:200]}",
                "timestamp": _now_iso(),
            }
        )

    mission_ids: list[str] = []
    if decision_id:
        mission_ids, mission_errors = _materialize_milestone_chain(
            mcp=mcp,
            decision_id=decision_id,
            plan=plan,
            project_id=project_id,
        )
        errors.extend(mission_errors)

    # Re-tag the plan journal: 'ratified-plan-draft' → 'ratified-plan'.
    if plan_journal_id:
        try:
            mcp.rka_update_note(
                plan_journal_id,
                tags=[project_id, "ratified-plan"] if project_id else ["ratified-plan"],
            )
        except Exception as e:  # noqa: BLE001
            errors.append(
                {
                    "node_name": "pi_plan_ratify",
                    "error_type": "pi_plan_ratify_journal_retag_failed",
                    "detail": f"rka_update_note raised: {type(e).__name__}: {str(e)[:200]}",
                    "timestamp": _now_iso(),
                }
            )

    update["ratified_plan_decision_id"] = decision_id
    update["ratified_mission_ids"] = mission_ids
    update["current_milestone_index"] = 0
    artifacts = []
    if decision_id:
        artifacts.append(
            {
                "rka_id": decision_id,
                "entity_type": "decision",
                "node_name": "pi_plan_ratify",
                "timestamp": _now_iso(),
            }
        )
    for mid in mission_ids:
        artifacts.append(
            {
                "rka_id": mid,
                "entity_type": "mission",
                "node_name": "pi_plan_ratify",
                "timestamp": _now_iso(),
            }
        )
    if artifacts:
        update["artifacts"] = artifacts
    if errors:
        update["errors"] = errors
    return update


# ---------------------------------------------------------------------------
# Phase O — Phase H: pi_phase_entry_ack (per-milestone go/no-go)
# ---------------------------------------------------------------------------


def pi_phase_entry_ack(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Phase H — per-milestone acknowledgment before mission dispatch.

    Surfaces the next milestone in ``state["ratified_mission_ids"]``
    (indexed by ``state["current_milestone_index"]``) with cost + ETA
    + remaining-queue summary. PI's response routes:

      - accept   → the orchestrator launches the milestone's mission via
                   ``orchestrator_run_start(mission_id=...)``; the server
                   coordinates the mission lifecycle and re-parks at the
                   next pi_phase_entry_ack when the mission terminates.
      - reject   → queue paused; PI resumes later via
                   ``orchestrator_continue_plan(project_id)``.
      - correct  → freeform redirect (re-order / skip ahead); the text
                   lands on brain_position for the runner to interpret.

    State writes:
      - current_node                = "pi_phase_entry_ack"
      - current_phase               = "init"
      - current_milestone_index     = bumped on accept only
                                      (orchestrator advances queue)
      - brain_position              = redirect text on correct
    """
    mission_ids = list(state.get("ratified_mission_ids") or [])
    idx = int(state.get("current_milestone_index") or 0)
    remaining = mission_ids[idx:] if 0 <= idx < len(mission_ids) else []
    current_mission_id = remaining[0] if remaining else None

    # Resolve the mission entity for metadata (cost / objective / etc.).
    current_mission: dict = {}
    if current_mission_id:
        try:
            current_mission = mcp.rka_get_mission(current_mission_id) or {}
        except Exception:  # noqa: BLE001
            current_mission = {}

    # Aggregate remaining cost / wall-clock if available on the mission
    # entity. (For Phase H MVP, we don't refetch every remaining mission
    # — the orchestrator-pi skill can paginate if needed.)
    payload: dict[str, Any] = {
        "type": "pi_phase_entry_ack",
        "title": "Mission queue — ready for next milestone?",
        "current_mission_id": current_mission_id,
        "current_mission": current_mission,
        "remaining_mission_ids": remaining,
        "remaining_count": len(remaining),
        "current_milestone_index": idx,
        "items": [current_mission] if current_mission else [],
        "total_items": 1 if current_mission else 0,
    }

    pi_response = interrupt_fn(payload)
    response_text = str(pi_response or "").lower()
    is_accept = "approve" in response_text or "accept" in response_text

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "pi_phase_entry_ack",
        "interrupts": [
            _record_interrupt(
                node_name="pi_phase_entry_ack",
                payload_size=len(remaining),
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }
    if is_accept:
        update["current_milestone_index"] = idx + 1
    elif response_text and response_text != "reject":
        # Freeform correction — stash for the runner / next iteration.
        update["brain_position"] = str(pi_response)[:5000]

    return update


# ---------------------------------------------------------------------------
# 4. pi_onboarding_topic — initial topic elicitation (Phase D)
# ---------------------------------------------------------------------------


def pi_onboarding_topic(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """First PI interrupt in the onboarding subgraph.

    Asks the PI for the project's topic, field, and target venue.
    Brain's research_toolkit_node reads the response from
    state["topic_metadata"] downstream to suggest a toolkit.

    Response shape (free-form, parsed by the next node):
      - The PI Claude session renders a structured prompt
        ("topic? field? venue? keywords?") and packages the response.
      - The graph routing function expects the response string to
        contain "accept" so the workflow proceeds; orchestrator_accept
        emits "approve" for greenlight-class interrupts → we treat
        this onboarding interrupt similarly to greenlight (i.e.,
        "approve" advances).
    """
    payload = {
        "type": "pi_onboarding_topic",
        "title": "PI topic elicitation — onboard a new project",
        "prompt": (
            "Tell me about the project: a 1-2 sentence summary, the "
            "research field, target venue (conference/journal), and "
            "3-5 keywords. Your response is captured as the project's "
            "topic_metadata and drives tool-discovery in the next step."
        ),
        "items": [],
        "total_items": 0,
    }
    pi_response = interrupt_fn(payload)

    # The PI's response is captured as-is into a brain-readable topic
    # field — the orchestrator-pi skill instructs Claude-the-assistant
    # to structure the response into {summary, research_field, venue,
    # keywords} when calling orchestrator_correct, OR to pass through
    # verbatim text when calling orchestrator_accept. Brain's
    # research_toolkit_node tolerates partial data.
    response_str = str(pi_response)
    topic = {"summary": response_str, "research_field": None, "venue": None, "keywords": []}

    return {
        "current_phase": "init",
        "current_node": "pi_onboarding_topic",
        "topic_metadata": topic,
        "interrupts": [
            _record_interrupt(
                node_name="pi_onboarding_topic",
                payload_size=0,
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }


# ---------------------------------------------------------------------------
# 5. pi_toolkit_ratify — PI accepts/rejects/corrects the proposed toolkit
# ---------------------------------------------------------------------------


def pi_toolkit_ratify(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Second PI interrupt in the onboarding subgraph.

    Surfaces the Brain's proposed_toolkit for PI multi-select. On
    accept, every tool in proposed_toolkit is copied to
    ratified_toolkit; on reject, escalation; on correct, the freeform
    text is treated as a redirect (Brain re-runs research_toolkit_node
    with the new direction). Mirrors pi_decision_select's set-identity
    semantics (Phase 2.7 T3d).
    """
    proposed = state.get("proposed_toolkit", []) or []

    payload, batched = _build_interrupt_payload(
        node_name="pi_toolkit_ratify",
        items=proposed,
        title="PI ratification — proposed project toolkit",
    )
    # Include Brain's notes-for-PI paragraph if it exists (set by
    # research_toolkit_node when Brain emits a notes_for_pi field).
    notes = state.get("brain_position")
    if notes:
        payload["brain_notes"] = notes
    pi_response = interrupt_fn(payload)

    # On accept, the full proposed_toolkit moves to ratified_toolkit.
    response_text = str(pi_response).lower()
    is_accept = "accept" in response_text
    ratified = list(proposed) if is_accept else []

    return {
        "current_phase": "init",
        "current_node": "pi_toolkit_ratify",
        "ratified_toolkit": ratified,
        "batch_review_active": batched,
        "batch_review_payload_size": len(proposed),
        "interrupts": [
            _record_interrupt(
                node_name="pi_toolkit_ratify",
                payload_size=len(proposed),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }


# ---------------------------------------------------------------------------
# 6. pi_credentials_ready — PI signals they've edited .env
# ---------------------------------------------------------------------------


def pi_credentials_ready(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Third PI interrupt — single-tap "I've filled in the .env" gate.

    The draft_manifest_node emits the manifest + env template as
    structured content on decisions_to_present (it does NOT write
    files to disk). This interrupt surfaces the expected secrets so
    the PI's Claude session can render them. The PI saves the .env
    file to their workspace manually.

    On accept, the next node (finalize_node) attempts credential
    probes. The PI's response carries no semantic content beyond
    "I'm done editing".
    """
    proposed = state.get("proposed_toolkit", []) or []

    expected_secrets = []
    for tool_dict in proposed:
        for s in tool_dict.get("secrets") or []:
            expected_secrets.append(
                {
                    "tool": tool_dict.get("name"),
                    "name": s.get("name"),
                    "criticality": s.get("criticality"),
                    "description": s.get("description"),
                }
            )

    project_id = state.get("project_id", "")
    workspace_path = state.get("workspace_path", "")

    # Use PI-provided workspace path if available; otherwise suggest
    # a default the PI can override.
    if workspace_path:
        env_path = f"{workspace_path}/.rka/.env"
    else:
        env_path = f"<your-workspace>/.rka/.env"

    # Also surface the manifest + env template content from
    # decisions_to_present so the PI's Claude session can render them.
    pending = state.get("decisions_to_present") or []
    manifest_items = [d for d in pending if d.get("source_node") == "draft_manifest"]

    payload = {
        "type": "pi_credentials_ready",
        "title": "PI credential entry — save .env to your workspace and accept when ready",
        "prompt": (
            f"The orchestrator has prepared a tools.json manifest and "
            f"an .env template for this project. Save the .env to your "
            f"workspace (suggested: {env_path}), fill in each "
            f"<paste-here> placeholder with the real value, then accept "
            f"this interrupt. Never paste keys into the chat. "
            f"Reject to cancel onboarding."
        ),
        "suggested_env_path": env_path,
        "workspace_path": workspace_path,
        "manifest_content": manifest_items,
        "expected_secrets": expected_secrets,
        "items": [],
        "total_items": 0,
    }
    pi_response = interrupt_fn(payload)

    return {
        "current_phase": "init",
        "current_node": "pi_credentials_ready",
        "interrupts": [
            _record_interrupt(
                node_name="pi_credentials_ready",
                payload_size=len(expected_secrets),
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }


# ---------------------------------------------------------------------------
# Phase B (Bootstrap) PI interrupts — orchestrator-level credential setup
# ---------------------------------------------------------------------------
#
# Phase B is distinct from Phase D: Phase D handles per-project
# credentials (writes ~/rka-projects/<id>/.env); Phase B handles the
# orchestrator daemon's own credentials (writes orchestrator/.env)
# so the daemon can call Claude at all. Three interrupts gate the
# flow: intent capture → ratification → fill ack.


_PI_BOOTSTRAP_INTENT_PROMPT = """\
Welcome to orchestrator bootstrap. Describe your install state in a
short sentence and I'll propose the credentials to set up. Examples:

  - "fresh install on my laptop"
  - "switching from API key to Claude Max OAuth"
  - "I want everything including SerpAPI for web search"
  - "minimal setup, just Claude OAuth"

The orchestrator catalog covers: Claude OAuth (or API key as alternative),
Semantic Scholar (rate-limit boost), SerpAPI (paid web search),
OpenAlex polite-pool email. I'll skip any you don't mention unless they're
required for the orchestrator to run at all.
"""


def pi_bootstrap_intent(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """First Phase B PI interrupt — free-form install-state description.

    The PI session captures the response into state["bootstrap_intent"]
    so the downstream bootstrap_propose node can match it against the
    catalog. Low-stakes (no TWO-TAP) — the ratification happens at
    pi_bootstrap_ratify after the proposal is rendered.
    """
    payload = {
        "type": "pi_bootstrap_intent",
        "title": "PI bootstrap intent — describe your install state",
        "prompt": _PI_BOOTSTRAP_INTENT_PROMPT,
        "items": [],
        "total_items": 0,
    }
    pi_response = interrupt_fn(payload)
    response_str = str(pi_response or "").strip()
    # When PI hits accept with the greenlight token, leave the intent
    # empty -- propose_for_intent then returns the required-and-recommended
    # default set.
    if response_str.lower() in {"approve", "accept", "reject"}:
        intent = ""
    else:
        intent = response_str[:2000]
    return {
        "current_phase": "init",
        "current_node": "pi_bootstrap_intent",
        "bootstrap_intent": intent,
        "interrupts": [
            _record_interrupt(
                node_name="pi_bootstrap_intent",
                payload_size=0,
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }


def pi_bootstrap_ratify(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Second Phase B PI interrupt — ratify the proposed catalog subset.

    Set-identity: ratified_ids is populated iff PI accepts (mirrors
    pi_toolkit_ratify's Phase 2.7 T3d pattern). On accept, every
    proposed id moves into bootstrap_ratified_ids; on reject/correct,
    the list stays empty and the graph routes to END.
    """
    proposed_ids = state.get("bootstrap_proposed_ids", []) or []
    # The propose node also writes a serializable view of the chosen
    # entries onto decisions_to_present so we can surface it here without
    # re-loading the catalog. Tolerant of missing data.
    pending = state.get("decisions_to_present", []) or []
    items = [d for d in pending if d.get("source_node") == "bootstrap_propose"]

    payload, batched = _build_interrupt_payload(
        node_name="pi_bootstrap_ratify",
        items=items,
        title="PI ratification — bootstrap credential shortlist",
    )
    pi_response = interrupt_fn(payload)
    response_text = str(pi_response).lower()
    is_accept = "accept" in response_text or "approve" in response_text
    ratified = list(proposed_ids) if is_accept else []

    remaining = [d for d in pending if d.get("source_node") != "bootstrap_propose"]
    return {
        "current_phase": "init",
        "current_node": "pi_bootstrap_ratify",
        "decisions_to_present": remaining,
        "bootstrap_ratified_ids": ratified,
        "batch_review_active": batched,
        "batch_review_payload_size": len(items),
        "interrupts": [
            _record_interrupt(
                node_name="pi_bootstrap_ratify",
                payload_size=len(items),
                response=pi_response,
                batch_review_used=batched,
            )
        ],
    }


def pi_bootstrap_fill_ack(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    interrupt_fn: Callable[[dict], Any],
) -> dict:
    """Third Phase B PI interrupt — replayable wait for the PI to fill .env.

    Parks with the file path + list of expected env_vars + criticality
    + sign-up URLs. Never surfaces values. On accept, the next node
    (bootstrap_verify) probes each filled key and emits a report.
    On reject, the bootstrap aborts cleanly (the .env.example file
    stays on disk so the PI can resume manually with --continue).
    """
    template_path = state.get("bootstrap_template_path", "") or "orchestrator/.env"
    pending = state.get("decisions_to_present", []) or []
    items = [d for d in pending if d.get("source_node") == "bootstrap_emit_template"]

    payload = {
        "type": "pi_bootstrap_fill_ack",
        "title": "PI fill ack — edit orchestrator/.env then accept",
        "prompt": (
            f"Open {template_path} (file-mode 0600). Replace each "
            f"`<paste-here>` placeholder with the real value, save, "
            "then accept this interrupt. The orchestrator will probe "
            "each filled key without logging the value and report "
            "pass/fail. Reject to abort -- the template file stays "
            "on disk so you can resume later."
        ),
        "template_path": template_path,
        "expected_entries": items,
        "items": [],
        "total_items": 0,
    }
    pi_response = interrupt_fn(payload)

    remaining = [d for d in pending if d.get("source_node") != "bootstrap_emit_template"]
    return {
        "current_phase": "init",
        "current_node": "pi_bootstrap_fill_ack",
        "decisions_to_present": remaining,
        "interrupts": [
            _record_interrupt(
                node_name="pi_bootstrap_fill_ack",
                payload_size=len(items),
                response=pi_response,
                batch_review_used=False,
            )
        ],
    }
