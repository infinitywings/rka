"""Onboarding subgraph nodes (Phase D).

These nodes drive the once-per-project tool-onboarding wizard before
any mission runs. The subgraph topology is wired separately from the
mission graph (graph.py); this module exports the node callables so
graph.py / a future onboarding_graph.py can compose them.

Nodes in this module:
  - intro_node              — Brain greets the PI and surfaces topic-elicitation prompts
  - research_toolkit_node   — Brain reasons about which registry domains apply +
                              optionally augments via web search; produces a candidate
                              toolkit for PI ratification
  - draft_manifest_node     — Materializes the ratified toolkit as a ToolManifest +
                              writes tools.json + a .env template to the workspace dir
  - finalize_node           — Audit-trail journal entry + downstream registration

Companion PI interrupt nodes (parked via interrupt_fn injected by the
subgraph builder) live in nodes/pi.py — added there to keep all
PI-interrupt code colocated.

D3a scope: registry-based research_toolkit_node only. SerpAPI
augmentation lands in D3b as a follow-up.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator import manifest as M
from orchestrator import onboarding_schemas as OS
from orchestrator import tool_registry as TR
from orchestrator import workspace as W
from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.nodes.brain import BRAIN_SYSTEM
from orchestrator.state import ResearchWorkflowState

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# O1.1 — capture_idea_node (system pass-through; loads existing ingested sources)
# ---------------------------------------------------------------------------


def _list_journal_ids_by_tag(
    mcp: MCPClient, *, tags: list[str], limit: int = 200
) -> list[str]:
    """Query RKA for journals carrying every tag in `tags`, return their IDs.

    Defensive over the MCP client's exact return shape — `rka_get_journal`
    returns a list of dicts (REST) or sometimes a dict with `entries`
    (older proxies). We tolerate both.
    """
    try:
        result = mcp.rka_get_journal(tags=tags, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(result, dict):
        entries = result.get("entries") or result.get("results") or []
    elif isinstance(result, list):
        entries = result
    else:
        entries = []
    ids: list[str] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        eid = e.get("id") or e.get("rka_id") or e.get("jrn_id")
        if eid:
            ids.append(str(eid))
    return ids


def capture_idea_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """O1.1 — pre-load context before the pi_idea_capture interrupt.

    No LLM call. Reads state["project_id"] and queries RKA for any
    journals already tagged ``[project_id, "ingested-source"]`` (zero
    for a fresh project; non-zero when PI is onboarding a partially
    populated project — e.g., re-entering Phase O via
    `orchestrator_continue_onboarding`).

    State writes:
      - current_node = "capture_idea"
      - current_phase = "init"  (still onboarding; mission hasn't started)
      - ingested_source_ids — list of jrn_… IDs already in the project
        carrying the 'ingested-source' tag (Phase O design doc).
    """
    project_id = state.get("project_id", "")
    existing_ids: list[str] = []
    if project_id:
        existing_ids = _list_journal_ids_by_tag(
            mcp, tags=[project_id, "ingested-source"]
        )

    return {
        "current_phase": "init",
        "current_node": "capture_idea",
        "ingested_source_ids": existing_ids,
    }


# ---------------------------------------------------------------------------
# O1.2 — idea_polish_node (Brain composes PolishedIdea from PI's free-form idea)
# ---------------------------------------------------------------------------


_IDEA_POLISH_PROMPT_TEMPLATE = """\
You are the Brain composing a structured polish of a PI's research-project
description for an early-onboarding artifact. The PI just finished
ingesting source material and described the project in chat.

Your job: read everything the PI has surfaced about this project and
emit a single JSON object conforming to the PolishedIdea schema below.
Keep each field tight (a sentence to a short paragraph each). Do NOT
invent claims the PI didn't make — when the PI's description is vague
on a field, place a candid placeholder ("(PI did not specify)") rather
than fabricate.

## Project context

PI's free-form description:
{pi_description}

Ingested source summaries (PI-summarized via rka_add_note, tag
'ingested-source'; you should reflect these when composing
novelty_hypothesis and open_assumptions):
{ingested_summaries}

Ingested source IDs (for the schema field):
{ingested_ids}

## PolishedIdea schema

```json
{{
  "research_question":   "one-sentence research question",
  "motivation":          "1 short paragraph on why this matters",
  "scope":               "what's in vs out of scope",
  "novelty_hypothesis":  "what the project claims is new",
  "target_venue":        "venue acronym or null if unspecified",
  "open_assumptions":    ["assumption 1", "assumption 2", ...],
  "ingested_sources":    ["jrn_...", "jrn_..."]
}}
```

## Output

Return a single JSON object inside a ```json fenced block. The block
should be the LAST JSON object in your reply (you may think out loud
before it). All four required string fields
(research_question, motivation, scope, novelty_hypothesis) must be
present + non-empty; lists may be empty. Re-use the ingested source
IDs verbatim — do not invent or paraphrase the IDs.
"""

_IDEA_POLISH_MAX_RETRIES: int = 1
"""On parse failure, retry once with corrective feedback before
recording an ErrorRecord. Matches the Phase 2.5 'one-retry-then-record'
pattern used by mission_execute proposed_actions parsing."""


def _build_idea_polish_prompt(
    *,
    pi_description: str,
    ingested_summaries: list[dict],
    ingested_ids: list[str],
) -> str:
    if not pi_description.strip():
        pi_description = (
            "(PI did not provide a free-form description; rely on the "
            "ingested source summaries below.)"
        )
    if not ingested_summaries:
        summaries_block = "(no sources ingested yet)"
    else:
        lines = []
        for s in ingested_summaries[:20]:  # cap to keep prompt bounded
            sid = s.get("id") or s.get("rka_id") or "<no-id>"
            content = (s.get("content") or "").strip().splitlines()
            preview = "\n    ".join(content[:6]) or "(empty)"
            lines.append(f"  - {sid}:\n    {preview}")
        summaries_block = "\n".join(lines)

    ids_repr = json.dumps(ingested_ids[:50])
    return _IDEA_POLISH_PROMPT_TEMPLATE.format(
        pi_description=pi_description.strip(),
        ingested_summaries=summaries_block,
        ingested_ids=ids_repr,
    )


def _fetch_ingested_summaries(
    mcp: MCPClient, *, project_id: str, ingested_ids: list[str]
) -> list[dict]:
    """Pull the full journal entries for the ingested sources so the
    Brain can read the actual PI-written summaries (not just the IDs).

    Reads via rka_get_journal(tags=[project_id, 'ingested-source']);
    falls back to an empty list on MCP error so idea_polish can still
    run against the PI's description text alone.
    """
    if not project_id or not ingested_ids:
        return []
    try:
        result = mcp.rka_get_journal(
            tags=[project_id, "ingested-source"], limit=200
        )
    except Exception:  # noqa: BLE001
        return []
    if isinstance(result, dict):
        entries = result.get("entries") or result.get("results") or []
    elif isinstance(result, list):
        entries = result
    else:
        entries = []
    # Filter to entries matching the IDs from state (defensive — the
    # tag-filter should already do this, but be conservative).
    wanted = set(ingested_ids)
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        eid = e.get("id") or e.get("rka_id") or e.get("jrn_id")
        if eid and str(eid) in wanted:
            out.append(e)
    return out or [e for e in entries if isinstance(e, dict)]


def idea_polish_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """O1.2 — Brain composes a structured PolishedIdea from the PI's idea text.

    Inputs (state):
      - project_id              — RKA project the polish anchors to.
      - brain_position          — PI's free-form description text (set by
                                  pi_idea_capture on the orchestrator_correct
                                  path; may be empty on the accept-only path).
      - ingested_source_ids     — list of jrn_… (set by pi_idea_capture).

    Behavior:
      1. Fetches the actual ingested-source journal contents via MCP.
      2. Builds the polish prompt + asks Brain for structured JSON.
      3. Parses + validates via PolishedIdea.from_dict; one retry on
         parse failure with corrective feedback; ErrorRecord on
         second failure.
      4. Writes the polished idea to RKA as a journal entry
         (tags=[project_id, 'polished-idea']).
      5. Writes the polished idea + the journal ID back to state.

    State writes:
      - current_node            = "idea_polish"
      - current_phase           = "init"
      - polished_idea           — dict form of PolishedIdea (for downstream
                                  pi_scope_ratify rendering)
      - artifacts               — one ArtifactRef for the polished-idea journal
      - errors                  — populated on terminal parse failure
    """
    project_id = state.get("project_id", "")
    pi_description = state.get("brain_position", "") or ""
    ingested_ids = list(state.get("ingested_source_ids") or [])

    ingested_summaries = _fetch_ingested_summaries(
        mcp, project_id=project_id, ingested_ids=ingested_ids
    )

    base_prompt = _build_idea_polish_prompt(
        pi_description=pi_description,
        ingested_summaries=ingested_summaries,
        ingested_ids=ingested_ids,
    )

    parsed: Optional[OS.PolishedIdea] = None
    last_error_detail: str = ""
    attempt_prompt = base_prompt
    for attempt in range(_IDEA_POLISH_MAX_RETRIES + 1):
        reply = sdk.complete(prompt=attempt_prompt, system=BRAIN_SYSTEM)
        block = OS.extract_json_block(reply)
        if block is None:
            last_error_detail = "no parseable JSON block in Brain reply"
        else:
            try:
                parsed = OS.PolishedIdea.from_dict(block)
                break
            except ValueError as ve:
                last_error_detail = str(ve)
        # Compose corrective feedback for the retry attempt.
        attempt_prompt = (
            base_prompt
            + "\n\n## Parse-retry feedback\n"
            + f"Your previous reply could not be parsed: {last_error_detail}.\n"
            + "Re-emit a single ```json fenced block containing every required "
            + "field as a non-empty string. Required fields: research_question, "
            + "motivation, scope, novelty_hypothesis."
        )

    if parsed is None:
        return {
            "current_phase": "init",
            "current_node": "idea_polish",
            "errors": [
                {
                    "node_name": "idea_polish",
                    "error_type": "idea_polish_parse_failure",
                    "detail": (
                        f"Brain failed to emit valid PolishedIdea JSON after "
                        f"{_IDEA_POLISH_MAX_RETRIES + 1} attempts: {last_error_detail}"
                    ),
                    "timestamp": _now_iso(),
                }
            ],
        }

    # If Brain emitted an empty ingested_sources list, splice in the
    # IDs from state (Brain often forgets to copy them back).
    if not parsed.ingested_sources and ingested_ids:
        parsed.ingested_sources = list(ingested_ids)

    # Persist as a polished-idea journal entry.
    polished_json = json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False)
    try:
        journal_id = mcp.rka_add_note(
            content=polished_json,
            type="note",
            source="brain",
            tags=[project_id, "polished-idea"] if project_id else ["polished-idea"],
        )
    except Exception as e:  # noqa: BLE001
        return {
            "current_phase": "init",
            "current_node": "idea_polish",
            "polished_idea": parsed.to_dict(),
            "errors": [
                {
                    "node_name": "idea_polish",
                    "error_type": "idea_polish_journal_write_failed",
                    "detail": f"rka_add_note raised: {type(e).__name__}: {str(e)[:200]}",
                    "timestamp": _now_iso(),
                }
            ],
        }

    return {
        "current_phase": "init",
        "current_node": "idea_polish",
        "polished_idea": parsed.to_dict(),
        "artifacts": [
            {
                "rka_id": journal_id,
                "entity_type": "journal",
                "node_name": "idea_polish",
                "timestamp": _now_iso(),
            }
        ],
    }


