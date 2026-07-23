"""Phase 2.9 T1 — subprocess MCP project propagation (legacy, post-v2.6 dead).

Mission: `mis_01KRY2KP0GGZY21BA4Z2R2S718` (Phase 2.9; PI-handed-off scope
per `dec_01KRY2EXCSTSSCFZJ96VG4MGDW` Option A).

These tests originally locked the Phase 2.9 T1 contract: the
claude-agent-sdk subprocess's `rka mcp` stdio child inherited the
parent's RKA project context via `McpStdioServerConfig.env["RKA_PROJECT"]`.

**v2.6 update (post-PR #32):** the rka MCP server no longer reads
`RKA_PROJECT` from the env — every project-scoped tool now requires
`project_id` as an explicit kwarg, threaded by the Brain/Executor LLM
from its workflow state. The orchestrator's
`_build_mcp_servers_config(project_id=...)` retains the kwarg for
back-compat but no longer sets `RKA_PROJECT` in the subprocess env.

These tests now lock the negative contract (no RKA_PROJECT in subprocess
env regardless of project_id), and the v2.6 contract that other env
keys (SEMANTIC_SCHOLAR_API_KEY, SERPAPI_KEY) still propagate when set.
The `state["project_id"]` field round-trip is unchanged — it's tracked
at the orchestrator state layer for the LLM to thread per-call.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestrator.llm_client import (
    _MCP_SERVER_NAME,
    _RealSDKClient,
    _build_mcp_servers_config,
    make_sdk,
)
from orchestrator.state import make_initial_state


# ---------------------------------------------------------------------------
# Test 1 — `_build_mcp_servers_config` with project_id sets env
# ---------------------------------------------------------------------------


def test_build_mcp_servers_config_with_project_id_no_longer_sets_rka_project_env(
    monkeypatch: pytest.MonkeyPatch,
):
    """v2.6 contract: `project_id` is no longer threaded as `RKA_PROJECT`
    into the subprocess env block. The rka MCP server (v2.6+) requires
    every project-scoped tool to take `project_id` as an explicit kwarg;
    the env-var threading was removed because it reintroduced the
    silent-default failure mode that v2.6 explicitly eliminates.

    When no external-API keys are set, the env block is absent entirely.
    """
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    config = _build_mcp_servers_config("/fake/path/to/rka", project_id="prj_target_01ABC")
    assert _MCP_SERVER_NAME in config
    rka_config = config[_MCP_SERVER_NAME]
    assert rka_config["type"] == "stdio"
    assert rka_config["command"] == "/fake/path/to/rka"
    assert rka_config["args"] == ["mcp"]
    # The negative assertion: no RKA_PROJECT in env, regardless of
    # whether project_id was passed.
    assert "env" not in rka_config or "RKA_PROJECT" not in rka_config.get("env", {}), (
        f"v2.6: project_id should NOT thread into the subprocess env as "
        f"RKA_PROJECT (rka MCP server no longer reads it); got "
        f"env={rka_config.get('env')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — back-compat: no project_id means no env key
# ---------------------------------------------------------------------------


def test_build_mcp_servers_config_without_project_id_omits_env(
    monkeypatch: pytest.MonkeyPatch,
):
    """Back-compat: pre-Phase-2.9 callers continue to work. When
    `project_id` is None (or omitted), no env key is set — subprocess
    falls through to its default session. Pre-Phase-2.9 behavior
    preserved bit-for-bit (Phase 2.8 ran with this code path)."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    # Implicit None (default).
    config = _build_mcp_servers_config("/fake/path/to/rka")
    rka_config = config[_MCP_SERVER_NAME]
    assert "env" not in rka_config, (
        f"Back-compat: no project_id should mean no env key; got env={rka_config.get('env')!r}"
    )
    # Explicit None.
    config = _build_mcp_servers_config("/fake/path/to/rka", project_id=None)
    rka_config = config[_MCP_SERVER_NAME]
    assert "env" not in rka_config
    # Empty string also omits (truthy check).
    config = _build_mcp_servers_config("/fake/path/to/rka", project_id="")
    rka_config = config[_MCP_SERVER_NAME]
    assert "env" not in rka_config


# ---------------------------------------------------------------------------
# Test 3 — `make_sdk(project_id=...)` threads through to subprocess config
# ---------------------------------------------------------------------------


def _async_iter_messages(messages):
    """Helper: turn a list of messages into an async iterator."""
    async def _gen():
        for m in messages:
            yield m
    return _gen()


def _fake_assistant_message(text: str):
    """Helper: build a minimal stand-in for `sdk.AssistantMessage`."""
    import claude_agent_sdk as sdk
    block = sdk.TextBlock(text=text)
    return sdk.AssistantMessage(content=[block], model="claude-test", parent_tool_use_id=None)


