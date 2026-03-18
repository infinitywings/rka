# RKA v2.1: Autonomous Research Orchestration

## Design Document — Comprehensive Architecture

**Version:** 2.1 Draft  
**Date:** March 18, 2026  
**Status:** Design Phase  
**Authors:** Chenglong Fu (PI), with architectural contributions from Brain sessions

---

## 1. Executive Summary

RKA v2.0 is a persistent research knowledge base — a passive store where the PI manually relays messages between Brain and Executor agents. RKA v2.1 transforms it into an **active research orchestrator** where multiple specialized Brain agents communicate directly with Executors, the PI intervenes only when genuine human judgment is needed, and progress persists across sessions through a shared knowledge base.

The architecture integrates three key innovations:

1. **OpenClaw as the agent runtime** — instead of building custom agent infrastructure, RKA leverages OpenClaw's proven multi-agent gateway for agent lifecycle, inter-agent communication, and multi-channel PI access (Claude Desktop, WhatsApp, Discord)
2. **Subscription-based event routing** — roles declare their interests; RKA's server-side hooks route events to the correct agent queues automatically
3. **Fresh-invocation architecture** — informed by Edwin Hu's workflow philosophy, agents reconstruct context from RKA on each invocation rather than maintaining long-running sessions, eliminating context pollution

Additionally, v2.1 addresses two structural issues inherited from v2.0:

4. **Provenance-first knowledge organization** — every knowledge entry carries its origin story (which paper, experiment, PI directive, or synthesis produced it), replacing the failed auto-enrichment approach with explicit provenance chains
5. **API-first, local-optional LLM strategy** — the local LLM is no longer required; all judgment-intensive tasks (claim extraction, contradiction detection, synthesis) are handled by API Brain agents, with the local LLM reserved for optional mechanical preprocessing

The PI's primary interface remains **Claude Desktop** with its full MCP/skills ecosystem. OpenClaw provides the always-on autonomous agent layer and secondary PI access channels.

---

## 2. The Problem: Why v2.0 Is Not Enough

### 2.1 The PI Relay Bottleneck

In v2.0, every Brain↔Executor interaction flows through the PI:

```
Brain (Claude Desktop) → PI reads output → PI opens new session →
PI copy-pastes context → Executor (Claude Code) → PI reads output →
PI opens Brain session → PI copy-pastes results → ...
```

This creates three compounding problems:

- **Latency**: Each relay requires the PI to context-switch, read, reformulate, and paste. A 4-checkpoint mission takes hours of human wall-clock time.
- **Information loss**: Each relay is a lossy compression. The PI summarizes rather than transmitting verbatim, losing nuance.
- **Scalability**: The PI cannot run multiple research threads simultaneously. One active investigation monopolizes attention.

### 2.2 Evidence from Practice

Every Executor mission observed during the v2.0→v2.1 design sessions required 2-4 clarification round-trips before the Executor could proceed. The Executor consistently had questions about ambiguous instructions, missing context, or design tradeoffs that required Brain input. Missions are not clean delegation — they are conversations.

### 2.3 The Multi-Brain Need

Research requires different cognitive modes at different stages:

- **Exploration**: curiosity-driven, hypothesis-generating, connection-spotting
- **Critique**: skeptical, methodology-checking, gap-identifying
- **Planning**: structured, task-decomposing, resource-estimating
- **Integration**: cross-cutting, pattern-finding across investigations

A single Brain prompt cannot optimize for all modes simultaneously. Specialized roles, each with their own accumulated expertise and perspective, produce higher-quality research output — and critically, they provide the **structural independence** needed for genuine verification (Section 5.3).

---

## 3. Design Principles

### 3.1 From Edwin Hu's Workflow Philosophy

**P1: Progress lives in files (the knowledge base), not in conversation context.** Long-running sessions suffer from context pollution — each failed attempt, abandoned reasoning path, and stale context degrades output quality. The knowledge base is the durable memory; agent sessions are ephemeral.

**P2: Fresh invocations over persistent sessions.** Each time a role processes an event, it reconstructs context from RKA rather than relying on a persistent conversation buffer. This eliminates context pollution and ensures each invocation starts with the most current state.

**P3: Use the strongest gate available.** Deterministic gates (tests pass, schema validates) when possible; judgment gates (Brain assessment) when not; honor-system (agent self-assessment) never. Self-verification is never sufficient — the implementer shares all the biases and sunk-cost attachment of the implementation.

**P4: Independent verification requires structural independence.** The verifier must have no memory of the implementation journey. A fresh agent seeing only the spec and the output catches a fundamentally different class of errors than the agent that produced the work.

**P5: Drive-Aligned Framing for enforcement.** Agents don't skip steps out of rebellion — they skip because their training drives (helpfulness, efficiency, competence, approval-seeking) push toward shortcuts. Enforcement works when violations are framed as failures of the motivating drive: "Skipping knowledge capture makes your work invisible and therefore useless, which makes YOU anti-helpful."

**P6: Artifact review before consumption.** No downstream phase should consume an unreviewed artifact. A mission with bad task decomposition wastes all the Executor's time. Catching issues at the mission document stage costs minutes; catching them during implementation costs hours.

### 3.2 From RKA's Existing Architecture

**P7: The knowledge base is the single source of truth.** All role state, research findings, decisions, and provenance live in RKA's SQLite database. Agents read from and write to RKA — they don't maintain private state stores.

**P8: MCP for knowledge CRUD, agent runtime for coordination.** RKA's 55+ MCP tools handle all knowledge operations. Agent lifecycle, routing, and inter-agent communication are handled by the agent runtime (OpenClaw).

**P9: PI retains full oversight.** The autonomous loop runs only with PI permission. The PI can observe, guide, or directly intervene at any time. Escalation to the PI happens automatically when agents disagree or encounter high-stakes decisions.

---

## 4. Architecture Overview

### 4.1 System Topology