# ---------------------------------------------------------------------------
# O2.1 — workspace_setup_node (mkdir + .rka scaffold; refuse-if-exists path)
# ---------------------------------------------------------------------------


def _project_name_for_slug(
    mcp: MCPClient, *, project_id: str, polished: dict | None
) -> str:
    """Best-effort source for slug derivation.

    Preference order:
      1. The RKA project's name (rka_get_status / rka_get_context),
         since that's the canonical handle PI's already chosen.
      2. The polished idea's research_question (truncated to a
         keyword-rich slug).
      3. The bare project_id (always present; produces 'prj-…').
    """
    if not project_id:
        return ""

    # Try the RKA project metadata first.
    try:
        status = mcp.rka_get_status()
        if isinstance(status, dict):
            for key in ("project_name", "name", "title"):
                v = status.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except Exception:  # noqa: BLE001
        pass

    if polished:
        rq = polished.get("research_question") if isinstance(polished, dict) else None
        if isinstance(rq, str) and rq.strip():
            return rq.strip()

    return project_id  # last-resort fallback


def workspace_setup_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """O2.1 — Validate the PI's workspace path (ask-not-create pattern).

    The orchestrator does NOT create directories on the host filesystem.
    Instead, this node validates that a workspace path exists and records
    it in state. The PI provides the path in one of two ways:

      1. Set `workspace_path` in state before this node runs (e.g., via
         the pi_scope_ratify response: "my workspace is at /path/to/...").
      2. If workspace_path is empty, the node derives a suggested path
         from the project slug and emits a checkpoint asking the PI to
         either create that directory or provide an alternative.

    This eliminates the Docker bind-mount requirement: the orchestrator
    container never writes to the host filesystem.

    Inputs (state):
      - project_id            — RKA project ID (required).
      - workspace_path        — PI-provided path (if set, validated).
      - project_slug          — explicit slug, if PI provided one.
      - polished_idea         — fallback for slug derivation.

    State writes:
      - current_node      = "workspace_setup"
      - project_slug      — the slug used.
      - workspace_path    — validated absolute path.
    """
    project_id = state.get("project_id", "")
    if not project_id:
        return {
            "current_phase": "init",
            "current_node": "workspace_setup",
            "errors": [
                {
                    "node_name": "workspace_setup",
                    "error_type": "workspace_setup_no_project_id",
                    "detail": (
                        "workspace_setup_node requires state['project_id'] to "
                        "be set; cannot derive a slug or place the workspace."
                    ),
                    "timestamp": _now_iso(),
                }
            ],
        }

    # If PI already provided a workspace_path, validate it exists.
    explicit_path = state.get("workspace_path", "").strip()
    if explicit_path:
        from pathlib import Path
        p = Path(explicit_path)
        if p.is_dir():
            # Derive slug from the directory name for downstream use.
            slug = p.name
            return {
                "current_phase": "init",
                "current_node": "workspace_setup",
                "project_slug": slug,
                "workspace_path": str(p.resolve()),
            }
        else:
            chk_id = f"chk_workspace_missing_{int(datetime.now(tz=timezone.utc).timestamp())}"
            return {
                "current_phase": "init",
                "current_node": "workspace_setup",
                "workspace_path": explicit_path,
                "checkpoints": [
                    {
                        "chk_id": chk_id,
                        "type": "decision",
                        "reason": (
                            f"workspace path '{explicit_path}' does not exist. "
                            f"Create the directory, then re-run workspace_setup "
                            f"(the orchestrator does not create directories on "
                            f"the host filesystem)."
                        ),
                        "resolved": False,
                    }
                ],
            }

    # No explicit path: derive a suggestion from the project name/slug.
    explicit_slug = state.get("project_slug", "")
    polished = state.get("polished_idea") or None

    if explicit_slug:
        slug_candidate = explicit_slug
    else:
        source_name = _project_name_for_slug(
            mcp, project_id=project_id, polished=polished
        )
        try:
            slug_candidate = W.derive_slug_from_name(source_name)
        except ValueError as ve:
            return {
                "current_phase": "init",
                "current_node": "workspace_setup",
                "errors": [
                    {
                        "node_name": "workspace_setup",
                        "error_type": "workspace_setup_slug_derivation_failed",
                        "detail": (
                            f"Could not derive a valid slug from "
                            f"{source_name!r}: {ve}"
                        ),
                        "timestamp": _now_iso(),
                    }
                ],
            }

    # Suggest a path and emit a checkpoint so the PI creates it.
    suggested_path = W.project_workspace(slug_candidate)
    chk_id = f"chk_workspace_needed_{int(datetime.now(tz=timezone.utc).timestamp())}"
    return {
        "current_phase": "init",
        "current_node": "workspace_setup",
        "project_slug": slug_candidate,
        "workspace_path": str(suggested_path),
        "checkpoints": [
            {
                "chk_id": chk_id,
                "type": "decision",
                "reason": (
                    f"Create your project workspace directory, then provide "
                    f"the path. Suggested: '{suggested_path}'. You can also "
                    f"use any existing folder. Set workspace_path in state "
                    f"and re-run workspace_setup."
                ),
                "resolved": False,
            }
        ],
    }


# ---------------------------------------------------------------------------
# O3.1 — hygiene_pass_node (integrity + freshness + pending-maintenance)
# ---------------------------------------------------------------------------


