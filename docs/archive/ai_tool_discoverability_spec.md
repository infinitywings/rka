# AI Tool Discoverability and Onboarding — Implementation Spec

**Context**: RKA v2.0 will have 50+ MCP tools. AI agents (Brain/Executor) see all tools listed but don't reliably know the *workflow* — which tools to call first, which depend on others, what the session lifecycle looks like. This spec defines three layers of discoverability to solve this.

**Decision**: Three-layer approach — improved MCP instructions + auto-generated CLAUDE.md + updated orientation prompts.

---

## Overview: Three Layers

| Layer | Mechanism | Audience | Per-project effort | When it helps |
|-------|----------|----------|-------------------|--------------|
| **1. MCP instructions** | `RKA_INSTRUCTIONS` constant in `server.py` | Every connected AI client | Zero — baked into server | Immediately on connection |
| **2. Auto-generated CLAUDE.md** | New `rka_generate_claude_md` tool | Claude Code (Executor) | ~1 min (run tool, save) | Session start |
| **3. Updated orientation prompts** | `brain_orientation()`, `executor_orientation()` | Brain/Executor on demand | Zero — baked into server | On first call or PI nudge |

---

## Layer 1: Replace RKA_INSTRUCTIONS in server.py

### What to change

Replace the current `RKA_INSTRUCTIONS` constant (~30 lines, category listing) with the v2.0 version below (~80 lines, prescriptive decision table). The current version lists tool *categories* ("Notes: rka_add_note, rka_update_note, rka_get_journal") — this tells the AI *what exists* but not *when to use it*. The new version maps *situations* to tools.

### When to implement

Phase 1 (when entity types change) — must be updated at the same time as the journal type migration so the instructions match the actual schema.

### Exact replacement text for RKA_INSTRUCTIONS

```python
RKA_INSTRUCTIONS = """\
Research Knowledge Agent (RKA) — structured knowledge base for AI-assisted research.
RKA tracks journal entries (note/log/directive), decisions, literature, missions,
claims, evidence clusters, and a three-layer research map with full provenance chains.

## Session Start — ALWAYS do this first
1. `rka_get_context()` — load current project state, phase, recent knowledge
2. `rka_get_status()` — see current phase, focus, next steps
3. `rka_get_checkpoints(status="open")` — check for unresolved blockers
4. `rka_get_review_queue()` — (Brain only) items flagged for deep reasoning

## When to Use What

| Situation | Tool | Key parameters |
|-----------|------|---------------|
| Starting a session | `rka_get_context()` | Always first |
| Recorded an observation or analysis | `rka_add_note` | `type="note"`, `source="brain"` or `"executor"` |
| Documented a procedure step | `rka_add_note` | `type="log"`, `related_mission=id` |
| Giving instructions to Executor | `rka_add_note` | `type="directive"` |
| Made a research or design decision | `rka_add_decision` | `related_journal=[ids]` for justification |
| Need to assign implementation work | `rka_create_mission` | `motivated_by_decision=id` |
| Hit a blocker, need Brain/PI input | `rka_submit_checkpoint` | `blocking=True` |
| Finished an assigned mission | `rka_submit_report` | `related_decisions=[ids]` |
| Found a relevant paper | `rka_add_literature` or `rka_enrich_doi` | |
| Want to search for papers | `rka_search_semantic_scholar` / `rka_search_arxiv` | |
| Want the research overview | `rka_get_research_map` | Three-level: RQs → clusters → claims |
| Want to trace why something exists | `rka_trace_provenance` | `direction="upstream"` or `"both"` |
| Need to overturn a past decision | `rka_supersede_decision` | Triggers re-distillation |
| (Brain) Review flagged items | `rka_get_review_queue` then `rka_review_cluster` | |
| (Brain) Deep topic synthesis | `rka_synthesize_topic` | Better than local LLM |
| (Brain) Resolve a contradiction | `rka_resolve_contradiction` | |
| Searching for anything | `rka_search` | Searches all entity types |
| End of session | `rka_update_status` | Update summary and next_steps |

## Tool Categories
- **Project**: `rka_list_projects`, `rka_set_project`, `rka_create_project`, `rka_get_status`, `rka_update_status`
- **Notes**: `rka_add_note`, `rka_update_note`, `rka_get_journal`
- **Decisions**: `rka_add_decision`, `rka_update_decision`, `rka_get_decision_tree`
- **Literature**: `rka_add_literature`, `rka_update_literature`, `rka_get_literature`, `rka_enrich_doi`
- **Missions**: `rka_create_mission`, `rka_get_mission`, `rka_update_mission_status`, `rka_submit_report`
- **Checkpoints**: `rka_submit_checkpoint`, `rka_get_checkpoints`, `rka_resolve_checkpoint`
- **Research Map**: `rka_get_research_map`, `rka_get_claims`, `rka_supersede_decision`, `rka_trace_provenance`
- **Review Queue**: `rka_get_review_queue`, `rka_review_cluster`, `rka_review_claims`, `rka_resolve_contradiction`
- **Search & Context**: `rka_search`, `rka_get_context`, `rka_ask`
- **Graph**: `rka_get_graph`, `rka_get_ego_graph`, `rka_graph_stats`
- **Academic**: `rka_search_semantic_scholar`, `rka_search_arxiv`, `rka_search_elicit`, `rka_import_bibtex`
- **Workspace**: `rka_scan_workspace`, `rka_bootstrap_workspace`
- **Session**: `rka_session_digest`, `rka_reset_session`
- **Onboarding**: `rka_generate_claude_md`

## Entity Types (v2.0)
- **Journal entries**: `note` (observations, analyses), `log` (procedures), `directive` (instructions)
- **Claims**: Extracted from entries by LLM — `hypothesis`, `evidence`, `method`, `result`, `observation`, `assumption`
- **Decisions**: `research_question`, `design_choice`, or `operational` (set via `kind` field)
- **Evidence clusters**: Groups of related claims with LLM-generated synthesis
- **Cross-references**: 12 link types forming provenance chains (informed_by, justified_by, motivated, produced, etc.)

## Roles
- **Brain** (Claude Desktop): strategy, decisions, literature review, deep reasoning, review queue
- **Executor** (Claude Code): implementation, experiments, data processing, mission execution
- **PI** (human): supervision, final authority, research direction

Use `brain_orientation` or `executor_orientation` prompts for detailed role guidance.

## Multi-Project
`rka_list_projects()` → `rka_set_project(id)` to switch. All tools scope to active project.
"""
```