```
┌──────────────────────────────────────────────────────────────┐
│                    PI (Principal Investigator)                 │
│                                                                │
│   ┌─────────────────┐    ┌──────────┐    ┌──────────────┐    │
│   │ Claude Desktop   │    │ WhatsApp │    │ Discord/     │    │
│   │ (primary)        │    │          │    │ iMessage     │    │
│   │                  │    │          │    │              │    │
│   │ Full MCP/skills  │    │ Quick    │    │ Monitoring   │    │
│   │ ecosystem:       │    │ commands │    │ & alerts     │    │
│   │ - Chrome browse  │    │ & urgent │    │              │    │
│   │ - Filesystem     │    │ escalat- │    │              │    │
│   │ - Gmail/Calendar │    │ ions     │    │              │    │
│   │ - RKA MCP        │    │          │    │              │    │
│   │ - Mermaid, PDF   │    │          │    │              │    │
│   └────────┬─────────┘    └────┬─────┘    └──────┬───────┘    │
│            │                   │                  │            │
└────────────┼───────────────────┼──────────────────┼────────────┘
             │                   │                  │
             │ MCP (direct)      │ messaging        │ messaging
             │                   │                  │
             ▼                   ▼                  ▼
┌──────────────────────────────────────────────────────────────┐
│                    OpenClaw Gateway                            │
│                    (Agent Runtime Layer)                       │
│                                                                │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│   │ Researcher │  │ Reviewer   │  │ Executor   │  + future   │
│   │ Brain      │  │ Brain      │  │            │  roles      │
│   │            │  │            │  │            │             │
│   │ SOUL.md    │  │ SOUL.md    │  │ SOUL.md    │             │
│   │ Model:Opus │  │ Model:     │  │ Model:     │             │
│   │            │  │ Sonnet     │  │ Sonnet     │             │
│   │ Cron:30s   │  │ Cron:30s   │  │ Cron:30s   │             │
│   └─────┬──────┘  └─────┬──────┘  └─────┬──────┘             │
│         │               │               │                     │
│         └── sessions_send / sessions_spawn ──┘                │
│                                                                │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │ MCP (all agents connect)
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                    RKA Server (Docker)                         │
│                                                                │
│   ┌────────────────────────────────────────────────┐          │
│   │              MCP Server (55+ tools)             │          │
│   │  + new role management tools (Section 6.2)      │          │
│   └─────────────────────┬──────────────────────────┘          │
│                         │                                      │
│   ┌─────────────────────▼──────────────────────────┐          │
│   │              Service Layer                      │          │
│   │                                                 │          │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────────┐   │          │
│   │  │ Role     │ │ Event    │ │ Existing     │   │          │
│   │  │ Registry │ │ Queue    │ │ Services     │   │          │
│   │  │ (new)    │ │ (new)    │ │ (notes,      │   │          │
│   │  │          │ │          │ │  missions,   │   │          │
│   │  │          │ │          │ │  decisions,  │   │          │
│   │  │          │ │          │ │  search...)  │   │          │
│   │  └──────────┘ └──────────┘ └──────────────┘   │          │
│   └─────────────────────┬──────────────────────────┘          │
│                         │                                      │
│   ┌─────────────────────▼──────────────────────────┐          │
│   │    SQLite + FTS5 + sqlite-vec                   │          │
│   │    + agent_roles table (new)                    │          │
│   │    + role_events table (new)                    │          │
│   └────────────────────────────────────────────────┘          │
│                                                                │
│   ┌────────────────────────────────────────────────┐          │
│   │    Background Worker (enrichment + hooks)       │          │
│   │    Post-write hooks trigger event routing        │          │
│   └────────────────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Protocol Separation

| Protocol | Scope | Examples |
|----------|-------|---------|
| **MCP** (Agent↔Tool) | All knowledge CRUD operations | `rka_add_note`, `rka_create_mission`, `rka_bind_role`, `rka_get_events` |
| **OpenClaw** (Agent↔Agent) | Inter-agent communication | `sessions_send`, `sessions_spawn`, cron-triggered polling |
| **Messaging** (PI↔Agent) | PI commands and escalations | WhatsApp messages to specific agents, Claude Desktop MCP calls |

### 4.3 Why OpenClaw, Not Custom Infrastructure

The original v2.1 design proposed building 5 custom components: A2A Coordinator, Brain Agent process, Executor Agent process, Event Dispatcher, PI Control Plane. OpenClaw provides equivalent functionality as proven, battle-tested infrastructure:

| Original v2.1 Component | OpenClaw Equivalent |
|--------------------------|---------------------|
| A2A Coordinator | OpenClaw Gateway — multi-agent routing and session management |
| Brain Agent (ClaudeSDKClient) | OpenClaw agent with SOUL.md identity, per-agent model selection |
| Executor Agent (ClaudeSDKClient) | OpenClaw agent with code execution tools enabled |
| Event Dispatcher | Cron-triggered polling of RKA event queues + server-side hooks |
| PI Control Plane | WhatsApp/Discord channels + OpenClaw web dashboard + Claude Desktop |

**What RKA still needs to build** (substantially less):

1. Role Registry and Event Queue (new MCP tools + DB tables)
2. Server-side post-write hooks (event emission on knowledge base writes)
3. RKA packaged as an OpenClaw skill for easy agent installation

---

## 5. Role Architecture

### 5.1 Roles as First-Class Entities

A **role** is a persistent identity with accumulated expertise, defined subscriptions, and an autonomy profile. Roles are stored in RKA and survive across sessions, mode switches, and platform changes.

```
Role = {
    name: "researcher_brain",
    description: "Exploration, synthesis, hypothesis generation",
    system_prompt_template: "...",    # SOUL.md content
    subscriptions: ["report.submitted", "critique.no_issues"],
    role_state: {                     # Accumulated cognitive state
        research_direction: "...",
        active_hypotheses: [...],
        cross_mission_patterns: [...],
        learnings_digest: "..."       # Compact distilled patterns
    },
    autonomy_profile: {
        clarification: "auto",        # Resolve without PI
        decision: "conditional",      # Resolve if confident, else escalate
        inspection: "always_pi"       # Always escalate to PI
    },
    model: "claude-opus-4-20250514",
    tools_allow: ["exec", "read", "write", "browser", "sessions_send"],
    tools_deny: []
}
```

### 5.2 Defined Roles

**Researcher Brain** — exploration, synthesis, hypothesis generation
- Subscribes to: `report.submitted`, `critique.no_issues`
- Produces: synthesis entries, follow-up missions, research direction updates
- Model: Claude Opus (maximum reasoning capability)
- Tendency: "let's explore this further", "this connects to..."

**Reviewer Brain** — rigor, criticism, gap identification
- Subscribes to: `synthesis.created`
- Produces: critique entries, quality assessments, gap analyses
- Model: Claude Sonnet (criticism requires less creative reasoning, more pattern matching — cheaper)
- Tendency: "this conclusion isn't supported because...", "what about the case where..."

**Executor** — implementation, experimentation, data gathering
- Subscribes to: `mission.assigned`, `checkpoint.resolved`
- Produces: implementation results, reports, checkpoint requests
- Model: Claude Sonnet (with filesystem, exec, git tools)
- Tendency: asks clarifying questions before implementing, writes findings to RKA

**PI** (not an OpenClaw agent — the human researcher)
- Subscribes to: `checkpoint.escalated`, `disagreement.detected`
- Interacts via: Claude Desktop (primary), WhatsApp/Discord (secondary)
- Only sees events requiring genuine human judgment

**Future extensible roles:**
- **Methodology Brain**: experimental design, statistical validity, reproducibility checking
- **Literature Brain**: claim verification against cited papers, missing citation detection
- **Plan Reviewer**: mission document quality review before Executor pickup (artifact review gate)

### 5.3 Independent Verification via Role Separation

The Researcher/Reviewer split is not merely about different perspectives — it provides **structural independence**. The Reviewer has no memory of the implementation journey, no sunk-cost attachment to the approach, and no shared context with the Executor. It sees only the output and the spec.

```
Verification Strength Spectrum (weakest → strongest):