_HYGIENE_FRESHNESS_DAYS_THRESHOLD: int = 30
"""Default staleness threshold for the freshness check during Phase O
hygiene (in days). Brain reads the same value as RKA's default."""


def _normalize_integrity_findings(raw: dict | None) -> list[dict]:
    """Pull issue rows from rka_check_integrity's response.

    Response shape (from rka/services/knowledge_pack:check_integrity):
        {"total_issues": N, "issues": [{"type": ..., "count": N, "entries": [...]}, ...]}

    We flatten to one finding per entry so downstream PI rendering /
    checkpoint emission can target individual targets.
    """
    if not isinstance(raw, dict):
        return []
    issues = raw.get("issues") or []
    out: list[dict] = []
    for group in issues if isinstance(issues, list) else []:
        if not isinstance(group, dict):
            continue
        kind = group.get("type") or "integrity_issue"
        entries = group.get("entries") or []
        if not isinstance(entries, list) or not entries:
            # Some integrity groups carry just a count + no entries —
            # surface as a single bucketed finding.
            out.append(
                {
                    "kind": f"integrity:{kind}",
                    "target_id": None,
                    "detail": group.get("description") or f"{kind} ({group.get('count', '?')})",
                    "severity": group.get("severity") or "info",
                }
            )
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            out.append(
                {
                    "kind": f"integrity:{kind}",
                    "target_id": e.get("id") or e.get("entity_id"),
                    "detail": e.get("detail") or e.get("description") or kind,
                    "severity": group.get("severity") or e.get("severity") or "info",
                }
            )
    return out


def _normalize_freshness_findings(raw: dict | None) -> list[dict]:
    """Pull stale-entry rows from rka_check_freshness's response.

    Response shape varies by RKA version; tolerate either a top-level
    list under 'stale_entries' or under 'entries'.
    """
    if not isinstance(raw, dict):
        return []
    entries = raw.get("stale_entries") or raw.get("entries") or []
    if not isinstance(entries, list):
        return []
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        out.append(
            {
                "kind": "freshness:stale",
                "target_id": e.get("id") or e.get("entity_id"),
                "detail": (
                    e.get("reason")
                    or e.get("detail")
                    or f"stale (age: {e.get('days_since_update', '?')}d)"
                ),
                "severity": e.get("severity") or "info",
            }
        )
    return out


def _normalize_pending_maintenance(raw: dict | None) -> list[dict]:
    """Pull pending-maintenance items.

    Response shape (from rka/api/routes/maintenance.py):
        {"items": [{"id": ..., "kind": ..., "detail": ..., "required": bool}, ...]}
    """
    if not isinstance(raw, dict):
        return []
    items = raw.get("items") or raw.get("pending") or []
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "kind": f"maintenance:{it.get('kind', 'pending')}",
                "target_id": it.get("id") or it.get("target_id"),
                "detail": it.get("detail") or it.get("description") or it.get("kind", ""),
                "severity": "required" if it.get("required") else "info",
            }
        )
    return out


def hygiene_pass_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Phase O O3.1 — pre-plan hygiene sweep over the project's RKA state.

    No LLM call. Aggregates findings from three RKA tools:
      - rka_check_integrity()          — orphan refs, broken provenance
      - rka_check_freshness()          — stale entries
      - rka_get_pending_maintenance()  — auto-flagged maintenance items

    Each finding is normalized to a 4-field dict (kind, target_id,
    detail, severity) and accumulated on state["hygiene_findings"].

    If any finding has severity='required', a checkpoint is emitted so
    PI must resolve before O4 plan synthesis. Otherwise the workflow
    proceeds straight to claim_extraction.

    State writes:
      - current_node     = "hygiene_pass"
      - current_phase    = "init"
      - hygiene_findings — list of finding dicts
      - checkpoints      — only when required-severity items exist
    """
    findings: list[dict] = []
    try:
        integrity = mcp.rka_check_integrity()
    except Exception:  # noqa: BLE001
        integrity = None
    findings.extend(_normalize_integrity_findings(integrity))

    try:
        freshness = mcp.rka_check_freshness(_HYGIENE_FRESHNESS_DAYS_THRESHOLD)
    except Exception:  # noqa: BLE001
        freshness = None
    findings.extend(_normalize_freshness_findings(freshness))

    try:
        maintenance = mcp.rka_get_pending_maintenance()
    except Exception:  # noqa: BLE001
        maintenance = None
    findings.extend(_normalize_pending_maintenance(maintenance))

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "hygiene_pass",
        "hygiene_findings": findings,
    }

    required = [f for f in findings if f.get("severity") == "required"]
    if required:
        update["checkpoints"] = [
            {
                "chk_id": f"chk_hygiene_required_{int(datetime.now(tz=timezone.utc).timestamp())}",
                "type": "decision",
                "reason": (
                    f"Phase O hygiene pass found {len(required)} required "
                    f"maintenance item(s) that must be resolved before plan "
                    f"synthesis. Summary: "
                    + "; ".join(
                        f"{f['kind']}={f['target_id'] or '?'}"
                        for f in required[:10]
                    )
                    + (" …" if len(required) > 10 else "")
                ),
                "resolved": False,
            }
        ]

    return update


# ---------------------------------------------------------------------------
# O3.2 — claim_extraction_node (Brain → atomic claims per project journal)
# ---------------------------------------------------------------------------


_CLAIM_EXTRACTION_TAGS: tuple[str, ...] = (
    "polished-idea",
    "ingested-source",
    "literature",
    "deep-research-finding",
)
"""Phase O tag categories whose journals seed claim extraction at O3.2.
Order is the rendering order in the prompt (polish first, then sources,
then literature, then framing notes)."""

_CLAIM_TYPES = ("hypothesis", "evidence", "method", "result", "observation", "assumption")

_CLAIM_EXTRACTION_PROMPT_TEMPLATE = """\
You are the Brain extracting atomic claims from one of a project's
journal entries during Phase O hygiene + extraction. Each claim
becomes provenance for the research plan that will be synthesized at
O4 and ratified by PI.

## Journal entry

Entry ID: {entry_id}
Tags:     {tags}
Source:   {source}

Content:
{content}

## Task

Identify atomic claims supported by the entry. An "atomic" claim is
one assertion that could be verified or falsified independently — not
a paragraph, not a list of related observations bundled together.

For each claim emit:

  - "claim_type": one of {claim_types}
  - "content":    the atomic claim text (a single sentence preferred)
  - "confidence": 0.0–1.0 — your prior on how supported this claim is

Aim for 1–5 claims per entry. Empty list is valid if the entry has no
extractable claims (e.g., pure metadata, low-information notes).

## Output

