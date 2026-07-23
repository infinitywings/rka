---
description: "Show status and open checkpoints for one explicit RKA project."
argument-hint: "<project_id>"
---

Require a canonical `project_id`. If absent, list projects and ask the user to
choose one. Then call:

```python
rka_query(args={"operation": "status", "project_id": "<id>"})
rka_query(args={"operation": "checkpoints", "project_id": "<id>",
                "filters": {"status": "open"}})
```

Present project id/name, phase, summary, and open checkpoint previews. There is
no active-project state or environment default; do not call `rka_set_project`.