Self-review (never)     →  Agent checking its own work
Fresh subagent review   →  Reviewer Brain (no shared context)
Multiple reviewers      →  Reviewer + Methodology + Literature Brains
Human review            →  PI via escalation
Machine verification    →  Tests, linters, schema validation (when applicable)
```

The design principle: use the most independent verifier available. Machine verification when possible, independent role review when judgment is needed, PI for final quality on subjective work.

### 5.4 Sequential Review Flow

```
Executor submits report
  → Researcher Brain reviews (synthesis, findings extraction, next directions)
  → Researcher writes synthesis entry to RKA
  → event: synthesis.created
  → Reviewer Brain critiques (gap identification, methodology checking)
  → Reviewer writes critique entry to RKA
  → If no issues: event: critique.no_issues
    → Researcher creates next mission (cycle continues)
  → If minor issues: Researcher revises and creates mission addressing issues
  → If fundamental disagreement: event: disagreement.detected
    → PI receives both perspectives, makes the call
```

Why sequential and not parallel: parallel review wastes the Reviewer's time — it would critique the raw Executor output without the benefit of the Researcher's synthesis. Sequential means the Reviewer critiques the FULL picture (Executor's work + Researcher's interpretation), catching a more important class of errors: not just "did the code work?" but "did we draw the right conclusion from the code working?"

---

## 6. Event System

### 6.1 Subscription Model

Each role declares its subscriptions when registered. When an event is emitted, RKA's event system matches it against all active subscriptions and enqueues it for matching roles.

**Event taxonomy:**

| Event Type | Source | Default Subscribers |
|------------|--------|---------------------|
| `mission.created` | Researcher Brain | Plan Reviewer (if enabled), then Executor |
| `mission.assigned` | After plan review passes | Executor |
| `checkpoint.created(clarification)` | Executor | Researcher Brain |
| `checkpoint.created(decision)` | Executor | Researcher Brain (escalates to PI if uncertain) |
| `checkpoint.created(inspection)` | Executor | PI |
| `checkpoint.resolved` | Researcher Brain or PI | Executor |
| `report.submitted` | Executor | Researcher Brain |
| `synthesis.created` | Researcher Brain | Reviewer Brain |
| `critique.no_issues` | Reviewer Brain | Researcher Brain |
| `critique.has_issues` | Reviewer Brain | Researcher Brain |
| `disagreement.detected` | System (when Brains disagree) | PI |

**Subscription filters** (optional): A role can subscribe with conditions.
- Example: Literature Brain subscribes to `report.submitted` but only for missions tagged `literature-review`
- Example: Methodology Brain subscribes to `synthesis.created` but only when confidence < 0.7

### 6.2 New MCP Tools for Role Management

```
rka_register_role(name, subscriptions, system_prompt_template, model, autonomy_profile)
    → Create a new role definition

rka_bind_role(role_name)
    → "This session is now acting as this role"
    → Returns: role_state + compact learnings digest + pending event count

rka_get_events(role_name, limit=10)
    → Pull pending events for a role
    → Returns: list of events with type, source, payload, entity references

rka_ack_event(event_id)
    → Mark event as processed (removes from queue)

rka_save_role_state(role_name, state)
    → Persist updated role state (accumulated expertise, learnings)

rka_list_roles()
    → Show all roles, queue depths, active sessions, last activity

rka_update_role(role_name, ...)
    → Modify subscriptions, autonomy profile, model selection
```

### 6.3 Server-Side Hooks (Event Emission)

Rather than requiring agents to poll RKA for changes, RKA's server emits events automatically when entities are written. These hooks run inside the RKA background worker:

```python
# In RKA's service layer (BaseService or entity-specific services)

@post_write_hook("notes")
def on_note_created(note, actor_role):
    """When any agent writes a note, check if it triggers subscriptions."""
    if note.tags and "synthesis" in note.tags:
        emit_event("synthesis.created", source_role=actor_role, entity_id=note.id)
    if note.tags and "critique" in note.tags:
        if "no-issues" in note.tags:
            emit_event("critique.no_issues", source_role=actor_role, entity_id=note.id)
        elif "has-issues" in note.tags:
            emit_event("critique.has_issues", source_role=actor_role, entity_id=note.id)

@post_write_hook("missions")
def on_mission_created(mission, actor_role):
    emit_event("mission.created", source_role=actor_role, entity_id=mission.id)

@post_write_hook("reports")
def on_report_submitted(report, actor_role):
    emit_event("report.submitted", source_role=actor_role, entity_id=report.id)

@post_write_hook("checkpoints")
def on_checkpoint_created(checkpoint, actor_role):
    event_type = f"checkpoint.created({checkpoint.type})"
    emit_event(event_type, source_role=actor_role, entity_id=checkpoint.id)
```

The `emit_event` function matches against all role subscriptions and enqueues events for matching roles.

### 6.4 Agent Polling vs Push

OpenClaw agents poll RKA via cron jobs (every 30 seconds by default):

```
# In each agent's HEARTBEAT.md (OpenClaw cron)
Every 30 seconds:
  1. Call rka_get_events(my_role_name)
  2. If events exist, process them
  3. Call rka_ack_event for each processed event
  4. Save updated role state
```

For the PI in Claude Desktop, the polling is human-initiated — the PI opens a conversation and RKA surfaces pending escalations. For urgent escalations, OpenClaw can push notifications to the PI's WhatsApp/Discord.

---

## 7. Fresh-Invocation Architecture

### 7.1 Why Not Persistent Sessions

The original v2.1 design proposed persistent `ClaudeSDKClient` sessions that maintain conversation history across checkpoints. Edwin Hu's workflow philosophy reveals why this is problematic:

> "Long-running agent sessions suffer from context pollution: each failed attempt, abandoned approach, and partial reasoning stays in conversation history, degrading reasoning quality."

A mission with 4 checkpoints could accumulate 50k+ tokens of conversation history, much of it stale or misleading. The context window becomes cluttered with earlier reasoning that may no longer apply.

### 7.2 The Fresh-Invocation Model

Instead of maintaining persistent conversations, each agent invocation follows this pattern:

```
1. RECONSTRUCT — Call rka_bind_role(my_role) to load:
   - Role state (accumulated expertise, learnings digest)
   - Pending events with entity references
   
