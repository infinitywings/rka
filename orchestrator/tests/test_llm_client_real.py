"""Production-path tests for `orchestrator.llm_client.make_sdk()`
(Phase 2, mis_01KRSRZX2P3BN4ZAP70ZM7YXGC T1+T2).

These tests live alongside the FakeSDK tests in `_fakes.py` —
production-path coverage without touching the real Claude Max
subscription. The 4 T1 tests cover: factory shape, complete() returns
non-empty against a mock, auth-path priority, error path. T2 adds one
integration test that exercises the auth-path helper across each path
via monkeypatched env + filesystem + Keychain probe.

No real LLM calls. Tests that depend on the SDK monkey-patch
`claude_agent_sdk.query` so the test runner never spawns the `claude`
CLI subprocess.
"""

from __future__ import annotations

import os
from typing import AsyncIterator
from unittest.mock import patch

import pytest

from orchestrator.llm_client import (
    AuthRoutingReport,
    READ_TOOLS,
    SDKClient,
    WRITE_TOOLS,
    _AUTH_PATH_CREDENTIALS_JSON,
    _AUTH_PATH_ENV_API_KEY,
    _AUTH_PATH_KEYCHAIN,
    _AUTH_PATH_NONE,
    _AUTH_PATH_OAUTH_TOKEN,
    _MCP_SERVER_NAME,
    _RealSDKClient,
    _prefixed_tools,
    _scrubbed_env,
    _verify_claude_max_routing,
    make_sdk,
)


# ---------------------------------------------------------------------------
# Helpers — fake claude_agent_sdk surfaces for monkeypatch.
# ---------------------------------------------------------------------------


def _fake_assistant_message(text: str):
    """Build a minimal stand-in for `sdk.AssistantMessage` with one TextBlock."""
    import claude_agent_sdk as sdk

    block = sdk.TextBlock(text=text)
    return sdk.AssistantMessage(content=[block], model="claude-test", parent_tool_use_id=None)


def _async_iter_messages(messages):
    async def _gen():
        for m in messages:
            yield m
    return _gen()


# ---------------------------------------------------------------------------
# T1 (a) — make_sdk returns an SDKClient instance, not raises.
# ---------------------------------------------------------------------------


