"""Phase S4 — per-call LLM-timeout test surface.

Covers three layers:

1. **Protocol contract** — `SDKClient.complete()` accepts `timeout_s` as
   a kwarg; the real impl wraps the streaming loop in `asyncio.wait_for`
   and raises `SDKTimeoutError` on expiry.

2. **Per-node timeout handling** — all 9 `sdk.complete()` call sites
   across `brain.py` (6) + `executor.py` (3) catch `SDKTimeoutError`
   and return the canonical `llm_call_timeout` ErrorRecord with
   `next_node_override='escalation_router'`. Each node's per-call
   timeout constant is passed explicitly so the wire matches the
   intended budget.

3. **Routing** — `escalation_router` happily classifies the new error
   type without graph topology change.

Phase D2.6 (segment-level watchdog) and Phase S4 (per-call timeout)
are complementary: the segment watchdog catches stalls AFTER a graph
segment returns without advancing; this per-call layer catches a
single hung LLM call BEFORE the segment ever finishes. A real
hang surfaces as a classified `llm_call_timeout` ErrorRecord
rather than as the segment-watchdog's opaque "no progress" message.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from orchestrator import llm_client
from orchestrator.llm_client import (
    SDK_TIMEOUT_BACKBRIEF_S,
    SDK_TIMEOUT_DEFAULT_S,
    SDK_TIMEOUT_TOOL_USE_S,
    SDKClient,
    SDKTimeoutError,
)
from orchestrator.nodes import brain, executor
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP


# ---------------------------------------------------------------------------
# Test doubles: SDK fake that raises SDKTimeoutError on demand
# ---------------------------------------------------------------------------


@dataclass
class _TimeoutSDK:
    """SDK fake that always raises SDKTimeoutError on complete().

    Mirrors the `SDKClient.complete()` Protocol surface exactly so it
    drops in where the canonical `FakeSDK` would. Records every call
    so tests can assert which budget the node passed.
    """

    last_call_cost_usd: float = 0.0
    calls: list[dict] = field(default_factory=list)

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        system: str | None = None,
        timeout_s: float | None = None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "system": system,
                "timeout_s": timeout_s,
            }
        )
        raise SDKTimeoutError(
            f"SDKClient.complete() exceeded {timeout_s or 0:.0f}s budget"
        )


def _initial_state() -> dict:
    return make_initial_state(
        workflow_thread_id="thr_test_s4",
        mission_id="mis_test_s4",
        motivated_by_decision_id="dec_test_s4",
    )


def _assert_timeout_error_state(
    update: dict,
    *,
    node_name: str,
    current_phase: str,
    timeout_s: float,
) -> None:
    """Standard assertion bundle for an S4 timeout error_state."""
    assert update["current_phase"] == current_phase
    assert update["current_node"] == node_name
    assert update["next_node_override"] == "escalation_router"
    errs = update["errors"]
    assert len(errs) == 1
    err = errs[0]
    assert err["node_name"] == node_name
    assert err["error_type"] == "llm_call_timeout"
    assert f"{timeout_s:.0f}s budget" in err["detail"]
    assert node_name in err["detail"]
    assert err["timestamp"]  # ISO-8601 stamp present
    # Crucially, the error_state should NOT carry the node's
    # happy-path side effects (no artifacts, no usd_spent, no
    # node-specific output). escalation_router needs a clean
    # error signal, not a polluted dict.
    assert "artifacts" not in update
    assert "usd_spent" not in update


# ---------------------------------------------------------------------------
# Layer 1 — Protocol contract
# ---------------------------------------------------------------------------


class TestSDKTimeoutErrorClass:
    def test_sdkclient_protocol_has_timeout_s_kwarg(self):
        """The Protocol's `complete()` declares timeout_s."""
        import inspect

        sig = inspect.signature(SDKClient.complete)
        assert "timeout_s" in sig.parameters
        # Default must be None so callers and fakes that don't pass it
        # see the legacy unbounded behavior.
        assert sig.parameters["timeout_s"].default is None

    def test_sdktimeouterror_is_an_exception(self):
        """Distinct from asyncio.TimeoutError; nodes catch the Protocol type."""
        assert issubclass(SDKTimeoutError, Exception)
        # Must NOT subclass asyncio.TimeoutError — we want a single
        # vocabulary at the Protocol boundary.
        assert not issubclass(SDKTimeoutError, asyncio.TimeoutError)

    def test_timeout_constants_are_floats_and_ordered(self):
        """Per-node budgets are sane: default < backbrief < tool_use."""
        assert isinstance(SDK_TIMEOUT_DEFAULT_S, float)
        assert isinstance(SDK_TIMEOUT_BACKBRIEF_S, float)
        assert isinstance(SDK_TIMEOUT_TOOL_USE_S, float)
        # Ordering matches the semantic intent — tool-use loop is
        # the heaviest, plain LLM call the lightest.
        assert SDK_TIMEOUT_DEFAULT_S < SDK_TIMEOUT_BACKBRIEF_S
        assert SDK_TIMEOUT_BACKBRIEF_S < SDK_TIMEOUT_TOOL_USE_S
        # All > 60 seconds — too-tight floors would intercept legit
        # slow LLM calls, which is the explicit anti-goal.
        assert SDK_TIMEOUT_DEFAULT_S > 60.0


