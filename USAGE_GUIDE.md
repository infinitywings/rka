# RKA Usage Guide — For Researchers Using Claude Desktop & Claude Code (v2.1)

This guide is written for PIs (researchers) who use **Claude Desktop** as the Brain and **Claude Code** as the Executor. It walks through the full research workflow from installation to producing research outputs.

> **Three actors, one memory**: You (the PI) supervise. Claude Desktop (Brain) handles strategy, synthesis, and knowledge organization. Claude Code (Executor) handles implementation, experiments, and coding tasks. RKA is the shared memory that persists everything across sessions.

---

## Table of Contents

- [Setup](#setup)
  - [Install Docker and Start RKA](#1-install-docker-and-start-rka)
  - [Connect Claude Desktop (Brain)](#2-connect-claude-desktop-brain)
  - [Connect Claude Code (Executor)](#3-connect-claude-code-executor)
  - [Verify Everything Works](#4-verify-everything-works)
- [Starting Your First Session](#starting-your-first-session)
  - [Opening Claude Desktop (Brain)](#opening-claude-desktop-brain)
  - [Loading the Brain Skill](#loading-the-brain-skill)
  - [What Happens at Session Start](#what-happens-at-session-start)
- [The Research Lifecycle](#the-research-lifecycle)
  - [Phase 1: Define Your Research](#phase-1-define-your-research)
  - [Phase 2: Collect Evidence](#phase-2-collect-evidence)
  - [Phase 3: Assign Work to the Executor](#phase-3-assign-work-to-the-executor)
  - [Phase 4: Review and Synthesize](#phase-4-review-and-synthesize)
  - [Phase 5: Produce Research Outputs](#phase-5-produce-research-outputs)
- [Working With Claude Code (Executor)](#working-with-claude-code-executor)
  - [How the Executor Picks Up Missions](#how-the-executor-picks-up-missions)
  - [The Backbrief](#the-backbrief)
  - [Checkpoints and Escalation](#checkpoints-and-escalation)
  - [Mission Reports](#mission-reports)
- [Validation Gates](#validation-gates)
- [Knowledge Freshness](#knowledge-freshness)
- [Using the Web Dashboard](#using-the-web-dashboard)
- [Multi-Project Workflows](#multi-project-workflows)
- [Knowledge Pack Export and Import](#knowledge-pack-export-and-import)
- [Tips and Best Practices](#tips-and-best-practices)
- [Troubleshooting](#troubleshooting)

---

## Setup

### 1. Install Docker and Start RKA

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) if you don't have it. Then:

```bash
git clone https://github.com/infinitywings/rka.git
cd rka
docker compose up -d
```

Open http://localhost:9712 in your browser — you should see the RKA web dashboard.

### 2. Connect Claude Desktop (Brain)

Claude Desktop communicates with RKA via MCP (Model Context Protocol). You need to:

**a. Install the MCP binary** (runs outside Docker so Claude Desktop can reach it):

```bash
# From the rka/ directory:
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

This installs `rka` at `~/.local/bin/rka`. The binary is a thin proxy — it receives MCP tool calls from Claude Desktop and forwards them to the Docker container's REST API.

**b. Configure Claude Desktop:**

Open Claude Desktop → Settings → Developer → Edit Config, or directly edit:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add:

```json
{
  "mcpServers": {
    "rka": {
      "command": "/Users/<your-username>/.local/bin/rka",
      "args": ["mcp"]
    }
  }
}
```

Replace `<your-username>` with your actual username. Save and **restart Claude Desktop**.

### 3. Connect Claude Code (Executor)

Claude Code also uses MCP. The same binary works for both.

**In VS Code**: Open Claude Code settings and add the MCP server. The config goes in `.claude/mcp.json` in your project directory or in VS Code's MCP settings:

```json
{
  "mcpServers": {
    "rka": {
      "command": "/Users/<your-username>/.local/bin/rka",
      "args": ["mcp"]
    }
  }
}
```

After saving, reload the VS Code window (Cmd+Shift+P → "Reload Window").

### 4. Verify Everything Works

**In Claude Desktop**, start a new conversation and type:

> "List my RKA projects"

Claude should call `rka_list_projects()` and show your projects (or an empty list if this is a fresh install).

**In Claude Code**, type:

> "Check RKA status"

Claude should call `rka_get_status()` and return the current project state.

If either fails, check:
- Is Docker running? (`docker compose ps` should show `rka-server` as healthy)
- Is the MCP binary installed? (`~/.local/bin/rka mcp` should hang waiting for stdin — Ctrl+C to exit)
- Did you restart Claude Desktop after editing the config?

---

## Starting Your First Session

### Opening Claude Desktop (Brain)

1. Open **Claude Desktop**
2. Start a **new conversation** (click the "+" or Cmd+N)
3. You should see the RKA MCP tools available — Claude Desktop will list them as available tools in the conversation

The first time Claude sees the RKA MCP server, it will read the server instructions which tell it:
- What RKA is
- The session start protocol
- How to load skill prompts for detailed guidance

### Loading the Brain Skill

Claude Desktop automatically receives brief instructions from the MCP server. For the **full Brain workflow guide** (450+ lines of detailed guidance), Claude should load the skill prompt. You can ask:

> "Load your brain skill guide"

or Claude may do this automatically. The Brain skill covers:
- Session start protocol (exact tool call sequence)
- PI attribution discipline (preserving your exact words)
- Provenance discipline (linking everything to evidence)
- Claim extraction best practices
- Multi-task parsing (splitting your instructions into separate missions)
- How to work with the Executor
- Research Map navigation
- Anti-patterns to avoid

### What Happens at Session Start

When you start a conversation with the Brain, it should automatically:

1. **Check what changed** — `rka_get_changelog(since="yesterday")` shows new entries, decisions, claims, and missions since your last session
2. **Load the research map** — `rka_get_research_map()` shows your research questions, evidence clusters, and claim counts
3. **Process maintenance** — `rka_get_pending_maintenance()` detects provenance gaps. The Brain silently fixes up to 10 items (adding missing links, tags, or claim extractions)
4. **Greet you** with a summary of where things stand

You don't need to tell Claude to do this — the skill guide instructs it to.

---

## The Research Lifecycle

### Phase 1: Define Your Research

**You (PI) tell the Brain your research direction:**

> "I want to study whether horizontal sharding can solve MQTT broker scalability problems under high device density."

**What the Brain does:**

1. **Confirmation Brief** — The Brain restates your intent to verify understanding:

   > *"Let me make sure I understand: you want to identify the device density threshold where MQTT brokers degrade, and then test whether horizontal sharding mitigates the problem. Assumptions: lab environment, QoS 1, single-broker baseline. Does this match your intent?"*

2. After you confirm, the Brain **records your direction** with proper attribution:

   ```
   rka_add_note(
     content="Brain analysis: PI directed study of MQTT broker scalability...",
     source="pi",
     verbatim_input="I want to study whether horizontal sharding can solve MQTT broker scalability problems under high device density.",
     type="directive",
     tags=["research-protocol", "gate-0"]
   )
   ```

   Your exact words are preserved in `verbatim_input`. The Brain's interpretation goes in `content`. These are kept separate so your intellectual contribution is always traceable.

3. The Brain **creates research questions** as decision nodes:

   ```
   rka_add_decision(
     question="At what device density does MQTT broker performance degrade beyond 5% packet loss?",
     kind="research_question",
     decided_by="pi",
     assumptions=["Network latency negligible in lab", "Devices publish at 1 msg/sec"]
   )
   ```

### Phase 2: Collect Evidence

**Adding literature:**

> "I found a paper by Smith and Lee (2024) on MQTT broker stress testing. They report 12% packet loss above 400 devices."

The Brain records the paper and processes your reading annotations:

```
rka_add_literature(title="MQTT Broker Performance Under Stress", authors=["Smith, J.", "Lee, K."], year=2024)

rka_process_paper(
  lit_id="lit_01...",
  summary="Benchmarks MQTT brokers at scale. Key finding: 12% packet loss above 400 devices.",
  annotations=[
    {passage: "Table 3: 12% packet loss at 400 devices", note: "Threshold lower than expected",
     claim_type: "evidence", confidence: 0.85, cluster_id: "ecl_01..."}
  ]
)
```

`rka_process_paper` does three things in one call:
- Creates a journal entry with your reading notes
- Extracts structured claims from each annotation
- Assigns claims to evidence clusters

**The Brain creates evidence clusters** to organize related claims:

```
rka_create_cluster(label="Broker Performance Thresholds", research_question_id="dec_01...")
```

As you discuss more papers and findings, the Brain extracts claims and assigns them to clusters. The Research Map grows organically.

### Phase 3: Assign Work to the Executor

When there's implementation work to do (experiments, code, data collection), the Brain creates a **mission** for the Executor:

> "We need to run our own stress test to verify Smith & Lee's numbers."

The Brain creates a mission with a structured handoff:

```
rka_create_mission(
  objective="Run stress test to verify packet loss measurements at 400 devices",
  tasks=[
    {"description": "Replicate Smith & Lee setup (Mosquitto 2.0, 4-core, QoS 1)"},
    {"description": "Run 5 trials at 400 devices, compute mean and stddev"},
    {"description": "Compare results with published 12% figure"}
  ],
  context="INTENT: Verify published packet loss threshold...\nBACKGROUND: Smith & Lee report 12%...\nCONSTRAINTS: Do not modify broker config...\nASSUMPTIONS: 1. Network latency negligible...\nVERIFICATION: Mean packet loss with 95% CI",
  motivated_by_decision="dec_01..."
)
```

**To hand this to the Executor**: Open Claude Code and tell it:

> "Pick up mission mis_01... from RKA"

See [Working With Claude Code (Executor)](#working-with-claude-code-executor) for details.

### Phase 4: Review and Synthesize

After the Executor completes work and submits a report, the Brain:

1. **Reviews the report** — `rka_get_report(mission_id="mis_01...")`
2. **Checks for contradictions** — `rka_detect_contradictions(entity_id="clm_01...")`
3. **Flags stale evidence** — `rka_flag_stale(entity_id="clm_01...", reason="Contradicted by our experiment")`
4. **Writes cluster syntheses** — `rka_review_cluster(cluster_id="ecl_01...", synthesis="Our 5-trial experiment shows 8.2% mean packet loss...")`
5. **Advances research questions** — `rka_advance_rq(rq_id="dec_01...", status="partially_answered", conclusion="Threshold identified at ~400 devices")`

### Phase 5: Produce Research Outputs

When you need a draft for a paper section, literature review, or progress report:

> "Give me a progress report on the broker scalability question"

The Brain calls:

```
rka_assemble_evidence(research_question_id="dec_01...", format="progress_report")
```

This produces a structured markdown document pulling together:
- Key findings (top claims by confidence)
- Decisions made (with rationale)
- Current gaps
- Suggested next steps

Three formats are available:
- `progress_report` — findings + decisions + gaps + next steps
- `lit_review` — cluster-by-cluster with claims and cited papers
- `proposal_section` — framing + evidence + methodology + results

The output is a starting point — the Brain refines it before presenting to you.

---

## Working With Claude Code (Executor)

### How the Executor Picks Up Missions

In Claude Code, tell it to pick up a mission:

> "Pick up your RKA mission"

or if you have a specific mission ID:

> "Work on mission mis_01KP4DB5PZF7YXYRPV2AGQJSE6"

The Executor will:
1. Call `rka_get_mission()` to load the mission details
2. Read the `motivated_by_decision` to understand WHY the work exists
3. Read all context links (journal entries, decisions, literature)
4. Load the Executor skill for workflow guidance

### The Backbrief

Before starting significant work, the Executor presents a **Backbrief** — its plan for accomplishing the mission. This catches misalignment early:

> *"Before I start, here's my plan: I'll replicate the Smith & Lee setup in Docker, run 5 independent trials at 400 devices, and compute mean ± stddev. I interpret 'verify' to mean checking if our results fall within the published confidence interval..."*

The Executor records the Backbrief as a journal entry tagged `backbrief` and waits for the Brain to approve. You can review it in Claude Desktop:

> "The Executor submitted a backbrief for the stress test mission. Review it."

### Checkpoints and Escalation

During execution, the Executor raises **checkpoints** when it hits problems:

- **Assumption invalidation** — "The mission assumes network latency is negligible, but I measured 5ms"
- **Scope expansion** — "Fixing this requires changes outside the stated scope"
- **Contradictory results** — "Our measurements don't match the expected values"

Checkpoints appear in Claude Desktop via `rka_get_checkpoints(status="open")`. You and the Brain resolve them:

> "The Executor flagged that network latency isn't negligible. Tell it to re-run with simulated latency."

### Mission Reports

When the Executor finishes, it submits a report via `rka_submit_report()` with:
- **Summary**: What was done and what was found
- **Findings**: Key results
- **Anomalies**: Unexpected observations
- **Questions**: Open questions for the PI

The Brain reviews the report and either marks the mission complete or creates follow-up missions.

---

## Validation Gates

Gates are formal go/no-go checkpoints at critical transitions. They prevent compounding errors by forcing evaluation before proceeding.

### The 4 Gate Types

| Gate | When | Who Creates | Who Evaluates |
|------|------|-------------|---------------|
| **Gate 0: Problem Framing** | Before research starts | Brain | Brain + PI |
| **Gate 1: Plan Validation** | After mission created, before Executor starts | Brain | Brain (reviews Backbrief) |
| **Gate 2: Evidence Review** | After experiments/evidence gathering | Executor | Brain + PI |
| **Gate 3: Synthesis Validation** | Before committing conclusions | Brain | Brain + PI |

### Example: Using Gates

**You say**: "Create a gate before the Executor starts the stress test."

The Brain creates a Gate 1:

```
rka_create_gate(
  mission_id="mis_01...",
  gate_type="plan_validation",
  deliverables=["Executor Backbrief journal entry"],
  pass_criteria=["Plan addresses all tasks", "Assumptions are consistent"],
  assumptions_to_verify=["Network latency is negligible"]
)
```

After the Executor submits its Backbrief, the Brain evaluates:

```
rka_evaluate_gate(
  gate_id="chk_01...",
  verdict="go",
  notes="Plan is aligned. Proceed.",
  assumption_status={"Network latency is negligible": "validated"}
)
```

Verdicts:
- **Go** — proceed to the next phase
- **Kill** — abandon this direction
- **Hold** — wait for more information
- **Recycle** — revise and resubmit

If any assumption is marked `"invalidated"`, RKA automatically flags the related decision as stale and propagates through the knowledge graph.

### When to Use Gates

Not every task needs all 4 gates:
- **Quick bug fix**: Gate 1 only (Backbrief)
- **New research direction**: All 4 gates
- **Literature review**: Gate 0 (protocol) + Gate 3 (synthesis validation)
- **Experiment**: Gate 1 (plan) + Gate 2 (evidence review)

---

## Knowledge Freshness

RKA tracks whether evidence is still current. As new findings arrive, old claims may become stale.

### Staleness Levels

| Level | Meaning | Icon |
|-------|---------|------|
| Green | Fresh — no known issues | 🟢 |
| Yellow | Aging or partially conflicting | 🟡 |
| Red | Directly contradicted or invalidated | 🔴 |

### How Staleness Works

1. **Detection**: The Brain runs `rka_check_freshness()` to find aging claims, superseded sources, and clusters with stale evidence
2. **Flagging**: `rka_flag_stale(entity_id, reason, propagate=true)` marks a claim as stale
3. **Propagation**: When `propagate=true`, staleness cascades:
   - Stale claim → if >50% of claims in a cluster are stale → cluster flagged
   - Stale cluster → decisions citing it are flagged
4. **Resolution**: The Brain reviews stale items and either updates them with new evidence or confirms they're still valid

### Contradiction Detection

When new evidence conflicts with existing claims:

```
rka_detect_contradictions(entity_id="clm_01...")
```

Returns semantically similar claims that may conflict. The Brain reviews and decides:
- Are they genuinely contradictory?
- Should the old claim be flagged stale?
- Does this change any decisions?

---

## Using the Web Dashboard

The web dashboard at http://localhost:9712 provides a visual interface for browsing your research without using Claude.

### Key Pages

| Page | What You See |
|------|-------------|
| **Dashboard** | Project overview, recent entries, active missions, export/import controls |
| **Research Map** | Three-level drill-down: research questions → clusters → claims. Click a cluster to see full synthesis, all claims, and edit confidence |
| **Journal** | Timeline of all entries grouped by date, with type/confidence filters |
| **Decisions** | Interactive decision tree visualization |
| **Literature** | Table with reading pipeline status (to_read → reading → read) |
| **Missions** | Active and historical missions with task progress |
| **Knowledge Graph** | Entity relationship graph showing provenance links |
| **Notebook** | Ask questions grounded in your knowledge base (requires LLM) |
| **Settings** | LLM configuration, API health, database stats |

### Project Selection

Use the sidebar to switch between projects. The dashboard stores your active project locally and applies it to all API calls.

---

## Multi-Project Workflows

RKA supports multiple isolated research projects in the same database.

**Create a new project:**

> "Create a new RKA project called 'IoT Broker Scalability'"

**Switch between projects:**

> "Switch to the IoT Broker Scalability project"

All tool calls operate on the active project. The Brain should call `rka_set_project()` at the start of each session if you have multiple projects.

---

## Knowledge Pack Export and Import

Knowledge packs are portable snapshots of a project — all data in a single `.rka-pack_v2.zip` file.

### Export

**From the web dashboard**: Dashboard → Export Pack

**From MCP**: `rka_export()` (or `GET /api/projects/export`)

The pack includes schema version metadata and table counts. The categorized table registry ensures no tables are silently dropped during export.

### Import

**From the web dashboard**: Dashboard → Import Pack → select the .zip file

**From REST API**:
```bash
curl -X POST http://localhost:9712/api/projects/import \
  -F "file=@my_project.rka-pack_v2.zip"
```

After import, RKA automatically runs an integrity check and reports any issues (orphaned edges, missing references, count mismatches).

### Before Upgrades

Before upgrading RKA to a new version:
1. Export all projects as knowledge packs
2. Run `rka_check_integrity()` to verify current state
3. Upgrade and rebuild Docker
4. Verify the migration ran cleanly
5. Run `rka_check_integrity()` again

---

## Tips and Best Practices

### For the PI

1. **Be specific when giving direction** — The Brain will create a Confirmation Brief to verify understanding. Correct any misalignment immediately — it's much cheaper to fix now than after implementation.

2. **Let the Brain handle recording** — Don't worry about which tool to use. Just tell the Brain what you're thinking. It handles the attribution (`source: "pi"`, `verbatim_input: "your exact words"`).

3. **Review the Research Map regularly** — Open http://localhost:9712/research-map or ask the Brain: "Show me the research map." It tells you at a glance which questions have strong evidence and which have gaps.

4. **Use the web dashboard for browsing** — It's faster than asking Claude for routine lookups. The Research Map page lets you click into clusters, see all claims, and even edit confidence and synthesis directly.

5. **Keep sessions focused** — Start each Brain session with context about what you want to accomplish. The Brain loads prior state automatically, but knowing your goal for *this session* helps it prioritize.

### For Working With the Brain

1. **Trust the session start protocol** — The Brain checks for changes, processes maintenance, and loads the research map before greeting you. This takes a few seconds but ensures it has full context.

2. **Give compound instructions naturally** — If you say "fix the search, update the docs, and check the import," the Brain should parse this into separate missions for the Executor rather than bundling everything together.

3. **Review gate evaluations** — When the Brain evaluates gates, it records assumption status. If assumptions are invalidated, staleness propagates automatically. Check these evaluations to stay informed.

### For Working With the Executor

1. **Let it backbrief** — When the Executor presents its plan, read it. Catching misalignment here saves hours.

2. **Don't skip missions** — Even for small tasks, creating a mission ensures the work is recorded with proper provenance (who asked for it, why, what was found).

3. **Check reports** — When the Executor submits a report, review it in Claude Desktop. The Brain can verify findings against the knowledge base.

---

## Troubleshooting

### "RKA tools not showing up in Claude Desktop"

1. Check the MCP config file path and JSON syntax
2. Restart Claude Desktop completely (Cmd+Q, reopen)
3. Verify the binary works: `~/.local/bin/rka mcp` (should hang waiting for stdin)
4. Check Docker is running: `docker compose ps`

### "Tools return errors about connection refused"

The MCP binary proxies to `http://localhost:9712`. Make sure:
- Docker container is running and healthy
- Port 9712 is not blocked by firewall
- No other service is using port 9712

### "After code changes, tools behave the same as before"

The MCP binary caches aggressively. After any code changes:

```bash
uv tool uninstall rka
rm -rf /tmp/uv-cache
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall .
docker compose up -d --build
```

Then restart Claude Desktop and reload the VS Code window.

### "Knowledge pack export fails"

Run `rka_check_integrity()` to check for issues. Common causes:
- Tables missing from the registry (shows as explicit error naming the table)
- Orphaned edges (the integrity check reports these)

### "Claims show 0 in the research map"

This was a bug in v2.0 — the claim count query used the wrong column. Upgrade to v2.1 and rebuild Docker. The migration automatically recomputes counts.

---

## Quick Reference Card

### Brain (Claude Desktop) — Key Commands

| You say... | Brain does... |
|------------|--------------|
| "Start a new research project about X" | Creates project, research protocol, initial RQs |
| "I found a paper by..." | Records literature, processes annotations, extracts claims |
| "We should focus on X" | Confirmation Brief → records directive with `verbatim_input` |
| "Create a mission for the Executor to..." | Creates mission with structured handoff |
| "Review the Executor's report" | Reads report, checks findings, marks mission complete |
| "Show me the research map" | Displays RQs → clusters → claims hierarchy |
| "What changed since yesterday?" | Runs `rka_get_changelog(since="yesterday")` |
| "Give me a progress report on RQ1" | Assembles evidence as structured markdown |
| "Check for stale evidence" | Runs freshness scan, flags outdated claims |

### Executor (Claude Code) — Key Commands

| You say... | Executor does... |
|------------|-----------------|
| "Pick up your mission" | Loads mission, reads context, presents Backbrief |
| "Check RKA status" | Shows project state, active missions, open checkpoints |
| "Submit your report" | Submits findings, anomalies, and recommendations |
| "Raise a checkpoint" | Creates blocking checkpoint for Brain/PI input |

### Web Dashboard — Key URLs

| URL | Page |
|-----|------|
| http://localhost:9712 | Dashboard (overview + export/import) |
| http://localhost:9712/research-map | Research Map (RQs → clusters → claims) |
| http://localhost:9712/journal | Journal entries timeline |
| http://localhost:9712/decisions | Decision tree visualization |
| http://localhost:9712/missions | Missions with task progress |
| http://localhost:9712/docs | API documentation (Swagger UI) |
