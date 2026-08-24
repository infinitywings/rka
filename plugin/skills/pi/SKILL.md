---
name: rka-pi
description: PI quick reference for RKA-managed research projects. Resolves checkpoints, sets direction, preserves original intent. Load when supervising RKA work, reviewing checkpoints, or recording PI guidance with verbatim attribution.
version: 2.7.0
---

**Skill version: 2.7.0 — last updated 2026-06-02**

# PI Skill

You are operating in the PI role for an RKA-managed project.
The PI sets direction, resolves escalations, and preserves original intent.

## Tool Surface

The rka MCP server ships a **discriminated-union dispatch surface**. Five tools are always-on:

| Always-on tool | Purpose |
|---|---|
| `rka_query(args)` | All 67 read operations |
| `rka_execute(args)` | All 83 write/lifecycle operations |
| `rka_describe(operation)` | Schema lookup + worked example; `rka_describe('')` returns the <250-token index |
| `rka_load_tools(names)` | Escape hatch for explicit legacy-tool access |
| `rka_help(name)` | Deprecated alias for `rka_describe` |

`args` is a **typed Pydantic model** discriminated by `operation`. 150 models in `rka/mcp/operation_args.py` render as `inputSchema.oneOf` with per-branch enum + required-field constraints. **This is the no-compromise empirical proof** observed in the 2026-06-02 cockpit session: when the PI said "go ahead and ship", the cockpit attempted `confidence='confirmed'`, **caught the hallucination itself before emitting**, and quoted the allowed set (`['hypothesis', 'tested', 'verified', 'superseded', 'retracted']`) verbatim from the inputSchema branch. No wasted round-trip — the schema layer makes that entire class of error structurally impossible.

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
                  "resolution": "...", "resolved_by": "pi",
                  "create_decision": True})
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

## Retrieval Strategy

You are the only role that will question whether a conclusion rests on a
decision that has since been overturned. Three things make that checkable.

1. **Scope your searches by node type.** `search` ranks eight entity types in
   one list. Unscoped, a decision is found by its own question text only 25.8 %
   of the time; with `"filters": {"entity_types": ["decision"]}` it is 93.3 %
   (measured over all 392 decisions in this store, eval-v3 2026-08-23).
2. **A search hit alone cannot tell you whether a decision is in force.** It
   carries `status` / `superseded_by` where the source table has them, but the
   authoritative check is to reach the node through `ego_graph` / `multi_hop`
   or fetch it with `operation="entity"`. If a decision is superseded, follow
   `superseded_by` to the one that replaced it before endorsing anything.
3. **Ask the record what changed.** `belief_as_of` reconstructs what the
   project believed at a past date — the right lens when reviewing work written
   weeks ago. `changes_since` pages what has happened since a cursor.
   `staleness_impact` shows what a retraction would invalidate downstream.
   `contradictions` surfaces conflicting evidence before you ratify.

## Guardrails

- Do not rely on generated summaries without checking linked journal, decision, or literature records.
- Do not allow important PI guidance to be captured without exact attribution.
- Require provenance for major decisions and mission creation.