class TestAsyncioWaitForIntegration:
    """Drive `_async_complete` with a stub `claude_agent_sdk` module so we
    can prove the asyncio.wait_for wrapper actually fires SDKTimeoutError
    when the streaming loop hangs longer than `timeout_s`.
    """

    @pytest.mark.asyncio
    async def test_hung_stream_raises_sdk_timeout_error(self, monkeypatch):
        """When the SDK's async generator never yields, wait_for cancels
        and the wrapper translates asyncio.TimeoutError → SDKTimeoutError."""

        # Build a fake `claude_agent_sdk` module surface.
        class _StubAssistantMessage:
            content: list[Any] = []

        class _StubResultMessage:
            total_cost_usd: float = 0.0

        class _StubOptions:
            def __init__(self, **kw):
                self.kw = kw

        async def _hung_query(*, prompt, options):  # noqa: ARG001
            # Sleep way longer than the test's timeout_s to guarantee
            # wait_for fires. asyncio.sleep is cancellable, so the
            # cancellation propagates cleanly.
            await asyncio.sleep(60.0)
            yield _StubAssistantMessage()  # never reached

        # SimpleNamespace so `stub_sdk.query` stays a plain async-generator
        # function (NOT a bound method that would receive self as a
        # positional arg the real `claude_agent_sdk.query` doesn't take).
        stub_sdk = SimpleNamespace(
            AssistantMessage=_StubAssistantMessage,
            ResultMessage=_StubResultMessage,
            ClaudeAgentOptions=_StubOptions,
            query=_hung_query,
        )
        monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", stub_sdk)

        # Build the real client. We bypass make_sdk()'s pre-flight by
        # constructing the wrapper directly via its class.
        from orchestrator.llm_client import _RealSDKClient

        client = _RealSDKClient(env={}, project_id="", workspace_path="")

        # Disable the rka MCP binary discovery so the streaming-input
        # path is exercised but no real subprocess is spawned. We
        # monkeypatch `_find_rka_mcp_binary` to return None.
        monkeypatch.setattr(llm_client, "_find_rka_mcp_binary", lambda: None)

        with pytest.raises(SDKTimeoutError) as excinfo:
            await client._async_complete(
                prompt="hello", system=None, timeout_s=0.1
            )
        assert "0s budget" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_fast_stream_returns_text_normally(self, monkeypatch):
        """With a fast stream and a generous timeout, the wrapper returns
        the accumulated text — the bound is a CEILING, not a floor."""

        class _StubBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class _StubAssistantMessage:
            def __init__(self, parts: list[str]) -> None:
                self.content = [_StubBlock(p) for p in parts]

        class _StubResultMessage:
            total_cost_usd: float = 0.0042

        class _StubOptions:
            def __init__(self, **kw):
                self.kw = kw

        async def _fast_query(*, prompt, options):  # noqa: ARG001
            yield _StubAssistantMessage(["hello ", "world"])
            yield _StubResultMessage()

        stub_sdk = SimpleNamespace(
            AssistantMessage=_StubAssistantMessage,
            ResultMessage=_StubResultMessage,
            ClaudeAgentOptions=_StubOptions,
            query=_fast_query,
        )
        monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", stub_sdk)
        monkeypatch.setattr(llm_client, "_find_rka_mcp_binary", lambda: None)

        from orchestrator.llm_client import _RealSDKClient

        client = _RealSDKClient(env={}, project_id="", workspace_path="")
        text = await client._async_complete(
            prompt="hi", system=None, timeout_s=30.0
        )
        assert text == "hello world"
        # Cost extraction still works behind the wait_for wrapper.
        assert client.last_call_cost_usd == pytest.approx(0.0042)

    @pytest.mark.asyncio
    async def test_no_timeout_when_timeout_s_is_none(self, monkeypatch):
        """timeout_s=None reverts to unbounded legacy behavior — no
        wait_for wrapping, no SDKTimeoutError. Verified by simulating
        a stream slower than any reasonable bound."""

        class _StubBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class _StubAssistantMessage:
            def __init__(self, parts: list[str]) -> None:
                self.content = [_StubBlock(p) for p in parts]

        class _StubResultMessage:
            total_cost_usd: float = 0.0

        class _StubOptions:
            def __init__(self, **kw):
                self.kw = kw

        async def _slow_query(*, prompt, options):  # noqa: ARG001
            await asyncio.sleep(0.2)  # would trigger any sane bound
            yield _StubAssistantMessage(["ok"])
            yield _StubResultMessage()

        stub_sdk = SimpleNamespace(
            AssistantMessage=_StubAssistantMessage,
            ResultMessage=_StubResultMessage,
            ClaudeAgentOptions=_StubOptions,
            query=_slow_query,
        )
        monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", stub_sdk)
        monkeypatch.setattr(llm_client, "_find_rka_mcp_binary", lambda: None)

        from orchestrator.llm_client import _RealSDKClient

        client = _RealSDKClient(env={}, project_id="", workspace_path="")
        text = await client._async_complete(
            prompt="hi", system=None, timeout_s=None
        )
        assert text == "ok"