---

## Layer 2: New rka_generate_claude_md Tool

### What to build

A new MCP tool + REST endpoint that queries the live database and produces a project-specific `CLAUDE.md` file. The PI runs it once when setting up a new project (or after major changes) and saves the output to the project root.

### When to implement

Phase 7 (when all v2.0 tools exist, so the generated doc references them correctly).

### Tool signature

```python
@tool()
async def rka_generate_claude_md(
    project_path: str = ".",
    role: str = "executor",
) -> str:
    """Generate a project-specific CLAUDE.md for Claude Code.

    Queries the live RKA database and produces a CLAUDE.md tailored to
    the current project state: active phase, established tags, open missions,
    research questions, recording conventions, and v2.0 tool guidance.

    Args:
        project_path: Root path of the project (for directory structure reference)
        role: Target role — "executor" (default) or "brain"
    """
```

### REST endpoint

```
GET /api/generate-claude-md?role=executor
```

Returns the generated markdown string. The MCP tool calls this endpoint.

### New route file

Create `rka/api/routes/onboarding.py`:

```python
from fastapi import APIRouter, Depends
from rka.services.onboarding import OnboardingService

router = APIRouter(prefix="/api", tags=["onboarding"])

@router.get("/generate-claude-md")
async def generate_claude_md(
    role: str = "executor",
    svc: OnboardingService = Depends(),
) -> dict:
    md = await svc.generate_claude_md(role=role)
    return {"markdown": md, "role": role}
```

### New service

Create `rka/services/onboarding.py` with a single method `generate_claude_md(role)` that:

1. Queries `project_state` for name, phase, summary
2. Queries `decisions` where `kind='research_question'` and `status='active'` — with cluster/claim counts from `evidence_clusters`
3. Queries `missions` where `status IN ('pending', 'active')`
4. Queries `tags` — top 20 by usage count (GROUP BY tag ORDER BY COUNT DESC LIMIT 20)
5. Queries `topics` table for hierarchical topics
6. Queries `checkpoints` where `status='open'`
7. Queries `decisions` — last 10 active decisions (ORDER BY created_at DESC)
8. Assembles the markdown from a template string

### Output template

The tool should generate markdown matching this structure (values filled from DB):

````markdown
# CLAUDE.md — {project_name} ({role} instructions)

This project uses **RKA (Research Knowledge Agent)** for persistent knowledge management.
You are the **{Role}**: {role_description}.

---

## Project
**Name**: {project_state.project_name}
**Phase**: {project_state.current_phase}
**RKA dashboard**: http://127.0.0.1:9712
**Focus**: {first 200 chars of project_state.summary}

---

