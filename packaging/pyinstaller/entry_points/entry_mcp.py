"""PyInstaller entry point for the bundled `rka mcp` stdio proxy.

This binary is what each MCP client (Claude Desktop, Claude Code, Cursor,
VSCode-Copilot, Codex, Antigravity) invokes through the stable launcher
script. It proxies tool calls to the local REST API the Tauri shell
manages.
"""
from __future__ import annotations

import sys

from rka.cli import main


def run() -> None:
    sys.argv = [sys.argv[0], "mcp", *sys.argv[1:]]
    main()


if __name__ == "__main__":
    run()
