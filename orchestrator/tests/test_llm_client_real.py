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
    """Phase 2.7 T2 (1): the SDK ClaudeAgentOptions must carry READ_TOOLS
    prefixed with `mcp__rka__` in allowed_tools, the rka stdio mcp_servers
    config, strict_mcp_config=True, and permission_mode='dontAsk'.

    Phase-A: when context7 is also configured (npx available), the
    `mcp__context7__*` tools join the allowlist. Test forces npx
    unavailable so the comparison locks the rka-only baseline.
    """
    # Pretend `rka` is on PATH at a known location.
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    # Force the Phase-A context7 expansion to be skipped: pretend npx
    # isn't installed. The "context7 present" path has its own test.
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "orchestrator.llm_client.shutil.which",
        lambda name: None if name == "npx" else real_which(name),
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
    context; cannot mutate entities).

    Phase-A (agentic) added 3 external-API search tools (semantic
    scholar, arxiv, doi-enrich) so the Brain can enrich context
    without escalating to the PI; total is now 14.
    """
    assert "rka_list_projects" in READ_TOOLS, (
        "Phase 2.9 T2: rka_list_projects must be in READ_TOOLS so brain "
        "LLM can self-recover by enumerating projects if RKA_PROJECT env "
        "propagation regresses"
    )
    assert "rka_set_project" in READ_TOOLS, (
        "Phase 2.9 T2: rka_set_project must be in READ_TOOLS so brain "
        "LLM can switch session project as recovery path"
    )
    # READ_TOOLS lineage: 9 (Phase 2.7) → 11 (Phase 2.9) → 14 (Phase-A
    # external-API tools).
    assert len(READ_TOOLS) == 14, (
        f"READ_TOOLS should have exactly 14 entries (Phase 2.7's 9 + "
        f"Phase 2.9's 2 project selectors + Phase-A's 3 external-API "
        f"search tools); got {len(READ_TOOLS)}"
    )


def test_phase_a_read_tools_includes_external_api_search():
    """Phase-A (agentic, Option A scope expansion): the Brain subprocess
    gets read-side access to external-API search tools so it can enrich
    research context during Confirmation Brief drafting without
    escalating to the PI for routine literature lookups.

    These are read-side: they hit external services (Semantic Scholar,
    arXiv, CrossRef) and return search results; they do NOT mutate RKA
    state. Anything that mutates is in WRITE_TOOLS and stays parent-side
    behind pi_decision_select ratification."""
    for tool in ("rka_search_semantic_scholar", "rka_search_arxiv", "rka_enrich_doi"):
        assert tool in READ_TOOLS, f"Phase-A: {tool} should be in READ_TOOLS"


def test_phase_a_external_api_tools_not_in_write_tools():
    """Safety check: the Phase-A external-API search tools must NOT
    appear in WRITE_TOOLS. If misclassified, the parent-side ratification
    pipeline would treat them as state mutations and they'd lose their
    "free read in the subprocess" property — defeating the expansion."""
    for tool in ("rka_search_semantic_scholar", "rka_search_arxiv", "rka_enrich_doi"):
        assert tool not in WRITE_TOOLS, f"Phase-A: {tool} must not be in WRITE_TOOLS"


def test_phase_2_9_project_selectors_not_in_write_tools():
    """Critical safety check: rka_list_projects + rka_set_project must
    NOT be in WRITE_TOOLS. They're read-side selectors that change
    session routing context, not entity state. If either is incorrectly
    classified as write, the parent-side execute_ratified_actions
    pipeline would treat them as ratifiable mutations — wrong semantic
    layer."""
    assert "rka_list_projects" not in WRITE_TOOLS
    assert "rka_set_project" not in WRITE_TOOLS


# ---------------------------------------------------------------------------
# Phase 2.13 T3 — WRITE_TOOLS allowlist expansion (6 → 7) for rka_bulk_update
# (mis_01KRYZMEAT01SMNNXQXS3JRC4W; per dec_01KRYZGF8N1SNJX5TSP0GM77Z7 Option A
#  — closes the 10th trigger surfaced empirically by Phase 2.12, where the
#  brain LLM methodologically chose rka_bulk_update for cross-reference
#  hygiene but it was not allowlisted)
# ---------------------------------------------------------------------------


def test_write_tools_contains_rka_bulk_update():
    """Phase 2.13 T2: rka_bulk_update must be in WRITE_TOOLS so the
    parent-side execute_ratified_actions can dispatch it when the brain
    proposes it (which Phase 2.12 empirically demonstrated the brain
    will do for cross-reference hygiene work). Without this entry, the
    Phase 2.7 Option C defense-in-depth rejects the action even when
    the brain's methodology is correct."""
    assert "rka_bulk_update" in WRITE_TOOLS, (
        "Phase 2.13 T2: rka_bulk_update must be in WRITE_TOOLS so the "
        "parent-side dispatch path accepts brain-proposed bulk-update "
        "actions ratified by PI."
    )


