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
from orchestrator import tool_registry as TR
from orchestrator.llm_client import SDKClient
from orchestrator.mcp_client import MCPClient
from orchestrator.nodes.brain import BRAIN_SYSTEM
from orchestrator.state import ResearchWorkflowState

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
