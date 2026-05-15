"""Claude SDK client abstraction.

Nodes call Claude via the `SDKClient` Protocol. T7 binds the real
`claude-agent-sdk` async client; tests inject fakes via the same Protocol.

Keeping the SDK call surface narrow (one `complete()` method) lets the
nodes stay pure functions of `(state, sdk, mcp) -> state_update` and lets
T11's audit-symmetry walk only one entry point per LLM hop.
"""

from __future__ import annotations

from typing import Protocol


class SDKClient(Protocol):
    """Synchronous wrapper around the Claude Agent SDK.

    A real implementation (T7) wraps `claude_agent_sdk.AsyncClient` with
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


def make_sdk() -> SDKClient:
    """Construct the production SDK client. Wired in T7."""
    raise NotImplementedError("make_sdk arrives in T7")