def test_write_tools_length_9():
    """WRITE_TOOLS lineage:
       Phase 2.7   — initial 6 (add_note, add_decision, submit_checkpoint,
                     submit_report, create_mission, update_note)
       Phase 2.13  — +1 (rka_bulk_update) → 7
       Phase-A2    — +2 (rka_update_mission_status, rka_ingest_document) → 9

    Catches accidental deletion or silent drift of the registry shape.
    """
    assert len(WRITE_TOOLS) == 9, (
        f"WRITE_TOOLS should have exactly 9 entries (Phase 2.7's 6 + "
        f"Phase 2.13's rka_bulk_update + Phase-A2's mission_status + "
        f"ingest_document); got {len(WRITE_TOOLS)}"
    )


def test_phase_a2_write_tools_includes_mission_status_and_ingest_document():
    """Phase-A2 expansion (agentic): empirical PI-driven on the
    IoT-edge-LLM Phase-1 test mission. Brain proposed `rka_update_mission_status`
    + `rka_ingest_document` for the synthesis-note delivery; the
    execute_ratified_actions dispatcher correctly rejected them as
    not-in-WRITE_TOOLS. Real RKA endpoints exist (PUT /api/missions/{id},
    POST /api/ingest/document); MCPClient Protocol methods + RestMCPClient
    impls added alongside this allowlist entry."""
    assert "rka_update_mission_status" in WRITE_TOOLS
    assert "rka_ingest_document" in WRITE_TOOLS


def test_phase_a2_write_tools_not_in_read_tools():
    """Both Phase-A2 additions are write-side: they create new entities
    (ingest_document → journal) or mutate existing ones
    (update_mission_status → mission). They must NOT appear in READ_TOOLS,
    or the subprocess SDK's allowed_tools would let the brain LLM call
    them directly, bypassing pi_decision_select ratification."""
    for tool in ("rka_update_mission_status", "rka_ingest_document"):
        assert tool not in READ_TOOLS, (
            f"Phase-A2: {tool!r} mutates state, must be PI-gated; "
            f"keeping it out of READ_TOOLS keeps the subprocess "
            f"strictly read-only."
        )


def test_rka_bulk_update_not_in_read_tools():
    """Critical safety check: rka_bulk_update is a write-side tool
    (mutates note/decision/literature entities via per-entity PUT
    endpoints). It must NOT be in READ_TOOLS — if misclassified, the
    subprocess SDK's allowed_tools would let the brain LLM call it
    directly, bypassing the parent-side PI ratification gate the entire
    Phase 2.7 Option C architecture is built on."""
    assert "rka_bulk_update" not in READ_TOOLS, (
        "Read/write separation: rka_bulk_update mutates entity state "
        "and must never appear in READ_TOOLS — that would let the "
        "subprocess LLM bypass the parent-side ratification gate."
    )


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


# ---------------------------------------------------------------------------
# Phase-A (agentic, Option A scope expansion):
#   - SEMANTIC_SCHOLAR_API_KEY + SERPAPI_KEY propagation to subprocess env
#   - context7 MCP server registration when npx is available
# ---------------------------------------------------------------------------


def _force_npx_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper: pretend `npx` is not on PATH so the context7 expansion
    path doesn't fire in this test."""
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "orchestrator.llm_client.shutil.which",
        lambda name: None if name == "npx" else real_which(name),
    )


def _force_npx_at(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """Helper: pretend `npx` is on PATH at the given path."""
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "orchestrator.llm_client.shutil.which",
        lambda name: path if name == "npx" else real_which(name),
    )


