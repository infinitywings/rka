"""Tests for `rka cred ...` (Phase 1 — global creds only).

All tests isolate from the real user home by setting XDG_CONFIG_HOME
via monkeypatch.setenv to a tmp_path-anchored directory.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from rka.cli import main
from rka.cli_cred import probes as probes_mod
from rka.cli_cred import propagators as propagators_mod
from rka.cli_cred.manifest import (
    DEFAULT_MANIFEST,
    Manifest,
    Versions,
    load_manifest,
    load_versions,
    render_manifest,
    render_versions,
    write_default_manifest,
    write_default_versions,
)
from rka.cli_cred.probes import (
    PROBE_FAIL,
    PROBE_PASS,
    PROBE_SKIP,
    probe_claude_desktop,
    probe_claude_code_json,
    probe_host_rka_version,
    probe_manifest_coverage,
    probe_orchestrator_version,
    probe_rka_server_health,
    probe_rka_server_zotero,
)
from rka.cli_cred.propagators import (
    propagate_claude_code,
    propagate_claude_desktop,
    propagate_orchestrator_env,
    propagate_rka_server,
)
from rka.cli_cred.vault import (
    Dotenv,
    DotenvLine,
    atomic_write_text,
    creds_path,
    ensure_vault_dir,
    file_mode,
    load_dotenv,
    manifest_path,
    parse_dotenv,
    save_dotenv,
    vault_root,
    versions_path,
)


# ----------------------------------------------------------------------
# Isolation fixture — point XDG_CONFIG_HOME at tmp_path
# ----------------------------------------------------------------------


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # Also prevent HOST_ORCH_ENV from polluting tests.
    monkeypatch.delenv("HOST_ORCH_ENV", raising=False)
    return xdg


@pytest.fixture
def runner():
    return CliRunner()


# ----------------------------------------------------------------------
# Parser round-trip
# ----------------------------------------------------------------------


def test_dotenv_parse_simple_kv():
    body = "FOO=bar\nBAZ=qux\n"
    dot = parse_dotenv(body)
    assert dot.get("FOO") == "bar"
    assert dot.get("BAZ") == "qux"
    assert dot.keys() == ["FOO", "BAZ"]


def test_dotenv_preserves_comments_and_blanks():
    body = "# top comment\n\nFOO=bar\n# inline\nBAZ=qux\n"
    dot = parse_dotenv(body)
    rendered = dot.render()
    assert "# top comment" in rendered
    assert "# inline" in rendered
    assert "FOO=bar" in rendered
    assert "BAZ=qux" in rendered


def test_dotenv_quoted_values_roundtrip():
    body = 'FOO="hello world"\nBAR="has = sign"\n'
    dot = parse_dotenv(body)
    assert dot.get("FOO") == "hello world"
    assert dot.get("BAR") == "has = sign"
    rendered = dot.render()
    # Re-parse and assert idempotent.
    dot2 = parse_dotenv(rendered)
    assert dot2.get("FOO") == "hello world"
    assert dot2.get("BAR") == "has = sign"


def test_dotenv_inline_hash_comment_stripped():
    body = "FOO=bar # this is a comment\n"
    dot = parse_dotenv(body)
    assert dot.get("FOO") == "bar"


def test_dotenv_export_prefix_handled():
    body = "export FOO=bar\n"
    dot = parse_dotenv(body)
    assert dot.get("FOO") == "bar"


def test_dotenv_set_preserves_order():
    body = "# header\nA=1\nB=2\nC=3\n"
    dot = parse_dotenv(body)
    dot.set("B", "two")
    rendered = dot.render()
    lines = [line for line in rendered.splitlines() if "=" in line]
    assert lines == ["A=1", "B=two", "C=3"]


def test_dotenv_set_new_key_appended():
    body = "A=1\n"
    dot = parse_dotenv(body)
    dot.set("B", "2")
    rendered = dot.render()
    assert "A=1" in rendered
    assert "B=2" in rendered
    assert rendered.index("A=1") < rendered.index("B=2")


def test_dotenv_unset_idempotent():
    body = "A=1\nB=2\n"
    dot = parse_dotenv(body)
    assert dot.unset("A") is True
    assert dot.unset("A") is False  # second call no-op
    assert dot.get("A") is None
    assert dot.get("B") == "2"


def test_dotenv_value_with_special_chars_quoted():
    dot = parse_dotenv("")
    dot.set("FOO", "value with spaces")
    rendered = dot.render()
    assert 'FOO="value with spaces"' in rendered


# ----------------------------------------------------------------------
# Vault root + file-mode enforcement
# ----------------------------------------------------------------------


def test_vault_root_xdg(vault_env):
    root = vault_root()
    assert root == vault_env / "rka"


def test_vault_root_fallback_when_xdg_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    root = vault_root()
    assert root == tmp_path / ".config" / "rka"


def test_ensure_vault_dir_creates_with_0700(vault_env):
    root = ensure_vault_dir()
    assert root.exists()
    mode = root.stat().st_mode & 0o777
    assert mode == 0o700


def test_save_dotenv_enforces_0600(vault_env):
    ensure_vault_dir()
    path = vault_env / "rka" / "creds.env"
    dot = parse_dotenv("")
    dot.set("FOO", "bar")
    save_dotenv(path, dot)
    assert path.exists()
    mode = file_mode(path)
    assert mode == 0o600


def test_atomic_write_text_creates_no_tmp_file(vault_env):
    ensure_vault_dir()
    path = vault_env / "rka" / "test.txt"
    atomic_write_text(path, "hello")
    assert path.read_text() == "hello"
    # No leftover .tmp files.
    tmps = [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]
    assert tmps == []


# ----------------------------------------------------------------------
# CLI: set / unset / get / env
# ----------------------------------------------------------------------


def test_cli_set_then_get_masked(vault_env, runner):
    res = runner.invoke(main, ["cred", "set", "FOO", "bar"])
    assert res.exit_code == 0, res.output
    res2 = runner.invoke(main, ["cred", "get", "FOO"])
    assert res2.exit_code == 0
    assert res2.output.strip() == "***"


def test_cli_get_show_unmasks(vault_env, runner):
    runner.invoke(main, ["cred", "set", "FOO", "secret"])
    res = runner.invoke(main, ["cred", "get", "FOO", "--show"])
    assert res.exit_code == 0
    assert res.output.strip() == "secret"


def test_cli_get_missing_exits_1(vault_env, runner):
    # Ensure vault file exists empty.
    runner.invoke(main, ["cred", "set", "OTHER", "x"])
    res = runner.invoke(main, ["cred", "get", "DOES_NOT_EXIST"])
    assert res.exit_code == 1


def test_cli_unset_idempotent(vault_env, runner):
    runner.invoke(main, ["cred", "set", "FOO", "bar"])
    res = runner.invoke(main, ["cred", "unset", "FOO"])
    assert res.exit_code == 0
    res2 = runner.invoke(main, ["cred", "unset", "FOO"])
    assert res2.exit_code == 0
    assert "no-op" in res2.output


def test_cli_set_preserves_creds_file_mode(vault_env, runner):
    runner.invoke(main, ["cred", "set", "A", "1"])
    runner.invoke(main, ["cred", "set", "B", "2"])
    mode = file_mode(creds_path())
    assert mode == 0o600


def test_cli_env_dotenv_format(vault_env, runner):
    runner.invoke(main, ["cred", "set", "FOO", "bar"])
    runner.invoke(main, ["cred", "set", "BAZ", "qux"])
    res = runner.invoke(main, ["cred", "env"])
    assert res.exit_code == 0
    assert "FOO=bar" in res.output
    assert "BAZ=qux" in res.output


def test_cli_env_json_format(vault_env, runner):
    runner.invoke(main, ["cred", "set", "FOO", "bar"])
    runner.invoke(main, ["cred", "set", "BAZ", "qux"])
    res = runner.invoke(main, ["cred", "env", "--format", "json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data == {"FOO": "bar", "BAZ": "qux"}


def test_cli_env_shell_format(vault_env, runner):
    runner.invoke(main, ["cred", "set", "FOO", "bar"])
    res = runner.invoke(main, ["cred", "env", "--format", "shell"])
    assert res.exit_code == 0
    assert "export FOO='bar'" in res.output


# ----------------------------------------------------------------------
# Init (non-interactive)
# ----------------------------------------------------------------------


def test_cli_init_non_interactive_creates_defaults(vault_env, runner):
    res = runner.invoke(main, ["cred", "init", "--non-interactive"])
    assert res.exit_code == 0, res.output
    assert manifest_path().exists()
    assert versions_path().exists()
    assert creds_path().exists()
    # File mode on creds.env.
    assert file_mode(creds_path()) == 0o600


def test_cli_init_idempotent_does_not_overwrite_manifest(vault_env, runner):
    # First init.
    runner.invoke(main, ["cred", "init", "--non-interactive"])
    # Edit manifest by hand.
    manifest_path().write_text('[global]\nrequired = ["CUSTOM_KEY"]\noptional = []\n')
    # Second init should not overwrite.
    runner.invoke(main, ["cred", "init", "--non-interactive"])
    body = manifest_path().read_text()
    assert "CUSTOM_KEY" in body


# ----------------------------------------------------------------------
# Manifest TOML round-trip
# ----------------------------------------------------------------------


def test_render_manifest_parses_back(vault_env):
    body = render_manifest(DEFAULT_MANIFEST)
    # Validate we can parse it back via tomllib (used by load_manifest).
    import tomllib

    parsed = tomllib.loads(body)
    assert parsed["global"]["required"] == DEFAULT_MANIFEST["global"]["required"]
    assert parsed["global"]["optional"] == DEFAULT_MANIFEST["global"]["optional"]


def test_render_versions_parses_back(vault_env):
    body = render_versions(
        {"rka": "2.7.0.3", "zotero-mcp": ">=0.1.0"},
        {"rka-server": "2.7.0.3", "rka-orchestrator": "0.6.8"},
    )
    import tomllib

    parsed = tomllib.loads(body)
    assert parsed["host"]["binaries"]["rka"] == "2.7.0.3"
    assert parsed["containers"]["rka-server"] == "2.7.0.3"


def test_load_manifest_falls_back_to_defaults_when_missing(vault_env):
    m = load_manifest()
    assert m.global_required == DEFAULT_MANIFEST["global"]["required"]
    assert m.global_optional == DEFAULT_MANIFEST["global"]["optional"]


# ----------------------------------------------------------------------
# Propagation: dry-run does NOT write
# ----------------------------------------------------------------------


def _make_claude_desktop_config(path: Path, env: dict[str, str]):
    body = {
        "mcpServers": {
            "rka": {"command": "rka", "args": ["mcp"]},
            "zotero": {
                "command": "zotero-mcp",
                "args": [],
                "env": env,
            },
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2))


def test_propagate_claude_desktop_dry_run_does_not_write(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    _make_claude_desktop_config(cfg, env={"ZOTERO_API_KEY": "old", "ZOTERO_LIBRARY_ID": "old"})
    original_body = cfg.read_text()

    creds = {"ZOTERO_API_KEY": "new", "ZOTERO_LIBRARY_ID": "new", "ZOTERO_LIBRARY_TYPE": "user"}
    result = propagate_claude_desktop(creds, apply=False, config_path=cfg)

    assert result.status == "would_change"
    # File contents unchanged.
    assert cfg.read_text() == original_body


def test_propagate_claude_desktop_apply_writes(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    _make_claude_desktop_config(cfg, env={"ZOTERO_API_KEY": "old", "ZOTERO_LIBRARY_ID": "old"})

    creds = {"ZOTERO_API_KEY": "new", "ZOTERO_LIBRARY_ID": "new123", "ZOTERO_LIBRARY_TYPE": "user"}
    result = propagate_claude_desktop(creds, apply=True, config_path=cfg)

    assert result.status == "applied"
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["zotero"]["env"]["ZOTERO_API_KEY"] == "new"
    assert data["mcpServers"]["zotero"]["env"]["ZOTERO_LIBRARY_ID"] == "new123"
    # Preserved: other mcpServers entries.
    assert "rka" in data["mcpServers"]
    assert data["mcpServers"]["rka"]["command"] == "rka"


def test_propagate_claude_desktop_unchanged_when_matched(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    _make_claude_desktop_config(
        cfg, env={"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "12", "ZOTERO_LIBRARY_TYPE": "user"}
    )
    creds = {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "12", "ZOTERO_LIBRARY_TYPE": "user"}
    result = propagate_claude_desktop(creds, apply=True, config_path=cfg)
    assert result.status == "unchanged"


def test_propagate_claude_desktop_skipped_when_zotero_block_missing(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"rka": {}}}))
    creds = {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "12"}
    result = propagate_claude_desktop(creds, apply=True, config_path=cfg)
    assert result.status == "skipped"


def test_propagate_claude_desktop_skipped_when_file_missing(tmp_path):
    cfg = tmp_path / "missing.json"
    creds = {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "12"}
    result = propagate_claude_desktop(creds, apply=True, config_path=cfg)
    assert result.status == "skipped"


def test_propagate_claude_code_apply_writes(tmp_path):
    cfg = tmp_path / "claude.json"
    body = {
        "mcpServers": {
            "rka": {"command": "rka"},
            "zotero": {"type": "stdio", "command": "zotero-mcp", "env": {}},
        }
    }
    cfg.write_text(json.dumps(body))
    creds = {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    result = propagate_claude_code(creds, apply=True, config_path=cfg)
    assert result.status == "applied"
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["zotero"]["env"]["ZOTERO_API_KEY"] == "k"
    assert data["mcpServers"]["rka"]["command"] == "rka"  # preserved


# ----------------------------------------------------------------------
# Propagation: orchestrator/.env (excludes ANTHROPIC_API_KEY)
# ----------------------------------------------------------------------


def test_propagate_orchestrator_env_dry_run(tmp_path):
    env_file = tmp_path / "orchestrator.env"
    env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=foo\nZOTERO_API_KEY=old\n")
    original = env_file.read_text()
    creds = {"ZOTERO_API_KEY": "new", "ZOTERO_LIBRARY_ID": "9", "ANTHROPIC_API_KEY": "skip-me"}
    result = propagate_orchestrator_env(creds, apply=False, target_path=env_file)
    assert result.status == "would_change"
    assert "ZOTERO_API_KEY" in result.changes
    assert "ANTHROPIC_API_KEY" not in result.changes
    # File unchanged.
    assert env_file.read_text() == original


def test_propagate_orchestrator_env_apply_excludes_anthropic(tmp_path):
    env_file = tmp_path / "orchestrator.env"
    env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=foo\nZOTERO_API_KEY=old\n")
    creds = {
        "ZOTERO_API_KEY": "new",
        "ZOTERO_LIBRARY_ID": "9",
        "ZOTERO_LIBRARY_TYPE": "user",
        "ANTHROPIC_API_KEY": "should-not-appear",
    }
    result = propagate_orchestrator_env(creds, apply=True, target_path=env_file)
    assert result.status == "applied"
    body = env_file.read_text()
    assert "ZOTERO_API_KEY=new" in body
    assert "ZOTERO_LIBRARY_ID=9" in body
    assert "ANTHROPIC_API_KEY" not in body
    assert "CLAUDE_CODE_OAUTH_TOKEN=foo" in body  # preserved


def test_propagate_orchestrator_env_skipped_when_missing(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    creds = {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "9"}
    result = propagate_orchestrator_env(creds, apply=True, target_path=missing)
    assert result.status == "skipped"


# ----------------------------------------------------------------------
# Propagation: rka-server REST (with injected httpx mock)
# ----------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status_code: int
    body: dict

    def json(self):
        return self.body

    @property
    def text(self):
        return json.dumps(self.body)


class _FakeHttpClient:
    """Mimics httpx top-level functions get/put."""

    def __init__(self, get_response: _FakeResponse, put_response: _FakeResponse | None = None):
        self._get = get_response
        self._put = put_response
        self.put_calls = []
        self.get_calls = []

    def get(self, url, **kw):
        self.get_calls.append((url, kw))
        return self._get

    def put(self, url, **kw):
        self.put_calls.append((url, kw))
        return self._put


def test_propagate_rka_server_dry_run_no_put(tmp_path):
    client = _FakeHttpClient(
        get_response=_FakeResponse(200, {"api_key": "", "library_id": "old", "library_type": "user"}),
    )
    creds = {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    result = propagate_rka_server(creds, apply=False, http_client=client)
    assert result.status == "would_change"
    assert client.put_calls == []


def test_propagate_rka_server_apply_puts(tmp_path):
    client = _FakeHttpClient(
        get_response=_FakeResponse(200, {"api_key": "", "library_id": "old", "library_type": "user"}),
        put_response=_FakeResponse(
            200, {"api_key": "***", "library_id": "9", "library_type": "user"}
        ),
    )
    creds = {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    result = propagate_rka_server(creds, apply=True, http_client=client)
    assert result.status == "applied"
    assert len(client.put_calls) == 1
    url, kw = client.put_calls[0]
    assert "/api/config/zotero" in url
    assert kw["json"]["api_key"] == "k"
    assert kw["json"]["library_id"] == "9"
    assert kw["params"]["actor"] == "cred-vault"


def test_propagate_rka_server_skipped_when_missing_creds(tmp_path):
    client = _FakeHttpClient(get_response=_FakeResponse(200, {}))
    creds = {"ZOTERO_API_KEY": ""}
    result = propagate_rka_server(creds, apply=True, http_client=client)
    assert result.status == "skipped"


# ----------------------------------------------------------------------
# Probes: claude_desktop, claude_code_json (file-based)
# ----------------------------------------------------------------------


def test_probe_claude_desktop_pass(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    _make_claude_desktop_config(
        cfg, env={"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    )
    creds = {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    r = probe_claude_desktop(creds, config_path=cfg)
    assert r.status == PROBE_PASS


def test_probe_claude_desktop_fail_on_divergence(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    _make_claude_desktop_config(
        cfg, env={"ZOTERO_API_KEY": "old", "ZOTERO_LIBRARY_ID": "old"}
    )
    creds = {"ZOTERO_API_KEY": "new", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    r = probe_claude_desktop(creds, config_path=cfg)
    assert r.status == PROBE_FAIL


def test_probe_claude_desktop_skip_when_missing(tmp_path):
    cfg = tmp_path / "missing.json"
    r = probe_claude_desktop({"ZOTERO_API_KEY": "v"}, config_path=cfg)
    assert r.status == PROBE_SKIP


def test_probe_claude_code_json_pass(tmp_path):
    cfg = tmp_path / "claude.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "zotero": {
                        "type": "stdio",
                        "env": {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "9"},
                    }
                }
            }
        )
    )
    creds = {"ZOTERO_API_KEY": "v", "ZOTERO_LIBRARY_ID": "9"}
    r = probe_claude_code_json(creds, config_path=cfg)
    assert r.status == PROBE_PASS


# ----------------------------------------------------------------------
# Probes: manifest coverage
# ----------------------------------------------------------------------


def test_probe_manifest_coverage_pass():
    manifest = Manifest(global_required=["A", "B"], global_optional=[])
    creds = {"A": "1", "B": "2"}
    r = probe_manifest_coverage(manifest, creds)
    assert r.status == PROBE_PASS


def test_probe_manifest_coverage_fail():
    manifest = Manifest(global_required=["A", "B"], global_optional=[])
    creds = {"A": "1"}
    r = probe_manifest_coverage(manifest, creds)
    assert r.status == PROBE_FAIL
    assert "B" in r.found


# ----------------------------------------------------------------------
# Probes: rka-server REST (httpx mocked)
# ----------------------------------------------------------------------


def test_probe_rka_server_zotero_pass():
    client = _FakeHttpClient(
        get_response=_FakeResponse(
            200, {"api_key": "***", "library_id": "9", "library_type": "user"}
        )
    )
    creds = {"ZOTERO_API_KEY": "x", "ZOTERO_LIBRARY_ID": "9", "ZOTERO_LIBRARY_TYPE": "user"}
    r = probe_rka_server_zotero(creds, http_client=client)
    assert r.status == PROBE_PASS


def test_probe_rka_server_zotero_fail_on_library_id_mismatch():
    client = _FakeHttpClient(
        get_response=_FakeResponse(
            200, {"api_key": "***", "library_id": "OTHER", "library_type": "user"}
        )
    )
    creds = {"ZOTERO_API_KEY": "x", "ZOTERO_LIBRARY_ID": "9"}
    r = probe_rka_server_zotero(creds, http_client=client)
    assert r.status == PROBE_FAIL


def test_probe_rka_server_zotero_skip_on_connection_error():
    class _Boom:
        def get(self, *_a, **_kw):
            raise RuntimeError("connect refused")

    r = probe_rka_server_zotero({"ZOTERO_API_KEY": "x", "ZOTERO_LIBRARY_ID": "9"}, http_client=_Boom())
    assert r.status == PROBE_SKIP


def test_probe_rka_server_health_pass():
    client = _FakeHttpClient(get_response=_FakeResponse(200, {"status": "ok", "version": "2.7.0.3"}))
    versions = Versions(host_binaries={}, containers={"rka-server": "2.7.0.3"})
    r = probe_rka_server_health(versions, http_client=client)
    assert r.status == PROBE_PASS


def test_probe_rka_server_health_fail_on_version_mismatch():
    client = _FakeHttpClient(get_response=_FakeResponse(200, {"version": "2.7.0.2"}))
    versions = Versions(host_binaries={}, containers={"rka-server": "2.7.0.3"})
    r = probe_rka_server_health(versions, http_client=client)
    assert r.status == PROBE_FAIL


# ----------------------------------------------------------------------
# Probes: host rka --version (subprocess mocked)
# ----------------------------------------------------------------------


def test_probe_host_rka_version_pass(monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "rka, version 2.7.0.3\n"

    monkeypatch.setattr(probes_mod.subprocess, "run", lambda *a, **kw: _Completed())
    versions = Versions(host_binaries={"rka": "2.7.0.3"}, containers={})
    r = probe_host_rka_version(versions)
    assert r.status == PROBE_PASS


def test_probe_host_rka_version_fail(monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "rka, version 2.7.0.1\n"

    monkeypatch.setattr(probes_mod.subprocess, "run", lambda *a, **kw: _Completed())
    versions = Versions(host_binaries={"rka": "2.7.0.3"}, containers={})
    r = probe_host_rka_version(versions)
    assert r.status == PROBE_FAIL


def test_probe_host_rka_version_fail_when_missing(monkeypatch):
    def _raise(*a, **kw):
        raise FileNotFoundError("no rka in PATH")

    monkeypatch.setattr(probes_mod.subprocess, "run", _raise)
    versions = Versions(host_binaries={"rka": "2.7.0.3"}, containers={})
    r = probe_host_rka_version(versions)
    assert r.status == PROBE_FAIL


# ----------------------------------------------------------------------
# Probes: orchestrator container version (subprocess mocked)
# ----------------------------------------------------------------------


def test_probe_orchestrator_version_skip_when_not_running(monkeypatch):
    monkeypatch.setattr(probes_mod, "_docker_container_running", lambda c: False)
    versions = Versions(host_binaries={}, containers={"rka-orchestrator": "0.6.8"})
    r = probe_orchestrator_version(versions)
    assert r.status == PROBE_SKIP


def test_probe_orchestrator_version_fail_on_mismatch(monkeypatch):
    monkeypatch.setattr(probes_mod, "_docker_container_running", lambda c: True)

    class _Completed:
        returncode = 0
        stdout = 'version = "0.6.6"\n'

    monkeypatch.setattr(probes_mod.subprocess, "run", lambda *a, **kw: _Completed())
    versions = Versions(host_binaries={}, containers={"rka-orchestrator": "0.6.8"})
    r = probe_orchestrator_version(versions)
    assert r.status == PROBE_FAIL


def test_probe_orchestrator_version_pass(monkeypatch):
    monkeypatch.setattr(probes_mod, "_docker_container_running", lambda c: True)

    class _Completed:
        returncode = 0
        stdout = 'version = "0.6.8"\n'

    monkeypatch.setattr(probes_mod.subprocess, "run", lambda *a, **kw: _Completed())
    versions = Versions(host_binaries={}, containers={"rka-orchestrator": "0.6.8"})
    r = probe_orchestrator_version(versions)
    assert r.status == PROBE_PASS


# ----------------------------------------------------------------------
# CLI propagate end-to-end (dry-run uses CliRunner)
# ----------------------------------------------------------------------


def test_cli_propagate_dry_run_default(vault_env, runner, monkeypatch):
    # Stub all propagators to return SKIP so the CLI doesn't touch real fs.
    def _stub(creds, *, apply, **kw):
        from rka.cli_cred.propagators import PropagationResult

        return PropagationResult(consumer="stub", status="skipped", summary="stubbed")

    monkeypatch.setattr(
        "rka.cli_cred.commands.all_propagators",
        lambda: [("stub", _stub)],
    )
    runner.invoke(main, ["cred", "set", "FOO", "bar"])
    res = runner.invoke(main, ["cred", "propagate"])
    assert res.exit_code == 0
    assert "DRY-RUN" in res.output


def test_cli_propagate_apply_flag(vault_env, runner, monkeypatch):
    seen_apply = []

    def _stub(creds, *, apply, **kw):
        from rka.cli_cred.propagators import PropagationResult

        seen_apply.append(apply)
        return PropagationResult(consumer="stub", status="unchanged", summary="ok")

    monkeypatch.setattr(
        "rka.cli_cred.commands.all_propagators",
        lambda: [("stub", _stub)],
    )
    runner.invoke(main, ["cred", "set", "FOO", "bar"])
    res = runner.invoke(main, ["cred", "propagate", "--apply"])
    assert res.exit_code == 0
    assert "APPLY mode" in res.output
    assert seen_apply == [True]


# ----------------------------------------------------------------------
# CLI check: exit-code semantics
# ----------------------------------------------------------------------


def test_cli_check_exit_0_when_all_pass_or_skip(vault_env, runner, monkeypatch):
    def _stub_probes(*a, **kw):
        from rka.cli_cred.probes import ProbeResult

        return [
            ProbeResult(name="x", status=PROBE_PASS),
            ProbeResult(name="y", status=PROBE_SKIP),
        ]

    monkeypatch.setattr("rka.cli_cred.commands.run_all_probes", _stub_probes)
    res = runner.invoke(main, ["cred", "check"])
    assert res.exit_code == 0


def test_cli_check_exit_1_on_any_fail(vault_env, runner, monkeypatch):
    def _stub_probes(*a, **kw):
        from rka.cli_cred.probes import ProbeResult

        return [
            ProbeResult(name="x", status=PROBE_PASS),
            ProbeResult(name="y", status=PROBE_FAIL, hint="fix it"),
        ]

    monkeypatch.setattr("rka.cli_cred.commands.run_all_probes", _stub_probes)
    res = runner.invoke(main, ["cred", "check"])
    assert res.exit_code == 1
    assert "FAIL" in res.output
    assert "fix it" in res.output


# ----------------------------------------------------------------------
# Smoke: cred group registered on main
# ----------------------------------------------------------------------


def test_cred_group_registered_on_main(runner):
    res = runner.invoke(main, ["cred", "--help"])
    assert res.exit_code == 0
    for sub in ("init", "set", "unset", "get", "env", "propagate", "check"):
        assert sub in res.output
