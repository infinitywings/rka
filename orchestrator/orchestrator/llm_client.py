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
)

# Parent-side WRITE_TOOLS registry. Subprocess `disallowed_tools` mirrors this list
# (prefixed); the orchestrator's `executor.execute_ratified_actions` node (T3) is the
# only call site that invokes these. `rka_update_note` joins MCPClient Protocol in T3
# (pre-registered here per T1 ratification).
WRITE_TOOLS: tuple[str, ...] = (
    "rka_add_note",
    "rka_add_decision",
    "rka_submit_checkpoint",
    "rka_submit_report",
    "rka_create_mission",
    "rka_update_note",
)


def _prefixed_tools(names: tuple[str, ...]) -> list[str]:
    """Prefix MCP tool names with `mcp__<server_name>__` per the SDK's
    allowed_tools / disallowed_tools naming convention."""
    return [f"mcp__{_MCP_SERVER_NAME}__{n}" for n in names]


def _find_rka_mcp_binary() -> str | None:
    """Locate the local `rka` MCP stdio binary on PATH. Returns the absolute
    path if found, None otherwise. Discovered at SDK-call time (not import
    time) so tests can monkeypatch this independently."""
    return shutil.which("rka")


def _build_mcp_servers_config(
    rka_binary: str | None, project_id: str | None = None
) -> dict:
    """Build the McpStdioServerConfig dict for the subprocess. Returns `{}`
    if no binary found — subprocess falls back to Phase 1 text-only mode
    (caller logs a warning).

    Phase 2.9 (mis_01KRY2KP0GGZY21BA4Z2R2S718 T1; PI-handed-off scope per
    dec_01KRY2EXCSTSSCFZJ96VG4MGDW Option A): when `project_id` is non-None,
    set `McpStdioServerConfig.env = {"RKA_PROJECT": project_id}` so the
    `rka mcp` stdio binary spawned by claude-agent-sdk inherits the parent's
    project context. Closes the 8th mandatory-pause trigger surfaced
    empirically by Phase 2.8 (`mis_01KRXRF6VRFAAV1T8XKZ3RHJXJ`): subprocess
    MCP session inheriting `Default Project` (proj_default) instead of the
    parent's configured `project_id`.

    When `project_id` is None (no parent context), the env key is omitted
    for back-compat — subprocess falls through to its default session
    (typically proj_default). Pre-Phase-2.9 behavior is preserved."""
    if not rka_binary:
        return {}
    server_config: dict = {
        "type": "stdio",
        "command": rka_binary,
        "args": ["mcp"],
    }
    if project_id:
        server_config["env"] = {"RKA_PROJECT": project_id}
    return {_MCP_SERVER_NAME: server_config}


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
            options = sdk.ClaudeAgentOptions(
                system_prompt=system,
                env=self._env,
                mcp_servers=mcp_servers,
                strict_mcp_config=True,   # only `rka` server; no host config bleed
                allowed_tools=_prefixed_tools(READ_TOOLS),
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
    "_prefixed_tools",
    "_find_rka_mcp_binary",
    "_build_mcp_servers_config",
]
