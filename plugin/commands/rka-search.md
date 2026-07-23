---
description: "Search one explicit RKA project across journal, decisions, literature, missions, claims, and clusters."
argument-hint: "<project_id> <2-4 keyword terms>"
---

Require both an explicit canonical project id and a short query. If either is
missing, ask for it before searching. Call:

```python
rka_query(args={"operation": "search", "project_id": "<id>",
                "query": "<terms>", "limit": 10})
```

Present a numbered list with entity type, id, and one-line summary. If empty,
suggest shorter/different keywords. Do not silently search `proj_default`.