## Session Start Protocol
1. `rka_get_context()` — load current project state
{if role == "executor":}
2. `rka_get_mission()` — check for active/pending missions
3. `rka_get_checkpoints(status="open")` — check for blockers
{if role == "brain":}
2. `rka_get_checkpoints(status="open")` — resolve Executor blockers first
3. `rka_get_review_queue()` — items flagged for your attention
4. `rka_get_research_map()` — see the big picture

---

## Active Research Questions
{for each decision where kind='research_question' and status='active':}
- **{decision.question}** (clusters: {count}, claims: {count}, gaps: {gap_count})
{if none: "No research questions defined yet. Use rka_add_decision(kind='research_question') to create one."}

## Active Missions
{for each mission where status in ('pending', 'active'):}
- [{mission.status}] **{mission.objective}** (ID: `{mission.id}`)
  Tasks: {number of tasks}, Phase: {mission.phase}
{if none: "No active missions."}

## Recording Standards (v2.0)

| Situation | Tool | Parameters |
|-----------|------|-----------|
| Got a result | `rka_add_note` | `type="note", related_mission="{active_mission_id}"` |
| Ran an experiment/procedure | `rka_add_note` | `type="log", related_mission="{active_mission_id}"` |
| PI/Brain instruction | `rka_add_note` | `type="directive"` |
| Hit a decision point | `rka_submit_checkpoint` | `blocking=True` |
| Finished a mission | `rka_submit_report` | Include `related_decisions=[...]` |
| Found a paper | `rka_add_literature` or `rka_enrich_doi` | |
| Made a decision | `rka_add_decision` | Include `related_journal=[...]` |

**Always set `related_mission` when working on a mission task.**
**Always set `related_decisions` when a finding bears on a decision.**

## Established Tags
{for each tag in top 20 most-used tags:}
- `{tag}` ({count} entries)
{if none: "No tags established yet."}

## Established Topics
{for each topic in topics table:}
- `{topic.name}` — {topic.description or "No description"}
{if none: "No topics defined yet."}

## Open Checkpoints
{for each checkpoint where status='open':}
- [{checkpoint.type}] **{checkpoint.description}** (ID: `{checkpoint.id}`)
{if none: "No open checkpoints."}

## Key Decisions (recent)
{for each of last 10 active decisions:}
- **{decision.question}** → {decision.chosen} ({decision.kind})
{if none: "No decisions recorded yet."}

## Constraints
- Journal entry types: `note` (observations/analyses), `log` (procedures), `directive` (instructions)
- Old types (finding, insight, methodology, etc.) are accepted but mapped to these three
- Always set `related_mission` when working on a mission task
- Always set `related_decisions` when a finding bears on a decision
- Raise checkpoints for strategic decisions — don't decide unilaterally
- Cross-reference everything: decisions need `related_journal`, missions need `motivated_by_decision`
````

### Data sources for each section

| Section | Query |
|---------|-------|
| Project | `GET /api/status` → project_state |
| Research Questions | `SELECT * FROM decisions WHERE kind='research_question' AND status='active'` + cluster counts from `evidence_clusters` |
| Active Missions | `SELECT * FROM missions WHERE status IN ('pending', 'active') ORDER BY created_at DESC` |
| Tags | `SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC LIMIT 20` |
| Topics | `SELECT * FROM topics ORDER BY name` |
| Checkpoints | `SELECT * FROM checkpoints WHERE status='open'` |
| Key Decisions | `SELECT * FROM decisions WHERE status='active' ORDER BY created_at DESC LIMIT 10` |

### Important implementation notes

1. **Output only** — the tool returns a markdown string. It does NOT write to the filesystem (respects the no-Docker-mount principle). The user saves the output.
2. **Role-aware** — the `role` parameter changes: session start protocol steps, which tools are emphasized, the opening description.
3. **Graceful degradation** — if tables like `topics`, `evidence_clusters`, or `review_queue` don't exist yet (pre-migration), skip those sections with a note like "Not available yet — run migration 009."
4. **Also update `scripts/research_project_CLAUDE.md`** — update this static template to match v2.0 types and tools. This serves as a fallback when the server isn't running.

---

## Layer 3: Updated Orientation Prompts

### What to change

Update both `brain_orientation()` and `executor_orientation()` MCP prompts in `server.py` to include v2.0 additions. These are comprehensive (~2000 tokens each) and loaded only when explicitly called.

### When to implement

Phase 7 (when all v2.0 tools exist).

### brain_orientation additions

Add these sections to the existing `brain_orientation()` return string:

