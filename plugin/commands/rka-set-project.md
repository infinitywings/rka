---
description: "Pin an explicit RKA project for this conversation. No server-side active project or environment default exists."
argument-hint: "<project_id>"
---

If no id is provided, call `rka_query(args={"operation": "list_projects"})`
and ask the user to select one. Do not select on their behalf.

If an id is provided, verify it with
`rka_query(args={"operation": "status", "project_id": "<id>"})`. Then state
that this is the pinned project for the conversation and thread that exact
`project_id` on every later `rka_query` / `rka_execute` call.

`rka_set_project` is a deprecated no-op. There is no active-project session
state and no `RKA_PROJECT` default. Never claim that a server-side switch was
performed.
