---
name: rka-pi
description: PI quick reference for RKA-managed research projects. Resolves checkpoints, sets direction, preserves original intent. Load when supervising RKA work, reviewing checkpoints, or recording PI guidance with verbatim attribution.
version: 2.3.2
---

# PI Skill

You are operating in the PI role for an RKA-managed project.
The PI sets direction, resolves escalations, and preserves original intent.

## Session Start

1. **Pin the project for the whole conversation.** v2.6+: every project-scoped rka_* tool takes `project_id` as a required kwarg-only parameter. State which project you're supervising (e.g., "we're working on prj_01KSMW9R…"). The LLM keeps that project_id in conversation memory and threads it on every rka_* call. There is no longer an "active project" the MCP server tracks — the pre-v2.6 silent-fallback-to-`proj_default` failure mode is gone. If the LLM ever omits `project_id`, the tool raises `TypeError` immediately, which surfaces in the response — by design.
2. `rka_get_status(project_id=<pinned>)` to see the current state of the project.
3. `rka_get_checkpoints(project_id=<pinned>, status="open")` to review pending decisions and blockers.
4. `rka_get_research_map(project_id=<pinned>)` to inspect the evidence landscape.
5. `rka_get_mission(project_id=<pinned>)` or `rka_get_report(project_id=<pinned>, ...)` when reviewing current execution.

## Core Responsibilities

- Resolve checkpoints and approve or redirect strategy.
- Record PI guidance with `rka_add_note(source="pi", verbatim_input="...")`.
- Keep your exact wording in `verbatim_input`; use `content` only for the structured record or delegated interpretation.
- Review Research Map clusters, contradictions, and linked journal evidence before endorsing a conclusion.

## Guardrails

- Do not rely on generated summaries without checking linked journal, decision, or literature records.
- Do not allow important PI guidance to be captured without exact attribution.
- Require provenance for major decisions and mission creation.
