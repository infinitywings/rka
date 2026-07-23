#!/usr/bin/env python3
"""session-start.py — fires once at Claude Code session start.

Reads integration.json (OS-specific location), pings the RKA backend's health
endpoint, prints a one-line status that becomes session context. Always exits
0 — never blocks session start; surfaces unreachability as a stdout warning
the model can act on.

Cross-platform replacement for hooks/session-start.sh.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


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
            return Path.home() / "AppData" / "Roaming" / "RKA" / "integration.json"
        return Path(appdata) / "RKA" / "integration.json"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "RKA" / "integration.json"


def main() -> None:
    int_path = integration_path()

    if not int_path.is_file():
        # Without integration.json we can still try the default API URL.
        api_url = "http://localhost:9712"
        version_str = "unknown"
    else:
        try:
            data = json.loads(int_path.read_text())
        except json.JSONDecodeError as exc:
            print(
                f"⚠️  RKA integration.json is malformed at {int_path}: {exc}. "
                f"Plugin tools will likely fail until this is fixed."
            )
            sys.exit(0)

        api_url = (data.get("api_endpoint_url") or "http://localhost:9712").strip()
        version_str = (data.get("version") or "unknown").strip()

    health_url = api_url.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(health_url, timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:200]
            if resp.status == 200:
                print(
                    f"✅ RKA reachable at {api_url} (version {version_str}; explicit project_id required per operation)."
                )
            else:
                print(
                    f"⚠️  RKA at {api_url} returned HTTP {resp.status}: {body}. "
                    f"Tool calls may fail until the backend is healthy."
                )
    except urllib.error.URLError as exc:
        print(
            f"⚠️  RKA NOT reachable at {api_url} ({exc.reason}). "
            f"Start RKA.app or run `docker compose up -d` from the rka repo. "
            f"RKA tool calls will fail until the backend is running."
        )
    except Exception as exc:
        print(
            f"⚠️  RKA SessionStart probe error at {api_url}: {exc}. "
            f"Tool calls may fail until the backend is healthy."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
