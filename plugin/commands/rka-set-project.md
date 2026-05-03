---
description: "Switch the active RKA project for this session. Pass the project id (e.g. prj_01ABC...). Without an argument, lists available projects so the user can pick."
argument-hint: "<project_id>"
---

Two cases:

**Case A — user provided a project id as the argument** (e.g. `/rka-set-project prj_01ABC...`):
Call `rka_set_project(project_id="<the id>")`. Then call `rka_get_status()` to confirm the switch landed and show the new active project's phase + summary. If `rka_set_project` returned an error (project not found, invalid id), surface the error and call `rka_list_projects()` to show valid options.

**Case B — user provided no argument** (`/rka-set-project` alone):
Call `rka_list_projects()` to enumerate available projects. Present them as a numbered list with id + name + active marker. Tell the user to re-invoke the command with one of the listed project ids.

Do not switch to a project the user did not explicitly name. Keep the response under 15 lines.

Note: RKA's MCP `_session.project_id` is per-process and ephemeral. To make a project default automatically across all future sessions, set `RKA_PROJECT=<project_id>` in `claude_desktop_config.json` → `mcpServers.rka.env`, or in your shell environment (the integration.json `default_project_id` field, propagated by the rka-test plugin's wrapper, also serves this).