```python
# Add after the existing "## Core Workflow" section:

"""
## v2.0 Research Map Workflow

- `rka_get_research_map()` — see the three-level view (RQs → clusters → claims)
- When creating decisions, set `kind="research_question"` for questions that organize research
- Use `related_journal=[ids]` on decisions to link them to justifying evidence
- Use `motivated_by_decision=id` on missions to create provenance chains

## Review Queue (Brain-Only)

At session start, after loading context:
4. `rka_get_review_queue()` — items the local LLM flagged for your attention

Process high-priority items before starting new work:
- `rka_review_cluster(cluster_id, confidence, synthesis)` — refine cluster quality
- `rka_review_claims(entry_id, corrections)` — correct extracted claims
- `rka_synthesize_topic(topic_id)` — write deep topic synthesis
- `rka_resolve_contradiction(cluster_id, resolution)` — resolve flagged conflicts
- `rka_evaluate_evidence(scope="project")` — assess overall evidence state

Your syntheses are marked `synthesized_by: brain` — they override local LLM output.

## Cross-References

When recording decisions, always link evidence:
- `rka_add_decision(..., related_journal=["jrn_01...", "jrn_02..."])` — what findings justify this
- `rka_create_mission(..., motivated_by_decision="dec_01...")` — what decision triggers this work
- `rka_trace_provenance(entity_id, direction="upstream")` — understand why something exists

## Decision Lifecycle

- To overturn a past decision: `rka_supersede_decision(old_id, question, chosen, rationale)`
- This automatically triggers re-distillation of affected knowledge
- Raw journal entries are never changed — only the interpretive layer rebuilds
"""
```

### executor_orientation additions

Add these sections to the existing `executor_orientation()` return string:

```python
# Replace the existing "## Recording Standards" table with:

"""
## v2.0 Recording Standards

### Entry Types (simplified)

| Type | Use when | Example |
|------|---------|---------|
| `note` | You observed, analyzed, or discovered something | Results, insights, observations |
| `log` | You did a procedure step | "Ran stress test", "Deployed config" |
| `directive` | You received or are recording instructions | PI instructions, Brain directions |

Old types (finding, insight, methodology, etc.) are accepted but mapped to these three.

### Cross-References — Always Link Your Work

- `rka_add_note(..., related_mission="msn_01...")` — link to active mission (ALWAYS do this)
- `rka_add_note(..., related_decisions=["dec_01..."])` — link to relevant decisions
- `rka_submit_report(..., related_decisions=["dec_01..."])` — link findings to decisions they bear on

### Research Map Awareness

- `rka_get_research_map()` — see where your work fits in the big picture
- After completing a mission, check if your findings affect any research questions
- If they do, note which decisions your results justify or contradict

### Provenance

- `rka_trace_provenance(entity_id)` — trace the reasoning chain behind any entity
- Use this when you need to understand why a decision was made before implementing
"""
```

---

## Files to Modify — Summary

| File | Change | Phase |
|------|--------|-------|
| `rka/mcp/server.py` | Replace `RKA_INSTRUCTIONS` constant with v2.0 version (Section "Layer 1" above) | Phase 1 |
| `rka/mcp/server.py` | Add `rka_generate_claude_md` tool function | Phase 7 |
| `rka/mcp/server.py` | Update `brain_orientation()` prompt (Section "Layer 3" above) | Phase 7 |
| `rka/mcp/server.py` | Update `executor_orientation()` prompt (Section "Layer 3" above) | Phase 7 |
| `rka/api/routes/onboarding.py` | New route file for `GET /api/generate-claude-md` | Phase 7 |
| `rka/services/onboarding.py` | New service with `generate_claude_md()` method | Phase 7 |
| `rka/api/app.py` | Register the new onboarding router | Phase 7 |
| `scripts/research_project_CLAUDE.md` | Update template for v2.0 types and tools (fallback) | Phase 1 |

---

## Testing Checklist

1. **Connect fresh Claude Code session** → verify it calls `rka_get_context()` first without being told
2. **Present scenario: "I found a result"** → verify AI chooses `rka_add_note(type="note")` not old `type="finding"`
3. **Create a mission** → verify Executor sets `related_mission` on its notes
4. **Brain makes a decision** → verify it includes `related_journal` for justification
5. **Run `rka_generate_claude_md`** for existing project → verify output includes correct active missions, tags, RQs
6. **Run `rka_generate_claude_md` on empty project** → verify graceful output with "No X yet" placeholders
7. **Call `brain_orientation()`** → verify v2.0 sections (review queue, cross-refs, research map) are present
8. **Call `executor_orientation()`** → verify v2.0 types (note/log/directive) and cross-ref conventions are present
