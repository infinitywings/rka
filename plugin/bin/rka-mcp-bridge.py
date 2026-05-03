#!/usr/bin/env python3
"""rka-mcp-bridge.py — cross-platform wrapper invoked by Claude's plugin loader.

Reads integration.json (location is OS-specific), version-checks the recorded
RKA version against the plugin's compatibility range, propagates
default_project_id as RKA_PROJECT env var (caller-set RKA_PROJECT wins), and
execs the local rka stdio binary with the `mcp` subcommand.

If integration.json is missing, falls back to invoking `rka mcp` from PATH
(uv-tool installs land at ~/.local/bin/rka on macOS/Linux or
%USERPROFILE%\\.local\\bin\\rka.exe on Windows).

Errors emit to stderr; non-zero exit on failure so Claude Code's MCP layer
surfaces "tool unavailable" with the wrapper's stderr captured to logs.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
from pathlib import Path

# Plugin compatibility range. Bump the glob when shipping a plugin version
# that requires a newer RKA backend.
COMPATIBLE_GLOB = "2.3.*"


def integration_path() -> Path:
    """OS-specific default location for integration.json."""
    override = os.environ.get("RKA_INTEGRATION_FILE")
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "RKA" / "integration.json"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            # Fallback if APPDATA somehow unset — rare but possible.
            return Path.home() / "AppData" / "Roaming" / "RKA" / "integration.json"
        return Path(appdata) / "RKA" / "integration.json"
    # Linux + other Unix: XDG_DATA_HOME or ~/.local/share
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "RKA" / "integration.json"


def err(msg: str) -> None:
    print(f"[rka-mcp-bridge] {msg}", file=sys.stderr)


def find_rka_on_path() -> str | None:
    """Resolve the rka binary via PATH lookup (fallback when integration.json absent)."""
    candidate = shutil.which("rka")
    if candidate:
        return candidate
    # Common uv-tool install location not always on PATH.
    home_local = Path.home() / ".local" / "bin" / ("rka.exe" if sys.platform == "win32" else "rka")
    if home_local.is_file() and os.access(home_local, os.X_OK):
        return str(home_local)
    return None


def main() -> None:
    int_path = integration_path()

    binary_path: str | None = None
    version: str | None = None
    default_project: str | None = None

    if int_path.is_file():
        try:
            data = json.loads(int_path.read_text())
        except json.JSONDecodeError as exc:
            err(f"ERROR: integration.json is malformed JSON at {int_path}: {exc}")
            sys.exit(1)

        version = (data.get("version") or "").strip() or None
        binary_path = (data.get("binary_path") or "").strip() or None
        default_project = (data.get("default_project_id") or "").strip() or None
    else:
        err(f"NOTICE: integration.json not found at {int_path} — falling back to PATH lookup for `rka`.")
        err("If RKA.app is supposed to be running, this means it isn't (or hasn't written its config yet).")

    # Resolve binary path: integration.json wins, else PATH lookup.
    if not binary_path:
        binary_path = find_rka_on_path()
        if not binary_path:
            err("ERROR: rka binary not found. Either:")
            err("  1. Install via `uv tool install --force .` from the rka repo (lands at ~/.local/bin/rka).")
            err("  2. Start RKA.app so it writes integration.json with binary_path.")
            err("  3. Set RKA_INTEGRATION_FILE env var to the integration.json location.")
            sys.exit(1)

    if not Path(binary_path).is_file() or not os.access(binary_path, os.X_OK):
        err(f"ERROR: RKA binary not executable at: {binary_path}")
        err("Check integration.json's binary_path field, or rerun `uv tool install --force .` from the rka repo.")
        sys.exit(1)

    # Version check (only if integration.json supplied a version; PATH-fallback
    # mode skips the check since we have no version metadata to verify against).
    if version is not None:
        if not fnmatch.fnmatch(version, COMPATIBLE_GLOB):
            err(f"ERROR: RKA version '{version}' is incompatible with this plugin (requires {COMPATIBLE_GLOB}).")
            err(f"Either upgrade RKA to a {COMPATIBLE_GLOB} release, or install a matching plugin version.")
            sys.exit(1)

    # Propagate default_project_id as RKA_PROJECT (caller-set wins).
    env = os.environ.copy()
    if not env.get("RKA_PROJECT") and default_project:
        env["RKA_PROJECT"] = default_project

    # Exec — replaces this Python process with the rka binary so stdio passes
    # through cleanly to Claude.
    try:
        os.execvpe(binary_path, [binary_path, "mcp"], env)
    except OSError as exc:
        err(f"ERROR: failed to exec {binary_path}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
