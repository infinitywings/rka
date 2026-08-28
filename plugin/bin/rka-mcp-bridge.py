#!/usr/bin/env python3
"""rka-mcp-bridge.py — cross-platform wrapper invoked by Claude's plugin loader.

Reads integration.json (location is OS-specific), version-checks the recorded
RKA version against the plugin's compatibility range, and runs the local rka
stdio binary with the `mcp` subcommand. Project scope is never injected through
the environment; every project-scoped operation carries an explicit id.

Exec strategy:
- POSIX (macOS/Linux): os.execvpe — replaces this Python process with the
  rka binary so stdio passes through cleanly to Claude with no intermediate.
- Windows: subprocess.run with inherited stdio — os.exec* on Windows spawns
  a child and exits the original, which breaks stdio piping with Claude.
  subprocess.run waits for the child and exits with its return code.

If integration.json is missing, falls back to invoking `rka` from PATH
(uv-tool installs land at ~/.local/bin/rka on macOS/Linux or
%USERPROFILE%\\.local\\bin\\rka.exe on Windows).

If `binary_path` points at a Python script (`.py` / `.pyw`), the wrapper
re-execs it under the current Python interpreter — handles a possible
RKA.app config that uses a Python script rather than a frozen executable.

Errors emit to stderr; non-zero exit on failure so Claude Code's MCP layer
surfaces "tool unavailable" with the wrapper's stderr captured to logs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Oldest RKA Core backend this plugin can drive. Plugin 2.x intentionally
# requires the post-split Core 3.x surface so an older backend cannot
# reactivate the bundled Writer surface removed by this release. The check is
# still a *minimum*, not an
# allowlist of releases: a backend newer than the plugin is the normal state of
# affairs (the backend ships far more often than the plugin), and rejecting it
# strands a working install.
#
# An allowlist of accepted prefixes used to live here. It had to be widened by
# hand on every minor release, which is exactly the kind of edit that gets
# forgotten — and was: the tuple still read ("2.7", "2.8") after the backend
# reached 2.9.0, so a correctly-reported 2.9.0 was refused by its own plugin.
MINIMUM_BACKEND_VERSION = (3, 0)


def parse_version(version: str) -> tuple[int, ...] | None:
    """Parse a leading numeric version into a comparable tuple.

    Trailing prerelease markers are ignored: ``2.9.0-rc1`` compares as
    ``(2, 9, 0)``. Returns None when nothing numeric can be read, which the
    caller treats as "cannot verify" rather than "incompatible" — refusing to
    start over an unparseable string would be a worse failure than running.
    """
    parts: list[int] = []
    for chunk in version.strip().split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or None


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
    if home_local.is_file():
        return str(home_local)
    return None


def is_executable(path: str) -> bool:
    """Check executability cross-platform.

    os.access(X_OK) is unreliable on Windows (returns True for any readable
    file). On Windows, treat any existing file as a candidate; the actual
    runnability check happens at exec/spawn time.
    """
    p = Path(path)
    if not p.is_file():
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def is_python_script(path: str) -> bool:
    """True if the binary is a Python source file we should re-exec via interpreter."""
    return path.lower().endswith((".py", ".pyw"))


def run_binary(binary_path: str, env: dict[str, str]) -> None:
    """Replace this process with the rka binary (POSIX) or run-and-wait (Windows).

    Both paths inherit stdin/stdout/stderr from this wrapper, which inherited
    them from Claude — so MCP stdio passes through cleanly.
    """
    # If binary_path is actually a Python script, re-exec via current
    # interpreter so we don't depend on shebang handling on Windows.
    if is_python_script(binary_path):
        argv = [sys.executable, binary_path, "mcp"]
        prog = sys.executable
    else:
        argv = [binary_path, "mcp"]
        prog = binary_path

    if sys.platform == "win32":
        # subprocess.run with default stdin/stdout/stderr=None inherits from
        # this wrapper (which inherited from Claude). Wait for the child to
        # exit, propagate its return code.
        try:
            result = subprocess.run(argv, env=env)
            sys.exit(result.returncode)
        except OSError as exc:
            err(f"ERROR: failed to run {prog}: {exc}")
            sys.exit(1)
    else:
        # POSIX: replace this process with the rka binary. No intermediate.
        try:
            os.execvpe(prog, argv, env)
        except OSError as exc:
            err(f"ERROR: failed to exec {prog}: {exc}")
            sys.exit(1)


def main() -> None:
    int_path = integration_path()

    binary_path: str | None = None
    version: str | None = None

    if int_path.is_file():
        try:
            data = json.loads(int_path.read_text())
        except json.JSONDecodeError as exc:
            err(f"ERROR: integration.json is malformed JSON at {int_path}: {exc}")
            sys.exit(1)

        # Defensive str() cast in case RKA.app ever writes non-string values.
        version = str(data.get("version") or "").strip() or None
        binary_path = str(data.get("binary_path") or "").strip() or None
        if data.get("default_project_id"):
            err(
                "NOTICE: integration.json default_project_id is ignored; "
                "RKA requires project_id on every scoped operation."
            )

        # Resolve relative binary_path against integration.json's directory.
        # Absolute paths pass through unchanged.
        if binary_path and not Path(binary_path).is_absolute():
            binary_path = str((int_path.parent / binary_path).resolve())
    else:
        err(f"NOTICE: integration.json not found at {int_path} — falling back to PATH lookup for `rka`.")
        err("If RKA.app is supposed to be running, this means it isn't (or hasn't written its config yet).")

    # Resolve binary path: integration.json wins, else PATH lookup.
    if not binary_path:
        binary_path = find_rka_on_path()
        if not binary_path:
            err("ERROR: rka binary not found. Either:")
            err("  1. Install via `uv tool install --force --reinstall .` from the rka repo (lands at ~/.local/bin/rka).")
            err("  2. Start RKA.app so it writes integration.json with binary_path.")
            err("  3. Set RKA_INTEGRATION_FILE env var to the integration.json location.")
            sys.exit(1)

    if not is_executable(binary_path) and not is_python_script(binary_path):
        err(f"ERROR: RKA binary not executable at: {binary_path}")
        err("Check integration.json's binary_path field, or rerun `uv tool install --force --reinstall .` from the rka repo.")
        sys.exit(1)

    # Version check (only if integration.json supplied a version; PATH-fallback
    # mode skips the check since we have no version metadata to verify against).
    if version is not None:
        parsed = parse_version(version)
        minimum = ".".join(str(n) for n in MINIMUM_BACKEND_VERSION)
        if parsed is None:
            # Unreadable version string: warn, but do not block. The binary
            # itself will fail loudly if it really is incompatible.
            err(f"NOTICE: could not parse RKA version '{version}'; skipping the compatibility check.")
        elif parsed < MINIMUM_BACKEND_VERSION:
            err(f"ERROR: RKA version '{version}' is older than this plugin supports (requires {minimum} or newer).")
            err("Upgrade RKA, or install a plugin version matching your backend.")
            err(
                "If RKA is in fact newer than this and you are seeing a stale number, "
                f"integration.json is reporting it: {integration_path()}"
            )
            sys.exit(1)

    env = os.environ.copy()
    # Defensive cleanup for legacy launch configurations. v2.6+ ignores this
    # variable, but removing it makes the explicit-only contract unambiguous to
    # child processes and diagnostics.
    env.pop("RKA_PROJECT", None)

    run_binary(binary_path, env)


if __name__ == "__main__":
    main()
