---
description: "Show pending maintenance for one explicit RKA project without fixing anything."
argument-hint: "<project_id>"
---

Require a canonical project id; if absent, list projects and ask the user to
choose. Call:

```python
rka_query(args={"operation": "pending_maintenance", "project_id": "<id>"})
```

Present non-zero categories in priority order: decisions without provenance,
missions without motivation, unassigned clusters, missing cross-references,
and missing tags. This command is read-only and never falls back to a default
project.