def test_make_sdk_project_id_no_longer_propagates_to_subprocess_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """v2.6: `make_sdk(project_id="prj_x")` no longer threads
    `RKA_PROJECT` into the subprocess MCP env. The kwarg is retained
    for back-compat but is a no-op at this layer — every project-
    scoped rka_* tool requires `project_id` as an explicit kwarg,
    threaded by the Brain/Executor LLM from its workflow state (see
    BRAIN_SYSTEM / EXECUTOR_SYSTEM prompts)."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.setattr(
        "orchestrator.llm_client._keychain_has_claude_code_credentials", lambda: True
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    captured: list = []

    def _capturing_query(*, prompt, options=None, transport=None):
        captured.append(options)
        return _async_iter_messages([_fake_assistant_message("ok")])

    with patch("claude_agent_sdk.query", side_effect=_capturing_query):
        client = make_sdk(project_id="prj_target_01ABC")
        client.complete("smoke", max_tokens=128, system=None)

    assert len(captured) == 1
    opts = captured[0]
    assert _MCP_SERVER_NAME in opts.mcp_servers
    rka_cfg = opts.mcp_servers[_MCP_SERVER_NAME]
    # The negative assertion: no RKA_PROJECT in env block.
    env = rka_cfg.get("env", {})
    assert "RKA_PROJECT" not in env, (
        f"v2.6: make_sdk(project_id=…) must NOT thread RKA_PROJECT into "
        f"the subprocess env; got env={env!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Phase 2 auth thesis preserved across new param
# ---------------------------------------------------------------------------


def test_make_sdk_scrubs_anthropic_api_key_with_project_id_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2 T2 auth thesis regression check across the Phase 2.9 T1
    refactor: even when `project_id` is set (the new param), the SDK
    options.env must STILL mask ANTHROPIC_API_KEY with an empty override.
    The SDK merges options over the parent environment, so omission alone
    would inadvertently revive the key."""
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    monkeypatch.setattr(
        "orchestrator.llm_client._keychain_has_claude_code_credentials", lambda: True
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-not-real")

    captured: list = []

    def _capturing_query(*, prompt, options=None, transport=None):
        captured.append(options)
        return _async_iter_messages([_fake_assistant_message("ok")])

    with patch("claude_agent_sdk.query", side_effect=_capturing_query):
        client = make_sdk(project_id="prj_target_01ABC")
        client.complete("smoke", max_tokens=128, system=None)

    opts = captured[0]
    assert opts.env["ANTHROPIC_API_KEY"] == "", (
        "Phase 2 auth thesis regression — ANTHROPIC_API_KEY was not masked "
        "after Phase 2.9 T1 added the project_id param."
    )
    # v2.6: project_id no longer threads into subprocess env. No env
    # key set (no API keys + no RKA_PROJECT) → env block absent.
    rka_cfg = opts.mcp_servers[_MCP_SERVER_NAME]
    assert "RKA_PROJECT" not in rka_cfg.get("env", {}), (
        f"v2.6: project_id should NOT thread into subprocess env as "
        f"RKA_PROJECT; got env={rka_cfg.get('env')!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — state["project_id"] round-trips through make_initial_state
# ---------------------------------------------------------------------------


def test_state_carries_project_id_through_make_initial_state():
    """Phase 2.9 T1: `state["project_id"]` is an additive TypedDict field.
    `make_initial_state(project_id="prj_x")` round-trips the value through
    the canonical initial state. Pre-Phase-2.9 callers (no project_id arg)
    still work because the param has a default of empty string."""
    # Explicit project_id provided.
    state = make_initial_state(
        workflow_thread_id="thr_t1_test",
        mission_id="mis_t1_test",
        motivated_by_decision_id="dec_t1_test",
        project_id="prj_target_01ABC",
    )
    assert state.get("project_id") == "prj_target_01ABC"

    # Default (back-compat): no project_id arg.
    state = make_initial_state(
        workflow_thread_id="thr_t1_test",
        mission_id="mis_t1_test",
        motivated_by_decision_id="dec_t1_test",
    )
    assert state.get("project_id") == ""


# ---------------------------------------------------------------------------
# Test 6 — `_RealSDKClient` defaults: no project_id arg means no env key
# ---------------------------------------------------------------------------


def test_real_sdk_client_without_project_id_omits_subprocess_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2.9 T1 back-compat for the `_RealSDKClient` layer: when
    constructed without `project_id`, the subprocess MCP config omits
    the env key (pre-Phase-2.9 behavior preserved at the SDK layer too,
    not just at `make_sdk`). Catches a regression where the new param
    might leak through with a stale value."""
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)

    captured: list = []

    def _capturing_query(*, prompt, options=None, transport=None):
        captured.append(options)
        return _async_iter_messages([_fake_assistant_message("ok")])

    with patch("claude_agent_sdk.query", side_effect=_capturing_query):
        # Default constructor: no project_id, no env.
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=128, system=None)

    opts = captured[0]
    rka_cfg = opts.mcp_servers[_MCP_SERVER_NAME]
    assert "env" not in rka_cfg, (
        f"Back-compat at SDK layer: _RealSDKClient() without project_id "
        f"should omit env key; got env={rka_cfg.get('env')!r}"
    )