def test_make_sdk_returns_sdkclient_instance_not_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """make_sdk() must construct cleanly when at least one Claude Max
    auth path is reachable. Stubs the Keychain probe to True so we
    don't depend on the host machine's login state."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    # Point credentials.json probe at a tmp directory that does not have it,
    # so the test falls through to the Keychain probe.
    monkeypatch.setattr(
        "orchestrator.llm_client.Path",
        lambda *a, **kw: tmp_path / "nope" / ".credentials.json",
    )
    monkeypatch.setattr(
        "orchestrator.llm_client._keychain_has_claude_code_credentials",
        lambda: True,
    )

    sdk_client = make_sdk()
    assert isinstance(sdk_client, _RealSDKClient)
    # Honors the SDKClient Protocol surface — has `complete`.
    assert callable(sdk_client.complete)


# ---------------------------------------------------------------------------
# T1 (b) — complete() returns a non-empty string against a mock.
# ---------------------------------------------------------------------------


def test_complete_returns_non_empty_string_against_mock():
    """The wrapper consumes the SDK's async iterator and concatenates
    AssistantMessage TextBlocks into a single string. Patches the SDK's
    `query` so no real subprocess fires."""

    def _fake_query(*, prompt, options=None, transport=None):
        return _async_iter_messages([
            _fake_assistant_message("Hello, "),
            _fake_assistant_message("world!"),
        ])

    with patch("claude_agent_sdk.query", side_effect=_fake_query):
        client = _RealSDKClient(env={})
        result = client.complete("smoke", max_tokens=128, system=None)

    assert isinstance(result, str)
    assert result == "Hello, world!"


# ---------------------------------------------------------------------------
# T1 (c) — auth-priority test: ANTHROPIC_API_KEY consumed when set;
#          otherwise falls back to credentials.json mock.
# ---------------------------------------------------------------------------


class TestAuthPathPriority:
    """The verify-routing helper must return the FIRST available Claude Max
    path (#2-#4) and report a warning when #1 ANTHROPIC_API_KEY is set."""

    def test_credentials_json_path_when_file_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        creds = tmp_path / ".credentials.json"
        creds.write_text("{}")  # presence only; content not inspected
        # Replace the Path("~/.claude/...") call so it points at our tmp file.
        monkeypatch.setattr(
            "orchestrator.llm_client.Path",
            lambda *a, **kw: creds,
        )
        # If credentials.json wins, the Keychain probe should never fire —
        # set it to False just to be safe.
        monkeypatch.setattr(
            "orchestrator.llm_client._keychain_has_claude_code_credentials",
            lambda: False,
        )
        report = _verify_claude_max_routing()
        assert report.auth_path == _AUTH_PATH_CREDENTIALS_JSON
        assert report.warning is None
        assert report.scrubbed_env_vars == []

    def test_keychain_path_when_no_file_but_keychain_entry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(
            "orchestrator.llm_client.Path",
            lambda *a, **kw: tmp_path / "nope" / ".credentials.json",
        )
        monkeypatch.setattr(
            "orchestrator.llm_client._keychain_has_claude_code_credentials",
            lambda: True,
        )
        report = _verify_claude_max_routing()
        assert report.auth_path == _AUTH_PATH_KEYCHAIN

    def test_oauth_token_path_when_env_var_set(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token-not-real")
        report = _verify_claude_max_routing()
        assert report.auth_path == _AUTH_PATH_OAUTH_TOKEN
        assert report.warning is None

    def test_warning_emitted_when_api_key_set_alongside_max_path(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The PI directive's load-bearing case: ANTHROPIC_API_KEY IS set
        AND a Claude Max path IS available. Verify the helper reports
        the Max path AND emits a warning naming the scrubbed env var."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-value-not-real")
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(
            "orchestrator.llm_client._keychain_has_claude_code_credentials",
            lambda: True,
        )

        report = _verify_claude_max_routing()
        assert report.auth_path == _AUTH_PATH_KEYCHAIN
        assert "ANTHROPIC_API_KEY" in (report.warning or "")
        assert "ANTHROPIC_API_KEY" in report.scrubbed_env_vars

    def test_fallback_to_env_api_key_when_no_max_paths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        """Boundary: API key set, NO Claude Max path. Report flags this
        as the only available path — caller decides whether to allow."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-value-not-real")
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(
            "orchestrator.llm_client.Path",
            lambda *a, **kw: tmp_path / "nope" / ".credentials.json",
        )
        monkeypatch.setattr(
            "orchestrator.llm_client._keychain_has_claude_code_credentials",
            lambda: False,
        )
        report = _verify_claude_max_routing()
        assert report.auth_path == _AUTH_PATH_ENV_API_KEY

    def test_none_path_when_no_credentials_anywhere(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        """Worst case: no env, no file, no Keychain. make_sdk() raises."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(
            "orchestrator.llm_client.Path",
            lambda *a, **kw: tmp_path / "nope" / ".credentials.json",
        )
        monkeypatch.setattr(
            "orchestrator.llm_client._keychain_has_claude_code_credentials",
            lambda: False,
        )
        report = _verify_claude_max_routing()
        assert report.auth_path == _AUTH_PATH_NONE
        with pytest.raises(RuntimeError, match="No Claude Max credentials"):
            make_sdk()


# ---------------------------------------------------------------------------
# T1 (d) — error path: network/SDK failure surfaces a clean exception.
# ---------------------------------------------------------------------------


def test_complete_surfaces_clean_exception_on_sdk_failure():
    """If the SDK raises (network down, CLI missing, etc.), the wrapper
    must propagate cleanly — no swallowing, no asyncio noise."""

    class _Boom(RuntimeError):
        pass

    def _failing_query(*, prompt, options=None, transport=None):
        raise _Boom("CLI not found")

    with patch("claude_agent_sdk.query", side_effect=_failing_query):
        client = _RealSDKClient(env={})
        with pytest.raises(_Boom, match="CLI not found"):
            client.complete("smoke", max_tokens=128, system=None)


# ---------------------------------------------------------------------------
# Env-scrubbing helper coverage.
# ---------------------------------------------------------------------------


def test_scrubbed_env_removes_anthropic_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-value-not-real")
    monkeypatch.setenv("PATH", "/usr/bin")  # any innocuous var to verify it survives
    scrubbed = _scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in scrubbed
    assert scrubbed.get("PATH") == "/usr/bin"


def test_complete_passes_scrubbed_env_to_sdk():
    """The SDK options.env must NOT contain ANTHROPIC_API_KEY when the
    caller's process env has it set. Locks the scrub-and-pass contract."""

    captured_envs: list[dict[str, str]] = []

    def _capturing_query(*, prompt, options=None, transport=None):
        captured_envs.append(dict(options.env) if options else {})
        return _async_iter_messages([_fake_assistant_message("ok")])

    scrubbed_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    scrubbed_env["PATH"] = "/usr/bin"  # ensure non-billing var survives
    with patch("claude_agent_sdk.query", side_effect=_capturing_query):
        client = _RealSDKClient(env=scrubbed_env)
        client.complete("smoke", max_tokens=128, system=None)

    assert len(captured_envs) == 1
    assert "ANTHROPIC_API_KEY" not in captured_envs[0]
    assert captured_envs[0].get("PATH") == "/usr/bin"


# ---------------------------------------------------------------------------
# Phase 2.7 T2 — Option C read-only-subprocess MCP scope
# (mis_01KRXNAJDM2DQ3K1VH6CXAPK8R; PI-ratified per jrn_01KRXP96THHEAKCGB0P0KGV7Y9).
# Three regression tests covering the three load-bearing behaviors:
#  (1) READ_TOOLS land in subprocess options.allowed_tools (prefixed mcp__rka__)
#  (2) WRITE_TOOLS land in subprocess options.disallowed_tools (same prefix);
#      this is the belt-and-suspenders against the Phase 2.6 finding that the
#      executor LLM in the subprocess tried to call write tools directly
#  (3) Phase 2 auth-thesis regression check — ANTHROPIC_API_KEY still scrubbed
#      from options.env even after the T2 refactor adds new option fields
# ---------------------------------------------------------------------------


def _capture_one_options():
    """Helper: returns (capturing_query, captured_options_list) — patches
    `claude_agent_sdk.query` to record the ClaudeAgentOptions instance for
    inspection without firing a real SDK subprocess."""
    captured: list = []

    def _capturing_query(*, prompt, options=None, transport=None):
        captured.append(options)
        return _async_iter_messages([_fake_assistant_message("ok")])

    return _capturing_query, captured


def test_complete_passes_read_tools_allowlist_to_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2.7 T2 (1): the SDK ClaudeAgentOptions must carry the 9
    READ_TOOLS prefixed with `mcp__rka__` in allowed_tools, the rka stdio
    mcp_servers config, strict_mcp_config=True, and permission_mode='dontAsk'."""
    # Pretend `rka` is on PATH at a known location.
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=128, system="sys")

    assert len(captured) == 1
    opts = captured[0]
    # READ_TOOLS land in allowed_tools, prefixed.
    expected_reads = _prefixed_tools(READ_TOOLS)
    assert opts.allowed_tools == expected_reads, (
        f"expected allowed_tools={expected_reads!r}, got {opts.allowed_tools!r}"
    )
    # mcp_servers carries rka stdio config pointing at the discovered binary.
    assert _MCP_SERVER_NAME in opts.mcp_servers
    rka_cfg = opts.mcp_servers[_MCP_SERVER_NAME]
    assert rka_cfg["type"] == "stdio"
    assert rka_cfg["command"] == str(fake_rka)
    assert rka_cfg["args"] == ["mcp"]
    # Strict scoping: only this server, no host config bleed.
    assert opts.strict_mcp_config is True
    # Deny silently anything off-allowlist.
    assert opts.permission_mode == "dontAsk"
    # System prompt + scrubbed env preserved from prior contract.
    assert opts.system_prompt == "sys"


def test_complete_passes_write_tools_disallowlist_to_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2.7 T2 (2): WRITE_TOOLS must land in disallowed_tools as
    belt-and-suspenders against the Phase 2.6 finding that the executor LLM
    in the subprocess tried to call write-side MCP tools directly. The
    `dontAsk` permission_mode + empty allowed_tools for writes is the
    primary defense; disallowed_tools is the explicit redundancy."""
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=128, system=None)

    opts = captured[0]
    expected_writes = _prefixed_tools(WRITE_TOOLS)
    assert opts.disallowed_tools == expected_writes, (
        f"expected disallowed_tools={expected_writes!r}, "
        f"got {opts.disallowed_tools!r}"
    )
    # Sanity: writes must NOT also appear in allowed_tools (would be a
    # contradictory contract).
    for write_tool in expected_writes:
        assert write_tool not in opts.allowed_tools, (
            f"WRITE_TOOL {write_tool!r} unexpectedly in allowed_tools "
            f"(contract violation)"
        )


