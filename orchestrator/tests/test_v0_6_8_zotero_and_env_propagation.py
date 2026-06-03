"""v0.6.8 regression tests — Zotero MCP wiring + .rka/.env propagation.

Closes two gaps surfaced by the cockpit's hyperscaler-auditing D3
pre-flight audit on 2026-06-03:

1. The orchestrator's Brain/Executor subprocess MCP config was
   hard-coded to {rka, context7}. Projects needing Zotero literature
   lookups inside mission execution had the Executor silently degrade
   to no-zotero — same "cockpit ≠ run env" trap as the v2.7.0.1 host
   adapter staleness.

2. The Phase D2 bind-mount design assumed per-project ``.rka/.env``
   creds (DEEPSEEK, SEC_EDGAR, FRED, WRDS, etc.) would reach the
   subprocess via the bind-mounted workspace, but the env-loading
   step was never wired. The file was discoverable but never read.

Both fixes are scoped to orchestrator/orchestrator/llm_client.py.
No rka/ touches; bookkeeper invariant preserved.
"""

from __future__ import annotations

import pytest

from orchestrator.llm_client import (
    _ENV_VARS_TO_SCRUB,
    _ZOTERO_SERVER_NAME,
    _ZOTERO_TOOLS,
    _all_allowed_subprocess_tools,
    _build_mcp_servers_config,
    _build_zotero_server_if_configured,
    _find_zotero_mcp_binary,
    _merge_project_env_file,
    _parse_dotenv_lines,
    _prefixed_tools,
)


# ---------------------------------------------------------------------------
# _find_zotero_mcp_binary — PATH lookup + env override
# ---------------------------------------------------------------------------


def test_find_zotero_mcp_binary_returns_none_when_neither_path_nor_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ZOTERO_MCP_BINARY", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert _find_zotero_mcp_binary() is None


def test_find_zotero_mcp_binary_uses_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setenv("ZOTERO_MCP_BINARY", "/custom/path/zotero-mcp")
    assert _find_zotero_mcp_binary() == "/custom/path/zotero-mcp"


def test_find_zotero_mcp_binary_path_wins_over_env(monkeypatch: pytest.MonkeyPatch):
    """When PATH yields a binary, prefer it over the env override (PATH is
    the standard discovery; env is the fallback / override)."""
    monkeypatch.setattr(
        "shutil.which", lambda name: "/path/zotero-mcp" if name == "zotero-mcp" else None
    )
    monkeypatch.setenv("ZOTERO_MCP_BINARY", "/custom/override")
    assert _find_zotero_mcp_binary() == "/path/zotero-mcp"


# ---------------------------------------------------------------------------
# _build_zotero_server_if_configured — three signals required
# ---------------------------------------------------------------------------


def test_zotero_server_skipped_when_no_binary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.delenv("ZOTERO_MCP_BINARY", raising=False)
    monkeypatch.setenv("ZOTERO_API_KEY", "abc")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "123")
    assert _build_zotero_server_if_configured() is None


def test_zotero_server_skipped_when_api_key_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/x/zotero-mcp")
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "123")
    assert _build_zotero_server_if_configured() is None


def test_zotero_server_skipped_when_library_id_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("shutil.which", lambda _name: "/x/zotero-mcp")
    monkeypatch.setenv("ZOTERO_API_KEY", "abc")
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    assert _build_zotero_server_if_configured() is None


def test_zotero_server_built_when_binary_and_creds_present(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("shutil.which", lambda _name: "/x/zotero-mcp")
    monkeypatch.setenv("ZOTERO_API_KEY", "abc123")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "9646912")
    monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "user")

    config = _build_zotero_server_if_configured()
    assert config is not None
    assert config["type"] == "stdio"
    assert config["command"] == "/x/zotero-mcp"
    assert config["args"] == ["serve"]
    assert config["env"]["ZOTERO_API_KEY"] == "abc123"
    assert config["env"]["ZOTERO_LIBRARY_ID"] == "9646912"
    assert config["env"]["ZOTERO_LIBRARY_TYPE"] == "user"
    # ZOTERO_LOCAL pinned false (Web API path) — container has no Zotero.app
    assert config["env"]["ZOTERO_LOCAL"] == "false"


def test_zotero_server_defaults_library_type_to_user_when_unset(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("shutil.which", lambda _name: "/x/zotero-mcp")
    monkeypatch.setenv("ZOTERO_API_KEY", "abc")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "1")
    monkeypatch.delenv("ZOTERO_LIBRARY_TYPE", raising=False)
    config = _build_zotero_server_if_configured()
    assert config["env"]["ZOTERO_LIBRARY_TYPE"] == "user"


