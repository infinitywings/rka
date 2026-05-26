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
    """O2.1 — Materialize the project workspace on disk.

    Inputs (state):
      - project_id            — RKA project ID (required).
      - project_slug          — explicit slug, if PI provided one
                                during O1; otherwise derived.
      - polished_idea         — used as a fallback source for slug
                                derivation when RKA project name is
                                unavailable.

    Side effects:
      - Creates ``$RKA_WORKSPACE_ROOT/{slug}/`` (default ``$HOME/Research/{slug}/``)
        with subdirs (data/, code/, notebooks/, manuscripts/, results/, .rka/).
      - Writes ``.rka/project_id``, ``.rka/workspace.json``, ``README.md``,
        ``.gitignore`` at mode 0700 (directory) / 0600 (.env file inside .rka/,
        when later written by O5).
      - Advances workspace.json's phase tracker to ``o2`` (current sub-phase).

    State writes:
      - current_node      = "workspace_setup"
      - current_phase     = "init"
      - project_slug      — the slug used (locks for downstream nodes).
      - workspace_path    — absolute path of the workspace root.

    Failure modes:
      - Missing project_id            → ErrorRecord; no side effect.
      - Slug derivation produces a value that fails ProjectSlug
        validation → ErrorRecord (callers can re-run after extending
        the polished idea or fixing the RKA project name).
      - Workspace already exists      → checkpoint surfaced to PI with
        the conflicting path so PI can rename / remove and re-run.
      - Other IO failures             → ErrorRecord with the OSError detail.
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

    try:
        binding = W.create_workspace(
            slug_candidate, project_id, refuse_if_exists=True
        )
    except W.InvalidSlugError as ve:
        return {
            "current_phase": "init",
            "current_node": "workspace_setup",
            "errors": [
                {
                    "node_name": "workspace_setup",
                    "error_type": "workspace_setup_invalid_slug",
                    "detail": str(ve),
                    "timestamp": _now_iso(),
                }
            ],
        }
    except W.WorkspaceAlreadyExistsError as wae:
        # Conflict: workspace dir exists. Emit a checkpoint so the PI
        # can rename the slug or remove the conflicting directory.
        existing_path = W.project_workspace(slug_candidate)
        chk_id = f"chk_workspace_conflict_{int(datetime.now(tz=timezone.utc).timestamp())}"
        return {
            "current_phase": "init",
            "current_node": "workspace_setup",
            "project_slug": slug_candidate,
            "workspace_path": str(existing_path),
            "checkpoints": [
                {
                    "chk_id": chk_id,
                    "type": "decision",
                    "reason": (
                        f"workspace conflict: '{existing_path}' already exists. "
                        f"PI must rename the slug (set state['project_slug']) "
                        f"or remove the directory and re-run workspace_setup. "
                        f"Detail: {wae}"
                    ),
                    "resolved": False,
                }
            ],
        }
    except OSError as oe:
        return {
            "current_phase": "init",
            "current_node": "workspace_setup",
            "errors": [
                {
                    "node_name": "workspace_setup",
                    "error_type": "workspace_setup_io_failed",
                    "detail": f"{type(oe).__name__}: {oe}",
                    "timestamp": _now_iso(),
                }
            ],
        }

    # Advance the workspace phase to 'o2' (entering deep research).
    try:
        W.advance_phase(slug_candidate, "o2", note="workspace created")
    except W.WorkspaceError:
        # Non-fatal: workspace exists, just couldn't bump phase. The
        # next sub-phase can update phase tracking itself.
        pass

    return {
        "current_phase": "init",
        "current_node": "workspace_setup",
        "project_slug": slug_candidate,
        "workspace_path": str(binding.workspace_path),
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
parse failures as "no candidates").
"""


def _build_research_toolkit_prompt(
    state: ResearchWorkflowState,
    *,
    always_on: list[M.ToolDecl],
    domain_catalog: dict[str, str],
    domain_tools: dict[str, list[M.ToolDecl]],
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
            # User-added (Brain proposing a tool not in any registry
            # shortlist). Mark source explicitly; PI must scrutinize.
            tool = M.ToolDecl(
                name=name,
                type=entry.get("type", "mcp_stdio"),
                command=entry.get("command"),
                args=list(entry.get("args") or []),
                install_hint=entry.get("install_hint"),
                secrets=[],  # PI must hand-add via correct/edit later
                rationale=rationale,
                source="user_added",
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

    prompt = _build_research_toolkit_prompt(
        state,
        always_on=always_on,
        domain_catalog=domain_catalog,
        domain_tools=domain_tools,
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
    path = M.save_manifest(manifest)
    # Collect every secret declared across all ratified tools.
    all_secrets = [s for t in tool_decls for s in t.secrets]
    M.write_env_template(project_id, all_secrets)

    return {
        "current_phase": "init",
        "current_node": "draft_manifest",
        "draft_manifest_path": str(path),
        "draft_manifest_hash": manifest.compute_hash(),
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
                        f"No tools.json found for project {project_id} — "
                        "draft_manifest_node must run before finalize_node"
                    ),
                    "timestamp": _now_iso(),
                }
            ],
        }

    env_values = M.read_env(project_id)
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

    # Update the on-disk manifest with the audit_journal_id linkage.
    manifest.audit_journal_id = audit_id
    M.save_manifest(manifest)

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