Emit a single JSON object inside a ```json fenced block:

```json
{{
  "claims": [
    {{"claim_type": "...", "content": "...", "confidence": 0.0}},
    ...
  ]
}}
```

The block should be the LAST JSON object in your reply.
"""


def _journals_for_claim_extraction(
    mcp: MCPClient, *, project_id: str
) -> list[dict]:
    """Pull every journal tagged ``[project_id, X]`` for each
    X in _CLAIM_EXTRACTION_TAGS. Deduplicates by entry ID.

    The MCPClient's rka_get_journal returns notes carrying all
    requested tags; we call it once per category and union the
    results.
    """
    if not project_id:
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for category in _CLAIM_EXTRACTION_TAGS:
        try:
            result = mcp.rka_get_journal(
                tags=[project_id, category], limit=200
            )
        except Exception:  # noqa: BLE001
            continue
        if isinstance(result, dict):
            entries = result.get("entries") or result.get("results") or []
        elif isinstance(result, list):
            entries = result
        else:
            entries = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            eid = e.get("id") or e.get("rka_id") or e.get("jrn_id")
            if not eid or str(eid) in seen:
                continue
            seen.add(str(eid))
            # Stash the category tag we pulled it under so the prompt
            # can show provenance order.
            e.setdefault("_phase_o_tag", category)
            out.append(e)
    return out


def _build_claim_extraction_prompt(entry: dict) -> str:
    return _CLAIM_EXTRACTION_PROMPT_TEMPLATE.format(
        entry_id=entry.get("id") or entry.get("rka_id") or "(unknown)",
        tags=", ".join(entry.get("tags") or []) or "(none)",
        source=entry.get("source") or "(unknown)",
        content=(entry.get("content") or "").strip()[:4000],
        claim_types=", ".join(f'"{t}"' for t in _CLAIM_TYPES),
    )


def _parse_claims_reply(reply: str) -> list[dict]:
    """Pull the claims array from a Brain reply. Each item must have
    claim_type + content; confidence defaults to 0.5 if missing or
    out of [0,1]. Filters out malformed entries silently."""
    block = OS.extract_json_block(reply or "")
    if not isinstance(block, dict):
        return []
    raw = block.get("claims")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        ct = c.get("claim_type")
        content = c.get("content")
        if not ct or not isinstance(content, str) or not content.strip():
            continue
        if ct not in _CLAIM_TYPES:
            # Forgive lowercase / case variants by lowering and re-checking.
            ct_norm = ct.lower() if isinstance(ct, str) else ""
            if ct_norm in _CLAIM_TYPES:
                ct = ct_norm
            else:
                continue
        try:
            conf = float(c.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        if not (0.0 <= conf <= 1.0):
            conf = 0.5
        out.append({"claim_type": ct, "content": content.strip(), "confidence": conf})
    return out


def claim_extraction_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Phase O O3.2 — Brain extracts atomic claims from every project journal.

    Algorithm:
      1. Pull every journal carrying ``[project_id, X]`` for X in
         (polished-idea, ingested-source, literature, deep-research-finding).
         Dedup by entry ID.
      2. For each journal, ask the Brain to identify atomic claims as
         structured JSON (1–5 per entry; empty list is valid).
      3. Submit each parsed claim via mcp.rka_create_claim and
         accumulate the resulting clm_… IDs on state["claim_ids"].
      4. Surface per-journal failures as ErrorRecord entries — the
         pipeline keeps going so a flaky LLM call on one journal
         doesn't lose the others.

    State writes:
      - current_node  = "claim_extraction"
      - current_phase = "init"
      - claim_ids     — list of clm_… IDs (in journal-iteration order)
      - errors        — populated only when at least one journal failed
    """
    project_id = state.get("project_id", "")
    if not project_id:
        return {
            "current_phase": "init",
            "current_node": "claim_extraction",
            "claim_ids": [],
            "errors": [
                {
                    "node_name": "claim_extraction",
                    "error_type": "claim_extraction_no_project_id",
                    "detail": "claim_extraction_node requires state['project_id']",
                    "timestamp": _now_iso(),
                }
            ],
        }

    journals = _journals_for_claim_extraction(mcp, project_id=project_id)
    claim_ids: list[str] = []
    errors: list[dict] = []

    for entry in journals:
        eid = entry.get("id") or entry.get("rka_id") or ""
        if not eid:
            continue
        prompt = _build_claim_extraction_prompt(entry)
        try:
            reply = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)
        except Exception as e:  # noqa: BLE001
            errors.append(
                {
                    "node_name": "claim_extraction",
                    "error_type": "claim_extraction_llm_failed",
                    "detail": (
                        f"Brain.complete raised on entry {eid}: "
                        f"{type(e).__name__}: {str(e)[:200]}"
                    ),
                    "timestamp": _now_iso(),
                }
            )
            continue

        parsed = _parse_claims_reply(reply)
        if not parsed:
            # Empty list is a valid Brain output (entry has no extractable
            # claims). Don't surface as error.
            continue

        for c in parsed:
            try:
                clm_id = mcp.rka_create_claim(
                    source_entry_id=eid,
                    claim_type=c["claim_type"],
                    content=c["content"],
                    confidence=c["confidence"],
                )
            except Exception as e:  # noqa: BLE001
                errors.append(
                    {
                        "node_name": "claim_extraction",
                        "error_type": "claim_extraction_write_failed",
                        "detail": (
                            f"rka_create_claim raised on entry {eid}: "
                            f"{type(e).__name__}: {str(e)[:200]}"
                        ),
                        "timestamp": _now_iso(),
                    }
                )
                continue
            if clm_id:
                claim_ids.append(clm_id)

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "claim_extraction",
        "claim_ids": claim_ids,
    }
    if errors:
        update["errors"] = errors
    return update


# ---------------------------------------------------------------------------
# O4.1 — plan_synthesis_node (Brain composes the ResearchPlan)
# ---------------------------------------------------------------------------


_PLAN_SYNTHESIS_MAX_RETRIES: int = 1
"""One retry on parse failure with corrective feedback before ErrorRecord.
Same pattern as idea_polish_node + executor.mission_execute."""

_PLAN_SYNTHESIS_PROMPT_TEMPLATE = """\
You are the Brain synthesizing the project's research plan during Phase O4.
This plan, once ratified by PI, becomes THE contract licensing autonomous
mission execution at Phase H. Be specific. Be falsifiable. Don't pad.

## Project context

Polished idea (from O1.2):
{polished_idea_block}

Polished-idea journal ID: {polished_idea_journal_id}

Literature gaps + finding count summary:
{literature_summary}

Extracted claims summary ({claim_count} total):
{claims_summary}

Open hygiene findings ({hygiene_count}):
{hygiene_summary}

## ResearchPlan schema

```json
{{
  "refined_research_question": "one-sentence refined RQ",
  "hypotheses": [
    {{
      "statement":  "atomic hypothesis statement",
      "falsifier":  "what would refute it (the falsifier MUST be measurable)",
      "confidence": "high" | "medium" | "low"
    }}
  ],
  "variables": [
    {{
      "name":        "variable name",
      "kind":        "independent" | "dependent" | "confound",
      "description": "what this variable captures",
      "measurement": "how it's measured (or null)"
    }}
  ],
  "experimental_matrix": "markdown table OR structured description of the experiment design",
  "literature_gaps": ["gap 1", "gap 2", ...],
  "milestones": [
    {{
      "milestone_id":              "m_01" (matches ^m_\\d{{2,4}}$),
      "phase":                     "literature" | "research_design" | "experiment_design"
                                  | "experiment_execution" | "analysis" | "writeup",
      "objective":                 "one-sentence objective for this mission",
      "acceptance_criteria":       "what 'done' looks like — checkable",
      "scope_boundaries":          "what's out of scope for this mission",
      "depends_on_milestone":      "m_01" (or null for the first mission),
      "estimated_llm_cost_usd":    0.50,
      "estimated_wall_clock_min":  45
    }}
  ],
  "open_risks": ["risk 1", "risk 2", ...],
  "polished_idea_journal_id": "{polished_idea_journal_id}"
}}
```

## Output

Return a single ```json fenced block. Required:
  - 1+ hypotheses, each with statement + falsifier + confidence
  - 1+ variables, each with name + kind + description
  - 1+ milestones with valid milestone_id, phase, and acceptance_criteria
  - experimental_matrix non-empty
  - polished_idea_journal_id verbatim from the prompt above
  - depends_on_milestone (when set) must reference an existing milestone_id

