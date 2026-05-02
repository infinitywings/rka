"""Module-import-time constants shared across api/services/mcp.

`DEFAULT_PROJECT_ID` reads `RKA_PROJECT` from the environment once at module
import. Setting `RKA_PROJECT=prj_X` in `claude_desktop_config.json`'s
`mcpServers.rka.env` (or in the shell environment for the API process) makes
both the MCP-side `_session.project_id` and the API-side resolution chain
default to `prj_X` instead of `proj_default`. This prevents the wrong-project
silent-write path on fresh sessions where neither header nor query param
selects a project.

`SENTINEL_PROJECT_ID` is the immutable always-present project — used by the
delete guard and the legacy-state fallback. Never changes based on env.
"""

from __future__ import annotations

import os

SENTINEL_PROJECT_ID: str = "proj_default"

DEFAULT_PROJECT_ID: str = (os.environ.get("RKA_PROJECT") or "").strip() or SENTINEL_PROJECT_ID
