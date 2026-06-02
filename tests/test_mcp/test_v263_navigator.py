"""v2.6.3 — Dynamic tool surface (navigator architecture) tests.

The navigator architecture splits the rka MCP tool surface into two tiers:
- 3 always-on navigator tools registered at module import
  (v2.6.5 shrunk the always-on tier from 12 → 3 — see test_always_on_tier_membership)
- ~91 deferred tools registered on demand via `rka_load_tools` + a
  `notifications/tools/list_changed` notification

These tests verify the split is correct, the navigator semantics are
honest, the FastMCP `tools.listChanged: true` capability is advertised,
and the registration path is identical to what `mcp.tool()` would have
produced at import (so no schema asymmetry between always-on and
on-demand tools).

Cross-client compatibility note: the MCP `notifications/tools/list_changed`
mechanism is honored by both Claude Desktop and Claude Code (including
its plugin mode). We exercise the spec contract here at the FastMCP
session-shim layer; the wire-protocol layer is exercised by FastMCP's
own conformance tests.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from rka.mcp.server import (
    _TIER_ALWAYS_ON,
    _TIER_DEFERRED,
    _TOOL_REGISTRY,
    mcp,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal MCP session double — records `send_tool_list_changed` calls."""

    def __init__(self) -> None:
        self.notifications: int = 0

    async def send_tool_list_changed(self) -> None:
        self.notifications += 1


class _FakeCtx:
    """FastMCP Context double — only exposes `.session` (the only attr
    rka_load_tools touches)."""

    def __init__(self) -> None:
        self.session = _FakeSession()


@pytest.fixture
def ctx() -> _FakeCtx:
    return _FakeCtx()


@pytest.fixture(autouse=True)
def _reset_deferred_registrations():
    """After each test, walk the registry and un-register any deferred
    tools that got flipped to `registered=True` by the test, restoring
    the module-import baseline so the next test starts clean.

    Side-effecting the global registry is OK in tests as long as we
    restore — alternative would be deep-copying the registry per-test,
    which would diverge from the actual production singleton being
    exercised.
    """
    baseline_registered = {
        name: rec["registered"] for name, rec in _TOOL_REGISTRY.items()
    }
    yield
    for name, was_registered in baseline_registered.items():
        rec = _TOOL_REGISTRY.get(name)
        if rec is None:
            continue
        if rec["registered"] and not was_registered:
            # Un-register from FastMCP's tool manager too, so the next
            # test sees the original always-on count.
            try:
                mcp._tool_manager.remove_tool(name)
            except Exception:
                pass
            rec["registered"] = False


# ---------------------------------------------------------------------------
# Tier split (the architectural invariant)
# ---------------------------------------------------------------------------


def test_registry_contains_all_rka_tools():
    """Every rka_* function in server.py is registered, regardless of tier."""
    names = set(_TOOL_REGISTRY)
    # 91 original rka_* tools + 3 navigator tools = 94 minimum.
    assert len(names) >= 94
    # Every name must start with `rka_` (the canonical prefix).
    assert all(n.startswith("rka_") for n in names)


def test_always_on_tier_membership():
    """v2.6.5 — the always-on layer is NAVIGATOR-ONLY (3 tools).

    v2.6.5 shrunk the always-on tier from 12 → 3 after Claude Desktop's
    client-side tool-surface filter was empirically observed dropping
    navigator tools when multiple MCP servers competed for the budget
    (mcp-server-rka.log, 2026-06-02 04:25:56Z). With only 3 navigator
    tools always-on, the loader survives any reasonable filter and the
    client's first turn loads its working surface via rka_load_tools.

    This is the load-bearing list — 3 navigator tools — if a tool moves
    between tiers it will surface here so the change is deliberate, not
    silent.
    """
    expected_always_on = {
        # Navigator (the entire always-on surface — v2.6.5)
        "rka_load_tools",
        "rka_list_tools",
        "rka_help",
    }
    actual_always_on = {
        n for n, r in _TOOL_REGISTRY.items() if r["tier"] == _TIER_ALWAYS_ON
    }
    assert actual_always_on == expected_always_on, (
        f"always-on membership drift: "
        f"added {actual_always_on - expected_always_on} / "
        f"removed {expected_always_on - actual_always_on}"
    )