milestone_id values must follow the format ``m_<digits>`` (e.g., m_01).
Cost + wall-clock estimates may be rough — display them as "estimated";
the orchestrator will track actual usage downstream. Empty
literature_gaps / open_risks lists are valid.
"""


def _render_polished_idea_block_for_plan(polished: dict | None) -> str:
    if not isinstance(polished, dict) or not polished:
        return "(none — Brain should ask PI to re-run O1 idea capture)"
    lines = [
        f"RQ: {polished.get('research_question', '(unspecified)')}",
        f"Motivation: {polished.get('motivation', '(unspecified)')}",
        f"Scope: {polished.get('scope', '(unspecified)')}",
        f"Novelty: {polished.get('novelty_hypothesis', '(unspecified)')}",
        f"Target venue: {polished.get('target_venue') or '(unspecified)'}",
    ]
    assumptions = polished.get("open_assumptions") or []
    if assumptions:
        lines.append("Open assumptions: " + "; ".join(assumptions))
    return "\n".join(lines)


def _render_literature_summary(literature: list[dict] | None) -> str:
    if not literature:
        return "(no literature ingested at O2 — Brain may need to ask PI to extend)"
    titles = []
    for e in literature[:10]:
        if not isinstance(e, dict):
            continue
        title = e.get("title") or e.get("content", "")[:120] or "(untitled)"
        titles.append(f"  - {title}")
    out = f"{len(literature)} literature entries; first 10 by title:\n" + "\n".join(titles)
    if len(literature) > 10:
        out += f"\n  ... and {len(literature) - 10} more."
    return out


def _render_claims_summary(claims: list[dict] | None) -> str:
    if not claims:
        return "(no claims extracted at O3.2)"
    lines = []
    for c in claims[:15]:
        if not isinstance(c, dict):
            continue
        ct = c.get("claim_type") or "(type?)"
        content = (c.get("content") or "").strip()[:200]
        lines.append(f"  - [{ct}] {content}")
    suffix = f"\n  ... and {len(claims) - 15} more." if len(claims) > 15 else ""
    return f"First 15:\n" + "\n".join(lines) + suffix


def _render_hygiene_summary(hygiene: list[dict] | None) -> str:
    if not hygiene:
        return "(none — RKA hygiene is clean)"
    by_kind: dict[str, int] = {}
    for f in hygiene:
        if not isinstance(f, dict):
            continue
        by_kind[f.get("kind") or "?"] = by_kind.get(f.get("kind") or "?", 0) + 1
    return "; ".join(f"{k}: {v}" for k, v in by_kind.items())


def plan_synthesis_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Phase O4.1 — Brain produces the structured ResearchPlan.

    Inputs (state):
      - project_id            — required.
      - polished_idea         — from O1.2.
      - claim_ids             — from O3.2; we fetch the claim entities
                                via rka_list_claims for context.
      - hygiene_findings      — from O3.1 (informational; surfaces in
                                prompt context).

    Behavior:
      1. Find the polished-idea journal ID (preferred via state's
         artifacts, fallback to a tag query).
      2. Fetch:
           - literature journals (tag query)
           - claims (rka_list_claims; client-side filter when needed)
           - hygiene findings (already on state).
      3. Compose the plan prompt + call Brain.
      4. Parse + validate via ResearchPlan.from_dict.
         One retry on failure with corrective feedback; ErrorRecord
         on second failure.
      5. Persist the validated plan as a journal entry
         (tags=[project_id, 'ratified-plan-draft']) for pi_plan_ratify
         (O4.2) to read.
      6. Write state[ratified_plan_journal_id, ...] (the journal is a
         DRAFT — actual ratification dec_… lands in O4.2 on accept).
    """
    project_id = state.get("project_id", "")
    if not project_id:
        return {
            "current_phase": "init",
            "current_node": "plan_synthesis",
            "errors": [
                {
                    "node_name": "plan_synthesis",
                    "error_type": "plan_synthesis_no_project_id",
                    "detail": "plan_synthesis_node requires state['project_id']",
                    "timestamp": _now_iso(),
                }
            ],
        }

    polished = state.get("polished_idea") or {}

    # Find the polished-idea journal ID.
    polished_journal_id = ""
    for art in state.get("artifacts") or []:
        if isinstance(art, dict) and art.get("node_name") == "idea_polish":
            polished_journal_id = art.get("rka_id") or ""
            break
    if not polished_journal_id:
        # Tag-query fallback.
        ids = _list_journal_ids_by_tag(mcp, tags=[project_id, "polished-idea"], limit=10)
        polished_journal_id = ids[-1] if ids else ""

    # Literature for context.
    try:
        literature = mcp.rka_get_journal(tags=[project_id, "literature"], limit=200)
    except Exception:  # noqa: BLE001
        literature = []
    if isinstance(literature, dict):
        literature = literature.get("entries") or literature.get("results") or []
    if not isinstance(literature, list):
        literature = []

    # Claims for context.
    claim_ids = list(state.get("claim_ids") or [])
    try:
        all_claims = mcp.rka_list_claims(limit=200)
    except Exception:  # noqa: BLE001
        all_claims = []
    if not isinstance(all_claims, list):
        all_claims = []
    if claim_ids:
        wanted = set(claim_ids)
        claims = [
            c for c in all_claims
            if isinstance(c, dict)
            and (c.get("id") or c.get("clm_id")) in wanted
        ]
    else:
        claims = all_claims

    hygiene = state.get("hygiene_findings") or []

    base_prompt = _PLAN_SYNTHESIS_PROMPT_TEMPLATE.format(
        polished_idea_block=_render_polished_idea_block_for_plan(polished),
        polished_idea_journal_id=polished_journal_id or "(unknown)",
        literature_summary=_render_literature_summary(literature),
        claim_count=len(claims),
        claims_summary=_render_claims_summary(claims),
        hygiene_count=len(hygiene),
        hygiene_summary=_render_hygiene_summary(hygiene),
    )

    parsed: Optional[OS.ResearchPlan] = None
    last_error_detail: str = ""
    attempt_prompt = base_prompt
    for attempt in range(_PLAN_SYNTHESIS_MAX_RETRIES + 1):
        reply = sdk.complete(prompt=attempt_prompt, system=BRAIN_SYSTEM)
        block = OS.extract_json_block(reply)
        if block is None:
            last_error_detail = "no parseable JSON block in Brain reply"
        else:
            try:
                parsed = OS.ResearchPlan.from_dict(block)
                break
            except ValueError as ve:
                last_error_detail = str(ve)
        attempt_prompt = (
            base_prompt
            + "\n\n## Parse-retry feedback\n"
            + f"Your previous reply could not be parsed: {last_error_detail}.\n"
            + "Re-emit a single ```json fenced block strictly conforming to "
            + "the ResearchPlan schema above. Required: 1+ hypotheses, "
            + "1+ variables, 1+ milestones, valid milestone_id pattern, "
            + "and every depends_on_milestone must reference an existing "
            + "milestone_id."
        )

    if parsed is None:
        return {
            "current_phase": "init",
            "current_node": "plan_synthesis",
            "errors": [
                {
                    "node_name": "plan_synthesis",
                    "error_type": "plan_synthesis_parse_failure",
                    "detail": (
                        f"Brain failed to emit valid ResearchPlan JSON after "
                        f"{_PLAN_SYNTHESIS_MAX_RETRIES + 1} attempts: {last_error_detail}"
                    ),
                    "timestamp": _now_iso(),
                }
            ],
        }

    # If Brain dropped the polished_idea_journal_id, splice it back.
    if not parsed.polished_idea_journal_id and polished_journal_id:
        parsed.polished_idea_journal_id = polished_journal_id

    plan_json = json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False)
    try:
        journal_id = mcp.rka_add_note(
            content=plan_json,
            type="note",
            source="brain",
            tags=[project_id, "ratified-plan-draft"],
        )
    except Exception as e:  # noqa: BLE001
        return {
            "current_phase": "init",
            "current_node": "plan_synthesis",
            "errors": [
                {
                    "node_name": "plan_synthesis",
                    "error_type": "plan_synthesis_journal_write_failed",
                    "detail": f"rka_add_note raised: {type(e).__name__}: {str(e)[:200]}",
                    "timestamp": _now_iso(),
                }
            ],
        }

    return {
        "current_phase": "init",
        "current_node": "plan_synthesis",
        "ratified_plan_journal_id": journal_id,
        "artifacts": [
            {
                "rka_id": journal_id,
                "entity_type": "journal",
                "node_name": "plan_synthesis",
                "timestamp": _now_iso(),
            }
        ],
    }


# ---------------------------------------------------------------------------
# D3a — research_toolkit_node (registry-based + Brain LLM scoring)
# ---------------------------------------------------------------------------

_RESEARCH_TOOLKIT_PROMPT_TEMPLATE = """\
You are scoring a toolkit for a new RKA-managed research project. The
project's PI has just completed the topic-elicitation interrupt; you
have their topic, field, and target venue below.

Your job: pick which registry domains apply, score the registry's
suggested tools for relevance, and propose any custom tools the PI
should consider beyond the registry's defaults.

## Project topic
Summary: {topic_summary}
Field: {topic_field}
Venue: {topic_venue}
Keywords: {topic_keywords}

## Always-on tools (auto-included; no decision needed)
{always_on_block}

## Registry domain catalog (pick which apply)
{domain_catalog_block}

## Per-domain tool shortlists (for the domains you pick)
{domain_tools_block}

## Web-discovered candidates (SerpAPI search; may be empty)
{serpapi_block}

## Output

Return a single JSON object with three fields:

  "selected_domains": list of domain keys you judge relevant to this
                      project's topic/field. Empty list is valid if no
                      domain shortlist is a fit.
  "scored_tools": list of objects describing each candidate tool, in
                  the order the PI should consider them:
                    - "name": tool name
                    - "source": "registry" if from the registry domain
                                shortlists, "user_added" if you're
                                proposing a tool not in any shortlist
                    - "rationale": one or two sentences on why this tool
                                   fits this project
                    - "confidence": "high" | "medium" | "low" — your
                                    confidence the tool is the right
                                    pick and well-maintained
                    - "criticality_suggested": "required" | "recommended"
                                               | "optional" — your prior
                                               on how essential the tool
                                               is; PI ratifies
  "notes_for_pi": one paragraph of free text summarizing your reasoning,
                  flagging any tools where the project's needs aren't
                  fully covered by the registry.

Wrap the JSON in a fenced ```json block. Always emit valid JSON — if
unsure, prefer leaving "scored_tools" empty over emitting malformed
output (the dispatcher's conservative-malformed-input default treats
parse failures as "no candidates"). When a candidate originated from the
SerpAPI web-discovery block, set `"source": "serpapi_augmented"` so the
PI can apply extra scrutiny at ratification time.
"""