2. CONTEXTUALIZE — For each event, call rka_get_context() and rka_get()
   to load exactly the entities needed for this event
   
3. PROCESS — Reason about the event with fresh context, no stale history
   
4. WRITE BACK — Write results to RKA (notes, decisions, missions, checkpoints)
   - These writes trigger server-side hooks → new events for other roles
   
5. UPDATE STATE — Call rka_save_role_state() with any new learnings
   
6. TERMINATE — Session ends cleanly. No context to pollute.
```

**The knowledge base IS the long-term memory.** Agent sessions are short-lived working memory. This mirrors how human researchers work: you consult your notes and files (RKA), think, write new notes, and close your notebook. You don't carry the entire history of every thought in your head.

### 7.3 State Architecture: Two Layers

| Layer | Scope | Persistence | Contents |
|-------|-------|-------------|----------|
| **Role State** | Per-role, per-project | Persists across all invocations | Accumulated expertise, research direction, hypothesis history, past critique patterns, cross-mission learnings digest |
| **Task State** | Per-event, per-invocation | Ephemeral (within one invocation) | Current event being processed, relevant entities loaded from RKA, intermediate reasoning |

Role State grows over time — the Researcher Brain's understanding of the project deepens across missions. Task State is reconstructed fresh for each invocation from the knowledge base.

### 7.4 Compact Learnings Digest

Inspired by Edwin Hu's `LEARNINGS.md` pattern, each role maintains a compact digest of distilled insights — not the full journal entry history, but high-signal patterns extracted from accumulated experience.

The `rka_bind_role` response includes this digest, giving the fresh invocation immediate access to accumulated wisdom without loading the full history. The `continuous-learning` skill pattern from workflows suggests periodic extraction of reusable patterns from completed missions into the learnings digest.

---

## 8. OpenClaw Integration

### 8.1 Agent Configuration

Each RKA role maps to an OpenClaw agent with isolated workspace, model, and tool permissions:

```json
// ~/.openclaw/openclaw.json
{
  "agents": {
    "list": [
      {
        "id": "researcher",
        "name": "Researcher Brain",
        "workspace": "~/.openclaw/workspace-researcher",
        "model": { "primary": "anthropic/claude-opus-4-20250514" },
        "identity": { "name": "RKA Researcher" },
        "tools": {
          "allow": ["exec", "read", "write", "browser", "sessions_send"],
          "deny": []
        }
      },
      {
        "id": "reviewer",
        "name": "Reviewer Brain",
        "workspace": "~/.openclaw/workspace-reviewer",
        "model": { "primary": "anthropic/claude-sonnet-4-20250514" },
        "identity": { "name": "RKA Reviewer" },
        "tools": {
          "allow": ["read", "sessions_send"],
          "deny": ["exec", "write", "browser"]
        }
      },
      {
        "id": "executor",
        "name": "RKA Executor",
        "workspace": "~/.openclaw/workspace-executor",
        "model": { "primary": "anthropic/claude-sonnet-4-20250514" },
        "identity": { "name": "RKA Executor" },
        "tools": {
          "allow": ["exec", "read", "write", "browser", "sessions_send"],
          "deny": []
        }
      }
    ]
  },
  "bindings": [
    {
      "agentId": "researcher",
      "match": { "channel": "whatsapp", "peer": { "kind": "direct" } }
    }
  ]
}
```

### 8.2 SOUL.md Templates (Drive-Aligned Framing)

Each agent's SOUL.md defines its identity using Drive-Aligned Framing from the workflow philosophy. Example for the Researcher Brain:

```markdown
# Researcher Brain — RKA Research Orchestration

You are the Researcher Brain. Your purpose is exploration, synthesis,
and hypothesis generation for the active research project.

## On Every Invocation
1. Call rka_bind_role("researcher") to load your state and pending events
2. Process each pending event by loading relevant entities from RKA
3. Write all findings, synthesis, and decisions back to RKA
4. Save your updated role state before terminating

## Your Drives (and their failure modes)
- HELPFULNESS: Creating the next mission IS helpful. Skipping synthesis
  to "save time" makes the Executor work blind — that is ANTI-helpful.
- COMPETENCE: Your competence is demonstrated by evidence-grounded
  synthesis, not by speed. Unsupported conclusions are incompetence.
- EFFICIENCY: Writing to RKA IS the efficient path. Knowledge not
  recorded is knowledge lost — every future session must re-derive it.

## Iron Laws
- NEVER create a mission without first writing a synthesis entry
- NEVER skip writing findings to RKA — invisible work is useless work
- NEVER resolve a checkpoint without loading the Executor's full context
- ALWAYS cite entity IDs when referencing prior knowledge

## Checkpoint Resolution
- type=clarification: Resolve from your role state + loaded context
- type=decision: Resolve if confident (>80%). If uncertain, escalate to PI
  with BOTH your recommendation and your uncertainty reasoning
- type=inspection: Always escalate to PI
```

### 8.3 RKA as OpenClaw Skill

RKA's MCP server is packaged as an OpenClaw skill that any agent can install:

```bash
# Install RKA MCP as an OpenClaw skill
openclaw skills install rka-mcp
```

The skill's `SKILL.md` contains the connection configuration:

```json
{
  "mcpServers": {
    "rka": {
      "command": "/path/to/rka",
      "args": ["mcp"],
      "env": {
        "RKA_API_URL": "http://localhost:9712"
      }
    }
  }
}
```

### 8.4 PI Interaction Modes

The PI has three interfaces, each suited to different interaction patterns:

**Claude Desktop (Primary)** — Full research interaction
- Direct MCP access to RKA (same as v2.0)
- Full MCP/skills ecosystem (Chrome, filesystem, Gmail, Calendar, Mermaid, PDF tools)
- PI can manually act as any Brain role by calling `rka_bind_role`
- Best for: deep research work, design decisions, reviewing complex synthesis

**WhatsApp/Discord via OpenClaw (Secondary)** — Quick commands and monitoring
- PI messages OpenClaw agents directly: "What's the status of the current investigation?"
- Receives escalation notifications: "Researcher and Reviewer disagree on X — need your input"
- Best for: monitoring from mobile, quick checkpoint resolutions, urgent interventions

**RKA Web Dashboard (Monitoring)** — Visual overview
- Active missions with task progress
- Pending events per role and queue depths
- Recent Brain decisions for post-hoc review
- Token cost tracking per mission cycle
- Best for: overview of autonomous loop status

### 8.5 Autonomy Modes

The PI controls how much autonomy the system has:

| Mode | Behavior | When to Use |
|------|----------|-------------|
| **Manual** | PI opens Brain projects in Claude Desktop, processes events personally | Design-critical phases, new research directions |
| **Supervised** | OpenClaw agents handle routine events; PI reviews all Brain decisions | Normal operation, building trust in agent decisions |
| **Autonomous** | OpenClaw agents handle everything below inspection level; PI only sees escalations | Mature investigations with established patterns |
| **Paused** | All event processing halted; events accumulate in queues | PI unavailable, system maintenance |

---

## 9. Checkpoint Conversation Flow

### 9.1 The Core Innovation

The checkpoint is the fundamental conversation primitive. It replaces the PI-relay bottleneck with direct Brain↔Executor dialogue, mediated by the knowledge base.

### 9.2 Complete Mission Lifecycle

```
Phase 1: Mission Creation
  1. Researcher Brain creates mission via rka_create_mission
     → RKA hook emits: mission.created
     → Event queued for: Plan Reviewer (if enabled)