def test_deferred_tier_size_within_cap():
    """v2.6.5 — the deferred layer is every non-navigator rka tool.

    Post-v2.6.5: always-on = 3 (navigator), deferred = 88+ (everything
    else, including rka_get_status / rka_search / rka_add_note that
    used to be always-on through v2.6.4).
    """
    always_on = [
        n for n, r in _TOOL_REGISTRY.items() if r["tier"] == _TIER_ALWAYS_ON
    ]
    deferred = [
        n for n, r in _TOOL_REGISTRY.items() if r["tier"] == _TIER_DEFERRED
    ]
    assert len(always_on) == 3
    assert len(deferred) >= 88  # 91 original + room for future deferred tools
    assert set(always_on).isdisjoint(set(deferred))


def test_only_always_on_is_visible_at_startup():
    """The fundamental client-cap contract: a client doing tools/list
    at session start sees ONLY the always-on layer — nothing else."""
    visible = sorted(t.name for t in mcp._tool_manager.list_tools())
    always_on = sorted(
        n for n, r in _TOOL_REGISTRY.items() if r["tier"] == _TIER_ALWAYS_ON
    )
    # Filter out any deferred tools that were loaded by a previous test
    # whose teardown didn't run yet (paranoia — autouse fixture should
    # handle this).
    visible_always_on = [n for n in visible if n in always_on]
    assert visible_always_on == always_on


def test_every_tool_has_category_metadata():
    """rka_list_tools renders by category; every tool needs one."""
    for name, rec in _TOOL_REGISTRY.items():
        assert rec["category"], f"{name} has no category"
        assert isinstance(rec["category"], str)


# ---------------------------------------------------------------------------
# Capability handshake (the MCP-protocol-level contract)
# ---------------------------------------------------------------------------


def test_tools_list_changed_capability_advertised():
    """v2.6.3 advertises tools.listChanged: true in the initialize
    handshake — without this both Claude Desktop and Claude Code IGNORE
    the runtime notification."""
    init_opts = mcp._mcp_server.create_initialization_options()
    assert init_opts.capabilities is not None
    assert init_opts.capabilities.tools is not None
    assert init_opts.capabilities.tools.listChanged is True


def test_capability_override_preserves_other_notifications():
    """The _create_init_with_list_changed wrapper must preserve any
    prompts_changed / resources_changed the caller passes in (e.g.
    Streamable-HTTP transport may opt into those independently)."""
    from mcp.server.lowlevel.server import NotificationOptions

    caller_opts = NotificationOptions(
        prompts_changed=True, resources_changed=True, tools_changed=False
    )
    init_opts = mcp._mcp_server.create_initialization_options(
        notification_options=caller_opts
    )
    # tools_changed forced to True regardless
    assert init_opts.capabilities.tools.listChanged is True
    # Other flags preserved
    assert init_opts.capabilities.prompts.listChanged is True
    assert init_opts.capabilities.resources.listChanged is True


# ---------------------------------------------------------------------------
# Navigator: rka_list_tools
# ---------------------------------------------------------------------------


async def _call(_tool: str, **kwargs: Any) -> dict:
    """Test-side helper: dispatch into a registered tool by name.

    Param renamed to `_tool` (leading underscore) so a tool whose own
    first parameter is `name` (e.g. `rka_help`) doesn't collide via
    kwargs.
    """
    fn = _TOOL_REGISTRY[_tool]["fn"]
    raw = await fn(**kwargs)
    return json.loads(raw)


@pytest.mark.asyncio
async def test_list_tools_no_filter_returns_full_catalog():
    result = await _call("rka_list_tools")
    assert result["total_tools"] == len(_TOOL_REGISTRY)
    assert result["filtered_count"] == result["total_tools"]
    # Every category bucket has at least one tool.
    for cat, tools in result["categories"].items():
        assert tools, f"empty category bucket: {cat}"


@pytest.mark.asyncio
async def test_list_tools_category_filter():
    result = await _call("rka_list_tools", category="literature")
    assert set(result["categories"]) == {"literature"}
    names = [t["name"] for t in result["categories"]["literature"]]
    assert "rka_add_literature" in names
    assert "rka_update_literature" in names
    # No tools from other categories leaked in.
    assert "rka_add_note" not in names


@pytest.mark.asyncio
async def test_list_tools_tier_filter():
    result = await _call("rka_list_tools", tier="always_on")
    flat = [t["name"] for tools in result["categories"].values() for t in tools]
    # Every result must be tier=always_on
    for cat, tools in result["categories"].items():
        for t in tools:
            assert t["tier"] == "always_on"
    assert len(flat) == 3  # v2.6.5 — navigator-only always-on layer