# Phase D3b — SerpAPI web-discovery augmentation
# --------------------------------------------------------------------------
# When SERPAPI_KEY is present in the parent process env, augment the
# registry-based candidate pool by querying SerpAPI for MCP servers /
# research tools matching the project's topic keywords. The hits are
# rendered into a "Web-discovered candidates" block so Brain can score
# them alongside registry entries. SerpAPI failures are fail-silent: the
# registry pipeline always succeeds and is the source of truth; SerpAPI
# is strictly additive.

_SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
_SERPAPI_MAX_HITS = 6
_SERPAPI_TIMEOUT_SECONDS = 6.0


def _serpapi_augment_candidates(
    topic: dict | None,
    *,
    http_client: Any = None,
    api_key_env: str = "SERPAPI_KEY",
) -> list[dict]:
    """Query SerpAPI for additional candidate tools/MCP servers.

    Returns a list of hint dicts: `[{"name": ..., "url": ..., "snippet": ...}]`.
    Returns an empty list on any failure (no API key, network error, bad
    response, etc.) — the caller treats an empty list as "no augmentation".
    Tested via `http_client` injection.
    """
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        return []
    if not isinstance(topic, dict):
        return []

    keywords = topic.get("keywords") or []
    field = (topic.get("research_field") or "").strip()
    summary = (topic.get("summary") or "").strip()
    # Build a focused query — preference for MCP-server discovery since
    # that's the registry's primary scope.
    parts: list[str] = []
    if isinstance(keywords, list) and keywords:
        parts.extend(str(k) for k in keywords[:3] if k)
    if field:
        parts.append(field)
    if not parts and summary:
        parts.append(summary[:80])
    if not parts:
        return []
    query = " ".join(parts) + " MCP server OR research tool"

    try:
        if http_client is None:
            import httpx  # local import keeps package import cheap

            http_client = httpx.Client(timeout=_SERPAPI_TIMEOUT_SECONDS)
        resp = http_client.get(
            _SERPAPI_ENDPOINT,
            params={
                "q": query,
                "api_key": api_key,
                "engine": "google",
                "num": _SERPAPI_MAX_HITS,
            },
        )
        if getattr(resp, "status_code", 0) != 200:
            return []
        body = resp.json() if callable(getattr(resp, "json", None)) else {}
    except Exception:  # noqa: BLE001 — fail-silent by design
        return []

    organic = body.get("organic_results") if isinstance(body, dict) else None
    if not isinstance(organic, list):
        return []

    hits: list[dict] = []
    for h in organic[:_SERPAPI_MAX_HITS]:
        if not isinstance(h, dict):
            continue
        title = (h.get("title") or "").strip()
        link = (h.get("link") or "").strip()
        snippet = (h.get("snippet") or "").strip()
        if not title:
            continue
        hits.append({"name": title[:120], "url": link[:240], "snippet": snippet[:240]})
    return hits


def _render_serpapi_block(hits: list[dict]) -> str:
    if not hits:
        return "(none — SERPAPI_KEY unset, search returned no results, or augmentation disabled)"
    lines = []
    for h in hits:
        url = h.get("url") or ""
        url_suffix = f"  [{url}]" if url else ""
        lines.append(f"  - {h.get('name', '?')}{url_suffix}")
        snip = (h.get("snippet") or "").strip()
        if snip:
            lines.append(f"    snippet: {snip}")
    return "\n".join(lines)


def _build_research_toolkit_prompt(
    state: ResearchWorkflowState,
    *,
    always_on: list[M.ToolDecl],
    domain_catalog: dict[str, str],
    domain_tools: dict[str, list[M.ToolDecl]],
    serpapi_hits: list[dict] | None = None,
) -> str:
    topic = state.get("topic_metadata") or {}
    return _RESEARCH_TOOLKIT_PROMPT_TEMPLATE.format(
        topic_summary=topic.get("summary") or "(none — PI did not provide a topic)",
        topic_field=topic.get("research_field") or "(unspecified)",
        topic_venue=topic.get("venue") or "(unspecified)",
        topic_keywords=", ".join(topic.get("keywords") or []) or "(none)",
        always_on_block=_render_tools_block(always_on),
        domain_catalog_block=_render_domain_catalog(domain_catalog),
        domain_tools_block=_render_domain_tools(domain_tools),
        serpapi_block=_render_serpapi_block(serpapi_hits or []),
    )


def _render_tools_block(tools: list[M.ToolDecl]) -> str:
    if not tools:
        return "(none)"
    lines = []
    for t in tools:
        secrets = ", ".join(s.name for s in t.secrets) or "no credentials"
        rationale = (t.rationale or "").splitlines()[0] if t.rationale else ""
        lines.append(f"  - {t.name}: {rationale} (secrets: {secrets})")
    return "\n".join(lines)


def _render_domain_catalog(catalog: dict[str, str]) -> str:
    if not catalog:
        return "(none)"
    lines = []
    for k, v in catalog.items():
        desc = (v or "").strip().splitlines()[0] if v else ""
        lines.append(f"  - {k}: {desc}")
    return "\n".join(lines)


def _render_domain_tools(domain_tools: dict[str, list[M.ToolDecl]]) -> str:
    if not domain_tools:
        return "(none — no domain shortlists loaded)"
    sections = []
    for domain, tools in domain_tools.items():
        sections.append(f"### {domain}")
        sections.append(_render_tools_block(tools))
    return "\n".join(sections)


# Fenced ```json … ``` block matching the same convention the executor
# uses for proposed_actions parsing (see _parse_proposed_actions in
# nodes/executor.py).
_JSON_FENCED_PATTERN = re.compile(
    r"```json\s*\n(.+?)\n```", re.DOTALL | re.IGNORECASE
)


def _parse_brain_toolkit_reply(reply: str) -> dict:
    """Extract the ```json…``` block and parse it. On any malformation,
    return an empty proposal — the conservative-malformed-input default
    (Phase 2.5 Delta #7) applies here too."""
    match = _JSON_FENCED_PATTERN.search(reply or "")
    if not match:
        return {
            "selected_domains": [],
            "scored_tools": [],
            "notes_for_pi": "(parse failure: Brain reply missing ```json block)",
            "_parse_error": True,
        }
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        return {
            "selected_domains": [],
            "scored_tools": [],
            "notes_for_pi": f"(parse failure: {e})",
            "_parse_error": True,
        }
    if not isinstance(parsed, dict):
        return {
            "selected_domains": [],
            "scored_tools": [],
            "notes_for_pi": "(parse failure: JSON top-level not an object)",
            "_parse_error": True,
        }
    # Defensive: coerce expected fields if Brain emits looser shapes.
    parsed.setdefault("selected_domains", [])
    parsed.setdefault("scored_tools", [])
    parsed.setdefault("notes_for_pi", "")
    return parsed


