---
description: "Show RKA project status: active project, phase, current focus, open checkpoints, and recent maintenance items."
---

Call `rka_get_status()` to fetch the active project's state. Then call `rka_get_checkpoints(status="open")` to list any unresolved blockers.

Present the result as a concise dashboard:
- **Active project** (id + name)
- **Phase** (current research phase)
- **Summary** (first 200 chars)
- **Open checkpoints** (count + one-line previews; or "none" if zero)

If the active project is `proj_default` and no project was explicitly chosen this session, surface a warning: the user likely meant to work in a specific project — suggest `rka_list_projects()` and `rka_set_project(...)` to switch.

Do not call any other tools beyond `rka_get_status()` and `rka_get_checkpoints()` for this command. Keep the response under 15 lines.