def test_phase_a_semantic_scholar_key_propagates_to_subprocess_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """When SEMANTIC_SCHOLAR_API_KEY is set in the parent process env, it
    propagates into the rka MCP server's env block. Without explicit
    propagation, the McpStdioServerConfig.env field REPLACES (not
    augments) the parent env when the subprocess is spawned, so the rka
    MCP child would run anonymously against semanticscholar.org despite
    the parent having a key."""
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "s2k-phase-a-test")
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    _force_npx_unavailable(monkeypatch)

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=64, system=None)

    rka_cfg = captured[0].mcp_servers[_MCP_SERVER_NAME]
    assert "env" in rka_cfg, "rka server env block missing"
    assert rka_cfg["env"].get("SEMANTIC_SCHOLAR_API_KEY") == "s2k-phase-a-test"
    # SERPAPI not set in parent → should not appear in subprocess env.
    assert "SERPAPI_KEY" not in rka_cfg["env"]


def test_phase_a_serpapi_key_propagates_to_subprocess_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """SERPAPI_KEY propagates symmetrically with SEMANTIC_SCHOLAR_API_KEY.
    Used by rka-writer-tools' SerpAPI backend (when the subprocess gains
    access to writer-tools in a future scope expansion); harmless to
    propagate eagerly today."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.setenv("SERPAPI_KEY", "serpapi-phase-a-test")
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    _force_npx_unavailable(monkeypatch)

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=64, system=None)

    rka_cfg = captured[0].mcp_servers[_MCP_SERVER_NAME]
    assert rka_cfg["env"].get("SERPAPI_KEY") == "serpapi-phase-a-test"
    assert "SEMANTIC_SCHOLAR_API_KEY" not in rka_cfg["env"]


def test_phase_a_neither_api_key_set_no_env_pollution(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """When neither API key is in the parent env, neither lands in the
    subprocess env. Project_id-only env block (Phase 2.9 baseline) is
    preserved without leaking placeholder values."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    _force_npx_unavailable(monkeypatch)

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={}, project_id="prj_test")
        client.complete("smoke", max_tokens=64, system=None)

    rka_cfg = captured[0].mcp_servers[_MCP_SERVER_NAME]
    env_block = rka_cfg.get("env", {})
    assert env_block == {"RKA_PROJECT": "prj_test"}, (
        f"only RKA_PROJECT expected in env block; got {env_block}"
    )


def test_phase_a_context7_added_when_npx_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """When `npx` is on PATH, the context7 MCP server is added to
    mcp_servers and its tools join allowed_tools."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    _force_npx_at(monkeypatch, "/fake/bin/npx")

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=64, system=None)

    opts = captured[0]
    # context7 server config landed.
    assert "context7" in opts.mcp_servers, (
        f"context7 server missing from mcp_servers; got "
        f"{list(opts.mcp_servers.keys())}"
    )
    ctx_cfg = opts.mcp_servers["context7"]
    assert ctx_cfg["type"] == "stdio"
    assert ctx_cfg["command"] == "/fake/bin/npx"
    assert "@upstash/context7-mcp" in " ".join(ctx_cfg["args"])
    # Context7 tools join allowed_tools.
    assert "mcp__context7__query-docs" in opts.allowed_tools
    assert "mcp__context7__resolve-library-id" in opts.allowed_tools


def test_phase_a_context7_skipped_when_npx_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """When `npx` is NOT on PATH, the context7 server is silently
    skipped (no crash). The rka server remains; allowed_tools omits
    mcp__context7__ entries."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    fake_rka = tmp_path / "rka"
    fake_rka.write_text("#!/bin/sh\nexit 0\n")
    fake_rka.chmod(0o755)
    monkeypatch.setattr(
        "orchestrator.llm_client._find_rka_mcp_binary", lambda: str(fake_rka)
    )
    _force_npx_unavailable(monkeypatch)

    capturing_query, captured = _capture_one_options()
    with patch("claude_agent_sdk.query", side_effect=capturing_query):
        client = _RealSDKClient(env={})
        client.complete("smoke", max_tokens=64, system=None)

    opts = captured[0]
    assert "context7" not in opts.mcp_servers
    for t in opts.allowed_tools:
        assert not t.startswith("mcp__context7__"), (
            f"context7 tool {t!r} unexpectedly in allowed_tools when npx missing"
        )