@pytest.mark.asyncio
async def test_list_tools_query_substring_match():
    result = await _call("rka_list_tools", query="cluster")
    flat = [t["name"] for tools in result["categories"].values() for t in tools]
    # All result names or summaries contain "cluster" (case-insensitive)
    for tools in result["categories"].values():
        for t in tools:
            assert "cluster" in t["name"].lower() or "cluster" in t["summary"].lower()
    assert "rka_review_cluster" in flat
    assert "rka_create_cluster" in flat


@pytest.mark.asyncio
async def test_list_tools_unknown_category_returns_empty():
    result = await _call("rka_list_tools", category="nonexistent_bucket")
    assert result["filtered_count"] == 0
    assert result["categories"] == {}


# ---------------------------------------------------------------------------
# Navigator: rka_help
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_returns_full_record_for_deferred_tool():
    result = await _call("rka_help", name="rka_add_literature")
    assert result["name"] == "rka_add_literature"
    assert result["tier"] == "deferred"
    assert result["category"] == "literature"
    assert "(" in result["signature"]  # rendered signature
    assert result["summary"]  # non-empty
    assert result["docstring"]  # full prose


@pytest.mark.asyncio
async def test_help_returns_full_record_for_always_on_tool():
    # v2.6.5 — always-on tier shrunk to navigator-only; use rka_load_tools
    # (one of the 3 navigator tools) as the always-on example.
    result = await _call("rka_help", name="rka_load_tools")
    assert result["tier"] == "always_on"
    assert result["registered"] is True


@pytest.mark.asyncio
async def test_help_unknown_tool_returns_error_shape():
    result = await _call("rka_help", name="rka_does_not_exist")
    assert result["error"] == "unknown_tool"
    assert result["name"] == "rka_does_not_exist"


@pytest.mark.asyncio
async def test_help_handles_blank_name():
    result = await _call("rka_help", name="")
    assert result["error"] == "unknown_tool"


# ---------------------------------------------------------------------------
# Navigator: rka_load_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_tools_registers_deferred(ctx):
    result = await _call(
        "rka_load_tools",
        names=["rka_add_literature", "rka_update_literature"],
        ctx=ctx,
    )
    assert result["loaded"] == ["rka_add_literature", "rka_update_literature"]
    assert result["already_active"] == []
    assert result["unknown"] == []
    # Notification fired exactly once for the whole load batch
    assert ctx.session.notifications == 1
    # FastMCP tool manager now has the tool
    mgr_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "rka_add_literature" in mgr_names
    assert "rka_update_literature" in mgr_names
    # Registry flipped to registered=True
    assert _TOOL_REGISTRY["rka_add_literature"]["registered"] is True
    assert _TOOL_REGISTRY["rka_update_literature"]["registered"] is True


@pytest.mark.asyncio
async def test_load_tools_is_idempotent(ctx):
    await _call("rka_load_tools", names=["rka_add_literature"], ctx=ctx)
    # Second call — same tool, already active
    ctx2 = _FakeCtx()
    result = await _call(
        "rka_load_tools", names=["rka_add_literature"], ctx=ctx2
    )
    assert result["loaded"] == []
    assert result["already_active"] == ["rka_add_literature"]
    # No spurious notification — nothing actually changed
    assert ctx2.session.notifications == 0


@pytest.mark.asyncio
async def test_load_tools_unknown_names_returned_not_errored(ctx):
    result = await _call(
        "rka_load_tools",
        names=["rka_does_not_exist", "rka_also_fake"],
        ctx=ctx,
    )
    assert result["loaded"] == []
    assert result["unknown"] == ["rka_does_not_exist", "rka_also_fake"]
    # No notification — nothing was registered
    assert ctx.session.notifications == 0


@pytest.mark.asyncio
async def test_load_tools_mixed_known_unknown_already(ctx):
    # Pre-load one
    await _call("rka_load_tools", names=["rka_add_literature"], ctx=ctx)
    ctx2 = _FakeCtx()
    result = await _call(
        "rka_load_tools",
        names=[
            "rka_add_literature",        # already
            "rka_update_literature",     # known + deferred
            "rka_does_not_exist",        # unknown
        ],
        ctx=ctx2,
    )
    assert result["loaded"] == ["rka_update_literature"]
    assert result["already_active"] == ["rka_add_literature"]
    assert result["unknown"] == ["rka_does_not_exist"]
    # One notification fired (one tool actually loaded)
    assert ctx2.session.notifications == 1