def test_zotero_server_clamps_invalid_library_type_to_user(
    monkeypatch: pytest.MonkeyPatch,
):
    """library_type must be 'user' or 'group'. Anything else clamps to 'user'
    rather than raising — silent forgiveness for typos at the env layer."""
    monkeypatch.setattr("shutil.which", lambda _name: "/x/zotero-mcp")
    monkeypatch.setenv("ZOTERO_API_KEY", "abc")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "1")
    monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "bogus")
    config = _build_zotero_server_if_configured()
    assert config["env"]["ZOTERO_LIBRARY_TYPE"] == "user"


def test_zotero_server_uses_supplied_env_over_os_environ(
    monkeypatch: pytest.MonkeyPatch,
):
    """When `env=` is supplied (the v0.6.8 callsite from _build_mcp_servers_config
    passes the merged daemon+project env), read creds from that, not os.environ.
    This is what makes the .rka/.env propagation path actually wire Zotero —
    creds may not be in os.environ but DO reach via the merged env."""
    monkeypatch.setattr("shutil.which", lambda _name: "/x/zotero-mcp")
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    project_env = {
        "ZOTERO_API_KEY": "from-project-env",
        "ZOTERO_LIBRARY_ID": "9999999",
        "ZOTERO_LIBRARY_TYPE": "group",
    }
    config = _build_zotero_server_if_configured(env=project_env)
    assert config is not None
    assert config["env"]["ZOTERO_API_KEY"] == "from-project-env"
    assert config["env"]["ZOTERO_LIBRARY_ID"] == "9999999"
    assert config["env"]["ZOTERO_LIBRARY_TYPE"] == "group"


# ---------------------------------------------------------------------------
# _build_mcp_servers_config — Zotero wired conditionally
# ---------------------------------------------------------------------------


def test_build_mcp_servers_config_adds_zotero_when_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    # rka_binary supplied; npx NOT available so context7 stays out (focus
    # the assertion on zotero); zotero binary + creds present.
    def _which(name):
        if name == "zotero-mcp":
            return "/x/zotero-mcp"
        return None

    monkeypatch.setattr("shutil.which", _which)
    monkeypatch.setenv("ZOTERO_API_KEY", "abc")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "123")
    monkeypatch.delenv("ZOTERO_LIBRARY_TYPE", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)

    config = _build_mcp_servers_config("/fake/rka")
    assert "rka" in config
    assert "zotero" in config
    assert config["zotero"]["env"]["ZOTERO_API_KEY"] == "abc"
    assert "context7" not in config


def test_build_mcp_servers_config_omits_zotero_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
):
    """Pre-v0.6.8 default behavior preserved: when Zotero isn't configured,
    the subprocess config has no zotero server entry. No surprise tools
    surface in allowed_tools."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    monkeypatch.delenv("ZOTERO_MCP_BINARY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)

    config = _build_mcp_servers_config("/fake/rka")
    assert "rka" in config
    assert "zotero" not in config


def test_build_mcp_servers_config_threads_env_through_to_zotero_builder(
    monkeypatch: pytest.MonkeyPatch,
):
    """Pass an explicit env= and confirm the zotero builder reads from it
    rather than os.environ. This is the path that surfaces project-local
    .rka/.env creds — they may not be in os.environ at all."""
    monkeypatch.setattr(
        "shutil.which", lambda name: "/x/zotero-mcp" if name == "zotero-mcp" else None
    )
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)

    project_env = {
        "ZOTERO_API_KEY": "project-only-key",
        "ZOTERO_LIBRARY_ID": "9646912",
    }
    config = _build_mcp_servers_config("/fake/rka", env=project_env)
    assert "zotero" in config
    assert config["zotero"]["env"]["ZOTERO_API_KEY"] == "project-only-key"


# ---------------------------------------------------------------------------
# _all_allowed_subprocess_tools — zotero gate
# ---------------------------------------------------------------------------


def test_allowed_tools_excludes_zotero_when_include_zotero_false():
    """Default: zotero tools not surfaced. Matches pre-v0.6.8 behavior."""
    tools = _all_allowed_subprocess_tools(include_context7=False)
    assert not any(t.startswith("mcp__zotero__") for t in tools)


def test_allowed_tools_includes_zotero_when_include_zotero_true():
    tools = _all_allowed_subprocess_tools(include_context7=False, include_zotero=True)
    zotero_tools = [t for t in tools if t.startswith("mcp__zotero__")]
    # All declared _ZOTERO_TOOLS surface, each with the mcp__zotero__ prefix
    assert len(zotero_tools) == len(_ZOTERO_TOOLS)
    for tool_name in _ZOTERO_TOOLS:
        assert f"mcp__zotero__{tool_name}" in zotero_tools


def test_allowed_tools_zotero_orthogonal_to_context7():
    """include_zotero + include_context7 compose without interference."""
    both = _all_allowed_subprocess_tools(include_context7=True, include_zotero=True)
    only_zotero = _all_allowed_subprocess_tools(
        include_context7=False, include_zotero=True
    )
    only_context7 = _all_allowed_subprocess_tools(
        include_context7=True, include_zotero=False
    )
    neither = _all_allowed_subprocess_tools(include_context7=False, include_zotero=False)
    # Composability: union of singles matches both
    assert set(both) == set(only_zotero) | set(only_context7)
    # Neither: no MCP tools beyond rka + builtin FS
    assert not any("zotero" in t or "context7" in t for t in neither)


# ---------------------------------------------------------------------------
# _parse_dotenv_lines — the simple parser
# ---------------------------------------------------------------------------


def test_parse_dotenv_basic_key_value():
    out = _parse_dotenv_lines("FOO=bar\nBAZ=qux\n")
    assert out == {"FOO": "bar", "BAZ": "qux"}


def test_parse_dotenv_skips_comments_and_blank_lines():
    text = """
