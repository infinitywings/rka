---
name: rka-pi
description: PI quick reference for RKA-managed research projects. Resolves checkpoints, sets direction, preserves original intent. Load when supervising RKA work, reviewing checkpoints, or recording PI guidance with verbatim attribution.
version: 2.7.0
---

**Skill version: 2.7.0 — last updated 2026-06-02**

# PI Skill

You are operating in the PI role for an RKA-managed project.
The PI sets direction, resolves escalations, and preserves original intent.

## Tool Surface (v2.7.0+) — No-Compromise Typed-Arg Dispatch

The rka MCP server ships a **discriminated-union dispatch surface**. Five tools are always-on:

| Always-on tool | Purpose |
|---|---|
| `rka_query(args)` | All 42 read operations |
| `rka_execute(args)` | All 49 write/lifecycle operations |
| `rka_describe(operation)` | Schema lookup + worked example; `rka_describe('')` returns the <250-token index |
| `rka_load_tools(names)` | Escape hatch for explicit legacy-tool access |
| `rka_help(name)` | Full docs for one canonical `rka_*` tool name (active or deferred) — use before `rka_load_tools` |

`args` is a **typed Pydantic model** discriminated by `operation`. 91 models in `rka/mcp/operation_args.py` render as `inputSchema.oneOf` with per-branch enum + required-field constraints. **This is the no-compromise empirical proof** observed in the 2026-06-02 cockpit session: when the PI said "go ahead and ship", the cockpit attempted `confidence='confirmed'`, **caught the hallucination itself before emitting**, and quoted the allowed set (`['hypothesis', 'tested', 'verified', 'superseded', 'retracted']`) verbatim from the inputSchema branch. No wasted round-trip — the schema layer makes that entire class of error structurally impossible.

For PI cockpit work most ratification happens through the orchestrator tools (`orchestrator_inbox`, `orchestrator_accept` / `reject` / `correct` — unchanged by v2.7.0). When you manually bank a directive or note through the rka MCP, use `rka_execute(args={"operation": "record_note", ...})` etc.

### Worked PI examples

```python
# Bank a PI directive verbatim (source=pi, verbatim_input preserved)
rka_execute(args={"operation": "record_note",
                  "project_id": "prj_01...",
                  "content": "Brain reads as: lock the v2.7.0 binary for release...",
                  "verbatim_input": "go ahead and ship",
                  "type": "directive",
                  "source": "pi",
                  "confidence": "verified"})

# Review open blockers
rka_query(args={"operation": "checkpoints",
                "project_id": "prj_01...", "filters": {"status": "open"}})

# Resolve a checkpoint
rka_execute(args={"operation": "resolve_checkpoint",
                  "project_id": "prj_01...",
                  "id": "chk_01...",
                  "resolved_by": "pi",
                  "resolution": "...", "create_decision": True})
```

## Session Start

1. **Pin the project for the whole conversation.** v2.6+: every project-scoped operation requires `project_id` in `args`. State which project you're supervising (e.g., "we're working on prj_01KSMW9R…"). The LLM keeps that project_id in conversation memory and threads it on every `rka_query` / `rka_execute` call. There is no longer an "active project" the MCP server tracks — the pre-v2.6 silent-fallback-to-`proj_default` failure mode is gone. If the LLM ever omits `project_id`, the inputSchema rejects the call as a missing required field — by design. The `RKA_PROJECT` env var was removed in v2.6.
2. `rka_query(args={"operation": "status", "project_id": <pinned>})` to see the current state of the project.
3. `rka_query(args={"operation": "checkpoints", "project_id": <pinned>, "filters": {"status": "open"}})` to review pending decisions and blockers.
4. `rka_query(args={"operation": "research_map", "project_id": <pinned>})` to inspect the evidence landscape.
5. `rka_query(args={"operation": "mission", "project_id": <pinned>, "id": "mis_..."})` or `rka_query(args={"operation": "report", "project_id": <pinned>, "id": "mis_..."})` when reviewing current execution.

## Core Responsibilities

- Resolve checkpoints and approve or redirect strategy.
- Record PI guidance with `rka_execute(args={"operation": "record_note", "source": "pi", "verbatim_input": "...", ...})`.
- Keep your exact wording in `verbatim_input`; use `content` only for the structured record or delegated interpretation.
- Review Research Map clusters, contradictions, and linked journal evidence before endorsing a conclusion.

## Guardrails

- Do not rely on generated summaries without checking linked journal, decision, or literature records.
- Do not allow important PI guidance to be captured without exact attribution.
- Require provenance for major decisions and mission creation.
