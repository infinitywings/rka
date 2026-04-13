"""MCP server regressions."""

from __future__ import annotations

import asyncio

from rka.mcp.server import API_TIMEOUT, _client


def test_mcp_client_uses_extended_write_timeout():
    client = _client()
    try:
        assert API_TIMEOUT.connect == 30.0
        assert API_TIMEOUT.read == 120.0
        assert API_TIMEOUT.write == 120.0
        assert client.timeout.connect == 30.0
        assert client.timeout.read == 120.0
        assert client.timeout.write == 120.0
    finally:
        asyncio.run(client.aclose())