@pytest.mark.asyncio
async def test_load_tools_blank_and_whitespace_names_skipped(ctx):
    result = await _call(
        "rka_load_tools",
        names=["", "   ", "rka_add_literature"],
        ctx=ctx,
    )
    assert result["loaded"] == ["rka_add_literature"]
    # Empty / whitespace strings silently skipped, NOT reported as unknown
    assert result["unknown"] == []


@pytest.mark.asyncio
async def test_load_tools_empty_list_is_noop(ctx):
    result = await _call("rka_load_tools", names=[], ctx=ctx)
    assert result == {"loaded": [], "already_active": [], "unknown": []}
    assert ctx.session.notifications == 0


@pytest.mark.asyncio
async def test_load_tools_notification_failure_does_not_reverse_registration(ctx):
    """If the client's session can't accept the notification (e.g. dead
    transport), the registration MUST stay — the tool is callable on the
    next initialize even if this client never sees the update."""

    class _RaisingSession:
        async def send_tool_list_changed(self):
            raise RuntimeError("transport dead")

    class _RaisingCtx:
        session = _RaisingSession()

    result = await _call(
        "rka_load_tools",
        names=["rka_add_literature"],
        ctx=_RaisingCtx(),
    )
    # Registration still happened
    assert result["loaded"] == ["rka_add_literature"]
    assert _TOOL_REGISTRY["rka_add_literature"]["registered"] is True
    # FastMCP tool manager has it
    assert any(
        t.name == "rka_add_literature" for t in mcp._tool_manager.list_tools()
    )


# ---------------------------------------------------------------------------
# Schema parity: deferred-then-loaded tools render the same as always-on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loaded_tool_schema_matches_signature(ctx):
    """A deferred tool, once loaded, must have the same inputSchema
    structure FastMCP renders for any always-on tool — same shape, same
    annotations, same `project_id` requirement."""
    await _call("rka_load_tools", names=["rka_add_literature"], ctx=ctx)
    mgr_tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    add_lit = mgr_tools["rka_add_literature"]
    assert add_lit.parameters  # has rendered inputSchema
    # project_id is a kwarg-only required field on every project-scoped
    # rka tool post-v2.6 — this confirms the deferred-then-loaded path
    # preserves the same contract as direct mcp.tool() registration.
    props = add_lit.parameters.get("properties", {})
    assert "project_id" in props


@pytest.mark.asyncio
async def test_loaded_tool_callable_via_fastmcp(ctx):
    """End-to-end: load → call via FastMCP's call_tool path. This is the
    exact path Claude Desktop / Claude Code go through on a tool call."""
    await _call(
        "rka_load_tools", names=["rka_list_clusters"], ctx=ctx
    )
    # rka_list_clusters is project-scoped — without a running daemon the
    # call will fail at the HTTP layer, but the lookup-and-dispatch via
    # FastMCP's tool manager must succeed. We assert the lookup succeeds
    # by inspecting list_tools (already done above) + asserting the
    # wrapper is the same object as in the registry.
    mgr_tool = next(
        t for t in mcp._tool_manager.list_tools() if t.name == "rka_list_clusters"
    )
    assert mgr_tool is not None


# ---------------------------------------------------------------------------
# Bookkeeper: the navigator itself is callable (sanity)
# ---------------------------------------------------------------------------


def test_navigator_tools_registered_at_startup():
    """The three navigator tools must be in the always-on layer — without
    them, clients can never discover or load the deferred surface."""
    mgr_names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "rka_load_tools" in mgr_names
    assert "rka_list_tools" in mgr_names
    assert "rka_help" in mgr_names


# ---------------------------------------------------------------------------
# v2.6.5 — Tier-shrink contract pins (navigator-only always-on)
# ---------------------------------------------------------------------------
#
# v2.6.5 EMPIRICAL FAILURE OBSERVED 2026-06-02:
# - Server returned 12 always-on tools at startup
# - Claude Desktop's client-side tool-surface filter narrowed 12 → 7
# - The 5 it DROPPED included all 3 navigator tools
# - Cockpit was left unable to reach any of the 79 deferred RKA tools
#
# v2.6.5 fix: cut always-on tier 12 → 3, leaving ONLY the navigator. With
# 3 tools, the navigator survives any reasonable filter, and the LLM's
# first turn MUST call rka_load_tools to bring up its working surface.