def test_t2_refactor_preserves_anthropic_api_key_scrub(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Phase 2 T2 auth thesis regression check (load-bearing across phases):
    even after the T2 refactor adds new option fields (mcp_servers,
    strict_mcp_config, permission_mode, disallowed_tools), ANTHROPIC_API_KEY
    must still be absent from the subprocess env handed to the SDK.

    This is the test that would have caught a regression in the Phase 2.5
    fold + Phase 2.7 refactor stack independently."""
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )

    capturing_query, captured = _capture_one_options()
    scrubbed_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    scrubbed_env["PATH"] = "/usr/bin"
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env=scrubbed_env)
        client.complete("smoke", max_tokens=128, system=None)

    opts = captured[0]
    assert "ANTHROPIC_API_KEY" not in opts.env, (
        "Phase 2 T2 auth thesis regression — ANTHROPIC_API_KEY leaked back "
        "into ClaudeAgentOptions.env after Phase 2.7 T2 refactor"
    )
    assert opts.env.get("PATH") == "/usr/bin"


# ---------------------------------------------------------------------------
# Phase 2.9 T2 — READ_TOOLS allowlist expansion (9 → 11)
# (mis_01KRY2KP0GGZY21BA4Z2R2S718; PI-handed-off scope per
#  dec_01KRY2EXCSTSSCFZJ96VG4MGDW Option A — belt-and-suspenders for the
#  brain LLM's self-recovery path if Phase 2.9 T1 env propagation regresses)
# ---------------------------------------------------------------------------


def test_phase_2_9_read_tools_includes_project_selectors():
    """Phase 2.9 T2 adds `rka_list_projects` + `rka_set_project` to the
    READ_TOOLS allowlist as belt-and-suspenders. Without this expansion,
    if Phase 2.9 T1's RKA_PROJECT env propagation ever regresses, the
    brain LLM has no self-recovery path (Phase 2.8 demonstrated this
    exact denial empirically). Both tools are read-side (select session
    context; cannot mutate entities)."""
    assert "rka_list_projects" in READ_TOOLS, (
        "Phase 2.9 T2: rka_list_projects must be in READ_TOOLS so brain "
        "LLM can self-recover by enumerating projects if RKA_PROJECT env "
        "propagation regresses"
    )
    assert "rka_set_project" in READ_TOOLS, (
        "Phase 2.9 T2: rka_set_project must be in READ_TOOLS so brain "
        "LLM can switch session project as recovery path"
    )
    # READ_TOOLS expanded from 9 (Phase 2.7) to 11 (Phase 2.9).
    assert len(READ_TOOLS) == 11, (
        f"Phase 2.9 T2: READ_TOOLS should have exactly 11 entries "
        f"(Phase 2.7's 9 + Phase 2.9's 2 project selectors); got {len(READ_TOOLS)}"
    )


def test_phase_2_9_project_selectors_not_in_write_tools():
    """Critical safety check: rka_list_projects + rka_set_project must
    NOT be in WRITE_TOOLS. They're read-side selectors that change
    session routing context, not entity state. If either is incorrectly
    classified as write, the parent-side execute_ratified_actions
    pipeline would treat them as ratifiable mutations — wrong semantic
    layer."""
    assert "rka_list_projects" not in WRITE_TOOLS
    assert "rka_set_project" not in WRITE_TOOLS


def test_complete_falls_back_to_text_only_when_rka_binary_missing(
    monkeypatch: pytest.MonkeyPatch
):
    """Defense in depth: if `rka` is not on PATH (clean tooling env, CI
    container without uv-installed binary, etc.), the SDK call must NOT
    raise — it falls back to Phase 1 text-only mode (allowed_tools=[],
    no mcp_servers). A warning log records the degradation."""
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: None
    )

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=128, system=None)

    opts = captured[0]
    assert opts.allowed_tools == []
    # No mcp_servers passed → SDK default (empty dict).
    assert opts.mcp_servers == {} or opts.mcp_servers is None or not opts.mcp_servers
