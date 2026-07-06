# RKA Skills

RKA packages capability in MCP tools and operating expertise in role-specific skills.
Use exactly one role skill for the current session:

- `brain/SKILL.md` for strategy, literature review, research-map review, and decisions
- `executor/SKILL.md` for implementation, experiments, mission work, and reports
- `pi/SKILL.md` for supervision, checkpoint resolution, and preserving PI intent
- `writer/SKILL.md` for manuscript drafting in Claude Code (VSCode); loaded in a `manuscripts/<project-id>/<venue>/` working directory. Phase 1 MVP per `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D`; mission `mis_01KS0C3RP04XANCZAB3HTNAG0P`.

## Common Rules

- **Pin the project for the whole conversation, every session.** v2.6+: every project-scoped operation requires `project_id` as a typed field on `args`. There is no longer a per-process active project on the MCP server, and the `RKA_PROJECT` env var was removed. State the project at the start (e.g. "we're working on prj_01KSMW9R…"); call `rka_query(args={"operation": "list_projects"})` once to discover the canonical ID if you don't know it; then thread `"project_id": "prj_..."` on every subsequent `rka_query` / `rka_execute` call. The legacy `rka_set_project` is a deprecated no-op.
- **v2.7.0+ tool surface.** Five tools are always-on at the MCP server: `rka_query(args)` for all 42 reads, `rka_execute(args)` for all 49 writes, `rka_describe(operation)` for schema lookup, plus `rka_load_tools` / `rka_help` as escape hatches. The 91 typed Pydantic models behind `rka_query` / `rka_execute` render as `inputSchema.oneOf` with per-branch enum + required-field enforcement, so wrong enum values and missing provenance are rejected at the schema layer BEFORE the call dispatches.
- Treat journal, decisions, literature, and missions as canonical records.
- Treat claims, evidence clusters, and review items as derived knowledge that must stay linked to sources.
- Never create orphaned entities. Always provide `related_journal`, `related_decisions`, `related_mission`, or `motivated_by_decision` when applicable.
- Preserve PI attribution exactly: when recording PI guidance, use `source="pi"` and `verbatim_input` with the PI's exact words.
- Use the Research Map and review queue for interpretation work; do not let generated summaries become the canonical truth.

## Fallback

If the MCP instruction block and these skill files disagree, follow these skill files.