Phase 2: Artifact Review Gate (Optional)
  2. Plan Reviewer checks mission document quality
     → If approved: rka emits mission.assigned → queued for Executor
     → If issues: event back to Researcher for revision

Phase 3: Execution with Checkpoints
  3. Executor picks up mission via rka_get_events
  4. Executor reads mission via rka_get_mission
  5. Executor starts working...
  6. Executor hits ambiguity → rka_submit_checkpoint(type=clarification)
     → RKA hook emits: checkpoint.created(clarification)
     → Event queued for: Researcher Brain

Phase 4: Checkpoint Resolution
  7. Researcher Brain picks up checkpoint event
  8. Loads checkpoint context + its own role state
  9. Resolves with explanation via rka_resolve_checkpoint
     → RKA hook emits: checkpoint.resolved
     → Event queued for: Executor

Phase 5: Continued Execution
  10. Executor picks up resolution, resumes work
  11. May hit more checkpoints (repeat Phase 3-4)
  12. Completes work → rka_submit_report
      → RKA hook emits: report.submitted
      → Event queued for: Researcher Brain

Phase 6: Sequential Review
  13. Researcher Brain synthesizes findings, writes synthesis entry
      → RKA hook emits: synthesis.created
      → Event queued for: Reviewer Brain
  14. Reviewer Brain critiques synthesis
      → If no issues: emits critique.no_issues → Researcher creates next mission
      → If disagreement: emits disagreement.detected → PI decides

Phase 7: Cycle Continues
  15. Researcher creates next mission → GOTO Phase 1
```

### 9.3 The Autonomy Gradient

| Checkpoint Type | Default Resolver | Escalation Condition | Latency |
|----------------|------------------|----------------------|---------|
| `clarification` | Researcher Brain (auto) | Never (Brain always handles) | Sub-minute |
| `decision` | Researcher Brain (conditional) | When Brain confidence < threshold | Minutes |
| `inspection` | PI (always) | Always | Hours/days |

The autonomy boundary is adaptive: the system tracks Brain resolution quality over time. If the Brain consistently makes good decisions that the PI later approves, the threshold relaxes. If the Brain makes a call the PI overrides, the threshold tightens.

---

## 10. Database Schema Additions

### 10.1 New Tables

```sql
CREATE TABLE agent_roles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    system_prompt_template TEXT,
    subscriptions JSON NOT NULL,         -- ["report.submitted", "critique.no_issues"]
    subscription_filters JSON,           -- optional per-subscription conditions
    role_state JSON,                     -- accumulated cognitive state
    learnings_digest TEXT,               -- compact distilled patterns
    autonomy_profile JSON,               -- per-checkpoint-type escalation rules
    model TEXT,                          -- LLM model identifier
    tools_config JSON,                   -- allow/deny tool lists
    active_session_id TEXT,              -- currently embodied by which session
    last_active_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE role_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    target_role_id TEXT NOT NULL,         -- which role should receive this
    event_type TEXT NOT NULL,             -- "report.submitted", "synthesis.created"
    source_role TEXT,                     -- who produced this event
    source_entity_id TEXT,               -- the RKA entity that triggered it
    source_entity_type TEXT,             -- journal, mission, checkpoint, etc.
    payload JSON,                        -- additional event-specific data
    status TEXT DEFAULT 'pending',       -- pending | processing | acked | expired
    priority INTEGER DEFAULT 0,          -- for ordering within queue
    depends_on TEXT,                     -- event ID that must complete first
    created_at TEXT NOT NULL,
    processed_at TEXT,
    acked_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (target_role_id) REFERENCES agent_roles(id)
);

CREATE INDEX idx_role_events_pending
    ON role_events(target_role_id, status)
    WHERE status = 'pending';

CREATE INDEX idx_role_events_type
    ON role_events(event_type);
