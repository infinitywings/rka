---
description: "Onboard an RKA project: discuss topic + propose toolkit + write tools.json + .env template. Usage: /orchestrator-onboard <project_id>"
---

Parse the user's argument as the `project_id` (must start with `prj_`). If omitted, call `rka_list_projects()` and offer choices via `AskUserQuestion`.

Before kicking off:
1. `orchestrator_health()` — verify daemon. If unreachable, tell the user to bring up `rka-orchestrator` via the Compose overlay.
2. `orchestrator_get_manifest(project_id)` — if a manifest already exists, ask via `AskUserQuestion`: "This project already has a baseline manifest. Re-onboard would create a NEW baseline (the old one stays in journal audit). Continue?"
3. On confirm: `orchestrator_onboard_start(project_id)`.

After start_onboarding returns:
- Returns `{parked_interrupt_id, parked_interrupt_type: "pi_onboarding_topic", ...}`
- Load the `rka-orchestrator-pi` skill if not already loaded.
- Render the topic-elicitation prompt to the PI in chat. Ask for: 1-2 sentence summary, field, target venue, 3-5 keywords.
- Call `orchestrator_correct(interrupt_id, response_text=<PI's free text>)` to feed the response back as topic_metadata.

The subgraph then advances through `research_toolkit_node` → `pi_toolkit_ratify` → `draft_manifest_node` → `pi_credentials_ready` → `finalize_node`. Drive each interrupt per the orchestrator-pi skill's rules (TWO-TAP on toolkit_ratify; single-tap with the .env-edit prompt on credentials_ready).

After finalize completes, surface to the PI:
- Manifest path: `~/rka-projects/{project_id}/tools.json`
- Audit journal id (the orchestrator's `rka_add_note` write)
- Any required secrets that failed probe (if so, the run escalated; PI should fix and re-onboard or accept the partial state)

Do not call `orchestrator_accept` for the onboarding flow without going through the orchestrator-pi skill's TWO-TAP rule on `pi_toolkit_ratify` — the toolkit ratification is a privileged authorization gate.
