"""Module-import-time constants shared across api/services/mcp.

`DEFAULT_PROJECT_ID` is the project_id used as a fallback when an API
call doesn't pass `X-RKA-Project` header or `project_id` query param.
v2.6+: this is **always** `SENTINEL_PROJECT_ID` (= "proj_default"); the
pre-v2.6 `RKA_PROJECT` env-var override was removed because it
reintroduced the silent-default failure mode that v2.6 explicitly
eliminates at the MCP layer (every MCP tool now requires `project_id`
as a kwarg).

Non-MCP REST callers (web UI, curl, external integrations) that don't
pass project_id will still resolve to `proj_default`. To target a
specific project, set the `X-RKA-Project` header or `?project_id=…`
query param on every request — same explicit-contract principle the
MCP layer enforces.

`SENTINEL_PROJECT_ID` is the immutable always-present project — used by
the delete guard and the legacy-state fallback. Never changes.
"""

from __future__ import annotations

SENTINEL_PROJECT_ID: str = "proj_default"

# Pre-v2.6 read `os.environ.get("RKA_PROJECT")`. Removed in v2.6 — see
# module docstring above for the rationale.
DEFAULT_PROJECT_ID: str = SENTINEL_PROJECT_ID