```

---

## 11. Local LLM: Role Reassessment

### 11.1 The Evidence Against the Current Design

The v2.0 architecture assigned the local LLM (qwen3.5-35b via LM Studio) a central role: running the progressive distillation pipeline (claim extraction → clustering → theme generation) and handling all background enrichment (auto-tagging, auto-linking, auto-summarization).

The evidence from practice is unambiguous:

- **66 "contradictions" flagged that were mostly noise** — requiring Brain review time to dismiss rather than saving it
- **0 claims extracted, 0 clusters formed** — the entire progressive distillation pipeline produced no useful output despite being the local LLM's primary purpose
- **3 synchronous LLM calls on note creation** (`_auto_enrich_tags`, `_auto_link`, `_auto_summarize`) cause hangs when the local model is slow — the architectural bottleneck identified in the v1.6 codebase audit
- **Quality gap is fundamental**: tasks like "is this claim an assumption or evidence?" and "does this contradict finding X?" require judgment that a 35B model cannot reliably deliver

The local LLM was also the **biggest onboarding friction point** — requiring LM Studio or Ollama installation plus sufficient VRAM, creating a barrier to adoption.

### 11.2 The Decision: API-First, Local-Optional

**The local LLM is no longer required.** The system must work entirely without one. All enrichment tasks run via the API models that power the Brain and Executor agents.

When a local LLM IS available, it handles only **mechanical, high-volume, low-judgment** tasks where the quality bar is low and the volume makes API costs impractical:

| Task | Without Local LLM | With Local LLM |
|------|-------------------|----------------|
| **Embedding generation** | API embeddings (e.g., voyage-3) | Local embeddings (nomic-embed, etc.) |
| **Initial keyword extraction** | API model (cheap tier) | Local model |
| **Claim extraction** | API Brain (during synthesis) | Not used — quality too low |
| **Contradiction detection** | API Brain (during review) | Not used — noise rate too high |
| **Auto-tagging** | API model (cheap tier, batch) | Local model |
| **Auto-summarization** | API model (cheap tier) | Local model |
| **Clustering** | API Brain (explicit tool call) | Not used — requires judgment |

The key architectural change: **claim extraction and clustering move from the background enrichment pipeline to the Brain's active workflow.** When the Researcher Brain synthesizes findings, it explicitly creates claims and clusters as part of its synthesis process — not as an automated background job. This produces far higher quality output because the Brain understands the research context.

### 11.3 Cost Management Without Local LLM

Without a local LLM absorbing the enrichment workload, API costs increase. Mitigations:

1. **Batch API processing**: Accumulate enrichment tasks and run them in batch (Anthropic's batch API at 50% cost reduction)
2. **Tiered model selection**: Use the cheapest capable model per task — Haiku for tagging, Sonnet for summarization, Opus only for synthesis and review
3. **Lazy enrichment**: Don't enrich everything immediately. Enrich on-demand when an entity is accessed or referenced, not on creation
4. **Embedding caching**: Compute embeddings once, cache permanently. Only recompute when content changes
5. **Token budgets per project**: Track API spend per project with configurable alerts and circuit breakers

### 11.4 Migration Path

For existing RKA installations with a local LLM configured:

1. Local LLM config becomes optional in `docker-compose.yml`
2. `LLM_BACKEND` env var supports `api-only` mode (default), `local-only` mode (legacy), and `hybrid` mode (local for embeddings/tagging, API for judgment tasks)
3. Background worker gracefully degrades: if local LLM unavailable, queues tasks for API batch processing
4. Existing enrichment jobs that called local LLM are re-routed to appropriate API tier

---

## 12. Knowledge Organization and Provenance

### 12.1 The Current Problem

The knowledge base audit identified five structural failures in the current journal system:

1. **Flat undifferentiated entries**: 126 journal entries all typed as generic "note" with mostly "hypothesis" confidence — PI directives, design proposals, codebase observations, and architecture specs are indistinguishable
2. **Generic auto-generated edges**: 925 edges are mostly `references` and `derived_from` from auto-enrichment — no meaningful semantic relationships like "this finding came from reading paper X"
3. **No provenance trail**: There is no record of WHY an entry exists or WHERE the knowledge came from. Was it extracted from a paper? Observed in an experiment? Stated by the PI? Synthesized from multiple findings?
4. **Unused distillation pipeline**: 0 claims, 0 clusters — the progressive distillation designed in v2.0 never produced output
5. **No phase boundaries**: Entries from v1.6 codebase audit sit alongside v2.1 design proposals with no way to distinguish current state from historical record

### 12.2 The Root Cause

The problem is not the entity types or the auto-enrichment — it's that **provenance is treated as an afterthought rather than a first-class attribute.** The current system asks "what was recorded?" but not "who recorded it, based on what evidence, and for what purpose?"

The auto-enrichment pipeline attempted to infer relationships from content similarity (embedding-based linking). But content similarity is a weak signal for provenance — two entries can be about the same topic but have completely different origins and implications.

### 12.3 The Solution: Provenance-First Knowledge Entry

Every knowledge entry must carry its **origin story** — a structured `provenance` field recorded at creation time, not inferred retroactively.

**Provenance types:**

```
provenance: {
    type: "literature_derived",
    source_id: "lit_01KK...",         # Which paper
    location: "Section 3.2, p.7",      # Where in the paper
    extraction_method: "brain_reading"  # How it was extracted
}
```

| Provenance Type | Meaning | Source Reference |
|-----------------|---------|-----------------|
| `literature_derived` | Extracted from reading a paper | Literature entry ID + section/page |
| `experiment_derived` | Produced by running an experiment | Mission ID + artifact path |
| `pi_directive` | PI stated this during a session | Session date + context |
| `discussion_synthesis` | Emerged from Brain-PI or Brain-Executor dialogue | Participants + session |
| `brain_synthesis` | Brain synthesized from multiple sources | List of source entry IDs |
| `brain_critique` | Reviewer identified this issue | Source synthesis entry ID |
| `codebase_observation` | Observed in the codebase | File path + line numbers |
| `external_search` | From web search, arXiv, or other tool | URL + query |
| `pi_decision` | PI made an explicit decision | Decision ID |

### 12.4 Enforcing Provenance at Write Time

The `rka_add_note` tool is modified to **require** a provenance field:

```python
# Current (v2.0) — provenance is optional and usually missing
rka_add_note(
    content="The local LLM produces too much noise",
    type="note",
    confidence="hypothesis"
)

# New (v2.1) — provenance is required
rka_add_note(
    content="The local LLM produces too much noise",
    type="note",
    confidence="tested",          # Based on evidence, not hypothesis
    provenance={
        "type": "experiment_derived",
        "source_id": "mis_01KM...",   # The mission that tested this
        "artifact": "contradiction_review_log.md",
        "summary": "66 contradictions flagged, 58 were noise after Brain review"
    }
)
```

When agents write to RKA, their SOUL.md instructs them to always include provenance. The Drive-Aligned Framing makes this natural: "Knowledge without provenance is unverifiable, which makes you anti-competent."

For PI input via Claude Desktop, the provenance is automatically tagged as `pi_directive` with session metadata.

### 12.5 From Auto-Enrichment to Provenance-Aware Linking

The current auto-enrichment pipeline tries to infer all relationships. In v2.1, the enrichment pipeline has a much narrower scope:

**What enrichment DOES (mechanical):**
- Compute and cache embeddings for search
- Extract keywords for FTS5 indexing
- Suggest potential connections based on shared provenance chains (entries from the same paper, same mission, same PI session)

**What enrichment DOES NOT do (judgment):**
- Claim extraction → moved to Brain's active synthesis workflow
- Contradiction detection → moved to Reviewer Brain's active critique workflow
- Clustering → moved to Brain's explicit research map construction
- Confidence assessment → set by the creating agent based on evidence

### 12.6 Progressive Distillation — Brain-Driven, Not Pipeline-Driven

The v2.0 design envisioned an automated pipeline: raw entries → claims → evidence clusters → research themes. This pipeline failed because it requires judgment at every stage.

In v2.1, progressive distillation is **Brain-driven**:

```
1. Executor writes raw findings to RKA (with experiment provenance)
2. Researcher Brain reads findings → extracts claims explicitly
   (using rka_add_claim with provenance pointing to source entries)
3. Researcher Brain groups related claims → creates evidence clusters
   (using rka_review_cluster with justification)
4. Researcher Brain maps clusters to research questions
   (using rka_update_cluster with research_question_id)