# This is a comment
FOO=bar

# Another comment
BAZ=qux
"""
    assert _parse_dotenv_lines(text) == {"FOO": "bar", "BAZ": "qux"}


def test_parse_dotenv_strips_matching_quotes():
    text = """
SINGLE='alpha'
DOUBLE="beta"
MIXED="gamma'
NEITHER=delta
"""
    out = _parse_dotenv_lines(text)
    assert out["SINGLE"] == "alpha"
    assert out["DOUBLE"] == "beta"
    # Mismatched quotes preserved as-is
    assert out["MIXED"] == "\"gamma'"
    assert out["NEITHER"] == "delta"


def test_parse_dotenv_preserves_equals_in_value():
    """Values may contain '=' (e.g. base64 padding, query strings). Only
    the FIRST '=' is the separator."""
    out = _parse_dotenv_lines("URL=https://api.example.com/v1?key=abc=\n")
    assert out["URL"] == "https://api.example.com/v1?key=abc="


def test_parse_dotenv_skips_malformed_lines():
    text = """
GOOD=ok
malformed_no_equals
=no_key
GOOD2=alsoOk
"""
    out = _parse_dotenv_lines(text)
    assert out == {"GOOD": "ok", "GOOD2": "alsoOk"}


def test_parse_dotenv_empty_returns_empty_dict():
    assert _parse_dotenv_lines("") == {}
    assert _parse_dotenv_lines("\n\n\n") == {}
    assert _parse_dotenv_lines("# only comments\n") == {}


# ---------------------------------------------------------------------------
# _merge_project_env_file — the load-and-merge step
# ---------------------------------------------------------------------------


def test_merge_returns_env_unchanged_when_workspace_path_falsy():
    env = {"FOO": "bar"}
    assert _merge_project_env_file(env, None) == env
    assert _merge_project_env_file(env, "") == env


def test_merge_returns_env_unchanged_when_file_missing(tmp_path):
    """Missing .rka/.env is the NORMAL case for projects that don't use
    per-project creds. Must not raise."""
    env = {"FOO": "bar"}
    out = _merge_project_env_file(env, str(tmp_path))
    assert out == env


def test_merge_loads_values_from_existing_file(tmp_path):
    (tmp_path / ".rka").mkdir()
    (tmp_path / ".rka" / ".env").write_text(
        "DEEPSEEK_API_KEY=ds-abc\nSEC_EDGAR_USER_AGENT=foo\n"
    )
    env = {"BASELINE": "x"}
    out = _merge_project_env_file(env, str(tmp_path))
    assert out["BASELINE"] == "x"
    assert out["DEEPSEEK_API_KEY"] == "ds-abc"
    assert out["SEC_EDGAR_USER_AGENT"] == "foo"


def test_merge_project_values_override_inherited(tmp_path):
    """Project .rka/.env wins over inherited env when keys collide.
    Per-project context overrides daemon-level defaults."""
    (tmp_path / ".rka").mkdir()
    (tmp_path / ".rka" / ".env").write_text("API_KEY=project-value\n")
    env = {"API_KEY": "daemon-value", "OTHER": "preserved"}
    out = _merge_project_env_file(env, str(tmp_path))
    assert out["API_KEY"] == "project-value"
    assert out["OTHER"] == "preserved"


def test_merge_strips_anthropic_api_key_from_project_file(tmp_path):
    """Auth-scrub invariant: a .rka/.env that declares ANTHROPIC_API_KEY
    must NOT re-introduce it after _scrubbed_env stripped it. Otherwise
    a project file could re-route subprocess auth onto a billable
    API path."""
    (tmp_path / ".rka").mkdir()
    (tmp_path / ".rka" / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-malicious\nDEEPSEEK_API_KEY=ds-ok\n"
    )
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "max-path"}
    out = _merge_project_env_file(env, str(tmp_path))
    assert "ANTHROPIC_API_KEY" not in out
    assert out["CLAUDE_CODE_OAUTH_TOKEN"] == "max-path"  # untouched
    assert out["DEEPSEEK_API_KEY"] == "ds-ok"


def test_merge_handles_unreadable_file_gracefully(tmp_path, monkeypatch):
    """OS-level read errors (permission denied, etc.) must NOT raise —
    return the input env unchanged."""
    (tmp_path / ".rka").mkdir()
    env_path = tmp_path / ".rka" / ".env"
    env_path.write_text("FOO=bar\n")

    def _boom(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("pathlib.Path.read_text", _boom)
    env = {"BASELINE": "x"}
    out = _merge_project_env_file(env, str(tmp_path))
    assert out == env  # unchanged, no exception


def test_merge_returns_new_dict_does_not_mutate_input(tmp_path):
    """Defensive copy — caller's env should not be modified in place."""
    (tmp_path / ".rka").mkdir()
    (tmp_path / ".rka" / ".env").write_text("ADDED=x\n")
    env = {"ORIG": "y"}
    env_id_before = id(env)
    out = _merge_project_env_file(env, str(tmp_path))
    assert id(out) != env_id_before
    assert "ADDED" not in env  # original untouched
    assert "ADDED" in out