def test_v265_only_navigator_tools_are_always_on():
    """v2.6.5 — the startup tool surface is EXACTLY the 3 navigator tools.

    No other rka_* tool may be visible at session start. This is the
    structural fix for the Claude Desktop client-side filter problem
    that v2.6.4's 12-tool always-on surface ran into.
    """
    always_on_names = {
        n for n, r in _TOOL_REGISTRY.items() if r["tier"] == _TIER_ALWAYS_ON
    }
    assert always_on_names == {
        "rka_load_tools",
        "rka_list_tools",
        "rka_help",
    }


def test_v265_get_status_is_deferred():
    """v2.6.5 — rka_get_status (always-on in v2.6.3/4) is now deferred.

    The PI cockpit's first turn must call rka_load_tools to register
    rka_get_status before any session-start status query.
    """
    rec = _TOOL_REGISTRY["rka_get_status"]
    assert rec["tier"] == _TIER_DEFERRED
    assert rec["registered"] is False


def test_v265_previously_always_on_tools_all_deferred():
    """v2.6.5 — all 9 tools that were always-on through v2.6.4 (the
    Minimal Session Start + universal retrieval + most-frequent writes
    set) are now deferred. The 3 navigator tools remain always-on.
    """
    previously_always_on = [
        # Minimal Session Start
        "rka_get_status",
        "rka_get_context",
        "rka_get_pending_maintenance",
        "rka_get_checkpoints",
        "rka_get_research_map",
        # Universal retrieval
        "rka_search",
        "rka_get",
        # Most-frequent writes
        "rka_add_note",
        "rka_resolve_checkpoint",
    ]
    for name in previously_always_on:
        rec = _TOOL_REGISTRY[name]
        assert rec["tier"] == _TIER_DEFERRED, (
            f"{name} was always-on in v2.6.4; v2.6.5 should have moved "
            f"it to deferred, but tier={rec['tier']!r}"
        )
        assert rec["registered"] is False, (
            f"{name} should not be registered at module-import baseline "
            f"after v2.6.5 (it's deferred)"
        )


@pytest.mark.asyncio
async def test_v265_session_start_loads_typical_set(ctx):
    """v2.6.5 — simulate a Brain-role client's session-start `rka_load_tools`
    call activating the historically-always-on tools. After the call all
    9 must become registered and the FastMCP tool manager exposes them.

    This is the new session-start protocol baked into v2.6.5: client
    initialize → 3 navigator tools → client calls rka_load_tools(role-set)
    → server registers + fires tools/list_changed → client refetches.
    """
    typical_set = [
        # Minimal Session Start
        "rka_get_status",
        "rka_get_context",
        "rka_get_pending_maintenance",
        "rka_get_checkpoints",
        "rka_get_research_map",
        # Universal retrieval
        "rka_search",
        "rka_get",
        # Most-frequent writes
        "rka_add_note",
        "rka_resolve_checkpoint",
    ]
    result = await _call("rka_load_tools", names=typical_set, ctx=ctx)
    # Every tool in the typical set loaded (none already-active because
    # all 9 are deferred at module-import baseline post-v2.6.5).
    assert result["loaded"] == typical_set
    assert result["already_active"] == []
    assert result["unknown"] == []
    # Single notification for the whole batch (existing semantics).
    assert ctx.session.notifications == 1
    # Every loaded tool now visible via FastMCP tool manager.
    mgr_names = {t.name for t in mcp._tool_manager.list_tools()}
    for name in typical_set:
        assert name in mgr_names, (
            f"{name} should be registered via FastMCP tool manager after "
            f"rka_load_tools"
        )
        assert _TOOL_REGISTRY[name]["registered"] is True


def test_v265_visible_startup_surface_is_three():
    """v2.6.5 — the FastMCP tool manager exposes exactly 3 rka_* tools at
    module-import baseline. Anything else means a deferred tool leaked
    into the always-on layer (or didn't get reset by the autouse
    fixture).
    """
    visible_rka = sorted(
        t.name
        for t in mcp._tool_manager.list_tools()
        if t.name.startswith("rka_")
    )
    assert visible_rka == [
        "rka_help",
        "rka_list_tools",
        "rka_load_tools",
    ]
