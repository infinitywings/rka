"""Phase 2.9 T1 — subprocess MCP project propagation regression tests.

Mission: `mis_01KRY2KP0GGZY21BA4Z2R2S718` (Phase 2.9; PI-handed-off scope
per `dec_01KRY2EXCSTSSCFZJ96VG4MGDW` Option A).

These tests lock the contract that Phase 2.8 surfaced empirically: the
claude-agent-sdk subprocess's `rka mcp` stdio child must inherit the
parent's RKA project context via `McpStdioServerConfig.env["RKA_PROJECT"]`.
Without this, the subprocess MCP session defaults to `Default Project`
(proj_default) and all entity reads return 404 against missions/journals
that live in a different project — the exact failure mode Phase 2.8
documented at `jrn_01KRY18QH8RBK5TF445KWJW1H8`.

Five tests cover:
  1. `_build_mcp_servers_config(rka_binary, project_id="prj_x")` sets env
  2. `_build_mcp_servers_config(rka_binary, project_id=None)` omits env (back-compat)
  3. `make_sdk(project_id="prj_x")` threads to `_RealSDKClient` then to
     `_build_mcp_servers_config` at runtime (via `complete()` invocation)
  4. `make_sdk(project_id="prj_x")` still scrubs ANTHROPIC_API_KEY
     (Phase 2 auth thesis preserved across the new param)
  5. `state["project_id"]` round-trips through `make_initial_state`
     (additive TypedDict field; no breaking changes)
"""

from __future__ import annotations

import os
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


def test_build_mcp_servers_config_with_project_id_sets_env():
    """When `project_id` is provided, the McpStdioServerConfig dict carries
    `env={"RKA_PROJECT": project_id}` so the subprocess `rka mcp` child
    inherits the parent's project context. This is the load-bearing Phase
    2.9 T1 fix closing the 8th mandatory-pause trigger from Phase 2.8."""
    config = _build_mcp_servers_config("/fake/path/to/rka", project_id="prj_target_01ABC")
    assert _MCP_SERVER_NAME in config
    rka_config = config[_MCP_SERVER_NAME]
    assert rka_config["type"] == "stdio"
    assert rka_config["command"] == "/fake/path/to/rka"
    assert rka_config["args"] == ["mcp"]
    # The load-bearing assertion:
    assert rka_config["env"] == {"RKA_PROJECT": "prj_target_01ABC"}, (
        f"Phase 2.9 T1 contract: subprocess MCP child must inherit "
        f"RKA_PROJECT={'prj_target_01ABC'!r}; got env={rka_config.get('env')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — back-compat: no project_id means no env key
# ---------------------------------------------------------------------------


def test_build_mcp_servers_config_without_project_id_omits_env():
    """Back-compat: pre-Phase-2.9 callers continue to work. When
    `project_id` is None (or omitted), no env key is set — subprocess
    falls through to its default session. Pre-Phase-2.9 behavior
    preserved bit-for-bit (Phase 2.8 ran with this code path)."""
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


def test_make_sdk_threads_project_id_to_subprocess_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2.9 T1: `make_sdk(project_id="prj_x")` constructs a
    `_RealSDKClient` carrying the project_id; on `complete()`, the
    SDK options carry `mcp_servers={..., "env": {"RKA_PROJECT": "prj_x"}}`.
    End-to-end propagation through the orchestrator's SDK layer."""
    # Stub the rka binary discovery so the test doesn't depend on PATH.
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    # Stub the Keychain probe so make_sdk doesn't depend on host state.
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
    # The project_id must reach the subprocess MCP config.
    assert _MCP_SERVER_NAME in opts.mcp_servers
    rka_cfg = opts.mcp_servers[_MCP_SERVER_NAME]
    assert rka_cfg["env"] == {"RKA_PROJECT": "prj_target_01ABC"}, (
        f"Phase 2.9 T1 end-to-end: make_sdk(project_id=...) must propagate "
        f"to McpStdioServerConfig.env; got env={rka_cfg.get('env')!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Phase 2 auth thesis preserved across new param
# ---------------------------------------------------------------------------


def test_make_sdk_scrubs_anthropic_api_key_with_project_id_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2 T2 auth thesis regression check across the Phase 2.9 T1
    refactor: even when `project_id` is set (the new param), the SDK
    options.env must STILL NOT contain ANTHROPIC_API_KEY. Catches the
    regression where the new param's plumbing might inadvertently revive
    the env var."""
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
    assert "ANTHROPIC_API_KEY" not in opts.env, (
        "Phase 2 auth thesis regression — ANTHROPIC_API_KEY leaked back "
        "into ClaudeAgentOptions.env after Phase 2.9 T1 refactor added "
        "the project_id param. Auth thesis MUST hold across this change."
    )
    # And the project_id propagation still happens correctly.
    rka_cfg = opts.mcp_servers[_MCP_SERVER_NAME]
    assert rka_cfg["env"] == {"RKA_PROJECT": "prj_target_01ABC"}


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