# ---------------------------------------------------------------------------
# Layer 2 — Per-node timeout handling
# ---------------------------------------------------------------------------


class TestBrainNodeTimeouts:
    """All 6 Brain sdk.complete() call sites must:
      1. Pass their per-node `timeout_s` constant explicitly.
      2. Catch SDKTimeoutError + return the canonical error_state.
    """

    def test_strategy_node_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = brain.strategy_node(_initial_state(), sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="strategy_node",
            current_phase="brain_strategy",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )
        # No MCP write happened — the timeout fired BEFORE rka_add_note.
        ops = [c["op"] for c in mcp.calls]
        assert "rka_add_note" not in ops

    def test_confirmation_brief_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = brain.confirmation_brief(_initial_state(), sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="confirmation_brief",
            current_phase="brain_confirmation",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )

    def test_decision_present_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        # Empty proposed_actions forces the LLM-driven strategic-meta-
        # decision path (the only sdk.complete() in decision_present).
        state = _initial_state()
        update = brain.decision_present(state, sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="decision_present",
            current_phase="brain_review",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )

    def test_cluster_review_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = brain.cluster_review(_initial_state(), sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="cluster_review",
            current_phase="brain_review",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )

    def test_gate1_validation_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = brain.gate1_validation(_initial_state(), sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="gate1_validation",
            current_phase="brain_review",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )

    def test_final_synthesis_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = brain.final_synthesis(_initial_state(), sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="final_synthesis",
            current_phase="brain_synthesis",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )


