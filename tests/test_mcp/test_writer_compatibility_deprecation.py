"""Runtime compatibility notices for frozen Writer MCP operations."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from rka.mcp.operation_args import (
    CreateManuscriptArgs,
    QueryManuscriptArgs,
    QueryStatusArgs,
)


class WarningContext:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def warning(self, message: str) -> None:
        self.calls.append(message)


@pytest.mark.asyncio
async def test_deprecated_query_warns_without_changing_payload(monkeypatch) -> None:
    import rka.mcp.server as mcp_server

    expected = '[{"id": "man_legacy"}]'
    dispatch = AsyncMock(return_value=expected)
    monkeypatch.setattr(mcp_server, "_dispatch_query_typed", dispatch)
    context = WarningContext()

    result = await mcp_server.rka_query(
        QueryManuscriptArgs(project_id="prj_test", id="man_legacy"),
        ctx=context,
    )

    assert result == expected
    assert len(context.calls) == 1
    metadata = json.loads(context.calls[0])
    assert "deprecated" in metadata["message"]
    assert metadata["operation"] == "manuscript"
    assert metadata["owner"] == "rka-writer"
    assert metadata["removal_version"] == "not_scheduled"


@pytest.mark.asyncio
async def test_deprecated_write_warns_without_changing_payload(monkeypatch) -> None:
    import rka.mcp.server as mcp_server

    expected = '{"id": "man_new", "revision": 1}'
    dispatch = AsyncMock(return_value=expected)
    monkeypatch.setattr(mcp_server, "_dispatch_execute_typed", dispatch)
    context = WarningContext()

    result = await mcp_server.rka_execute(
        CreateManuscriptArgs(project_id="prj_test", title="Legacy manuscript"),
        ctx=context,
    )

    assert result == expected
    assert len(context.calls) == 1
    assert json.loads(context.calls[0])["operation"] == "create_manuscript"


@pytest.mark.asyncio
async def test_core_query_does_not_warn(monkeypatch) -> None:
    import rka.mcp.server as mcp_server

    dispatch = AsyncMock(return_value='{"phase": "execution"}')
    monkeypatch.setattr(mcp_server, "_dispatch_query_typed", dispatch)
    context = WarningContext()

    await mcp_server.rka_query(
        QueryStatusArgs(project_id="prj_test"),
        ctx=context,
    )

    assert context.calls == []


def test_context_injection_does_not_expand_public_tool_schema() -> None:
    import rka.mcp.server as mcp_server

    tools = {tool.name: tool for tool in mcp_server.mcp._tool_manager.list_tools()}

    for name in ("rka_query", "rka_execute"):
        properties = tools[name].parameters["properties"]
        assert set(properties) == {"args"}
        assert "ctx" not in properties
