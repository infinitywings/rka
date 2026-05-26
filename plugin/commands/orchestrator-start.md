---
description: "Start an orchestrator workflow on a given RKA mission. Usage: /orchestrator-start <mission_id> [project_id]"
---

Parse the user's command arguments:
- First argument is the `mission_id` (must start with `mis_`)
- Second argument (optional) is the `project_id` (must start with `prj_`). If omitted, ask the user which project to use via `rka_list_projects()` + `AskUserQuestion`.

Before kicking off:
1. Call `orchestrator_health()` to verify the daemon is reachable. If not, tell the user to bring it up:
   ```
   docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d
   ```
2. Call `rka_get_mission(id=<mission_id>)` to confirm the mission exists and surface its objective to the user so they can sanity-check it's the right one.
3. Confirm with the user via `AskUserQuestion`: "Start orchestrator workflow on this mission? Budget cap: $5 USD." with options Yes / Cancel.
4. On Yes → `orchestrator_run_start(mission_id, project_id, budget_usd=5.0)`.

On return:
- If `parked_interrupt_id` is present → load the `rka-orchestrator-pi` skill (or the rendering rules from it) and render the parked interrupt. Then prompt the PI for response.
- If `terminal_state` is present → tell the PI the workflow completed without needing input (rare); surface `final_report_id`.

Do not call `orchestrator_accept` / `orchestrator_reject` / `orchestrator_correct` in this command — those are the PI's response surface and require explicit two-tap confirmation per the orchestrator-pi skill.
