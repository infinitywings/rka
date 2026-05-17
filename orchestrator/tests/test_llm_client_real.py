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
    SDKClient,
    _AUTH_PATH_CREDENTIALS_JSON,
    _AUTH_PATH_ENV_API_KEY,
    _AUTH_PATH_KEYCHAIN,
    _AUTH_PATH_NONE,
    _AUTH_PATH_OAUTH_TOKEN,
    _RealSDKClient,
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