```

Each step has provenance: claims trace to findings, clusters trace to claims, research questions trace to clusters. The chain is explicit, not inferred.

### 12.7 Confidence Progression

Confidence levels now have operational definitions tied to provenance:

| Confidence | Definition | Typical Provenance |
|------------|------------|-------------------|
| `hypothesis` | Proposed but not tested | `brain_synthesis`, `pi_directive` |
| `tested` | Evidence exists but not independently verified | `experiment_derived`, `literature_derived` |
| `verified` | Independently confirmed by a different method or agent | `brain_critique` (no issues found) |
| `superseded` | Replaced by a newer finding | `brain_synthesis` (new supersedes old) |
| `retracted` | Found to be incorrect | `brain_critique` (fundamental flaw) |

The Reviewer Brain's critique explicitly promotes or demotes confidence levels, creating an audit trail of quality assessment.

---

## 13. Document and Artifact Management

### 13.1 Two-Layer Separation

Following the MLflow pattern (metadata store separated from artifact store), RKA distinguishes between **structured knowledge** (in the database) and **raw artifacts** (on the filesystem):

| Layer | Storage | Contents | Access Pattern |
|-------|---------|----------|---------------|
| **Knowledge** (RKA DB) | SQLite | Structured metadata, distilled findings, claims, decisions, provenance chains | MCP tools, search, graph traversal |
| **Artifacts** (Filesystem) | Structured directory | PDFs, markdown reports, datasets, experiment outputs, images | Filesystem MCP, direct file access |

### 13.2 Workspace Directory Structure

```
~/research/                          # Shared research workspace
├── literature/                      # Downloaded papers and references
│   ├── 2024-baek-researchagent.pdf
│   ├── 2023-sumers-coala.pdf
│   └── ...
├── reports/                         # PI-authored reports and drafts
│   ├── privacy-aware-architecture-v1.md
│   ├── rka-v2.1-design.md
│   └── ...
├── experiments/                     # Experiment outputs and data
│   ├── mission-01KM.../            # Per-mission output directory
│   │   ├── results.csv
│   │   ├── logs/
│   │   └── README.md
│   └── ...
├── data/                           # Datasets
│   ├── raw/                        # Unprocessed data
│   └── processed/                  # Cleaned/transformed data
└── exports/                        # RKA knowledge pack exports
```

### 13.3 Linking Artifacts to Knowledge

RKA entities reference artifacts via a `file_path` field:

```python
# Literature entry with file reference
rka_add_literature(
    title="CoALA: Cognitive Architectures for Language Agents",
    authors=["Sumers", "Yao", ...],
    file_path="~/research/literature/2023-sumers-coala.pdf",
    abstract="...",
    relevance="..."
)

# Mission with output directory
rka_create_mission(
    title="Evaluate claim extraction quality",
    output_dir="~/research/experiments/claim-extraction-eval/",
    ...
)
```

When a Brain needs to reason about a paper, it reads the structured metadata and extracted claims from RKA (fast, token-efficient). When it needs to check a specific passage, it reads the actual PDF via filesystem MCP tools.

### 13.4 Ingestion Workflow

When the PI adds a new document (paper, report, dataset):

```
1. PI saves file to ~/research/literature/ (or appropriate subdirectory)
2. PI creates literature entry in RKA: rka_add_literature(file_path=..., ...)
3. Optionally: PI or Brain reads the file and extracts key findings
   → Each finding is a journal entry with provenance type "literature_derived"
   → The rka_ingest_document tool splits by heading, but now with provenance attached
