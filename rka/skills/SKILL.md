# RKA Skills

RKA packages capability in MCP tools and operating expertise in role-specific skills.
Use exactly one role skill for the current session:

- `brain/SKILL.md` for strategy, literature review, research-map review, and decisions
- `executor/SKILL.md` for implementation, experiments, mission work, and reports
- `pi/SKILL.md` for supervision, checkpoint resolution, and preserving PI intent

## Common Rules

- **Confirm the active project FIRST, every session.** Call `rka_get_status()` — it returns the active project. If it's `proj_default` (or any project other than the one you intend), call `rka_list_projects()` then `rka_set_project(...)`. Do NOT skip — the MCP `_session.project_id` is per-process and ephemeral; without verification, writes silently land in `proj_default`. Set `RKA_PROJECT=<project_id>` in your MCP config (`claude_desktop_config.json` → `mcpServers.rka.env`, or shell env) to make this default automatic on session start.
- Treat journal, decisions, literature, and missions as canonical records.
- Treat claims, evidence clusters, and review items as derived knowledge that must stay linked to sources.
- Never create orphaned entities. Always provide `related_journal`, `related_decisions`, `related_mission`, or `motivated_by_decision` when applicable.
- Preserve PI attribution exactly: when recording PI guidance, use `source="pi"` and `verbatim_input` with the PI's exact words.
- Use the Research Map and review queue for interpretation work; do not let generated summaries become the canonical truth.

## Fallback

If the MCP instruction block and these skill files disagree, follow these skill files.