def test_merge_anthropic_api_key_is_in_scrub_list():
    """Sanity-check the scrub-list constant the helper depends on."""
    assert "ANTHROPIC_API_KEY" in _ENV_VARS_TO_SCRUB


# ---------------------------------------------------------------------------
# End-to-end — _RealSDKClient consumes both fixes
# ---------------------------------------------------------------------------


def test_real_sdk_client_merges_project_env_when_workspace_path_supplied(
    tmp_path, monkeypatch
):
    """The cockpit's repro: workspace_path is set, .rka/.env has
    DEEPSEEK_API_KEY, the client's _env must contain it."""
    (tmp_path / ".rka").mkdir()
    (tmp_path / ".rka" / ".env").write_text(
        "DEEPSEEK_API_KEY=ds-real\nSEC_EDGAR_USER_AGENT=ua\n"
    )
    # Clear from os.environ so we can prove it came from the file
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from orchestrator.llm_client import _RealSDKClient

    client = _RealSDKClient(workspace_path=str(tmp_path))
    assert client._env["DEEPSEEK_API_KEY"] == "ds-real"
    assert client._env["SEC_EDGAR_USER_AGENT"] == "ua"


def test_real_sdk_client_workspace_path_absent_skips_merge(
    tmp_path, monkeypatch
):
    """When workspace_path is None, behavior is pre-v0.6.8 (scrubbed
    os.environ only) — no surprise file loads."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from orchestrator.llm_client import _RealSDKClient

    client = _RealSDKClient(workspace_path=None)
    assert "DEEPSEEK_API_KEY" not in client._env


def test_real_sdk_client_explicit_env_skips_merge(tmp_path):
    """Explicit `env=` callers (tests) get exactly what they pass —
    no auto-merge from workspace_path."""
    (tmp_path / ".rka").mkdir()
    (tmp_path / ".rka" / ".env").write_text("FROM_FILE=yes\n")

    from orchestrator.llm_client import _RealSDKClient

    client = _RealSDKClient(env={"FROM_CALLER": "y"}, workspace_path=str(tmp_path))
    assert client._env == {"FROM_CALLER": "y"}
    assert "FROM_FILE" not in client._env
