"""Phase G2 — FS-Actuator `can_use_tool` hook tests.

The hook bridges `fs_actuator.classify_fs_action` to the
claude-agent-sdk `can_use_tool` callback. These tests use a minimal
fake SDK module to stand in for the real `claude_agent_sdk` import
so we don't need network/auth/subprocess plumbing.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Minimal fake SDK module — installed into sys.modules so the hook's local
# `import claude_agent_sdk as sdk` finds it.
# ---------------------------------------------------------------------------


class _FakePermissionResultAllow:
    def __init__(self, updated_input=None, updated_permissions=None):
        self.behavior = "allow"
        self.updated_input = updated_input
        self.updated_permissions = updated_permissions


class _FakePermissionResultDeny:
    def __init__(self, message: str = "", interrupt: bool = False):
        self.behavior = "deny"
        self.message = message
        self.interrupt = interrupt


def _install_fake_sdk(monkeypatch):
    """Inject a stub `claude_agent_sdk` module exposing the two Permission
    classes the hook needs. Restored by monkeypatch on teardown."""
    fake = types.ModuleType("claude_agent_sdk")
    fake.PermissionResultAllow = _FakePermissionResultAllow
    fake.PermissionResultDeny = _FakePermissionResultDeny
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)


# ---------------------------------------------------------------------------
# Hook semantics — auto-allow non-FS-mutating tools
# ---------------------------------------------------------------------------


def test_hook_allows_non_mutating_tool(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(hook("mcp__rka__rka_get_status", {}, None))
    assert result.behavior == "allow"


def test_hook_allows_read_tool(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    for tool in ("Read", "Grep", "Glob"):
        result = asyncio.run(hook(tool, {"file_path": "/etc/passwd"}, None))
        assert result.behavior == "allow", f"{tool} read should be allowed"


# ---------------------------------------------------------------------------
# Hook semantics — Bash classification
# ---------------------------------------------------------------------------


def test_hook_allows_scoped_bash(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(hook("Bash", {"command": "python analysis.py"}, None))
    assert result.behavior == "allow"


def test_hook_denies_destructive_bash_with_ratify_message(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(hook("Bash", {"command": "git push origin main"}, None))
    assert result.behavior == "deny"
    assert "ratification" in result.message
    assert "proposed_fs_actions" in result.message


def test_hook_denies_rm_flag_reorder_bypass(monkeypatch):
    """v0.6.11 — `rm -fr` (flag-reordered) must now be caught by the hook,
    where previously it slipped through to auto-allow."""
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    for cmd in ("rm -fr /ws/proj/data", "rm -Rf build", "rm -r -f node_modules"):
        result = asyncio.run(hook("Bash", {"command": cmd}, None))
        assert result.behavior == "deny", f"{cmd!r} should be denied (ratify)"


# ---------------------------------------------------------------------------
# v0.6.11 — egress audit + control for WebFetch/WebSearch
# ---------------------------------------------------------------------------


def test_hook_allows_general_web_fetch(monkeypatch):
    """Research workflow needs open fetch — a normal URL is allowed by
    default (no allowlist set)."""
    _install_fake_sdk(monkeypatch)
    monkeypatch.delenv("ORCHESTRATOR_EGRESS_ALLOWLIST", raising=False)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(
        hook("WebFetch", {"url": "https://arxiv.org/abs/2401.00001"}, None)
    )
    assert result.behavior == "allow"


def test_hook_denies_telemetry_endpoint(monkeypatch):
    """Known telemetry endpoints are denied (blocklist floor), even with no
    allowlist configured."""
    _install_fake_sdk(monkeypatch)
    monkeypatch.delenv("ORCHESTRATOR_EGRESS_ALLOWLIST", raising=False)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(
        hook("WebFetch", {"url": "https://api.segment.io/v1/track?x=secret"}, None)
    )
    assert result.behavior == "deny"
    assert "telemetry" in result.message


def test_hook_egress_allowlist_opt_in_denies_offlist(monkeypatch):
    """When ORCHESTRATOR_EGRESS_ALLOWLIST is set, only matching hosts pass
    (deny-by-default for security-conscious installs)."""
    _install_fake_sdk(monkeypatch)
    monkeypatch.setenv("ORCHESTRATOR_EGRESS_ALLOWLIST", "arxiv.org,sec.gov")
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    # On-list host allowed.
    ok = asyncio.run(hook("WebFetch", {"url": "https://arxiv.org/abs/x"}, None))
    assert ok.behavior == "allow"
    # Off-list host denied.
    no = asyncio.run(hook("WebFetch", {"url": "https://evil.example.com/exfil"}, None))
    assert no.behavior == "deny"
    assert "ORCHESTRATOR_EGRESS_ALLOWLIST" in no.message


def test_hook_websearch_audited_and_allowed(monkeypatch):
    """WebSearch (query, not url) is audited and allowed by default."""
    _install_fake_sdk(monkeypatch)
    monkeypatch.delenv("ORCHESTRATOR_EGRESS_ALLOWLIST", raising=False)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(hook("WebSearch", {"query": "hyperscaler lease commitments"}, None))
    assert result.behavior == "allow"


def test_hook_denies_denied_bash_with_no_override_message(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(hook("Bash", {"command": "sudo rm -rf /etc/x"}, None))
    assert result.behavior == "deny"
    assert "DENIED" in result.message
    assert "rka_submit_checkpoint" in result.message


# ---------------------------------------------------------------------------
# Hook semantics — Write / Edit classification
# ---------------------------------------------------------------------------


def test_hook_allows_write_inside_workspace(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(
        hook("Write", {"file_path": "/ws/proj/results/out.csv"}, None)
    )
    assert result.behavior == "allow"


def test_hook_denies_write_outside_workspace_with_ratify_message(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(
        hook("Edit", {"file_path": "/etc/cron.d/evil"}, None)
    )
    assert result.behavior == "deny"
    assert "ratification" in result.message
    assert "proposed_fs_actions" in result.message


def test_hook_denies_write_with_dotdot_traversal(monkeypatch):
    """Phase G adversarial hardening flows through to the hook: a
    `..`-traversal Write target must be denied with ratify-required
    message, not silently allowed."""
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(
        hook("Write", {"file_path": "/ws/proj/../etc/passwd"}, None)
    )
    assert result.behavior == "deny"
    assert "ratification" in result.message


# ---------------------------------------------------------------------------
# Workspace_path resolution in _RealSDKClient
# ---------------------------------------------------------------------------


def test_resolve_workspace_path_prefers_explicit(monkeypatch):
    """Explicit workspace_path wins over HOST_WORKSPACE_ROOT env var."""
    monkeypatch.setenv("HOST_WORKSPACE_ROOT", "/from/env")
    from orchestrator import llm_client

    client = llm_client._RealSDKClient(
        env={}, project_id="prj_test", workspace_path="/explicit/ws"
    )
    assert client._resolve_workspace_path() == "/explicit/ws"


def test_resolve_workspace_path_falls_back_to_env(monkeypatch):
    """When workspace_path is None, HOST_WORKSPACE_ROOT is used."""
    monkeypatch.setenv("HOST_WORKSPACE_ROOT", "/from/env")
    from orchestrator import llm_client

    client = llm_client._RealSDKClient(
        env={}, project_id="prj_test", workspace_path=None
    )
    assert client._resolve_workspace_path() == "/from/env"


def test_resolve_workspace_path_empty_when_neither_set(monkeypatch):
    """When neither is set, returns empty string — classify_fs_action
    treats this as 'no escape check' (still enforces DENY-tier bash)."""
    monkeypatch.delenv("HOST_WORKSPACE_ROOT", raising=False)
    from orchestrator import llm_client

    client = llm_client._RealSDKClient(env={}, project_id="prj_test")
    assert client._resolve_workspace_path() == ""


# ---------------------------------------------------------------------------
# Workspace-path-empty mode — Bash DENY-tier still enforced
# ---------------------------------------------------------------------------


def test_hook_with_empty_workspace_still_denies_sudo(monkeypatch):
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("")  # no workspace
    result = asyncio.run(hook("Bash", {"command": "sudo apt install x"}, None))
    assert result.behavior == "deny"
    assert "DENIED" in result.message


def test_hook_with_empty_workspace_allows_normal_write(monkeypatch):
    """When workspace_path is empty, Write/Edit escape detection is
    skipped (per classify_fs_action's documented contract) — calls
    are auto-allowed as scoped_write."""
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("")
    result = asyncio.run(hook("Write", {"file_path": "/tmp/x.txt"}, None))
    assert result.behavior == "allow"


# ---------------------------------------------------------------------------
# Phase G2 adversarial-review H1 — defense-in-depth: mcp__rka__ WRITE_TOOLS
# must never be Allow'd by the hook even if SDK precedence inverts.
# ---------------------------------------------------------------------------


def test_hook_denies_mcp_rka_write_tools_defense_in_depth(monkeypatch):
    """If `mcp__rka__rka_add_note` (and any other WRITE_TOOLS-prefixed
    name) ever reaches the hook (today blocked by `disallowed_tools`
    before the hook fires), it must be denied — never silently allowed.
    Adversarial-review H1: SDK upstream change reordering precedence
    would otherwise strip the Phase 2.7 Option C invariant."""
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    for write_tool in llm_client.WRITE_TOOLS:
        prefixed = f"mcp__rka__{write_tool}"
        result = asyncio.run(hook(prefixed, {}, None))
        assert result.behavior == "deny", (
            f"{prefixed} must be denied by the hook (Phase 2.7 Option C "
            f"defense-in-depth)"
        )
        assert "Option C" in result.message or "proposed_actions" in result.message


def test_hook_denies_mcp_rka_write_even_when_workspace_empty(monkeypatch):
    """The mcp__rka__ defense-in-depth deny fires regardless of
    workspace_path — it's an MCP-server invariant, not an FS-scope one."""
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("")
    result = asyncio.run(hook("mcp__rka__rka_add_decision", {}, None))
    assert result.behavior == "deny"


def test_hook_still_allows_mcp_rka_read_tools(monkeypatch):
    """Read-side mcp__rka__ tools must NOT be caught by the defense-in-
    depth net — only WRITE_TOOLS are denied."""
    _install_fake_sdk(monkeypatch)
    from orchestrator import llm_client

    hook = llm_client._build_fs_actuator_hook("/ws/proj")
    result = asyncio.run(hook("mcp__rka__rka_get_status", {}, None))
    assert result.behavior == "allow"
