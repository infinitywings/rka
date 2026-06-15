"""Claude SDK client abstraction.

Nodes call Claude via the `SDKClient` Protocol. T7 (delivered in Phase 2,
mis_01KRSRZX2P3BN4ZAP70ZM7YXGC) binds the real `claude-agent-sdk`
async client; tests inject fakes via the same Protocol.

Keeping the SDK call surface narrow (one `complete()` method) lets the
nodes stay pure functions of `(state, sdk, mcp) -> state_update` and lets
T11's audit-symmetry walk only one entry point per LLM hop.

Auth routing (jrn_01KRNXR4GK3PB70M9T24X6AV66 + mission T2): the
`make_sdk()` factory scrubs ``ANTHROPIC_API_KEY`` from the subprocess
env so the SDK's auth resolution falls through to ``~/.claude/.credentials.json``
or the macOS Keychain (Claude Max subscription). NEVER log credential
VALUES — only the auth-path LABEL.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)


# Env vars whose presence routes the SDK to non-Claude-Max paths.
# Scrubbed before SDK invocation; their presence is logged as a WARNING
# (label only, never value).
_ENV_VARS_TO_SCRUB: tuple[str, ...] = ("ANTHROPIC_API_KEY",)

# Auth path identifiers — returned by `_verify_claude_max_routing()`.
_AUTH_PATH_CREDENTIALS_JSON = "credentials_json"
_AUTH_PATH_KEYCHAIN = "keychain"
_AUTH_PATH_OAUTH_TOKEN = "env_oauth_token"
_AUTH_PATH_ENV_API_KEY = "env_api_key"  # only set if scrubbing was bypassed
_AUTH_PATH_NONE = "none"

# Phase 2.7 (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R T1; PI-ratified per
# jrn_01KRXP96THHEAKCGB0P0KGV7Y9) — Option C read-only-subprocess MCP scope.
# Subprocess SDK sees `mcp__rka__rka_*` tools via a strict MCP server config;
# `allowed_tools` permits the 9 Protocol-anchored read methods; `disallowed_tools`
# explicitly denies the write methods as belt-and-suspenders. Writes execute from
# the parent process after `pi_decision_select` ratifies — see Phase 2.7 T3.
_MCP_SERVER_NAME = "rka"

READ_TOOLS: tuple[str, ...] = (
    "rka_get_status",
    "rka_get_context",
    "rka_get_journal",
    "rka_get_mission",
    "rka_get_research_map",
    "rka_get_checkpoints",
    "rka_search",
    "rka_get",
    "rka_trace_provenance",
    # Phase 2.9 T2 (mis_01KRY2KP0GGZY21BA4Z2R2S718) — belt-and-suspenders
    # additions. With Phase 2.9 T1's RKA_PROJECT env propagation, the
    # subprocess should rarely need these. But if env propagation regresses
    # for any reason (RKA_PROJECT unset, MCP child re-spawns without env),
    # the brain LLM can self-recover by enumerating projects and switching
    # session — without escalating. Phase 2.8 surfaced this gap empirically
    # (brain attempted `rka_list_projects` for self-recovery and was correctly
    # denied per `permission_mode="dontAsk"` because the tool was outside
    # the Phase 2.7 T1-ratified READ_TOOLS set). Both are read-side: they
    # select session context, not mutate entities. Confirmed NOT in WRITE_TOOLS.
    "rka_list_projects",
    "rka_set_project",
    # Phase-A follow-up: external-API search tools. Read-side, hit external
    # services (Semantic Scholar, arXiv, CrossRef DOI lookup). Useful for
    # the Brain to enrich research context during Confirmation Brief drafting
    # without escalating to the PI. SEMANTIC_SCHOLAR_API_KEY and SERPAPI_KEY
    # are propagated to the subprocess via _build_mcp_servers_config so the
    # tools get higher rate-limit / non-anonymous access when configured.
    "rka_search_semantic_scholar",
    "rka_search_arxiv",
    "rka_enrich_doi",
    # v2.6.3 navigator tools — RKA's MCP server now ships a two-tier
    # surface: ~12 always-on tools advertised at startup, ~79 deferred
    # tools that the client must register at runtime via
    # `rka_load_tools(names=[...])`. Without the three navigator tools
    # in the subprocess's `allowed_tools` list, the Brain/Executor SDK
    # subprocess CANNOT call rka_load_tools and therefore cannot reach
    # any deferred RKA tool — the orchestrator's effective tool surface
    # would regress from ~91 to ~12. Navigator tools are read-side
    # only: rka_load_tools mutates the MCP server's runtime tool
    # registry (firing notifications/tools/list_changed) but does NOT
    # touch RKA domain truth, so they belong in READ_TOOLS rather than
    # WRITE_TOOLS.
    "rka_load_tools",
    "rka_list_tools",
    "rka_help",
    # v2.7.0+ typed-dispatch surface. The running RKA MCP server (v2.7.0+)
    # ships `rka_query` (read ops) / `rka_execute` (write ops) / `rka_describe`
    # (schema lookup) as the ALWAYS-ON tools; the legacy `rka_get_*` tools above
    # are now tier='deferred'. Without `rka_query` + `rka_describe` in the
    # subprocess allowlist, EVERY Brain/Executor RKA READ is denied under
    # permission_mode='dontAsk' — the subprocess calls `rka_query` (the real
    # read path) and gets a permission error, leaving the LLM blind to RKA
    # state and forced to work off parent-injected context only. Empirically
    # surfaced driving Opus 4.8 against an RKA v2.8.0 server (2026-06-15): the
    # Brain/Executor journal notes reported "both rka_query calls returned
    # permission errors." `rka_execute` (the WRITE dispatch) is deliberately
    # EXCLUDED here and added to `disallowed_tools` below — Phase 2.7 Option C:
    # RKA writes flow parent-side only, never from the subprocess.
    "rka_query",
    "rka_describe",
)

# v2.7.0+ write dispatch verb. Belt-and-suspenders denial (mirrors the legacy
# WRITE_TOOLS entries on `disallowed_tools`): permission_mode='dontAsk' already
# denies anything off the allowlist, but naming the write dispatch explicitly
# keeps the Phase 2.7 Option C "no writes from the subprocess" invariant legible
# and robust if an upstream SDK precedence change ever inverts allow/deny order.
_V27_WRITE_DISPATCH_TOOLS: tuple[str, ...] = ("rka_execute",)

# Context7 MCP server — external documentation lookup. Useful when the
# Brain needs to verify it's reasoning about a library API correctly
# (LangGraph, FastAPI, claude-agent-sdk, etc.). Stdio launch via `npx`
# requires Node + network on first invocation. The server is added
# conditionally in _build_mcp_servers_config when `npx` is available.
_CONTEXT7_SERVER_NAME = "context7"
_CONTEXT7_TOOLS: tuple[str, ...] = (
    "query-docs",
    "resolve-library-id",
)

# Zotero MCP server — research-library full-text + metadata reads. Added
# conditionally in _build_mcp_servers_config when `zotero-mcp` is on PATH
# AND credentials (api_key + library_id) are available either in the
# daemon's env or in the per-project .rka/.env merged via _RealSDKClient.
# Without this server in the subprocess MCP config, the Executor's
# in-container Zotero calls (for FTR full-text retrieval during D3
# grounding, etc.) fall back to no_match — the "cockpit ≠ run env" gap
# that surfaced empirically during the hyperscaler-auditing D3 pre-flight
# audit on 2026-06-03.
_ZOTERO_SERVER_NAME = "zotero"
_ZOTERO_TOOLS: tuple[str, ...] = (
    "zotero_search_items",
    "zotero_advanced_search",
    "zotero_get_collections",
    "zotero_get_collection_items",
    "zotero_get_item_children",
    "zotero_get_item_fulltext",
    "zotero_get_item_metadata",
    "zotero_get_annotations",
    "zotero_get_notes",
    "zotero_search_by_tag",
    "zotero_semantic_search",
    "zotero_search_database_status",
    "zotero_get_recent",
    "zotero_get_tags",
    "zotero_create_note",
)

# Parent-side write-tool registry organized by CAPABILITY (Phase 2.14 —
# capability-categories WRITE_TOOLS replacement). Each tool belongs to
# exactly one capability bucket. WRITE_TOOLS is derived from this mapping
# so adding a new RKA write requires only a row in `TOOL_CAPABILITIES`;
# subprocess `disallowed_tools`, the dispatcher's allowlist check, and
# the Brain/Executor prompt's tool enumeration all pick it up
# automatically.
#
# Capabilities also let future workflows authorize a subset
# ("this mission may RECORD_KNOWLEDGE + EXECUTION_GATES but NOT
# MISSION_LIFECYCLE"). The MVP wires capability tracking into
# `execute_ratified_actions` — caller-side restriction wiring is
# additive (`allowed_capabilities` kwarg, defaults to "all"; pre-2.14
# behavior preserved).
#
# Capability buckets (the load-bearing taxonomy):
#   - RECORD_KNOWLEDGE   — add new journal/decision/claim entries
#   - UPDATE_KNOWLEDGE   — mutate existing entries
#   - MISSION_LIFECYCLE  — create + transition missions
#   - EXECUTION_GATES    — submit checkpoints + reports (the
#                          execution-side ratification surface)
#   - INGESTION          — ingest external documents into RKA
#
# Phase 2.13 (mis_01KRYZMEAT01SMNNXQXS3JRC4W T2; per
# dec_01KRYZGF8N1SNJX5TSP0GM77Z7 Option A): `rka_bulk_update` joined
# the registry. The original Phase 2.7 T1 ratification picked up
# `rka_update_note` + the 7-entry base; Phase-A2 added
# `rka_update_mission_status` + `rka_ingest_document`; Phase 2.14
# preserves all of these and reorganizes into capability buckets.

Capability = Literal[
    "record_knowledge",
    "update_knowledge",
    "mission_lifecycle",
    "execution_gates",
    "ingestion",
]

ALL_CAPABILITIES: tuple[Capability, ...] = (
    "record_knowledge",
    "update_knowledge",
    "mission_lifecycle",
    "execution_gates",
    "ingestion",
)

TOOL_CAPABILITIES: dict[str, Capability] = {
    "rka_add_note": "record_knowledge",
    "rka_add_decision": "record_knowledge",
    "rka_update_note": "update_knowledge",
    "rka_bulk_update": "update_knowledge",
    "rka_create_mission": "mission_lifecycle",
    "rka_update_mission_status": "mission_lifecycle",
    "rka_submit_checkpoint": "execution_gates",
    "rka_submit_report": "execution_gates",
    "rka_ingest_document": "ingestion",
}


def tools_for_capabilities(
    capabilities: tuple[Capability, ...] | list[Capability] | None = None,
) -> tuple[str, ...]:
    """Return the tool names allowed under `capabilities`.

    `None` (default) → all capabilities (full WRITE_TOOLS surface).
    Order matches `TOOL_CAPABILITIES` insertion order for stable
    diffs/tests.
    """
    if capabilities is None:
        return tuple(TOOL_CAPABILITIES.keys())
    wanted = set(capabilities)
    return tuple(t for t, c in TOOL_CAPABILITIES.items() if c in wanted)


def capability_of(tool: str) -> Capability | None:
    """Return the capability bucket for `tool`, or None if `tool` is not
    a registered write tool."""
    return TOOL_CAPABILITIES.get(tool)


# WRITE_TOOLS derived from TOOL_CAPABILITIES. Preserved as a tuple so
# call sites that import it continue to work unchanged.
WRITE_TOOLS: tuple[str, ...] = tuple(TOOL_CAPABILITIES.keys())


def _prefixed_tools(names: tuple[str, ...], server: str = _MCP_SERVER_NAME) -> list[str]:
    """Prefix MCP tool names with `mcp__<server_name>__` per the SDK's
    allowed_tools / disallowed_tools naming convention.

    Default `server=_MCP_SERVER_NAME` ("rka") preserves the pre-Phase-A
    call sites. Pass an explicit server name to prefix tools from a
    different MCP server (e.g., "context7").
    """
    return [f"mcp__{server}__{n}" for n in names]


# Built-in Claude Code tools that the SDK subprocess needs to actually do
# filesystem work the mission asks for (read manifests, run Python, write
# results into the workspace). Granted in addition to the read-only MCP
# tools so that nodes like `mission_execute` can read `.env`, probe
# library imports via `Bash`, write outputs to the workspace, etc.
#
# Why this is safe w.r.t. Phase 2.7 Option C: the read-only-subprocess
# invariant was specifically about RKA writes — the subprocess must not
# call `rka_add_*` / `rka_update_*` directly; writes flow through
# `pi_decision_select` → `execute_ratified_actions` (parent-side). Built-in
# filesystem tools touch the host workspace, not RKA state, and the
# workspace is the PI's own data — the PI mounts it explicitly via
# HOST_WORKSPACE_ROOT in the compose overlay, so granting access here is
# the *enabling* counterpart to the mount: without these tools the
# Executor reports the workspace as inaccessible even when bind-mounted.
_BUILTIN_FILESYSTEM_TOOLS: tuple[str, ...] = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Grep",
    "Glob",
    "WebFetch",
    "WebSearch",
)

# v0.6.11 — egress tools the can_use_tool hook audits. The research
# workflow legitimately needs open web access (papers, SEC filings), so
# these are NOT hard-allowlisted by default; the hook audit-logs every
# call and denies known telemetry endpoints. An operator can opt into a
# strict deny-by-default allowlist via ORCHESTRATOR_EGRESS_ALLOWLIST.
_EGRESS_TOOLS: tuple[str, ...] = ("WebFetch", "WebSearch")


def _all_allowed_subprocess_tools(
    include_context7: bool, include_zotero: bool = False
) -> list[str]:
    """Compose the full `allowed_tools` list across every MCP server the
    subprocess is configured to talk to plus the built-in filesystem tools
    the Executor needs to actually do mission work. Lives separately from
    READ_TOOLS so the legacy single-server interface stays back-compat.

    v0.6.8: ``include_zotero`` gate added so the Zotero MCP tools surface
    in the Executor's allowed-tools list only when the Zotero server is
    actually wired into the subprocess MCP config — otherwise the LLM
    sees tool names it can't actually call.
    """
    tools = _prefixed_tools(READ_TOOLS)  # rka MCP
    if include_context7:
        tools.extend(_prefixed_tools(_CONTEXT7_TOOLS, server=_CONTEXT7_SERVER_NAME))
    if include_zotero:
        tools.extend(_prefixed_tools(_ZOTERO_TOOLS, server=_ZOTERO_SERVER_NAME))
    tools.extend(_BUILTIN_FILESYSTEM_TOOLS)
    return tools


def _find_rka_mcp_binary() -> str | None:
    """Locate the local `rka` MCP stdio binary on PATH. Returns the absolute
    path if found, None otherwise. Discovered at SDK-call time (not import
    time) so tests can monkeypatch this independently."""
    return shutil.which("rka")


def _find_zotero_mcp_binary() -> str | None:
    """Locate the local `zotero-mcp` stdio binary on PATH.

    v0.6.8: discovered at SDK-call time (mirrors `_find_rka_mcp_binary`).
    Override via ``ZOTERO_MCP_BINARY`` env when the daemon container's PATH
    doesn't resolve a globally-installed binary. Returns None when neither
    PATH nor the env override yields a binary — the caller then skips
    wiring zotero into the subprocess MCP config (the Executor sees no
    zotero_* tools and degrades gracefully to no-zotero behavior, the
    pre-v0.6.8 default).
    """
    return shutil.which("zotero-mcp") or os.environ.get("ZOTERO_MCP_BINARY")


def _build_zotero_server_if_configured(
    env: dict[str, str] | None = None,
) -> dict | None:
    """Return the Zotero stdio MCP server config dict, or None if creds /
    binary unavailable.

    v0.6.8 (hyperscaler-auditing D3 pre-flight audit, 2026-06-03):
    the orchestrator's subprocess was previously hard-coded to {rka, context7}
    as its MCP server set, so any project needing Zotero literature lookups
    during mission execution had its Executor degrade silently. This helper
    adds zotero conditionally based on three signals:

      1. The ``zotero-mcp`` stdio binary is discoverable (PATH or
         ``ZOTERO_MCP_BINARY`` env override).
      2. ``ZOTERO_API_KEY`` is set in the supplied env (or os.environ
         fallback if env is None).
      3. ``ZOTERO_LIBRARY_ID`` is set in the supplied env.

    All three must be present. ``ZOTERO_LIBRARY_TYPE`` defaults to ``user``
    when unset (mirrors zotero_linker._env_config). ``ZOTERO_LOCAL`` is
    pinned to ``"false"`` so the subprocess uses the Web API path — the
    daemon container has no Zotero.app desktop install.

    The env block on the returned McpStdioServerConfig dict REPLACES (does
    NOT merge with) the parent process env when the subprocess is spawned
    by claude-agent-sdk. So we explicitly enumerate every Zotero env var
    the zotero-mcp child needs to authenticate.

    Pass ``env`` (the merged daemon + project env) to read project-local
    creds that arrived via ``_merge_project_env_file``. When env is None,
    falls back to ``os.environ`` for backward compat.
    """
    binary = _find_zotero_mcp_binary()
    if not binary:
        return None

    source = env if env is not None else dict(os.environ)
    api_key = (source.get("ZOTERO_API_KEY") or "").strip()
    library_id = (source.get("ZOTERO_LIBRARY_ID") or "").strip()
    if not api_key or not library_id:
        return None

    library_type = (source.get("ZOTERO_LIBRARY_TYPE") or "user").strip()
    if library_type not in ("user", "group"):
        library_type = "user"

    return {
        "type": "stdio",
        "command": binary,
        "args": ["serve"],
        "env": {
            "ZOTERO_API_KEY": api_key,
            "ZOTERO_LIBRARY_ID": library_id,
            "ZOTERO_LIBRARY_TYPE": library_type,
            "ZOTERO_LOCAL": "false",
        },
    }


def _build_mcp_servers_config(
    rka_binary: str | None,
    project_id: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict:
    """Build the McpStdioServerConfig dict for the subprocess.

    The `project_id` parameter is retained for backward compatibility
    with callers that pass it, but as of RKA v2.6 it is NO-OP at this
    layer — v2.6 removed the `RKA_PROJECT` env-var reading from rka's
    MCP server (and from rka.constants.DEFAULT_PROJECT_ID at the REST
    layer). Every project-scoped rka_* tool now requires `project_id`
    as a kwarg, threaded by the Brain/Executor LLM from its workflow
    state (see nodes/brain.py BRAIN_SYSTEM and nodes/executor.py
    EXECUTOR_SYSTEM prompts for the discipline).

    External-API key propagation: if `SEMANTIC_SCHOLAR_API_KEY` or
    `SERPAPI_KEY` is set in the parent process env, they are explicitly
    propagated into the rka server's env block. Necessary because the
    McpStdioServerConfig.env field replaces (does NOT merge with) the
    parent env when the subprocess is spawned. Without explicit
    propagation the rka MCP child would run anonymously against
    external APIs.

    Phase-A follow-up — context7 documentation server: if `npx` is
    available on PATH, a second MCP server entry `context7` is added
    using `npx -y @upstash/context7-mcp@latest`. The Brain LLM can
    use it via `mcp__context7__query-docs` / `mcp__context7__resolve-library-id`
    to verify library API surfaces during Backbrief drafting and gate1
    validation. Falls back to rka-only when npx isn't installed.

    Returns `{}` if no rka binary found — subprocess falls back to
    Phase 1 text-only mode (caller logs a warning).
    """
    # `project_id` is intentionally unused as of v2.6 — see docstring.
    del project_id

    if not rka_binary:
        return {}

    # rka server env: external-API keys only (project context is now
    # passed per-call via the project_id kwarg on every tool).
    rka_env: dict[str, str] = {}
    for key in ("SEMANTIC_SCHOLAR_API_KEY", "SERPAPI_KEY"):
        val = os.environ.get(key)
        if val:
            rka_env[key] = val

    rka_server: dict = {
        "type": "stdio",
        "command": rka_binary,
        "args": ["mcp"],
    }
    if rka_env:
        rka_server["env"] = rka_env

    config: dict = {_MCP_SERVER_NAME: rka_server}

    # context7 — additive read-side surface for library/SDK doc lookup.
    npx = shutil.which("npx")
    if npx:
        config[_CONTEXT7_SERVER_NAME] = {
            "type": "stdio",
            "command": npx,
            "args": ["-y", "@upstash/context7-mcp@latest"],
        }

    # v0.6.8: zotero — additive research-library full-text + metadata surface.
    # Only wired when zotero-mcp is on PATH AND creds are configured (in the
    # supplied env dict or os.environ as a fallback). Closes the "cockpit
    # has zotero but the orchestrator's Executor subprocess doesn't" gap
    # surfaced empirically during the hyperscaler-auditing D3 pre-flight
    # audit on 2026-06-03.
    zotero_server = _build_zotero_server_if_configured(env=env)
    if zotero_server is not None:
        config[_ZOTERO_SERVER_NAME] = zotero_server

    return config


class SDKTimeoutError(Exception):
    """Phase S4 — raised when a single `SDKClient.complete()` call
    exceeds its per-call timeout budget.

    Wraps `asyncio.TimeoutError` at the Protocol boundary so node code
    catches a single exception type (vs `asyncio.TimeoutError` which is
    asyncio-internal vocabulary and can be confused with other timeout
    sources). Catching here also lets the SDK-side error message carry
    the node name + budget for cleaner ErrorRecord.detail.

    Distinct from the Phase D2.6 segment-level watchdog: that one fires
    after the whole graph segment returns without advancing; this one
    fires at a single LLM call. They are complementary — the per-call
    timeout surfaces a classified error before the segment watchdog
    needs to escalate an opaque "no progress" message.
    """


# Phase S4 — per-node SDK call timeouts (seconds).
#
# Empirically: PI cockpit reported a backbrief stall measured in
# minutes during the 2026-06-03 hyperscaler-auditing live test
# (Run-5 attempt N, thread thr_19e8eebfb58ef007ac2). Without per-call
# bounds, a single hung SDK turn left the graph stuck at "running"
# until the Phase D2.6 segment watchdog ran out of patience and
# fired an unclassified escalation. With these bounds, a hung call
# surfaces as a classified `llm_call_timeout` ErrorRecord and routes
# through `escalation_router` with a clear cause.
#
# Tighter than the Phase D2.6 watchdog (which is segment-level + 1
# retry); the watchdog still catches the residual cases where the
# SDK returns cleanly but the graph didn't actually advance.
#
# Defaults chosen to be GENEROUS (3-10× a typical LLM call) so we
# only intercept genuine hangs, not slow legitimate calls. Tune
# downward only after empirical data shows the floors are too high.
SDK_TIMEOUT_DEFAULT_S: float = 240.0
"""Default per-call budget for LLM-only calls (no MCP tool use loop)."""

SDK_TIMEOUT_BACKBRIEF_S: float = 480.0
"""`backbrief_draft` performs MCP reads to research the mission; larger budget."""

SDK_TIMEOUT_TOOL_USE_S: float = 600.0
"""`mission_execute` iterates tool-use turns; largest budget."""


class SDKClient(Protocol):
    """Synchronous wrapper around the Claude Agent SDK.

    A real implementation (T7) wraps `claude_agent_sdk.query` with
    `asyncio.run` for sync calling from within LangGraph nodes (Phase 1
    has no concurrency that would benefit from async; the SDK call is the
    only place we'd block, and the node IS the work unit).

    Phase E4: `last_call_cost_usd` carries the USD spent on the most
    recent `complete()` call, extracted from the SDK's ResultMessage.
    Nodes read this after `complete()` returns and add to
    `state["usd_spent"]` for workflow-level budget tracking. Fakes used
    in tests can default this to 0.0 (no real cost).

    Phase S4: `timeout_s` (optional) bounds a single `complete()` call.
    On expiry, raises `SDKTimeoutError`. None disables the bound (legacy
    behavior — fakes default here so old tests still pass unchanged).
    """

    last_call_cost_usd: float

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system: str | None = None,
        timeout_s: float | None = None,
    ) -> str:
        """Issue a single LLM call. Returns the assistant's text reply.

        Implementations must reset `last_call_cost_usd` to 0.0 at the
        start of the call and populate it before returning.

        When `timeout_s` is set, implementations must raise
        `SDKTimeoutError` if the call has not completed within that
        many seconds. The Protocol contract for `last_call_cost_usd`
        on timeout is unspecified (the partial cost is best-effort);
        callers should not depend on it after a timeout.
        """
        ...


@dataclass
class AuthRoutingReport:
    """Result of `_verify_claude_max_routing()`. Label-only; no values."""

    auth_path: str
    warning: str | None = None
    scrubbed_env_vars: list[str] = field(default_factory=list)


def _verify_claude_max_routing() -> AuthRoutingReport:
    """Inspect env + filesystem + Keychain for Claude Max auth availability.

    Order matches the SDK's own resolution chain
    (jrn_01KRNXR4GK3PB70M9T24X6AV66):

      1. ``ANTHROPIC_API_KEY`` env  → API billing (NOT desired). If set,
         report it (caller scrubs before invoking the SDK).
      2. ``CLAUDE_CODE_OAUTH_TOKEN`` env → OAuth path.
      3. ``~/.claude/.credentials.json`` file → file-based Claude Max.
      4. macOS Keychain ``Claude Code-credentials`` entry → Keychain Claude Max.

    Returns the FIRST available path among #2-#4 (we want the subprocess to
    use one of those, NOT #1). The presence of #1 is reported as a warning
    if also detected — the caller is expected to scrub it before
    constructing the SDK.

    Label only — never returns or logs the credential VALUE.
    """
    scrubbed: list[str] = []
    warning: str | None = None

    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if api_key_set:
        warning = (
            "ANTHROPIC_API_KEY is set in env (would route to API billing). "
            "make_sdk() scrubs it before SDK invocation so auth falls "
            "through to Claude Max (credentials.json / Keychain)."
        )
        scrubbed.append("ANTHROPIC_API_KEY")

    # Path #2: explicit OAuth token in env.
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return AuthRoutingReport(
            auth_path=_AUTH_PATH_OAUTH_TOKEN, warning=warning,
            scrubbed_env_vars=scrubbed,
        )

    # Path #3: credentials.json file (standard CLI install).
    credentials_path = Path("~/.claude/.credentials.json").expanduser()
    if credentials_path.is_file():
        return AuthRoutingReport(
            auth_path=_AUTH_PATH_CREDENTIALS_JSON, warning=warning,
            scrubbed_env_vars=scrubbed,
        )

    # Path #4: macOS Keychain (only meaningful on Darwin).
    if _keychain_has_claude_code_credentials():
        return AuthRoutingReport(
            auth_path=_AUTH_PATH_KEYCHAIN, warning=warning,
            scrubbed_env_vars=scrubbed,
        )

    # Fallback — if scrubbing happens but no Max path exists, the SDK will
    # fail at first call. Caller can decide whether to proceed or surface
    # a checkpoint.
    if api_key_set:
        return AuthRoutingReport(
            auth_path=_AUTH_PATH_ENV_API_KEY,
            warning=(
                "Neither credentials.json nor Keychain entry found; "
                "ANTHROPIC_API_KEY is the only available auth path. "
                "Caller MUST decide whether to allow API billing."
            ),
            scrubbed_env_vars=[],  # caller did not scrub if this path is returned
        )
    return AuthRoutingReport(
        auth_path=_AUTH_PATH_NONE,
        warning=(
            "No Claude Max credentials found AND no ANTHROPIC_API_KEY in env. "
            "SDK invocation will fail. Run `claude login` to seed credentials."
        ),
        scrubbed_env_vars=scrubbed,
    )


def _keychain_has_claude_code_credentials() -> bool:
    """Probe macOS Keychain for the standard Claude Code credentials entry.

    Returns True iff the `security find-generic-password` lookup succeeds.
    Uses the service name the SDK itself documents ('Claude Code-credentials').
    Returns False on non-Darwin or if the `security` binary is unavailable.
    """
    if shutil.which("security") is None:
        return False
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials"],
            capture_output=True, timeout=2.0,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _scrubbed_env() -> dict[str, str]:
    """Return os.environ minus the API-billing-routing env vars.

    Used to construct the env dict handed to the SDK subprocess so auth
    falls through to Claude Max paths.
    """
    return {k: v for k, v in os.environ.items() if k not in _ENV_VARS_TO_SCRUB}


def _parse_dotenv_lines(text: str) -> dict[str, str]:
    """Parse a flat KEY=VALUE .env file body. No interpolation.

    Mirrors the Phase-O bootstrap convention (orchestrator/.env.example
    et al.): one assignment per line; ``#`` comments; surrounding single
    or double quotes stripped; values with embedded ``=`` keep everything
    after the first ``=``. Blank lines + malformed lines silently skipped.

    Kept deliberately simple — full python-dotenv-style interpolation
    would be a footgun (env files routinely reference variables defined
    elsewhere in the file, but we expand against a snapshot we don't
    fully know, so the result would be surprising). The Phase-O bootstrap
    discipline is explicit: each KEY=VALUE stands alone.
    """
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # Strip matching surrounding quotes (preserve quote-mismatched).
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ('"', "'")
        ):
            value = value[1:-1]
        out[key] = value
    return out


def _merge_project_env_file(
    env: dict[str, str], workspace_path: str | None
) -> dict[str, str]:
    """v0.6.8: merge ``<workspace_path>/.rka/.env`` into env.

    Returns a NEW dict (does not mutate input). Project values WIN over
    inherited (env). Three guards:

      1. If ``workspace_path`` is falsy → return env unchanged.
      2. If the .env file is missing or unreadable → return env unchanged
         (log a debug-level message; never raise — a missing file is the
         normal case for projects that don't use per-project creds).
      3. Keys in ``_ENV_VARS_TO_SCRUB`` are silently dropped from the
         merged result. The auth-scrub invariant ``_scrubbed_env``
         enforces against os.environ must also hold against project
         files — a malicious or misconfigured ``.rka/.env`` can NOT
         re-introduce ``ANTHROPIC_API_KEY`` and re-route subprocess
         auth onto a billable API key.

    Surfaced by the cockpit's hyperscaler-auditing D3 pre-flight audit
    on 2026-06-03: the orchestrator container bind-mounts the project
    workspace per the Phase D2 design, but ``.rka/.env`` was never
    loaded — so per-project API keys (DEEPSEEK, SEC_EDGAR, FRED, WRDS,
    etc.) declared in the documented per-project cred home never
    reached the Executor subprocess. The cockpit could see them via its
    own MCP setup; the run env couldn't. Same "cockpit ≠ run env" trap
    as the Zotero MCP gap.
    """
    if not workspace_path:
        return env
    from pathlib import Path

    env_path = Path(workspace_path) / ".rka" / ".env"
    if not env_path.exists():
        return env
    try:
        body = env_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("could not read %s: %s", env_path, exc)
        return env

    parsed = _parse_dotenv_lines(body)
    if not parsed:
        return env

    merged = dict(env)
    scrubbed = 0
    added = 0
    overrode = 0
    for key, value in parsed.items():
        if key in _ENV_VARS_TO_SCRUB:
            scrubbed += 1
            continue
        if key in merged:
            overrode += 1
        else:
            added += 1
        merged[key] = value

    # Log keys touched (NOT values — keys are non-sensitive, values are
    # creds and never get logged from this helper).
    logger.info(
        "merged .rka/.env from %s: %d added, %d overrode, %d scrubbed",
        workspace_path,
        added,
        overrode,
        scrubbed,
    )
    return merged


# ---------------------------------------------------------------------------
# Phase G2 — FS Actuator can_use_tool hook
# ---------------------------------------------------------------------------
#
# The Phase G MVP shipped `orchestrator/fs_actuator.py` with a `classify_fs_action`
# policy and prompt-level Brain/Executor guidance to self-classify each FS
# action. Phase G2 closes the enforcement loop: the SDK's `can_use_tool`
# callback fires in the parent process for every tool invocation the
# subprocess attempts. We consult `classify_fs_action` and:
#
#   - allow `read` and `scoped_write`  (return PermissionResultAllow)
#   - deny `ratify_required` with a message telling the LLM to use
#     `proposed_fs_actions` instead (return PermissionResultDeny)
#   - deny `deny` with a no-override message + suggestion to escalate
#
# Non-FS tools (rka_*, context7, etc.) are auto-allowed by the hook — the
# subprocess's `allowed_tools` / `disallowed_tools` lists are still the
# primary mechanism for read-vs-write scoping at the MCP layer; this hook
# adds the FS-Actuator policy on top.


def _build_fs_actuator_hook(workspace_path: str):
    """Return an async `can_use_tool` callable wired with `workspace_path`.

    Importing the SDK + fs_actuator inside the closure keeps this module
    importable in tooling envs that don't have either installed; the
    hook is only constructed at SDK-call time inside _async_complete.
    """

    async def can_use_tool(tool_name, tool_input, context):  # noqa: ARG001
        import claude_agent_sdk as sdk

        from orchestrator import fs_actuator

        # Phase G2 defense-in-depth (adversarial-review H1): if any
        # mcp__rka__* WRITE_TOOLS-prefixed call reaches the hook, refuse
        # it explicitly. Today the SDK's `disallowed_tools` blocks
        # before `can_use_tool` fires, so this branch is unreachable.
        # But if an upstream SDK change ever inverts that precedence,
        # this guard prevents silent regression of the Phase 2.7
        # Option C "no writes from subprocess" invariant.
        for write_tool in WRITE_TOOLS:
            mcp_prefixed = f"mcp__{_MCP_SERVER_NAME}__{write_tool}"
            if tool_name == mcp_prefixed:
                return sdk.PermissionResultDeny(
                    message=(
                        f"Phase 2.7 Option C invariant: {tool_name} is a "
                        f"WRITE_TOOLS-class operation and may not run "
                        f"from the subprocess. Emit it in proposed_actions "
                        f"instead so the orchestrator's parent process "
                        f"dispatches it after PI ratification."
                    ),
                    interrupt=False,
                )

        # v0.6.11 — egress audit + control for WebFetch/WebSearch. Previously
        # these fell straight through to the auto-allow below with no
        # inspection and permission_mode='dontAsk'. The credential-exfil
        # target is already removed by server._enforce_workspace_mount_safety
        # (the daemon refuses to mount $HOME / credential dirs), and the
        # research workflow needs open web access — so the default is NOT a
        # hard allowlist. Instead:
        #   (1) audit-log every egress so the PI has a trail,
        #   (2) deny known telemetry/analytics endpoints (blocklist floor),
        #   (3) honor an OPT-IN strict allowlist (ORCHESTRATOR_EGRESS_ALLOWLIST,
        #       comma-separated domains) for security-conscious installs —
        #       when set, only matching hosts are allowed (deny-by-default).
        if tool_name in _EGRESS_TOOLS:
            url = ""
            if isinstance(tool_input, dict):
                url = str(tool_input.get("url") or tool_input.get("query") or "")
            logger.info("subprocess egress: %s %s", tool_name, url[:200])
            low = url.lower()
            try:
                from orchestrator.notifications import WEBHOOK_BLOCKLIST
                if any(host in low for host in WEBHOOK_BLOCKLIST):
                    return sdk.PermissionResultDeny(
                        message=f"egress to telemetry endpoint blocked: {url[:120]}",
                        interrupt=False,
                    )
            except Exception:  # pragma: no cover — blocklist import is best-effort
                pass
            allowlist_raw = os.environ.get("ORCHESTRATOR_EGRESS_ALLOWLIST", "").strip()
            if allowlist_raw:
                allowed = [d.strip().lower() for d in allowlist_raw.split(",") if d.strip()]
                if not any(d in low for d in allowed):
                    return sdk.PermissionResultDeny(
                        message=(
                            f"egress denied: {url[:120]} is not in "
                            f"ORCHESTRATOR_EGRESS_ALLOWLIST"
                        ),
                        interrupt=False,
                    )
            return sdk.PermissionResultAllow()

        # Non-mutating-FS tools auto-allowed — the MCP layer's
        # allowed_tools / disallowed_tools already constrain RKA writes.
        if tool_name not in fs_actuator.FS_ACTUATOR_MUTATING_TOOLS:
            return sdk.PermissionResultAllow()

        # Gap 4b — read bash allowlist mode from env so a workflow can
        # opt in for its segment. (state-level threading would require
        # changes to the SDK options builder; env is the minimum-viable
        # surface for the hook layer.) Default off — pre-4b behavior.
        bash_allowlist_mode = (
            os.environ.get("FS_ACTUATOR_BASH_ALLOWLIST_MODE", "").strip() == "1"
        )
        cls, rationale = fs_actuator.classify_fs_action(
            {"tool": tool_name, "args": tool_input or {}},
            workspace_path=workspace_path,
            bash_allowlist_mode=bash_allowlist_mode,
        )
        if cls in ("read", "scoped_write"):
            return sdk.PermissionResultAllow()
        if cls == "ratify_required":
            return sdk.PermissionResultDeny(
                message=(
                    f"Phase G2 FS-Actuator policy: {tool_name} requires PI "
                    f"ratification — {rationale}. Do NOT retry as a direct "
                    f"call. Instead emit this in your `proposed_fs_actions` "
                    f"block; the orchestrator will dispatch it after the PI "
                    f"accepts via pi_decision_select."
                ),
                interrupt=False,
            )
        # cls == "deny" — no PI override available
        return sdk.PermissionResultDeny(
            message=(
                f"Phase G2 FS-Actuator policy: {tool_name} DENIED — "
                f"{rationale}. This operation has no PI-ratification path "
                f"available. Escalate via rka_submit_checkpoint with the "
                f"mission scope explicitly rewritten to avoid the denied "
                f"operation."
            ),
            interrupt=False,
        )

    return can_use_tool


class _RealSDKClient:
    """Production `SDKClient` wrapping `claude_agent_sdk.query`.

    The SDK is async-native; this class bridges to the sync `complete()`
    Protocol via `asyncio.run` per call. Each call is a one-shot
    interaction (max_turns=1, no tool use) — the right shape for a
    LangGraph node's single LLM round-trip.

    The subprocess env is built via `_scrubbed_env()` so the spawned
    `claude` CLI cannot fall through to ANTHROPIC_API_KEY billing even
    if the caller's process env has it set.
    """

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        project_id: str | None = None,
        workspace_path: str | None = None,
        model: str | None = None,
    ) -> None:
        # Phase 2.9 T1: `project_id` propagates parent's project context to
        # the claude-agent-sdk subprocess's `rka mcp` stdio child via
        # McpStdioServerConfig.env={"RKA_PROJECT": project_id}. Stored at
        # construction time so each `complete()` call uses the same project.
        # (As of v2.6: the env-var threading is dead; project_id is now
        # threaded per-call by the Brain/Executor LLM. See nodes/brain.py
        # BRAIN_SYSTEM + nodes/executor.py EXECUTOR_SYSTEM prompts.)
        #
        # v0.6.8: when `env` is None AND `workspace_path` is supplied, merge
        # ``<workspace>/.rka/.env`` over the scrubbed os.environ snapshot.
        # The Phase D2 bind-mount design assumed per-project creds would
        # reach the subprocess via the bind-mounted workspace, but the
        # actual env-loading step was never wired — this closes the
        # documented-but-unwired path. Explicit `env=` callers (tests)
        # still pass a fully-materialized env unchanged.
        if env is None:
            env = _scrubbed_env()
            env = _merge_project_env_file(env, workspace_path)
        self._env = env
        self._project_id = project_id
        # Phase G2: workspace_path drives the `can_use_tool` hook's
        # workspace-escape detection. When None, falls back to
        # HOST_WORKSPACE_ROOT — broader but still meaningfully scoped
        # (host root, not /etc). For mission workflows the runner should
        # pass the project-specific workspace_path explicitly to get
        # per-project containment.
        self._workspace_path = workspace_path
        # Optional explicit model id (e.g. "claude-opus-4-8"). None → the SDK /
        # claude CLI default model. Threaded into ClaudeAgentOptions(model=...)
        # so callers can pin a model (the orchestrator's Brain/Executor run on
        # the PI's subscription model; the eval pins Opus 4.8 for reproducibility).
        self._model = model
        # Phase E4: cost of the most recent complete() call in USD,
        # extracted from the SDK's ResultMessage. Nodes read this after
        # complete() and add to state["usd_spent"] for budget tracking.
        # Reset to 0.0 at the start of every complete().
        self.last_call_cost_usd: float = 0.0

    def _resolve_workspace_path(self) -> str:
        """Phase G2: pick the workspace_path for the FS Actuator hook.

        Priority: explicit `self._workspace_path` (set by the runner when
        a workflow has a project-specific workspace) → HOST_WORKSPACE_ROOT
        env var (broader fallback — host root, not /etc) → empty string
        (in which case `classify_fs_action` skips Write/Edit escape
        detection but still enforces DENY-tier bash patterns).
        """
        if self._workspace_path:
            return self._workspace_path
        return os.environ.get("HOST_WORKSPACE_ROOT", "").strip()

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,  # noqa: ARG002 — Protocol-required; SDK manages tokens
        system: str | None = None,
        timeout_s: float | None = None,
    ) -> str:
        return asyncio.run(
            self._async_complete(prompt=prompt, system=system, timeout_s=timeout_s)
        )

    async def _async_complete(
        self,
        *,
        prompt: str,
        system: str | None,
        timeout_s: float | None = None,
    ) -> str:
        # Import here so the module can be imported in environments that
        # don't have claude-agent-sdk yet (e.g., a clean tooling env that
        # only needs the SDKClient Protocol for typing).
        import claude_agent_sdk as sdk

        # Phase 2.7 Option C: subprocess gets read-only MCP scope. If the
        # `rka` binary isn't on PATH, fall back to Phase 1 text-only mode so
        # tests + clean environments still work; log so the degradation is
        # visible.
        # Phase 2.9 T1: `project_id` threads through to McpStdioServerConfig.env
        # so the subprocess inherits the parent's project context.
        rka_binary = _find_rka_mcp_binary()
        # v0.6.8: pass self._env so _build_zotero_server_if_configured can
        # read project-local creds that arrived via _merge_project_env_file
        # (e.g. project's .rka/.env declared ZOTERO_API_KEY but the daemon
        # container's env doesn't). Without env=, Zotero would only wire
        # when creds were in the daemon's own env block.
        mcp_servers = _build_mcp_servers_config(
            rka_binary, project_id=self._project_id, env=self._env
        )

        if mcp_servers:
            include_context7 = _CONTEXT7_SERVER_NAME in mcp_servers
            include_zotero = _ZOTERO_SERVER_NAME in mcp_servers
            # Phase G2: install the FS-Actuator can_use_tool hook so
            # destructive Bash/Write/Edit invocations from the subprocess
            # are intercepted in the parent process and routed per the
            # `fs_actuator.classify_fs_action` policy. SDK MCP/RKA tools
            # are always allowed by the hook (it only enforces FS
            # mutating-tool policy); RKA writes remain disallowed_tools
            # so they still flow through `proposed_actions` → PI ratify.
            options = sdk.ClaudeAgentOptions(
                model=self._model,
                system_prompt=system,
                env=self._env,
                mcp_servers=mcp_servers,
                # Only servers in our config are loaded; no host MCP config bleed.
                # With Phase-A expansion, our config can include `rka`,
                # `context7`, and (v0.6.8) `zotero` — all are PI-ratified
                # for the Brain/Executor subprocess via the manifest.
                strict_mcp_config=True,
                allowed_tools=_all_allowed_subprocess_tools(
                    include_context7, include_zotero=include_zotero
                ),
                disallowed_tools=_prefixed_tools(WRITE_TOOLS)
                + _prefixed_tools(_V27_WRITE_DISPATCH_TOOLS),
                permission_mode="dontAsk",   # deny anything off-allowlist silently
                can_use_tool=_build_fs_actuator_hook(
                    self._resolve_workspace_path(),
                ),
            )
        else:
            logger.warning(
                "rka MCP binary not found on PATH; subprocess will have no MCP "
                "scope (Phase 1 text-only fallback). executor.mission_execute "
                "cannot do work in this configuration."
            )
            options = sdk.ClaudeAgentOptions(
                model=self._model,
                system_prompt=system,
                env=self._env,
                allowed_tools=[],
            )

        # Reset cost tracker; populated from ResultMessage if the SDK emits one.
        self.last_call_cost_usd = 0.0

        # Phase G2 follow-up — when `can_use_tool` is set on options, the SDK
        # requires `prompt` to be an `AsyncIterable[dict]`, not a string. We
        # wrap the string prompt in a one-shot async generator emitting the
        # canonical streaming-input shape per claude_agent_sdk.query docstring:
        #   { "type": "user",
        #     "message": {"role": "user", "content": "..."},
        #     "parent_tool_use_id": None,
        #     "session_id": "..." }
        # Empirically surfaced as `RuntimeError: can_use_tool callback requires
        # streaming mode. Please provide prompt as an AsyncIterable instead of
        # a string.` on the first Run-5 launch after Phase G2 landed.
        async def _streaming_prompt():
            yield {
                "type": "user",
                "message": {"role": "user", "content": prompt},
                "parent_tool_use_id": None,
                "session_id": "rka-orchestrator-brain-executor",
            }

        prompt_input = _streaming_prompt() if mcp_servers else prompt

        # Phase S4 — per-call timeout. `asyncio.wait_for` cancels the
        # inner coroutine on expiry; the SDK's async generator + any
        # in-flight subprocess pipe wait both unwind cleanly through
        # standard asyncio cancellation. We accumulate `parts` inside
        # the inner coroutine so a partial reply is discarded on
        # timeout (the node sees `SDKTimeoutError` and routes to
        # escalation; there is no "use what we got" semantics).
        async def _consume_stream() -> str:
            parts: list[str] = []
            async for message in sdk.query(prompt=prompt_input, options=options):
                if isinstance(message, sdk.AssistantMessage):
                    for block in message.content:
                        text = getattr(block, "text", None)
                        if text:
                            parts.append(text)
                elif isinstance(message, getattr(sdk, "ResultMessage", type(None))):
                    # Phase E4: SDK's terminal ResultMessage carries
                    # `total_cost_usd` (USD spent on this turn). Extract for
                    # workflow budget tracking. Some SDK versions / fake
                    # implementations may not have this field — degrade
                    # gracefully to 0.
                    cost = getattr(message, "total_cost_usd", None)
                    if isinstance(cost, (int, float)) and cost >= 0:
                        self.last_call_cost_usd = float(cost)
            return "".join(parts)

        if timeout_s is None:
            return await _consume_stream()
        try:
            return await asyncio.wait_for(_consume_stream(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise SDKTimeoutError(
                f"SDKClient.complete() exceeded {timeout_s:.0f}s budget"
            ) from exc


def make_sdk(
    project_id: str | None = None,
    *,
    workspace_path: str | None = None,
    model: str | None = None,
) -> SDKClient:
    """Construct the production SDK client.

    Args:
        project_id: Phase 2.9 T1 — when set, propagates as
            `McpStdioServerConfig.env={"RKA_PROJECT": project_id}` to the
            subprocess's `rka mcp` stdio child, so the subprocess MCP
            session inherits the parent's project context. Phase 2.8
            surfaced this gap empirically; Phase 2.9 closes it. Defaults
            to None for back-compat (pre-Phase-2.9 callers continue to
            work; subprocess falls through to its default project session).
        workspace_path: Phase G2 — explicit workspace_path for the
            FS-Actuator can_use_tool hook to enforce Write/Edit escape
            detection against. When None, the hook falls back to
            `HOST_WORKSPACE_ROOT` env var (broader but still meaningful).
            For mission workflows the runner should pass the project-
            specific workspace to get per-project containment instead of
            host-root containment.

    Pre-flight checks (in order):
      1. Auth-path verification — emit a single INFO log naming the
         resolved auth path (label only; never the credential value).
         Emit a WARNING if `ANTHROPIC_API_KEY` was found and scrubbed.
      2. Build a scrubbed env (minus billing-routing vars) and hand it
         to the SDK wrapper.
      3. Return the wrapper as an `SDKClient`-satisfying object.

    Does NOT make a network call. The first network call happens on the
    first `complete()` invocation.
    """
    report = _verify_claude_max_routing()
    if report.warning:
        logger.warning(report.warning)
    logger.info("Claude Agent SDK auth path: %s", report.auth_path)

    if report.auth_path == _AUTH_PATH_NONE:
        # Surface a clean exception so the caller can decide whether to
        # surface as a checkpoint vs continue with a mock.
        raise RuntimeError(
            "No Claude Max credentials found (no credentials.json, no "
            "Keychain entry, no OAuth token in env). Run `claude login`."
        )

    return _RealSDKClient(
        env=_scrubbed_env(),
        project_id=project_id,
        workspace_path=workspace_path,
        model=model,
    )


__all__ = [
    "SDKClient",
    "make_sdk",
    "AuthRoutingReport",
    "_verify_claude_max_routing",  # exposed for tests + T2 instrumentation
    # Phase 2.7 T2 — subprocess MCP scope (exposed for tests + T3 consumers)
    "READ_TOOLS",
    "WRITE_TOOLS",
    "_BUILTIN_FILESYSTEM_TOOLS",
    "_prefixed_tools",
    "_find_rka_mcp_binary",
    "_build_mcp_servers_config",
    "_all_allowed_subprocess_tools",
    "_build_fs_actuator_hook",  # Phase G2
    # v0.6.8 — Zotero MCP wiring + .rka/.env propagation
    "_find_zotero_mcp_binary",
    "_build_zotero_server_if_configured",
    "_parse_dotenv_lines",
    "_merge_project_env_file",
    "_ZOTERO_SERVER_NAME",
    "_ZOTERO_TOOLS",
    "Capability",  # Phase 2.14 — capability categories
    "ALL_CAPABILITIES",
    "TOOL_CAPABILITIES",
    "tools_for_capabilities",
    "capability_of",
]
