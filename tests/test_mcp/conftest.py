"""Shared fixtures for MCP-surface tests.

v2.7.0a3 — Test environment defaults to ``RKA_LEGACY_TOOLS=1`` so the
existing v2.6.x / v2.7.0-a1 / v2.7.0-a2 test suites continue exercising
the legacy 91 tools + 8 v2.7.0a2 verbs at tier='always_on' (the
v2.7.0a2 baseline). Tests for the v2.7.0a3 DEFAULT mode (the 3-tool
dispatch surface with legacy hidden) live in
``test_v270a3_dispatch_surface.py`` which explicitly toggles the flag
and reloads the module.

Without this conftest the env-flag would be unset at module import time,
collapsing the always-on surface to 5 tools (3 dispatch + rka_help +
rka_load_tools) and breaking ~150 tests that hard-code the older
20-tool always-on count. Setting the env var here BEFORE rka.mcp.server
is imported preserves backwards-compat for the existing suite.
"""

from __future__ import annotations

import os

# Force the v2.7.0a2-baseline mode for the existing test suite. Must
# run BEFORE any test module imports rka.mcp.server (whose @tool()
# decorators read this env var at module-import time).
os.environ.setdefault("RKA_LEGACY_TOOLS", "1")