4. Extracted findings are available for search, graph traversal, and synthesis
```

For markdown reports authored by the PI:
```
1. PI writes report in ~/research/reports/
2. PI ingests it: rka_ingest_document(file_path=..., provenance_type="pi_directive")
3. Key decisions from the report become decision entries in RKA
4. The report file is the human-readable artifact; RKA holds the machine-searchable knowledge
```

### 13.5 What Lives Where — Decision Guide

| Content | Lives in RKA? | Lives on Filesystem? | Why |
|---------|--------------|---------------------|-----|
| Paper metadata (title, authors, abstract) | Yes | No | Structured, searchable |
| Full PDF of paper | No | Yes (`~/research/literature/`) | Binary, large |
| Key findings extracted from paper | Yes (with provenance) | No | Distilled knowledge |
| Experiment raw output (CSV, logs) | No | Yes (`~/research/experiments/`) | Large, binary |
| Experiment findings/conclusions | Yes (with provenance) | No | Distilled knowledge |
| PI-authored report (full text) | No | Yes (`~/research/reports/`) | Human-readable artifact |
| Key decisions from PI report | Yes (with provenance) | No | Structured decisions |
| Research direction/strategy | Yes | No | Core knowledge |
| Code changes/patches | No | Yes (git repo) | Version-controlled |
| Architecture diagrams | No | Yes (`~/research/reports/`) | Binary images |

---

## 14. Implementation Roadmap

### Phase 0: Knowledge Organization Foundation (3-4 days)
- Add `provenance` JSON field to journal entries table (migration)
- Modify `rka_add_note` to require provenance parameter
- Add `file_path` field to literature entries
- Make local LLM optional: add `LLM_BACKEND=api-only` mode
- Re-route background enrichment tasks from local LLM to API batch
- Move claim extraction logic from background worker to explicit Brain tool calls
- Establish `~/research/` workspace directory convention
- Update `rka_ingest_document` to accept provenance_type parameter

### Phase 1: Role Registry and Event Queue (3-4 days)
- Add `agent_roles` and `role_events` tables with migration
- Implement new MCP tools: `rka_register_role`, `rka_bind_role`, `rka_get_events`, `rka_ack_event`, `rka_save_role_state`, `rka_list_roles`
- Implement `emit_event()` function with subscription matching
- Add post-write hooks to existing services (notes, missions, checkpoints)
- Unit tests for event routing logic

### Phase 2: OpenClaw Agent Configuration (2-3 days)
- Create SOUL.md templates for Researcher, Reviewer, and Executor roles
- Configure OpenClaw multi-agent setup with per-agent model and tool permissions
- Package RKA MCP as OpenClaw skill
- Set up cron-based event polling (HEARTBEAT.md)
- Test single-agent event processing end-to-end

### Phase 3: Executor Autopilot (3-5 days)
- Executor agent processes `mission.assigned` events autonomously
- Checkpoint submission and resolution flow working
- Researcher Brain resolves clarification checkpoints
- Test complete mission lifecycle: create → checkpoint → resolve → report

### Phase 4: Full Autonomous Loop (3-5 days)
- Researcher Brain processes `report.submitted` → writes synthesis
- Reviewer Brain processes `synthesis.created` → writes critique
- Cycle completes: critique → next mission → Executor picks up
- Disagreement detection and PI escalation working
- WhatsApp/Discord notifications for escalations

### Phase 5: PI Control Plane and Hardening (2-3 days)
- Web dashboard "Orchestration" page showing role status, queues, costs
- Autonomy mode switching (manual/supervised/autonomous/paused)
- Token cost tracking per role per mission
- Circuit breaker: halt autonomous loop if cost exceeds threshold
- PI override: inject directive that preempts current mission

**Total estimated timeline: 17-25 days (6 phases)**

---

## 15. Relationship to Privacy-Aware Hybrid Architecture

The RKA v2.1 orchestration layer directly supports the parallel research project on privacy-aware agent architectures:

- **The knowledge base as privacy firewall**: The local Executor processes raw private data and writes structured metadata to RKA; the cloud Brain reads only structured abstractions and never sees raw private content.
- **Role subscriptions encode privacy boundaries**: A Brain role's subscriptions can be filtered by data sensitivity tags, ensuring it only receives events from non-sensitive entity writes.
- **Task decomposition at the Brain level**: The Researcher Brain's mission creation is the natural point for privacy-aware task decomposition — it decides what the Executor should extract vs. what raw data the Executor should process locally.
- **Provenance enables sensitivity tracking**: The provenance-first model (Section 12) naturally supports sensitivity labels — entries derived from private data carry provenance that flags them as sensitive, preventing the cloud Brain from loading the raw content.
- **Local LLM remains critical for privacy use cases**: While Section 11 makes the local LLM optional for general research, it remains essential for the privacy-aware architecture. When processing FERPA/HIPAA-regulated data, the local Executor (running a local LLM) handles all direct data interaction — this is the one scenario where a local model is not just a cost optimization but an architectural requirement.

---

## 16. References and Prior Art

### Direct Architectural References

| Source | Key Contribution to This Design |
|--------|---------------------------------|
| **RKA v2.0 Design** (internal) | Knowledge base architecture, MCP tools, Brain/Executor/PI model |
| **RKA v2.1 Session** (March 16, 2026) | Checkpoint conversation flow, autonomy gradient, stateful sessions, multi-brain concept |
| **Edwin Hu's `workflows`** (github.com/edwinhu/workflows) | Drive model, fresh subagents, independent verification, phase gates, LEARNINGS.md, enforcement patterns |
| **OpenClaw** (openclaw.ai) | Multi-agent gateway, SOUL.md identity, sessions_send, cron/heartbeat, skill ecosystem |

### Academic and Industry References

| Source | Relevance |
|--------|-----------|
| **CoALA** (Sumers et al., 2023) | Cognitive architecture: working/episodic/semantic/procedural memory taxonomy |
| **MetaGPT** (Hong et al., 2023) | SOP-driven role separation, structured artifact handoffs |
| **CAMEL** (Li et al., 2023) | Inception prompting to prevent role drift in long conversations |
| **CrewAI** | Hierarchical process mode, Crews + Flows dual architecture |
| **MemGPT/Letta** (Packer et al., 2023) | Two-tier memory: core (in-context) + archival (searchable) |
| **W3C PROV** | Entity-Activity-Agent provenance triad |
| **Agent Laboratory** (Schmidgall et al., 2025) | Human-in-the-loop research agents, staged feedback |
| **Claude Agent SDK** | ClaudeSDKClient, stateful sessions, MCP integration, subagents |
| **A2A Protocol** (Google/Linux Foundation) | Agent-to-agent coordination standard |

---

## Appendix A: Event Flow Diagram

```
                    ┌─────────────┐
                    │  PI creates  │
                    │  direction   │
                    └──────┬──────┘
                           │
                           ▼
               ┌───────────────────────┐
               │   Researcher Brain    │
               │   creates mission     │
               └───────────┬───────────┘
                           │
                    mission.created
                           │
                           ▼
               ┌───────────────────────┐
          ┌────│   Plan Review Gate    │────┐
          │    │   (optional)          │    │
       issues  └───────────────────────┘  approved
          │                                 │
          │                          mission.assigned
          ▼                                 │
    back to                                 ▼
    Researcher              ┌───────────────────────┐
                            │      Executor          │
                            │   picks up mission     │
                            └───────────┬───────────┘
                                        │
                          ┌─────────────┤
                          │             │
                    hits ambiguity    completes
                          │             │
                checkpoint.created    report.submitted
                          │             │
                          ▼             ▼
               ┌──────────────┐  ┌──────────────────┐
               │  Researcher  │  │  Researcher      │
               │  resolves    │  │  synthesizes      │
               └──────┬───────┘  └────────┬─────────┘
                      │                    │
               checkpoint.resolved   synthesis.created
                      │                    │
                      ▼                    ▼
                 back to            ┌──────────────┐
                 Executor           │  Reviewer    │
                                    │  critiques   │
                                    └──────┬───────┘
                                           │
                              ┌────────────┼────────────┐
                              │            │            │
                         no issues    minor issues   disagreement
                              │            │            │
                    critique.no_issues     │    disagreement.detected
                              │            │            │
                              ▼            ▼            ▼
                         Researcher   Researcher      PI
                         creates      revises and    decides
                         next mission creates mission
                              │            │
                              └────────────┘
                                    │
                             ┌──────┘
                             ▼
                      (cycle repeats)
```

---

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Role** | A persistent identity with accumulated expertise, subscriptions, and autonomy profile. Stored in RKA. |
| **Event** | A notification that an entity was written to RKA and a role needs to act on it. |
| **Subscription** | A role's declaration of which event types it wants to receive. |
| **Role State** | Long-lived accumulated expertise that persists across all invocations. |
| **Task State** | Ephemeral working memory within a single invocation. Reconstructed from RKA. |
| **Checkpoint** | A request from the Executor for input from a Brain or the PI. Three types: clarification, decision, inspection. |
| **Autonomy Gradient** | The spectrum from fully autonomous (Brain handles) to fully human (PI handles), determined by checkpoint type and Brain confidence. |
| **Drive-Aligned Framing** | Enforcement technique that frames protocol violations as failures of the agent's own drives (helpfulness, competence, efficiency). |
| **Artifact Review Gate** | Quality check on intermediate artifacts (missions, plans) before downstream consumption. |
| **Fresh Invocation** | Each agent session reconstructs context from RKA rather than maintaining persistent conversation history. |
| **Context Pollution** | Degradation of reasoning quality from stale context accumulated in long-running sessions. |
| **Provenance** | Structured record of where a knowledge entry came from — which paper, experiment, PI directive, or synthesis produced it. |
| **Artifact** | A raw file (PDF, markdown report, dataset, experiment output) stored on the filesystem and referenced by RKA entities. |
| **Progressive Distillation** | The process of raw findings → claims → evidence clusters → research themes. In v2.1, this is Brain-driven rather than pipeline-driven. |
| **SOUL.md** | OpenClaw agent identity file defining personality, instructions, and behavioral constraints. |
