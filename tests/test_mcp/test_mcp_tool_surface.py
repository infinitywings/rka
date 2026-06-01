"""v2.6.1 — MCP tool-surface schema-divergence regression tests.

Pins the "PRIMARY FIELD: <name>" docstring convention added in
v2.6.1 (Phase-X²' polish on main, see roadmap at
orchestrator/docs/v2.6.x-roadmap.md §6) and cross-checks the MCP
signatures against the underlying Pydantic CreateModels.

The hyperscaler-auditing PA-2 dispatch failure (2026-06-01) surfaced
the root cause: the Brain LLM hallucinated `content=` on
rka_submit_checkpoint instead of the canonical `description=`. The
audit (workflow `wjyk2x82n`) identified that rka_submit_report had
an even worse failure mode — its MCP signature exposed `summary: str`
as the primary body field, but `MissionReportCreate` had NO `summary`
field; the wrapper synthesised it as `tasks_completed=[summary]`.
Brain reading the canonical OpenAPI schema was misled.

These tests prevent future drift:

1. Every WRITE_TOOL docstring opens with `PRIMARY FIELD: <name>`
   so the convention is uniform.
2. For tools whose primary body field maps to a Pydantic
   CreateModel field, the field name MUST exist on the model.
   Catches the rka_submit_report schema-lie at CI time.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from rka.mcp import server as mcp_server


# WRITE_TOOLS that this contract test covers. Mirrors the orchestrator's
# WRITE_TOOLS list (orchestrator/orchestrator/llm_client.py) so adding a
# write tool there without updating here is caught at next test run.
WRITE_TOOLS = (
    "rka_add_note",
    "rka_add_decision",
    "rka_update_note",
    "rka_bulk_update",
    "rka_create_mission",
    "rka_update_mission_status",
    "rka_submit_checkpoint",
    "rka_submit_report",
    "rka_ingest_document",
)

# Per-tool expected PRIMARY FIELD name (declared in the docstring).
PRIMARY_FIELDS: dict[str, str] = {
    "rka_add_note": "content",
    "rka_add_decision": "question",
    "rka_update_note": "id",
    "rka_bulk_update": "updates",
    "rka_create_mission": "objective",
    "rka_update_mission_status": "id",
    "rka_submit_checkpoint": "description",
    "rka_submit_report": "summary",
    "rka_ingest_document": "content",
}


def _get_underlying_func(name: str) -> Any:
    """Return the @tool()-decorated coroutine function for `name`.

    FastMCP wraps the function in a Tool object; we walk through the
    wrapping layers to retrieve the bare async fn so inspect.signature
    sees the real parameters and docstring.
    """
    obj = getattr(mcp_server, name, None)
    if obj is None:
        return None
    # FastMCP tool wraps as a structure with attributes; walk to find
    # the original `fn`. The exact attribute depends on the decorator
    # version — try common shapes.
    for attr in ("fn", "func", "__wrapped__"):
        fn = getattr(obj, attr, None)
        if fn is not None and inspect.iscoroutinefunction(fn):
            return fn
    if inspect.iscoroutinefunction(obj):
        return obj
    return None


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tool_exists(tool: str) -> None:
    """Each WRITE_TOOL must be importable from rka.mcp.server."""
    obj = getattr(mcp_server, tool, None)
    assert obj is not None, (
        f"WRITE_TOOL {tool!r} not exported by rka.mcp.server — "
        f"was it removed or renamed?"
    )


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tool_docstring_opens_with_primary_field(tool: str) -> None:
    """v2.6.1 docstring convention — every WRITE_TOOL must declare its
    PRIMARY FIELD in the docstring summary so LLMs reading the rendered
    schema see the canonical body field. Catches drift if a future
    refactor strips the convention from any tool.
    """
    fn = _get_underlying_func(tool)
    if fn is None:
        pytest.skip(f"could not unwrap @tool() for {tool}; FastMCP shape changed")
    docstring = (fn.__doc__ or "").strip()
    assert docstring.startswith("PRIMARY FIELD:"), (
        f"{tool!r} docstring must open with 'PRIMARY FIELD: <name>' — "
        f"got: {docstring[:80]!r}"
    )


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tool_docstring_mentions_expected_primary_field(tool: str) -> None:
    """The docstring's opening PRIMARY FIELD declaration must name the
    expected field per PRIMARY_FIELDS — catches typos or stale
    docstrings if the canonical field is renamed."""
    expected = PRIMARY_FIELDS.get(tool)
    if expected is None:
        pytest.skip(f"no PRIMARY_FIELD registered for {tool}")
    fn = _get_underlying_func(tool)
    if fn is None:
        pytest.skip(f"could not unwrap @tool() for {tool}")
    opener = (fn.__doc__ or "").strip().splitlines()[0]
    assert expected in opener, (
        f"{tool!r} docstring opener must mention canonical field "
        f"{expected!r}; got: {opener!r}"
    )


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tool_primary_field_is_in_signature(tool: str) -> None:
    """The declared PRIMARY FIELD must appear as a parameter on the
    tool function — otherwise the docstring is lying. (Different from
    the Pydantic-model cross-check below: this verifies the MCP
    signature itself carries the field LLMs would emit.)
    """
    expected = PRIMARY_FIELDS.get(tool)
    if expected is None:
        pytest.skip(f"no PRIMARY_FIELD registered for {tool}")
    fn = _get_underlying_func(tool)
    if fn is None:
        pytest.skip(f"could not unwrap @tool() for {tool}")
    sig = inspect.signature(fn)
    assert expected in sig.parameters, (
        f"{tool!r} declares PRIMARY FIELD {expected!r} in its docstring "
        f"but {expected!r} is not in the signature parameters: "
        f"{sorted(sig.parameters)}"
    )


def test_submit_checkpoint_accepts_content_alias() -> None:
    """v2.6.1 additive alias regression — `content` is a kwarg-only
    alias for `description`. The MCP signature must expose it so the
    OpenAPI schema reflects the contract."""
    fn = _get_underlying_func("rka_submit_checkpoint")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_submit_checkpoint")
    sig = inspect.signature(fn)
    assert "content" in sig.parameters, (
        "rka_submit_checkpoint must accept `content` as v2.6.1 alias "
        "for `description`"
    )
    param = sig.parameters["content"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "rka_submit_checkpoint `content` must be kwarg-only so "
        "positional callers continue to work via `description`"
    )


def test_submit_report_accepts_content_alias() -> None:
    """v2.6.1 additive alias regression — `content` is a kwarg-only
    alias for `summary`."""
    fn = _get_underlying_func("rka_submit_report")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_submit_report")
    sig = inspect.signature(fn)
    assert "content" in sig.parameters, (
        "rka_submit_report must accept `content` as v2.6.1 alias "
        "for `summary`"
    )


def test_update_status_accepts_content_alias() -> None:
    """v2.6.1 additive alias regression — `content` is a kwarg-only
    alias for `summary` on rka_update_status."""
    fn = _get_underlying_func("rka_update_status")
    if fn is None:
        pytest.skip("could not unwrap @tool() for rka_update_status")
    sig = inspect.signature(fn)
    assert "content" in sig.parameters, (
        "rka_update_status must accept `content` as v2.6.1 alias "
        "for `summary`"
    )


def test_mission_report_create_has_summary_field() -> None:
    """v2.6.1 schema-lie fix — MissionReportCreate must have a real
    `summary` field. Pre-v2.6.1 the MCP signature exposed `summary`
    but the Pydantic body had no such field; the wrapper synthesised
    it as `tasks_completed=[summary]`. Brain LLMs reading the canonical
    OpenAPI schema were misled.
    """
    from rka.models.mission import MissionReportCreate

    fields = MissionReportCreate.model_fields
    assert "summary" in fields, (
        "MissionReportCreate must have a `summary` field — the v2.6.1 "
        "schema-lie fix added this so Brain reading the canonical "
        "schema sees the actual storage shape"
    )


def test_mission_report_has_summary_field() -> None:
    """The stored MissionReport must also carry `summary` so downstream
    readers can retrieve it post-persist."""
    from rka.models.mission import MissionReport

    fields = MissionReport.model_fields
    assert "summary" in fields, (
        "MissionReport must have a `summary` field"
    )