class TestExecutorNodeTimeouts:
    """All 3 Executor sdk.complete() call sites must:
      1. Pass their per-node `timeout_s` constant explicitly
         (backbrief has a larger budget; mission_execute the largest).
      2. Catch SDKTimeoutError + return the canonical error_state.
    """

    def test_backbrief_draft_timeout_uses_backbrief_budget(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = executor.backbrief_draft(_initial_state(), sdk, mcp)

        # backbrief gets the dedicated, larger budget (does MCP reads).
        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_BACKBRIEF_S
        _assert_timeout_error_state(
            update,
            node_name="backbrief_draft",
            current_phase="executor_backbrief",
            timeout_s=SDK_TIMEOUT_BACKBRIEF_S,
        )

    def test_mission_execute_timeout_uses_tool_use_budget(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = executor.mission_execute(_initial_state(), sdk, mcp)

        # mission_execute iterates tool-use turns — largest budget.
        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_TOOL_USE_S
        _assert_timeout_error_state(
            update,
            node_name="mission_execute",
            current_phase="executor_execute",
            timeout_s=SDK_TIMEOUT_TOOL_USE_S,
        )

    def test_submit_report_timeout(self):
        sdk = _TimeoutSDK()
        mcp = FakeMCP()
        update = executor.submit_report(_initial_state(), sdk, mcp)

        assert sdk.calls[0]["timeout_s"] == SDK_TIMEOUT_DEFAULT_S
        _assert_timeout_error_state(
            update,
            node_name="submit_report",
            current_phase="executor_report",
            timeout_s=SDK_TIMEOUT_DEFAULT_S,
        )


# ---------------------------------------------------------------------------
# Layer 3 — Coverage gates so future call sites can't ship without a wrap
# ---------------------------------------------------------------------------


class TestCallSiteCoverage:
    """Lock-tests: if a new `sdk.complete()` site is added without the
    Phase S4 try/except wrap, these fail. Counted via source scan
    (cheap; no AST parse needed for this tight surface)."""

    def test_brain_py_all_complete_sites_are_wrapped(self):
        """Every `sdk.complete(...)` in brain.py must be inside a try
        block, identified by the immediately-preceding `try:` line."""
        from pathlib import Path

        src = Path(brain.__file__).read_text()
        lines = src.splitlines()
        complete_call_lines = [
            i for i, ln in enumerate(lines) if "sdk.complete(" in ln and "exceeded" not in ln
        ]
        # Skip docstring references (the _accrue_cost comment mentions it).
        complete_call_lines = [
            i for i, ln in enumerate(lines)
            if "sdk.complete(" in ln
            and not lines[i].lstrip().startswith("#")
            and not lines[i].lstrip().startswith('"')
            and "exceeded" not in ln
            and "Every Brain" not in ln
        ]
        # The 6 actual call sites — each line should have a `try:` within
        # the prior 3 lines (allow for arg-line spread).
        assert len(complete_call_lines) == 6, (
            f"expected 6 sdk.complete() sites in brain.py, found "
            f"{len(complete_call_lines)} at lines {[l+1 for l in complete_call_lines]}"
        )
        for ln_idx in complete_call_lines:
            window = lines[max(0, ln_idx - 3):ln_idx]
            joined = "\n".join(window)
            assert "try:" in joined, (
                f"sdk.complete() at brain.py:{ln_idx + 1} is NOT inside a "
                f"try block — Phase S4 timeout wrap missing.\nContext:\n"
                f"{joined}\n{lines[ln_idx]}"
            )

    def test_executor_py_all_complete_sites_are_wrapped(self):
        """Same lock-test for the 3 Executor call sites."""
        from pathlib import Path

        src = Path(executor.__file__).read_text()
        lines = src.splitlines()
        complete_call_lines = [
            i for i, ln in enumerate(lines)
            if "sdk.complete(" in ln
            and not lines[i].lstrip().startswith("#")
            and not lines[i].lstrip().startswith('"')
            and "exceeded" not in ln
            and "Executor node" not in ln
        ]
        # 4 sites: backbrief_draft, mission_execute, submit_report, and
        # v0.6.11 mission_redraft — all must be wrapped.
        assert len(complete_call_lines) == 4, (
            f"expected 4 sdk.complete() sites in executor.py, found "
            f"{len(complete_call_lines)} at lines {[l+1 for l in complete_call_lines]}"
        )
        for ln_idx in complete_call_lines:
            window = lines[max(0, ln_idx - 3):ln_idx]
            joined = "\n".join(window)
            assert "try:" in joined, (
                f"sdk.complete() at executor.py:{ln_idx + 1} is NOT inside a "
                f"try block — Phase S4 timeout wrap missing.\nContext:\n"
                f"{joined}\n{lines[ln_idx]}"
            )

    def test_brain_and_executor_export_sdk_timeout_error(self):
        """Both modules must import SDKTimeoutError so they can `except`
        it. A regression where the import is dropped would silently
        let SDKTimeoutError propagate out as an unhandled exception
        (the segment watchdog would catch the segment failure but the
        per-node classified error_type would never land in state.errors).
        """
        from pathlib import Path

        brain_src = Path(brain.__file__).read_text()
        executor_src = Path(executor.__file__).read_text()
        assert "SDKTimeoutError" in brain_src
        assert "SDKTimeoutError" in executor_src


class TestModelSelection:
    """`make_sdk(model=...)` / `_RealSDKClient(model=...)` pins the model id on
    ClaudeAgentOptions so the orchestrator's Brain/Executor run on the requested
    model (the eval pins claude-opus-4-8 for reproducibility)."""

    @pytest.mark.asyncio
    async def test_model_is_threaded_into_options(self, monkeypatch):
        captured: dict = {}

        class _StubBlock:
            def __init__(self, t):
                self.text = t

        class _StubAssistantMessage:
            def __init__(self, parts):
                self.content = [_StubBlock(p) for p in parts]

        class _StubResultMessage:
            total_cost_usd = 0.0

        class _StubOptions:
            def __init__(self, **kw):
                self.kw = kw

        async def _query(*, prompt, options):  # noqa: ARG001
            captured["model"] = options.kw.get("model")
            yield _StubAssistantMessage(["ok"])
            yield _StubResultMessage()

        stub_sdk = SimpleNamespace(
            AssistantMessage=_StubAssistantMessage,
            ResultMessage=_StubResultMessage,
            ClaudeAgentOptions=_StubOptions,
            query=_query,
        )
        monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", stub_sdk)
        monkeypatch.setattr(llm_client, "_find_rka_mcp_binary", lambda: None)

        from orchestrator.llm_client import _RealSDKClient

        client = _RealSDKClient(env={}, project_id="", workspace_path="",
                                model="claude-opus-4-8")
        text = await client._async_complete(prompt="hi", system=None, timeout_s=None)
        assert text == "ok"
        assert captured["model"] == "claude-opus-4-8"

    @pytest.mark.asyncio
    async def test_model_defaults_to_none(self, monkeypatch):
        captured: dict = {}

        class _StubBlock:
            def __init__(self, t):
                self.text = t

        class _StubAssistantMessage:
            def __init__(self, parts):
                self.content = [_StubBlock(p) for p in parts]

        class _StubResultMessage:
            total_cost_usd = 0.0

        class _StubOptions:
            def __init__(self, **kw):
                self.kw = kw

        async def _query(*, prompt, options):  # noqa: ARG001
            captured["model"] = options.kw.get("model", "MISSING")
            yield _StubAssistantMessage(["ok"])
            yield _StubResultMessage()

        stub_sdk = SimpleNamespace(
            AssistantMessage=_StubAssistantMessage,
            ResultMessage=_StubResultMessage,
            ClaudeAgentOptions=_StubOptions,
            query=_query,
        )
        monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", stub_sdk)
        monkeypatch.setattr(llm_client, "_find_rka_mcp_binary", lambda: None)

        from orchestrator.llm_client import _RealSDKClient

        client = _RealSDKClient(env={}, project_id="", workspace_path="")
        await client._async_complete(prompt="hi", system=None, timeout_s=None)
        # model key is present (None) — back-compat: SDK falls through to default.
        assert captured["model"] is None


class TestV27DispatchAllowlist:
    """v2.7.0+ RKA MCP surface: the subprocess must be ALLOWED rka_query +
    rka_describe (read dispatch) and DENIED rka_execute (write dispatch).

    Regression for the 2026-06-15 finding: driving Opus 4.8 against an RKA
    v2.8.0 server, every Brain/Executor read was denied because READ_TOOLS
    only listed legacy rka_get_* names — the subprocess calls rka_query (the
    real read path) and got a permission error under permission_mode='dontAsk'."""

    def test_read_dispatch_tools_in_allowlist(self):
        from orchestrator.llm_client import READ_TOOLS, _all_allowed_subprocess_tools
        assert "rka_query" in READ_TOOLS
        assert "rka_describe" in READ_TOOLS
        allowed = _all_allowed_subprocess_tools(include_context7=False)
        assert "mcp__rka__rka_query" in allowed
        assert "mcp__rka__rka_describe" in allowed
        # the WRITE dispatch must NOT be in the read allowlist
        assert "mcp__rka__rka_execute" not in allowed

    @pytest.mark.asyncio
    async def test_write_dispatch_in_disallowed_and_read_in_allowed(self, monkeypatch):
        captured: dict = {}

        class _StubBlock:
            def __init__(self, t):
                self.text = t

        class _StubAssistantMessage:
            def __init__(self, parts):
                self.content = [_StubBlock(p) for p in parts]

        class _StubResultMessage:
            total_cost_usd = 0.0

        class _StubOptions:
            def __init__(self, **kw):
                self.kw = kw

        async def _query(*, prompt, options):  # noqa: ARG001
            captured["disallowed"] = options.kw.get("disallowed_tools", [])
            captured["allowed"] = options.kw.get("allowed_tools", [])
            yield _StubAssistantMessage(["ok"])
            yield _StubResultMessage()

        stub_sdk = SimpleNamespace(
            AssistantMessage=_StubAssistantMessage,
            ResultMessage=_StubResultMessage,
            ClaudeAgentOptions=_StubOptions,
            query=_query,
        )
        monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", stub_sdk)
        # Force the MCP-server branch (rka binary "present") so disallowed_tools
        # is populated.
        monkeypatch.setattr(llm_client, "_find_rka_mcp_binary", lambda: "/fake/rka")

        from orchestrator.llm_client import _RealSDKClient

        client = _RealSDKClient(env={}, project_id="prj_x", workspace_path="")
        await client._async_complete(prompt="hi", system=None, timeout_s=None)
        assert "mcp__rka__rka_execute" in captured["disallowed"]
        assert "mcp__rka__rka_query" in captured["allowed"]
        assert "mcp__rka__rka_describe" in captured["allowed"]
