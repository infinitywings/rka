---
description: "Show the project's current effective tool manifest (baseline + any mid-mission extensions). Usage: /orchestrator-manifest <project_id>"
---

Parse the user's argument as the `project_id`. If omitted, call `rka_list_projects()` + ask via `AskUserQuestion`.

Call `orchestrator_get_manifest(project_id)`.

If 404: tell the user the project hasn't been onboarded yet. Offer `/orchestrator-onboard <project_id>`.

If 200, render the manifest concisely:

```
## Project tool manifest — {project_id}

Topic: {topic.summary}
Field: {topic.research_field} | Venue: {topic.venue}

Manifest type: {baseline | extension}
Manifest hash: sha256:{hash[:12]}...
Audit entry: {audit_journal_id or '(none)'}

Tools ({N} total):
  ✓ rka (always-on, registry)
  ✓ context7 (registry)
  ✓ sec-edgar (registry) — secrets: SEC_EDGAR_API_KEY (required)
  ⊕ wandb (user_added via extension mis_X) — secrets: WANDB_API_KEY (optional)
```

Use ✓ for healthy registry tools, ⊕ for extension-added tools.

For each tool's secrets, surface the criticality tier (required / recommended / optional).

Keep the output under ~25 lines unless the manifest is unusually large.

Don't call any other tools. This is a read-only introspection command.
