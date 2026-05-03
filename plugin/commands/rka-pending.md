---
description: "Show RKA pending maintenance: provenance gaps, untagged entries, decisions missing justified_by links, missions missing motivated_by_decision, unassigned clusters, etc."
---

Call `rka_get_pending_maintenance()` to fetch the project's maintenance manifest.

Present results grouped by category in priority order:
1. **decisions_without_justified_by** — count + first 3 ids
2. **missions_without_motivated_by** — count + first 3 ids
3. **unassigned_clusters** — count + first 3 ids
4. **entries_missing_cross_refs** — count + first 3 ids
5. **entries_without_tags** — count + first 3 ids

For each non-zero category, briefly describe the recommended fix action.

If all categories are empty, say "✅ No pending maintenance — knowledge graph is clean."

Do not actually fix anything; this command is informational only. The user must explicitly direct any fix work. Keep the response under 25 lines.