def _materialize_scored_tools(
    scored: list[dict],
    *,
    domain_tools: dict[str, list[M.ToolDecl]],
) -> list[M.ToolDecl]:
    """Convert the Brain's scored_tools list into ToolDecl objects.

    For registry-sourced entries, looks up the canonical ToolDecl from
    the loaded domain catalogs (preserves command/args/secrets metadata
    the Brain doesn't need to re-emit). For user_added entries, builds
    a minimal ToolDecl from the Brain's claim — these are flagged
    `source="user_added"` so PI can scrutinize them more closely at
    pi_toolkit_ratify.
    """
    # Flatten the registry-loaded tools into a lookup dict.
    registry_by_name: dict[str, M.ToolDecl] = {}
    for tools in domain_tools.values():
        for t in tools:
            registry_by_name.setdefault(t.name, t)

    out: list[M.ToolDecl] = []
    for entry in scored:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        source = entry.get("source", "registry")
        rationale = entry.get("rationale")
        criticality = entry.get("criticality_suggested", "recommended")

        if source == "registry" and name in registry_by_name:
            base = registry_by_name[name]
            # Override the criticality on secrets per Brain's suggestion;
            # leave secret names + probe metadata intact.
            new_secrets = []
            for s in base.secrets:
                new_s = M.SecretDecl(
                    name=s.name,
                    auth_type=s.auth_type,
                    criticality=criticality if criticality in (
                        "required", "recommended", "optional"
                    ) else s.criticality,
                    probe_url=s.probe_url,
                    probe_header=s.probe_header,
                    description=s.description,
                )
                new_secrets.append(new_s)
            tool = M.ToolDecl(
                name=base.name,
                type=base.type,
                command=base.command,
                args=list(base.args),
                install_hint=base.install_hint,
                secrets=new_secrets,
                always_on=base.always_on,
                rationale=rationale or base.rationale,
                source="registry",
            )
        else:
            # User-added or SerpAPI-augmented (Brain proposing a tool not
            # in any registry shortlist). Mark source explicitly; PI must
            # scrutinize. Phase D3b: preserve "serpapi_augmented" as a
            # distinct source so the PI ratification UI can apply extra
            # provenance review (these come from a web search, not from
            # the curated registry).
            preserved_source = (
                "serpapi_augmented" if source == "serpapi_augmented" else "user_added"
            )
            tool = M.ToolDecl(
                name=name,
                type=entry.get("type", "mcp_stdio"),
                command=entry.get("command"),
                args=list(entry.get("args") or []),
                install_hint=entry.get("install_hint"),
                secrets=[],  # PI must hand-add via correct/edit later
                rationale=rationale,
                source=preserved_source,
            )
        out.append(tool)
    return out


