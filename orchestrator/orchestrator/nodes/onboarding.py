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
