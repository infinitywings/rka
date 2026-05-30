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
from typing import Any, Protocol

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
)

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

# Parent-side WRITE_TOOLS registry. Subprocess `disallowed_tools` mirrors this list
# (prefixed); the orchestrator's `executor.execute_ratified_actions` node (T3) is the
# only call site that invokes these. `rka_update_note` joins MCPClient Protocol in T3
# (pre-registered here per T1 ratification).
#
# Phase 2.13 (mis_01KRYZMEAT01SMNNXQXS3JRC4W T2; per dec_01KRYZGF8N1SNJX5TSP0GM77Z7
# Option A): `rka_bulk_update` added as 7th entry. Closes the 10th trigger surfaced
# empirically by Phase 2.12 — brain LLM methodologically chose rka_bulk_update for
# cross-reference hygiene (target journal documented using it), but it was not
# allowlisted. The matching Protocol method + RestMCPClient fanout adapter shipped
# in T1 (commit bb6d008).
WRITE_TOOLS: tuple[str, ...] = (
    "rka_add_note",
    "rka_add_decision",
    "rka_submit_checkpoint",
    "rka_submit_report",
    "rka_create_mission",
    "rka_update_note",
    "rka_bulk_update",
    # Phase-A2 (agentic, PI-ratified scope expansion) — added after
    # Phase-1 IoT-edge-LLM mission's first pi_decision_select surfaced
    # the gap. Brain proposed these tools (real, exposed by the rka MCP
    # server) but execute_ratified_actions correctly rejected them
    # because they were not in WRITE_TOOLS. Now allowlisted with
    # matching MCPClient Protocol methods + RestMCPClient impls.
    "rka_update_mission_status",
    "rka_ingest_document",
)


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


def _all_allowed_subprocess_tools(include_context7: bool) -> list[str]:
    """Compose the full `allowed_tools` list across every MCP server the
    subprocess is configured to talk to plus the built-in filesystem tools
    the Executor needs to actually do mission work. Lives separately from
    READ_TOOLS so the legacy single-server interface stays back-compat."""
    tools = _prefixed_tools(READ_TOOLS)  # rka MCP
    if include_context7:
        tools.extend(_prefixed_tools(_CONTEXT7_TOOLS, server=_CONTEXT7_SERVER_NAME))
    tools.extend(_BUILTIN_FILESYSTEM_TOOLS)
    return tools


def _find_rka_mcp_binary() -> str | None:
    """Locate the local `rka` MCP stdio binary on PATH. Returns the absolute
    path if found, None otherwise. Discovered at SDK-call time (not import
    time) so tests can monkeypatch this independently."""
    return shutil.which("rka")


def _build_mcp_servers_config(
    rka_binary: str | None, project_id: str | None = None
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

    return config


class SDKClient(Protocol):
    """Synchronous wrapper around the Claude Agent SDK.

    A real implementation (T7) wraps `claude_agent_sdk.query` with
    `asyncio.run` for sync calling from within LangGraph nodes (Phase 1
    has no concurrency that would benefit from async; the SDK call is the
    only place we'd block, and the node IS the work unit).
    """

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> str:
        """Issue a single LLM call. Returns the assistant's text reply."""
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
    ) -> None:
        # Phase 2.9 T1: `project_id` propagates parent's project context to
        # the claude-agent-sdk subprocess's `rka mcp` stdio child via
        # McpStdioServerConfig.env={"RKA_PROJECT": project_id}. Stored at
        # construction time so each `complete()` call uses the same project.
        self._env = env if env is not None else _scrubbed_env()
        self._project_id = project_id

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,  # noqa: ARG002 — Protocol-required; SDK manages tokens
        system: str | None = None,
    ) -> str:
        return asyncio.run(self._async_complete(prompt=prompt, system=system))

    async def _async_complete(self, *, prompt: str, system: str | None) -> str:
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
        mcp_servers = _build_mcp_servers_config(rka_binary, project_id=self._project_id)

        if mcp_servers:
            include_context7 = _CONTEXT7_SERVER_NAME in mcp_servers
            options = sdk.ClaudeAgentOptions(
                system_prompt=system,
                env=self._env,
                mcp_servers=mcp_servers,
                # Only servers in our config are loaded; no host MCP config bleed.
                # With Phase-A expansion, our config can include both `rka` and
                # `context7` — both are PI-ratified for the Brain subprocess.
                strict_mcp_config=True,
                allowed_tools=_all_allowed_subprocess_tools(include_context7),
                disallowed_tools=_prefixed_tools(WRITE_TOOLS),
                permission_mode="dontAsk",   # deny anything off-allowlist silently
            )
        else:
            logger.warning(
                "rka MCP binary not found on PATH; subprocess will have no MCP "
                "scope (Phase 1 text-only fallback). executor.mission_execute "
                "cannot do work in this configuration."
            )
            options = sdk.ClaudeAgentOptions(
                system_prompt=system,
                env=self._env,
                allowed_tools=[],
            )

        parts: list[str] = []
        async for message in sdk.query(prompt=prompt, options=options):
            if isinstance(message, sdk.AssistantMessage):
                for block in message.content:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
        return "".join(parts)


def make_sdk(project_id: str | None = None) -> SDKClient:
    """Construct the production SDK client.

    Args:
        project_id: Phase 2.9 T1 — when set, propagates as
            `McpStdioServerConfig.env={"RKA_PROJECT": project_id}` to the
            subprocess's `rka mcp` stdio child, so the subprocess MCP
            session inherits the parent's project context. Phase 2.8
            surfaced this gap empirically; Phase 2.9 closes it. Defaults
            to None for back-compat (pre-Phase-2.9 callers continue to
            work; subprocess falls through to its default project session).

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

    return _RealSDKClient(env=_scrubbed_env(), project_id=project_id)


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
]
