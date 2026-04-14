# RKA Skills

RKA packages capability in MCP tools and operating expertise in role-specific skills.
Use exactly one role skill for the current session:

- `brain/SKILL.md` for strategy, literature review, research-map review, and decisions
- `executor/SKILL.md` for implementation, experiments, mission work, and reports
- `pi/SKILL.md` for supervision, checkpoint resolution, and preserving PI intent

## Common Rules

- Confirm the active project before doing scoped work: `rka_list_projects()` then `rka_set_project(...)` if needed.
- Treat journal, decisions, literature, and missions as canonical records.
- Treat claims, evidence clusters, and review items as derived knowledge that must stay linked to sources.
- Never create orphaned entities. Always provide `related_journal`, `related_decisions`, `related_mission`, or `motivated_by_decision` when applicable.
- Preserve PI attribution exactly: when recording PI guidance, use `source="pi"` and `verbatim_input` with the PI's exact words.
- Use the Research Map and review queue for interpretation work; do not let generated summaries become the canonical truth.

## Fallback

If the MCP instruction block and these skill files disagree, follow these skill files.