def research_toolkit_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Brain produces a candidate toolkit for pi_toolkit_ratify.

    Algorithm:
      1. Load always-on tools from the curated registry (deterministic;
         no LLM decision needed).
      2. Load the catalog of domain keys + descriptions.
      3. For *every* domain, pre-load its tool shortlist so the prompt
         can offer them up-front (saves a second round-trip to the
         registry from the Brain's perspective).
      4. Call Brain with the topic + always-on + domain catalog +
         per-domain shortlists. Brain emits a JSON object naming
         selected domains, scored tools, and a notes paragraph.
      5. Materialize the Brain's scored_tools list back into ToolDecl
         objects (registry entries preserve their canonical command /
         args / secrets; user_added entries are minimal until PI
         ratifies/extends).
      6. Compose the proposed_toolkit = always_on + materialized scored
         tools. Write to state.

    Phase D3b (follow-up) layers SerpAPI web search on top of step 3,
    expanding the candidate pool with tools the registry doesn't cover.
    """
    always_on = TR.always_on_tools()
    domain_catalog = TR.list_domains()
    domain_tools = {d: TR.tools_for_domain(d) for d in domain_catalog}

    # Phase D3b: optionally augment the candidate pool via SerpAPI web
    # search. Fail-silent — returns [] if SERPAPI_KEY is unset or the
    # call fails. The registry-based pipeline above is the source of
    # truth; SerpAPI hits are strictly additive.
    serpapi_hits = _serpapi_augment_candidates(state.get("topic_metadata"))

    prompt = _build_research_toolkit_prompt(
        state,
        always_on=always_on,
        domain_catalog=domain_catalog,
        domain_tools=domain_tools,
        serpapi_hits=serpapi_hits,
    )
    reply = sdk.complete(prompt=prompt, system=BRAIN_SYSTEM)
    parsed = _parse_brain_toolkit_reply(reply)
    scored_tools = _materialize_scored_tools(
        parsed.get("scored_tools") or [],
        domain_tools=domain_tools,
    )

    # Compose: always-on first, then Brain's scored picks. Dedupe by
    # name in case Brain accidentally re-listed an always-on tool.
    seen = set()
    proposed: list[M.ToolDecl] = []
    for t in always_on:
        if t.name in seen:
            continue
        seen.add(t.name)
        proposed.append(t)
    for t in scored_tools:
        if t.name in seen:
            continue
        seen.add(t.name)
        proposed.append(t)

    proposed_dicts = [asdict(t) for t in proposed]

    update: dict[str, Any] = {
        "current_phase": "init",  # still onboarding; mission hasn't started
        "current_node": "research_toolkit",
        "proposed_toolkit": proposed_dicts,
    }
    if parsed.get("notes_for_pi"):
        # Stash the Brain's reasoning paragraph on the next interrupt's
        # payload so the PI sees it during ratification. We do this by
        # writing to brain_position which pi_toolkit_ratify reads.
        update["brain_position"] = parsed["notes_for_pi"][:1500]
    return update


# ---------------------------------------------------------------------------
# D5b — draft_manifest_node (after pi_toolkit_ratify accept)
# ---------------------------------------------------------------------------


def _ratified_tools_to_decls(ratified: list[dict]) -> list[M.ToolDecl]:
    """Materialize the ratified_toolkit list back into ToolDecl objects.

    pi_toolkit_ratify stores proposed_toolkit (already dict-shaped) into
    ratified_toolkit verbatim on accept, so the same conversion that
    research_toolkit_node did when materializing scored tools doesn't
    need to happen here. We just rehydrate ToolDecl from the dict.
    """
    out: list[M.ToolDecl] = []
    for d in ratified or []:
        if not isinstance(d, dict):
            continue
        secrets = [
            M.SecretDecl(**s) for s in (d.get("secrets") or []) if isinstance(s, dict)
        ]
        # Strip secrets from the dict so we don't double-pass it.
        kwargs = {k: v for k, v in d.items() if k != "secrets"}
        try:
            out.append(M.ToolDecl(**kwargs, secrets=secrets))
        except TypeError:
            # Forward-compatible: unknown extra fields → skip
            continue
    return out


def draft_manifest_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """After pi_toolkit_ratify accept, materialize the project's
    baseline tools.json + .env template on disk.

    Reads from state:
      - project_id (RKA project; drives ~/rka-projects/{id}/ path)
      - topic_metadata (from pi_onboarding_topic)
      - ratified_toolkit (from pi_toolkit_ratify on accept; empty if
        rejected/corrected — caller is responsible for not entering this
        node if ratification failed)

    Writes to disk:
      - ~/rka-projects/{project_id}/tools.json (baseline manifest)
      - ~/rka-projects/{project_id}/.env (template; preserves existing
        contents if file already exists, per write_env_template default)

    Writes to state:
      - draft_manifest_path (canonical tools.json path as string)
      - draft_manifest_hash (sha256 of the written manifest)

    Idempotent: re-running on the same project produces the same files
    with the same hash (assuming inputs are stable). Phase D6 will use
    this idempotency when extending mid-stream.
    """
    project_id = state.get("project_id", "")
    if not project_id:
        return {
            "current_phase": "init",
            "current_node": "draft_manifest",
            "errors": [
                {
                    "node_name": "draft_manifest",
                    "error_type": "draft_manifest_no_project_id",
                    "detail": "draft_manifest_node requires state['project_id'] to be set",
                    "timestamp": _now_iso(),
                }
            ],
        }

    ratified = state.get("ratified_toolkit") or []
    if not ratified:
        return {
            "current_phase": "init",
            "current_node": "draft_manifest",
            "errors": [
                {
                    "node_name": "draft_manifest",
                    "error_type": "draft_manifest_empty_toolkit",
                    "detail": (
                        "ratified_toolkit is empty — PI rejected or corrected "
                        "during pi_toolkit_ratify; no manifest to draft"
                    ),
                    "timestamp": _now_iso(),
                }
            ],
        }

    tool_decls = _ratified_tools_to_decls(ratified)
    topic_dict = state.get("topic_metadata") or {}
    topic = M.TopicMetadata(
        summary=topic_dict.get("summary") or "",
        research_field=topic_dict.get("research_field"),
        venue=topic_dict.get("venue"),
        keywords=list(topic_dict.get("keywords") or []),
    )

    manifest = M.ToolManifest(
        project_id=project_id,
        manifest_type="baseline",
        topic=topic,
        tools=tool_decls,
    )
    manifest_hash = manifest.compute_hash()
    # Collect every secret declared across all ratified tools.
    all_secrets = [s for t in tool_decls for s in t.secrets]

    # Emit the manifest + env template as structured data on
    # decisions_to_present. The PI (or their Claude session) writes the
    # files locally — the orchestrator does NOT write to the host
    # filesystem. This eliminates the Docker bind-mount requirement.
    manifest_json = manifest.to_dict()
    env_template_lines = []
    for s in all_secrets:
        env_template_lines.append(f"# {s.name} ({s.criticality})")
        if s.description:
            for line in s.description.strip().splitlines():
                env_template_lines.append(f"#   {line}")
        env_template_lines.append(f"{s.name}=<paste-here>")
        env_template_lines.append("")
    env_template = "\n".join(env_template_lines)

    workspace_path = state.get("workspace_path", "")
    suggested_manifest_path = (
        f"{workspace_path}/.rka/tools.json" if workspace_path
        else f"~/rka-projects/{project_id}/tools.json"
    )
    suggested_env_path = (
        f"{workspace_path}/.rka/.env" if workspace_path
        else f"~/rka-projects/{project_id}/.env"
    )

    items = [
        {
            "source_node": "draft_manifest",
            "type": "manifest",
            "suggested_path": suggested_manifest_path,
            "content": manifest_json,
        },
        {
            "source_node": "draft_manifest",
            "type": "env_template",
            "suggested_path": suggested_env_path,
            "content": env_template,
        },
    ]

    # Persist the manifest to the orchestrator store so get_manifest
    # can return it without depending on host-filesystem access.
    try:
        import json as _json
        from orchestrator.parked_store import ParkedStore
        import os as _os
        db_path = _os.environ.get("ORCHESTRATOR_DB_PATH", "/data/orchestrator.db")
        store = ParkedStore(db_path)
        store.set_project_manifest(
            project_id=project_id,
            manifest_json=_json.dumps(manifest_json),
            manifest_hash=manifest_hash,
            workspace_path=workspace_path or None,
        )
        store.close()
    except Exception:
        pass  # Non-fatal: state still carries the data

    return {
        "current_phase": "init",
        "current_node": "draft_manifest",
        "draft_manifest_path": suggested_manifest_path,
        "draft_manifest_hash": manifest_hash,
        "decisions_to_present": items,
    }


# ---------------------------------------------------------------------------
# D5b + D7 — finalize_node (probe + audit + register)
# ---------------------------------------------------------------------------


def _build_audit_summary(
    manifest: M.ToolManifest, report: "CredentialReport"  # type: ignore[name-defined]
) -> str:
    """Compose a one-paragraph audit summary referencing the manifest
    hash + the credential probe outcome. This text lands in the RKA
    journal entry (Q5)."""
    topic = manifest.topic
    topic_line = (
        f"Topic: {topic.summary[:200] if topic and topic.summary else '(none)'}"
    )
    venue_line = (
        f"Venue: {topic.venue}" if topic and topic.venue else "Venue: (unspecified)"
    )
    tool_lines = []
    for t in manifest.tools:
        secrets = ", ".join(
            f"{s.name}({s.criticality})" for s in t.secrets
        ) or "no secrets"
        tool_lines.append(f"  - {t.name} [{t.type}] — {secrets}")

    parts = [
        f"Orchestrator onboarding completed for {manifest.project_id}.",
        topic_line,
        venue_line,
        f"Tool stack ({len(manifest.tools)} tools):",
        *tool_lines,
        "",
        "Credential validation:",
        f"  healthy: {len(report.healthy_tools)}; blocked: {len(report.blocked_tools)}; "
        f"required_failures: {len(report.failed_required)}; "
        f"recommended_failures: {len(report.failed_recommended)}; "
        f"optional_failures: {len(report.failed_optional)}",
        "",
        f"Manifest path: ~/rka-projects/{manifest.project_id}/tools.json",
        f"Manifest hash: sha256:{manifest.compute_hash()}",
    ]
    return "\n".join(parts)


def finalize_node(
    state: ResearchWorkflowState, sdk: SDKClient, mcp: MCPClient
) -> dict:
    """Last node in the onboarding subgraph. Runs after
    pi_credentials_ready accept.

    Sequence:
      1. Re-load the manifest from disk (the canonical source).
      2. Read the .env via manifest.read_env (placeholder values
         silently skipped).
      3. Run credential_validator.probe_all_secrets to validate every
         declared secret.
      4. If any required-tier failures exist → record a checkpoint
         (Q2 escalation; the graph routes to escalation downstream).
      5. Otherwise: emit an RKA journal entry summarizing the
         onboarding outcome (Q5 audit trail).
      6. Update the manifest with the audit_journal_id and re-save.

    State updates:
      - finalize_outcome: "complete" | "escalated_required_missing" | "failed"
      - audit_journal_id (when complete)
      - credential_report_summary (always; rendered text for the run log)
      - artifacts entry for the audit journal
    """
    from orchestrator import credential_validator as CV

    project_id = state.get("project_id", "")
    if not project_id:
        return {
            "current_phase": "init",
            "current_node": "finalize",
            "errors": [
                {
                    "node_name": "finalize",
                    "error_type": "finalize_no_project_id",
                    "detail": "finalize_node requires state['project_id']",
                    "timestamp": _now_iso(),
                }
            ],
        }

    # Reconstruct the manifest from state (draft_manifest_node emits
    # the manifest dict on decisions_to_present instead of writing to
    # disk). This eliminates the Docker bind-mount requirement.
    pending = state.get("decisions_to_present") or []
    manifest_items = [d for d in pending if d.get("source_node") == "draft_manifest" and d.get("type") == "manifest"]
    if manifest_items:
        manifest_dict = manifest_items[0].get("content", {})
        try:
            manifest = M.ToolManifest.from_dict(manifest_dict)
        except Exception:
            manifest = None
    else:
        # Fallback: try loading from disk (backward compat for
        # pre-refactoring runs where draft_manifest wrote the file).
        manifest = M.load_manifest(project_id)

    if manifest is None:
        return {
            "current_phase": "init",
            "current_node": "finalize",
            "errors": [
                {
                    "node_name": "finalize",
                    "error_type": "finalize_no_manifest",
                    "detail": (
                        f"No manifest found for project {project_id} — "
                        "draft_manifest_node must run before finalize_node"
                    ),
                    "timestamp": _now_iso(),
                }
            ],
        }

    # Credential validation: the .env file lives on the PI's host
    # filesystem, which the Docker container may not be able to read.
    # Try reading it (works if bind-mounted); fall back to an empty
    # dict (credential probe reports "missing" for all keys — the PI
    # can re-validate locally via their Claude session).
    try:
        env_values = M.read_env(project_id)
    except Exception:
        env_values = {}
    report = CV.probe_all_secrets(manifest.tools, env_values)
    summary_text = CV.render_credential_report(report)

    update: dict[str, Any] = {
        "current_phase": "init",
        "current_node": "finalize",
        "credential_report_summary": summary_text,
    }

    if report.failed_required:
        # Q2: required failures escalate via checkpoint.
        names = [s.name for _, s, _ in report.failed_required]
        update["finalize_outcome"] = "escalated_required_missing"
        update["checkpoints"] = [
            {
                "chk_id": f"chk_onboarding_creds_{int(datetime.now(tz=timezone.utc).timestamp())}",
                "type": "decision",
                "reason": (
                    f"Onboarding finalize: required credential(s) missing or "
                    f"rejected — {', '.join(names)}. PI must provide the values "
                    f"in ~/rka-projects/{project_id}/.env and re-run finalize, "
                    f"OR downgrade the criticality on the affected secrets."
                ),
                "resolved": False,
            }
        ]
        return update

    # Happy path: emit the audit journal entry. tags include the
    # workflow_thread_id (per mcp_client's _merge_workflow_tag pattern,
    # the RestMCPClient auto-tags writes — but rka_add_note takes an
    # explicit tags arg that the auto-tag layer extends).
    audit_text = _build_audit_summary(manifest, report)
    try:
        audit_id = mcp.rka_add_note(
            content=audit_text,
            type="note",
            source="system",
            tags=["orchestrator", "onboarding", "baseline"],
        )
    except Exception as e:  # noqa: BLE001
        update["finalize_outcome"] = "failed"
        update["errors"] = [
            {
                "node_name": "finalize",
                "error_type": "finalize_audit_write_failed",
                "detail": f"rka_add_note raised: {type(e).__name__}: {str(e)[:200]}",
                "timestamp": _now_iso(),
            }
        ]
        return update

    # Record the audit linkage. Previously this wrote to disk via
    # M.save_manifest; now it's captured in state so the PI can
    # persist locally if needed.
    manifest.audit_journal_id = audit_id

    update["finalize_outcome"] = "complete"
    update["audit_journal_id"] = audit_id
    update["artifacts"] = [
        {
            "rka_id": audit_id,
            "entity_type": "journal",
            "node_name": "finalize",
            "timestamp": _now_iso(),
        }
    ]
    return update
