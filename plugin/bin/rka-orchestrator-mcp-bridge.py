#!/usr/bin/env python3
"""rka-orchestrator-mcp-bridge.py — cross-platform wrapper invoked by
Claude's plugin loader for the orchestrator MCP stdio surface.

Sibling to `rka-mcp-bridge.py`. The orchestrator MCP server (a thin HTTP
proxy to the FastAPI daemon at port 9713) ships as a separate stdio
binary `rka-orchestrator-mcp`, installed via:

    uv tool install --force ./orchestrator

(from the repo root on the agentic branch).

Resolution strategy:

  1. PATH lookup (`shutil.which("rka-orchestrator-mcp")`). uv-tool
     installs land at ~/.local/bin on macOS/Linux or
     %USERPROFILE%\\.local\\bin on Windows.
  2. Explicit fallback to ~/.local/bin/rka-orchestrator-mcp(.exe).

Exec strategy mirrors `rka-mcp-bridge.py`:

  - POSIX: `os.execvp` — replaces this Python process so stdio passes
    through cleanly with no intermediate process to buffer / corrupt
    the MCP framing.
  - Windows: subprocess.run with inherited stdio.

Errors go to stderr; non-zero exit so Claude Code surfaces "MCP server
unavailable" with the wrapper's stderr captured to logs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def err(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def find_binary_on_path() -> str | None:
    """First check PATH, then fall back to the canonical install location."""
    if hit := shutil.which("rka-orchestrator-mcp"):
        return hit

    home = Path.home()
    if sys.platform == "win32":
        candidate = home / ".local" / "bin" / "rka-orchestrator-mcp.exe"
    else:
        candidate = home / ".local" / "bin" / "rka-orchestrator-mcp"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def run_binary(binary_path: str) -> None:
    """exec the binary, replacing this Python process."""
    env = os.environ.copy()
    # ORCHESTRATOR_API_URL lets the user override the daemon URL via
    # claude_desktop_config.json env section; the binary's default is
    # http://localhost:9713 which is what the Compose overlay exposes.
    if sys.platform == "win32":
        # Windows: subprocess.run + exit code passthrough.
        try:
            result = subprocess.run([binary_path], env=env)
            sys.exit(result.returncode)
        except OSError as exc:
            err(f"ERROR: failed to spawn {binary_path}: {exc}")
            sys.exit(1)
    else:
        try:
            os.execvpe(binary_path, [binary_path], env)
        except OSError as exc:
            err(f"ERROR: failed to exec {binary_path}: {exc}")
            sys.exit(1)


def main() -> None:
    binary_path = find_binary_on_path()
    if not binary_path:
        err(
            "ERROR: rka-orchestrator-mcp binary not found.\n"
            "\n"
            "Install via:\n"
            "  cd <rka-repo>/orchestrator && uv tool install --force .\n"
            "  (or `pip install -e .` if you don't use uv)\n"
            "\n"
            "The binary should land at ~/.local/bin/rka-orchestrator-mcp.\n"
            "\n"
            "The orchestrator MCP is shipped with the agentic-branch\n"
            "distribution of the rka plugin only — installing the plugin\n"
            "from the main branch does NOT include it (intentional, per\n"
            "the agentic-branch model)."
        )
        sys.exit(1)

    run_binary(binary_path)


if __name__ == "__main__":
    main()
