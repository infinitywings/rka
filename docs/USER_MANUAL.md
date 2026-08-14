# RKA User Manual (v2.3.2)

**Design Philosophy · Concepts · Workflows · Reference**

UNC Charlotte — CS / IoT / CPS Security Research

> For the recommended cross-platform install path (Docker + Claude Code plugin + automated Claude Desktop setup), see [`INSTALL.md`](../INSTALL.md). This manual focuses on concepts and reference; install is covered in Chapter 5 below as a brief overview.

---

## Table of Contents

**Part I — Philosophy & Concepts**
1. [Why RKA Exists](#chapter-1-why-rka-exists)
2. [Design Philosophy](#chapter-2-design-philosophy)
3. [The Three Actors](#chapter-3-the-three-actors)
4. [Core Terminology](#chapter-4-core-terminology)

**Part II — Getting Started**
5. [Installation & Setup](#chapter-5-installation--setup)
6. [Your First Project](#chapter-6-your-first-project)
7. [The Session Protocol](#chapter-7-the-session-protocol)

**Part III — The Knowledge Model**
8. [Entity Types in Detail](#chapter-8-entity-types-in-detail)
9. [The Provenance Chain](#chapter-9-the-provenance-chain)
10. [The Research Map](#chapter-10-the-research-map)
11. [The Knowledge Graph](#chapter-11-the-knowledge-graph)

**Part IV — Workflows**
12. [Starting a New Research Project](#chapter-12-starting-a-new-research-project)
13. [The Mission Lifecycle](#chapter-13-the-mission-lifecycle)
14. [Literature Management](#chapter-14-literature-management)
15. [Brain Maintenance & Enrichment](#chapter-15-brain-maintenance--enrichment)

**Part V — Reference**
16. [MCP Tools Quick Reference](#chapter-16-mcp-tools-quick-reference)
17. [Web Dashboard Guide](#chapter-17-web-dashboard-guide)
18. [Configuration](#chapter-18-configuration)
19. [Troubleshooting](#chapter-19-troubleshooting)

---

# Part I — Philosophy & Concepts

## Chapter 1: Why RKA Exists

Modern research increasingly involves iterative collaboration between humans and AI systems. But most AI interfaces are session-bound. Research questions, working hypotheses, literature interpretations, negative results, methodological choices, and the reasoning behind key decisions all disappear between sessions.

At the same time, research artifacts accumulate across papers, notes, code, datasets, experiment outputs, and meeting records without a unified structure for retrieval, provenance, or longitudinal reasoning.

RKA addresses this by acting as a persistent knowledge layer for the research lifecycle. It stores findings with explicit confidence states from hypothesis through verification, records decisions together with alternatives and rationale, links literature to the questions and claims it informed, and maintains an event-sourced audit trail that preserves how a project evolved across weeks or months.

> **The Core Problem:** A session in month six should be able to access the accumulated context of month one: what was tried, what failed, what evidence supported a decision, what was abandoned and why, and which questions remain unresolved.

Without RKA, this context lives in the researcher's head, scattered across chat logs, or in informal notes that are never connected to the decisions they informed. With RKA, the full reasoning chain is explicit, searchable, and traceable.

---

## Chapter 2: Design Philosophy

### 2.1 — Bookkeeper, Not Thinker

RKA's governing principle is that it is a bookkeeper and message transmitter, not a thinker. RKA stores, retrieves, links, and surfaces knowledge. It does not make research decisions, interpret findings, or generate hypotheses. That intelligence belongs to the Brain (Claude) and the PI (you).

This means RKA has no local LLM requirement. Since v2.0, all intelligent enrichment — tagging, claim extraction, cluster synthesis, contradiction resolution — is performed by the Brain during sessions, not by a background process. RKA only runs fast, reliable, non-LLM operations automatically: full-text search indexing and embedding generation.

> **Why No Local LLM?** Earlier versions required a local LLM (e.g., qwen3.5 via LM Studio) for background enrichment. This caused two problems: (1) onboarding friction — users needed LM Studio + sufficient VRAM, and (2) silent accuracy degradation — a weak model produced confidently wrong claim types, garbage cluster syntheses, and misleading research maps. An un-processed entry is honest; a wrongly-processed entry is dangerous.

### 2.2 — Immutable Data, Mutable Interpretation

Raw data (journal entries, literature, mission reports) is immutable once created. You can supersede an entry but never delete the original. The interpretation layer (claims, clusters, research themes) is always reconstructable from the raw data.

When a framing decision is overturned, RKA doesn't change the raw entries — it re-distills the derived structures (claims, clusters) under the new framing. The audit trail preserves both the old and new interpretations.

### 2.3 — Provenance Is Non-Negotiable

Every entity in RKA must know why it exists. Decisions must link to the evidence that justified them. Missions must link to the decision that motivated them. Journal entries must link to the decisions they bear on. Literature must link to the decisions it informed.

This is enforced through the Brain's instructions, not through code validation. The Brain is told to always provide provenance links when creating entities, and the maintenance manifest detects orphaned entities so the Brain can repair them.

### 2.4 — The Brain Handles Intelligence

With the local LLM removed, all knowledge enrichment happens when the Brain is present:

- Tagging and linking entries it creates (inline, at creation time)
- Processing un-enriched entries from Executor/web UI at session start
- Extracting claims from journal entries
- Synthesizing evidence clusters and resolving contradictions
- Gap analysis and evidence evaluation
- Assigning clusters to research questions

The Brain reads a maintenance manifest at the start of each session and silently processes pending items before greeting the user. This keeps the knowledge base healthy without requiring any user action.

---

## Chapter 3: The Three Actors

### 3.1 — Brain (Claude Desktop)

The Brain is the strategic layer. It interprets findings, decides research direction, manages literature, reviews evidence clusters, resolves contradictions, and creates missions for the Executor. The Brain communicates with RKA through MCP tools.

The Brain does NOT implement code, run experiments, or edit files directly. It delegates implementation work to the Executor via missions.

### 3.2 — Executor (Claude Code)

The Executor is the implementation layer. It runs experiments, writes code, collects data, and processes files. It receives missions from the Brain, executes the tasks, submits reports, and raises checkpoints when it needs Brain/PI input.

The Executor should read the mission's context links (motivated_by_decision, related journal entries, related literature) before starting work, so it understands not just what to do but why.

### 3.3 — PI (Human Researcher)

The PI (Principal Investigator) supervises both the Brain and Executor. The PI resolves escalated checkpoints, provides domain expertise, sets the overall research direction, and has final authority on all decisions.

The PI can interact with RKA through the web dashboard (browsing, Q&A, project management), through the REST API, or by asking the Brain to perform actions.

### 3.4 — How They Collaborate

| Actor | Creates | Reads | Responsibility |
|-------|---------|-------|----------------|
| **Brain** | Decisions, notes, literature, missions, claims, cluster syntheses | Context packages, research map, review queue, maintenance manifest | Strategy, synthesis, enrichment |
| **Executor** | Log entries, reports, checkpoints | Missions, context for assigned work | Implementation, experiments, data |
| **PI** | Directives, checkpoint resolutions | Dashboard, audit log, research map | Oversight, domain expertise, direction |

---

## Chapter 4: Core Terminology

### 4.1 — Entities

RKA stores research knowledge in seven entity types. Each has a type-prefixed ULID identifier (globally unique, sortable by creation time).

| Entity | ID Prefix | What It Stores |
|--------|-----------|----------------|
| **Journal Entry** | `jrn_` | Findings, observations, ideas, procedures, instructions. The raw data layer. |
| **Decision** | `dec_` | Research choices with options, rationale, and outcome. Forms a tree structure. |
| **Literature** | `lit_` | Papers, articles, books. Tracked through a reading pipeline. |
| **Mission** | `mis_` | Task packages assigned to the Executor with objectives and acceptance criteria. |
| **Checkpoint** | `chk_` | Escalation points where the Executor needs Brain/PI input. |
| **Interpretation Candidate** | `icd_` | Reviewable, source-located interpretation that is not yet canonical knowledge. |
| **Claim** | `clm_` | Atomic, source-grounded statement explicitly promoted from a reviewed candidate or intentionally recorded through the canonical claim API. |
| **Claim Scope Version** | `csc_` | Immutable research-level applicability boundary for a canonical claim, including typed conditions, uncertainty, extension limits, and falsifier/disconfirmation information. |
| **Evidence Cluster** | `ecl_` | Groups of related claims with a Brain-written synthesis. |

### 4.2 — Journal Entry Types

| Type | When to Use | Example |
|------|-------------|---------|
| `note` | You observed, analyzed, or discovered something | Experiment result, insight, literature observation |
| `log` | You performed a procedure step | Ran stress test, deployed config, executed script |
| `directive` | Instructions from PI or Brain | PI instruction, Brain guidance, scope clarification |

### 4.3 — Claim Types

Candidate extraction does not create a claim. It creates an `icd_` record with
an exact source locator, epistemic kind, scope conditions, uncertainty, and an
optional falsifier. A Brain or PI review must explicitly promote it before it
becomes a canonical `clm_` record. Rejection, deferral, merging, classification,
and promotion revocation preserve append-only history.

Each promoted claim has a type that describes what kind of knowledge it represents:

| Claim Type | What It Means | Example |
|------------|---------------|---------|
| `hypothesis` | A proposed explanation or prediction | "The broker needs horizontal scaling" |
| `evidence` | A factual observation from data | "12% packet loss above 400 connections" |
| `method` | A procedure or technique used | "Tested MQTT with 500 concurrent devices" |
| `result` | An experiment outcome | "Throughput improved 3x after sharding" |
| `observation` | Something noticed (not from controlled experiment) | "The LLM includes its prompt in the synthesis" |
| `assumption` | Something taken as given without proof | "Network latency is negligible at this scale" |

### 4.3.1 — Canonical Claim Scope

Candidate scope (`icd_`) describes what a source-located interpretation appears
to mean. Canonical scope (`csc_`) governs where a promoted `clm_` may be reused
as research knowledge. Manuscript wording (`mcl_`) is a third, paper-specific
boundary. They are intentionally separate.

Open **Claim Scope Review** at `/claim-scopes` to inspect missing, stale,
incomplete, unreviewed, and ready contracts. A reviewed contract requires at
least one typed applicability condition, resolved uncertainty, an exact or
bounded extension policy, prohibited extensions, and resolved falsifier
applicability. Every edit appends an immutable revision using optimistic
revision control. Editing claim wording later makes the older contract stale
until it is reviewed again.

MCP equivalents:

```text
rka_query(args={"operation": "claim_scope", "project_id": "prj_...", "id": "clm_..."})
rka_execute(args={"operation": "set_claim_scope", "project_id": "prj_...", ...})
```

`scope_readiness=ready` does not mean that a claim is scientifically supported
or uncontested. Check grounding, `evidence_status`, contradictions, and
staleness independently.

### 4.4 — Confidence Levels

| Level | Meaning | When to Use |
|-------|---------|-------------|
| `hypothesis` | Proposed but untested | Initial ideas, early observations |
| `tested` | Tried but not independently verified | Experiment results, first analysis |
| `verified` | Confirmed by multiple sources or methods | Replicated results, cross-validated |
| `superseded` | Replaced by newer information | Outdated findings after new evidence |
| `retracted` | Withdrawn as incorrect | Disproven hypotheses |

### 4.5 — Cluster Confidence Badges

Evidence clusters have confidence badges that indicate how solid the evidence is:

| Badge | Meaning |
|-------|---------|
| 🟢 **strong** | Multiple verified claims that agree — this topic is well-understood |
| 🟡 **moderate** | Some evidence but not fully verified — more work needed |
| 🔵 **emerging** | Very little evidence — only 1–2 claims, early stage |
| 🟠 **contested** | Claims disagree with each other — active contradiction |
| 🔴 **refuted** | Evidence contradicts the original claim |

### 4.6 — Link Types (Provenance)

Entities are connected by typed links that form provenance chains:

| Link Type | Direction | Meaning |
|-----------|-----------|---------|
| `justified_by` | decision ← journal | This journal entry justified this decision |
| `informed_by` | decision ← literature | This paper informed this decision |
| `motivated` | decision → mission | This decision motivated creating this mission |
| `produced` | mission → journal | This mission produced this journal entry |
| `derived_from` | claim ← journal | This claim was extracted from this entry |
| `derived_from` | candidate ← source | This candidate interprets the located journal, literature, or artifact record |
| `derived_from` | claim ← candidate | This claim was explicitly promoted from this reviewed candidate |
| `cites` | journal → literature | This entry cites this paper |
| `references` | any → any | General reference link |
| `supports` | claim → claim | This claim supports that claim |
| `contradicts` | claim → claim | This claim contradicts that claim |
| `supersedes` | entity → entity | This entity replaces an older one |
| `resolved_as` | checkpoint → decision | This checkpoint was resolved as this decision |
| `builds_on` | any → any | This entity builds on prior work |

---

# Part II — Getting Started

## Chapter 5: Installation & Setup

### 5.1 — Docker (Recommended)

Docker is the simplest way to run RKA. It requires no Python environment, no Node.js, and no local LLM.

**Prerequisites:** Docker Desktop ([docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/))

```bash
git clone https://github.com/infinitywings/rka.git
cd rka
docker compose up -d
```

Open `http://localhost:9712` in your browser. That's it.

### 5.2 — Install the MCP binary

Both Claude Desktop and Claude Code reach RKA through the same `rka` stdio binary. Install it once outside Docker:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

The binary lands at `~/.local/bin/rka`. Verify with `~/.local/bin/rka --version`.

### 5.3 — Register the MCP server in Claude Desktop and Claude Code

The same JSON config shape works for both clients. Replace `<your-username>` with your actual macOS username (the path must be absolute). Project scope is not stored in this process configuration: every project-scoped operation requires an explicit `project_id`.

**Claude Desktop** — edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Save and **fully quit Claude Desktop** (Cmd+Q on macOS) then reopen. RKA tools will be available in any new conversation.

**Claude Code** — same JSON shape, in `.claude/mcp.json` (per-project) or `~/.claude/settings.json` under the same `mcpServers` key (user-level), or via the VS Code extension's **MCP Servers** UI.

To find your project id: run `rka_query(args={"operation": "list_projects"})` in any Claude session, or open `http://localhost:9712` and read the id from the URL when you switch projects.

> **After Code Changes:** Always run `UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall .` (update MCP binary) then `docker compose up -d --build` (update server). Plain `uv tool install --force .` uses cached wheels and may NOT pick up changes.

### 5.4 — Using RKA from ChatGPT (Custom Connector)

RKA can also be reached from ChatGPT as a custom MCP connector. The path: start the MCP server in HTTP mode on `127.0.0.1:9713` with `RKA_SKILL_TOOLS=1` (which exposes the 8-tool skill surface), front it with the OAuth reverse proxy (`scripts/rka_mcp_oauth_proxy.py`) on `127.0.0.1:9720`, expose that over HTTPS with an ngrok tunnel, then register the tunnel URL as the ChatGPT connector **Server URL** (`https://<ngrok-host>/mcp`) and authenticate over OAuth. Only the MCP server is exposed — the web UI stays private and is never tunneled, and your OAuth passphrase and API keys stay on your machine. See [`CHATGPT_CONNECTOR.md`](CHATGPT_CONNECTOR.md) for the full step-by-step setup.

---

## Chapter 6: Your First Project

### 6.1 — Creating a Project

RKA supports multiple isolated projects. When you first start RKA, a default project exists. To create a new one:

- **Via web dashboard:** Click the **+** button next to the project selector in the sidebar.
- **Via MCP:** Brain calls `rka_execute(args={"operation": "create_project", "name": "IoT Security Analysis", "description": "Systematic review of CPS vulnerabilities"})`

### 6.2 — Switching Projects

- **Via web dashboard:** Use the project dropdown in the sidebar.
- **Via MCP:** Brain calls `rka_query(args={"operation": "list_projects"})` then pins the chosen `project_id` for the rest of the conversation. (Pre-v2.6 `rka_set_project` is a deprecated no-op; `project_id` is now passed as a required field on every operation.)

### 6.3 — Project Lifecycle

| Action | How |
|--------|-----|
| Create | Web UI **+** button or `rka_execute(args={"operation": "create_project", ...})` |
| Switch | Web UI dropdown or pin `project_id` at conversation start and thread it on every operation |
| Export | `GET /api/projects/export` — downloads a `.rka-pack.zip` |
| Import | `POST /api/projects/import` — uploads a pack into a new project |
| Delete | Web UI trash icon with confirmation dialog (recommends export first) |

---

## Chapter 7: The Session Protocol

> **Dispatch shape (v2.7.0+).** The calls below are shown as dispatch operations: reads go through `rka_query(operation="…")` and writes through `rka_execute(operation="…")`, with `project_id` threaded on every call. See the Chapter 16 banner for the full legacy-name → operation mapping and the `rka_describe` lookup.

### 7.1 — Brain Session Start

Every Brain session should begin with these steps. The `RKA_INSTRUCTIONS` tell the Brain to do this automatically:

| Step | Tool Call | Purpose |
|------|-----------|---------|
| 1 | `rka_query(operation="status")` | Load project phase, summary, metrics |
| 2 | `rka_query(operation="context", query="current work")` | Load recent knowledge relevant to the current focus |
| 3 | `rka_query(operation="pending_maintenance")` | Check for provenance gaps, untagged entries, orphaned clusters |
| 4 | *(silent processing)* | Tag entries, add links, extract claims — up to 10 items |
| 5 | Greet the user | Begin the actual conversation |

> **Silent Maintenance:** The Brain handles housekeeping as a brief preamble to every session, like a good assistant tidying the desk before starting work. The user sees their knowledge base gradually improving without doing anything.

### 7.2 — Executor Session Start

| Step | Tool Call | Purpose |
|------|-----------|---------|
| 1 | `rka_query(operation="mission")` | Load the current assigned mission with tasks |
| 2 | Read mission context links | Use `rka_query(operation="entity", id=…)` on `motivated_by_decision`, related journal/literature |
| 3 | `rka_query(operation="context", query="<mission topic>")` | Load relevant prior knowledge |

### 7.3 — Recording Standards

When creating entities, always provide provenance links:

| Situation | Operation | Required Links |
|-----------|-----------|----------------|
| Making a decision | `rka_execute(operation="record_decision")` | `related_journal` (what evidence?), `related_literature` (what papers?) |
| Creating a mission | `rka_execute(operation="create_mission")` | `motivated_by_decision` (which decision spawned this?) |
| Recording a finding | `rka_execute(operation="record_note")` | `related_decisions`, `related_mission`, `related_literature` (nested under `provenance={…}`) |
| Finishing a mission | `rka_execute(operation="submit_report")` | `related_decisions` (which decisions do the results bear on?) |

---

# Part III — The Knowledge Model

## Chapter 8: Entity Types in Detail

### 8.1 — Journal Entries

Journal entries are the raw data layer. Every observation, experiment result, meeting note, idea, and procedure step gets recorded as a journal entry. Entries are immutable once created (you can supersede them but not delete them).

**Fields:** content (text), type (note/log/directive), source (brain/executor/pi), confidence, importance, phase, tags, related_decisions, related_literature, related_mission.

### 8.2 — Decisions

Decisions record every non-trivial choice in the research process. Each decision has a question, a set of options considered, the chosen option, and the rationale. Decisions form a tree structure (parent/child relationships).

**Special kind: Research Questions.** A decision with `kind="research_question"` becomes a top-level node in the Research Map. Research questions organize the entire knowledge structure.

**Decision statuses:** `active` (current), `abandoned` (discarded with reason), `superseded` (replaced by a newer decision), `revisit` (flagged for reconsideration).

### 8.3 — Literature

Literature entries track papers, articles, and books through a reading pipeline:

**Pipeline:** `to_read` → `reading` → `read` → `cited` → `excluded`

Literature can be imported via BibTeX, DOI lookup (CrossRef), Semantic Scholar search, or arXiv search. Each entry stores title, authors, year, venue, DOI, abstract, key findings, methodology notes, relevance assessment, and related decisions.

### 8.4 — Missions

Missions are task packages assigned by the Brain to the Executor. Each mission has an objective, a task list, context, acceptance criteria, scope boundaries, and checkpoint triggers.

**Lifecycle:** `pending` → `active` → `complete` / `partial` / `blocked` / `cancelled`

**Key provenance link:** `motivated_by_decision` — every mission should link to the decision that triggered it, so the Executor knows why the work exists.

### 8.5 — Checkpoints

Checkpoints are escalation points where the Executor needs Brain or PI input:

| Type | When to Use | Who Resolves |
|------|-------------|--------------|
| `clarification` | Executor needs more information | Brain (often auto-resolved) |
| `decision` | A non-trivial choice needs to be made | Brain (may need PI input) |
| `inspection` | Work needs human review | PI directly |

---

## Chapter 9: The Provenance Chain

The provenance chain is RKA's most important feature. It answers the question: **"Why does this entity exist?"**

A complete provenance chain looks like this:

> **Literature** (MQTT benchmarks) → *informed* → **Decision** (test broker limits) → *motivated* → **Mission** (stress test at scale) → *produced* → **Finding** (12% packet loss) → *derived* → **Claim** (threshold at 400) → *justified* → **Decision** (implement sharding)

You can traverse this chain in either direction using `rka_query(operation="provenance", id=<entity_id>, filters={"direction": "backward"})` (upstream, toward what produced the entity) or `filters={"direction": "forward"}` (downstream).

> **Why Provenance Matters:** Without provenance links, the knowledge graph is disconnected islands — decisions in one column, literature in another, findings in a third. With provenance, you can ask "why did we decide to use sharding?" and get a chain: because the stress test showed 12% packet loss, which was motivated by the decision to test broker limits, which was informed by the MQTT benchmarks paper.

### 9.1 — The Maintenance Manifest

The maintenance manifest (`rka_query(operation="pending_maintenance")`) is a pure-SQL tool that detects provenance gaps:

- **Decisions without justified_by links** — no evidence trail
- **Missions without motivated_by_decision** — no triggering decision
- **Journal entries without related_decisions** — orphaned from the decision tree
- **Journal entries without tags** — not categorized
- **Entries without claims extracted** — not distilled into structured knowledge
- **Unassigned evidence clusters** — not linked to any research question
- **Pending contradiction flags** — claims that may conflict

The Brain processes these items at session start, silently fixing up to 10 gaps per session.

---

## Chapter 10: The Research Map

The Research Map is a three-level hierarchy for navigating your knowledge:

### Level 1: Research Questions

The big questions driving your project. Each RQ is a decision with `kind="research_question"`. RQs organize everything below them.

**Example:** *"How should RKA track provenance and decision reasoning chains across the research lifecycle?"*

### Level 2: Topic Clusters (Evidence Clusters)

Groups of related claims under each research question. Each cluster has a Brain-written synthesis paragraph summarizing what the claims collectively say. Clusters have confidence badges (strong/moderate/emerging/contested) indicating evidence quality.

**Example:** *"rka_decision_provenance_and_hierarchy" — covering provenance architecture, gap analysis, and W3C PROV mapping.*

### Level 3: Claims

Atomic, canonical statements promoted after source-grounding review. Each claim has a type (hypothesis/evidence/method/result/observation/assumption) and links through its candidate to the exact source record; journal-backed claims also retain their direct source offsets.

**Example:** *"12% packet loss above 400 connections" — an evidence claim extracted from jrn_01KK..., characters 54–139.*

### Evidence Gaps

Evidence gaps are areas where a research question has insufficient evidence. A gap means a cluster or RQ has too few claims to fully answer the question. Gaps are not necessarily problems — they signal where more investigation could strengthen the research.

> **Reading the Research Map:** Start at the top (Research Questions) to see the big picture. Click into an RQ to see its topic clusters. Click into a cluster to see individual claims. Each level provides more detail. If a cluster says "emerging" with 1 claim, that topic is thin. If it says "strong" with 30 claims, that topic is well-covered.

---

## Chapter 11: The Knowledge Graph

The Knowledge Graph page shows all entities and their relationships as a visual network. Nodes are colored by type:

| Color | Entity Type |
|-------|-------------|
| Blue | Decisions |
| Green | Journal entries / Findings |
| Indigo | Literature |
| Pink | Missions |
| Amber | Claims |
| Purple | Evidence Clusters |

Edges between nodes represent typed links (justified_by, motivated, produced, etc.). The density of cross-type edges indicates how well-connected your knowledge base is. A healthy graph has many edges between different node types. Disconnected columns of same-type nodes indicate missing provenance links.

The Knowledge Graph is a low-level debugging view. For structured navigation, use the Research Map instead.

---

# Part IV — Workflows

## Chapter 12: Starting a New Research Project

### Step 1: Create the Project

Use the web dashboard or have the Brain call `rka_execute(args={"operation": "create_project", ...})`. Give it a descriptive name and description.

### Step 2: Frame Your Research Questions

The Brain creates research questions as decisions with `kind="research_question"`. These become the top-level nodes in the Research Map and organize everything below.

**Example:** `rka_execute(args={"operation": "record_decision", "project_id": "prj_01...", "question": "Does protocol-specific feature engineering improve IDS detection?", "chosen": "Yes — test protocol-specific features", "rationale": "Prior IoT-IDS work suggests protocol fields carry discriminative signal worth evaluating.", "kind": "research_question", "phase": "exploration", "decided_by": "brain", "related_journal": ["jrn_01..."]})` — `record_decision` requires `question`, `chosen`, `rationale`, `decided_by`, `kind`, `phase`, and a non-empty `related_journal`; the typed-arg surface rejects the call before it leaves the client if any are missing.

### Step 3: Add Initial Literature

Import papers via BibTeX, DOI, Semantic Scholar, or arXiv search. Always link literature to the research questions it informs.

### Step 4: Record Initial Ideas and Observations

Use `rka_execute(operation="record_note")` for early observations, meeting notes, and hypotheses. Link them to relevant decisions (via `provenance={…}`).

### Step 5: Start the Mission Cycle

Once the Brain has enough context, it creates missions for the Executor. Each mission links to the decision that motivated it and includes context references.

---

## Chapter 13: The Mission Lifecycle

The mission lifecycle is the primary coordination mechanism between Brain and Executor:

| Phase | Who | What Happens |
|-------|-----|-------------|
| **Create** | Brain | Creates mission with objective, tasks, context, acceptance criteria, `motivated_by_decision` |
| **Accept** | Executor | Reads mission, loads context links, starts work |
| **Execute** | Executor | Works through tasks, records findings as journal entries with `related_mission` |
| **Checkpoint** | Executor | Raises a checkpoint if blocked; Brain/PI resolves it |
| **Report** | Executor | Submits structured report with findings, anomalies, recommended next steps |
| **Review** | Brain | Reviews report, updates project state, creates follow-up missions if needed |
| **Complete** | Brain | Marks mission complete or partial |

> **Context-Rich Missions:** When creating a mission, the Brain should include: `motivated_by_decision` (which decision?), related journal entries (prior findings), related literature (papers to read), and related decisions (constraints to respect). This way the Executor understands not just WHAT to do but WHY.

---

## Chapter 14: Literature Management

### 14.1 — Adding Papers

| Method | Operation | Best For |
|--------|-----------|----------|
| Manual | `rka_execute(operation="record_literature")` (title, authors, year, …) | Adding a known paper with metadata |
| DOI Lookup | `rka_execute(operation="enrich_doi")` (lit_id) | Filling in missing metadata from CrossRef |
| BibTeX Import | `rka_execute(operation="import_bibtex")` (bibtex) | Bulk import from a .bib file |
| Semantic Scholar | `rka_search_semantic_scholar` — deferred legacy tool; load via `rka_load_tools(names=[…])` | Searching for relevant papers |
| arXiv Search | `rka_search_arxiv` — deferred legacy tool; load via `rka_load_tools(names=[…])` | Finding preprints |

### 14.2 — Reading Pipeline

Track your reading progress through the pipeline: `to_read` → `reading` → `read` → `cited` → `excluded`. Use the Literature page in the dashboard to see papers at each stage.

---

## Chapter 15: Brain Maintenance & Enrichment

With the local LLM removed, the Brain is the sole intelligence layer. Maintenance happens at session start.

### 15.1 — What the Maintenance Manifest Detects

- **Entries without tags** — Brain reads the entry and adds appropriate tags
- **Entries without claims** — Brain reads the entry and extracts claims
- **Decisions without justified_by** — Brain identifies which evidence justified the decision and adds links
- **Missions without motivated_by** — Brain identifies which decision triggered the mission
- **Entries without cross-references** — Brain links orphaned entries to relevant decisions
- **Unassigned clusters** — Brain assigns clusters to research questions
- **Pending contradictions** — Brain evaluates whether claims truly conflict and resolves

### 15.2 — How Maintenance Works

The Brain processes up to 10 maintenance items per session, prioritized by importance: decisions without provenance > missions without context > unassigned clusters > missing cross-references. The Brain handles this silently — the user sees their knowledge base improving without taking any action.

> **You Don't Need to Ask:** The Brain follows its session protocol automatically. You don't need to say "go maintain the knowledge base." Just start a conversation, and the Brain will tidy up before responding.

---

# Part V — Reference

## Chapter 16: MCP Tools Quick Reference

> **v2.7.0+ dispatch surface.** RKA broadcasts exactly 5 always-on tools: 3 dispatch tools (`rka_query`, `rka_execute`, `rka_describe`) plus 2 escape hatches (`rka_load_tools`, `rka_help`). The tables below list the **operation names** — the values you pass as `operation`: 53 read operations go through `rka_query(args={"operation": ...})` and 62 write/lifecycle operations through `rka_execute(args={"operation": ...})`. There are 115 typed operations total. The pre-v2.7 per-tool names (`rka_add_note`, `rka_get_status`, `rka_trace_provenance`, …) are `tier=deferred` legacy synonyms: they resolve to these operations (typically drop the `rka_`/`get_`/`add_` prefix, e.g. `rka_get_status` → `status`, `rka_add_note` → `record_note`, `rka_trace_provenance` → `provenance`), but on the default surface you call the operation through the dispatch tools rather than the legacy name. The discipline (`source="pi"` + `verbatim_input`, `related_journal=[...]` on decisions, `motivated_by_decision=...` on missions, `project_id` on every call) is unchanged. See `rka_describe(operation="<name>")` for per-operation signatures, or `rka_describe(operation="")` for the full 115-operation index. `rka_set_project` was removed in v2.6 (deprecated no-op) — pin `project_id` at conversation start and thread it on every operation. The LLM-backed `rka_ask` / `rka_generate_summary` features were removed in v2.4.0 and are no longer part of the surface.

### Knowledge Management (`rka_execute`)

| Operation | Purpose |
|-----------|---------|
| `record_note` | Add a journal entry (note/log/directive) |
| `update_note` | Update an existing entry |
| `record_decision` | Add a decision to the tree |
| `update_decision` | Update a decision (status, rationale, links) |
| `record_literature` | Add a paper/article |
| `update_literature` | Update literature metadata |
| `bulk_update` | Batch update multiple entities |

### Mission Lifecycle

| Operation | Dispatch tool | Purpose |
|-----------|---------------|---------|
| `create_mission` | `rka_execute` | Create a mission for the Executor |
| `mission` | `rka_query` | Get current or specific mission |
| `update_mission_status` | `rka_execute` | Update mission status and tasks |
| `submit_report` | `rka_execute` | Submit execution report |
| `submit_checkpoint` | `rka_execute` | Escalate a decision/question |
| `resolve_checkpoint` | `rka_execute` | Resolve a checkpoint |

### Search & Context (`rka_query`)

| Operation | Purpose |
|-----------|---------|
| `search` | Hybrid search across all entities |
| `entity` | Get full content of any entity by ID |
| `context` | Generate a focused context package |
| `multi_hop` | Multi-hop retrieval for questions spanning several entities |
| `pending_maintenance` | Detect provenance gaps and maintenance items |

### Research Map & Review

| Operation | Dispatch tool | Purpose |
|-----------|---------------|---------|
| `research_map` | `rka_query` | Three-level view: RQs → clusters → claims |
| `claims` | `rka_query` | Query extracted claims with filters |
| `review_cluster` | `rka_execute` | Brain reviews and synthesizes a cluster |
| `resolve_contradiction` | `rka_execute` | Brain resolves conflicting claims |
| `provenance` | `rka_query` | Trace the reasoning chain behind any entity |
| `decision_tree` | `rka_query` | Get the full decision tree |
| `graph_stats` | `rka_query` | Knowledge graph statistics |

### Project & Session

| Operation | Dispatch tool | Purpose |
|-----------|---------------|---------|
| `list_projects` | `rka_query` | List all projects |
| *(project switching)* | — | `rka_set_project` was removed in v2.6 (deprecated no-op) — pin `project_id` per call instead |
| `create_project` | `rka_execute` | Create a new project |
| `status` | `rka_query` | Get project state |
| `update_status` | `rka_execute` | Update project state |
| `session_digest` | `rka_execute` | Compact session summary |

---

## Chapter 17: Web Dashboard Guide

The web dashboard at `http://localhost:9712` provides a visual interface for browsing and managing your research knowledge.

| Page | Path | What You See |
|------|------|-------------|
| **Dashboard** | `/` | Project overview, active missions, open checkpoints, recent entries, project management |
| **Journal** | `/journal` | Timeline of entries grouped by date, type/confidence filters |
| **Decisions** | `/decisions` | Interactive decision tree with side panel details |
| **Literature** | `/literature` | Reading pipeline with status tabs (to_read → reading → read → cited) |
| **Missions** | `/missions` | Active missions with task checklists and reports |
| **Timeline** | `/timeline` | Event stream with causal chain visualization |
| **Knowledge Graph** | `/graph` | Entity relationship network (low-level debugging view) |
| **Research Map** | `/research-map` | Three-level drill-down: RQs → clusters → claims |
| **Interpretation Review** | `/interpretations` | Review source-located `icd_` candidates before canonical promotion |
| **Claim Scope Review** | `/claim-scopes` | Append and audit canonical `csc_` applicability contracts; resolve Writer scope blockers |
| **Manuscript Workbench** | `/workbench` | Navigate manuscript stages, scope contracts, evidence lineage, and current readiness |
| **Notebook** | `/notebook` | (historical) Q&A chat and summary generation — the LLM-backed Q&A/summary features were removed in v2.4.0 |
| **Audit Log** | `/audit` | System audit trail with action/entity/actor filters |
| **Context Inspector** | `/context` | Generate and inspect context packages |
| **Research Health** | `/health` | Provenance coverage, research-debt trajectory, mission-cycle stats, bookkeeping overhead; staleness-review + link-support audit actions |
| **Report Context** | `/report-context` | Prose description + angle queries -> report-scoped node collection with per-node inclusion provenance |
| **Settings** | `/settings` | API health, DB stats, embedding backend config, project settings |

### Dashboard Page

The Dashboard is your starting point. It shows the current project name and phase, counts of active missions and open checkpoints, and the most recent journal entries. Use the project dropdown in the sidebar to switch between projects, the **+** button to create new ones, and the trash icon to delete (with safety confirmation).

### Journal Page

The Journal shows all entries in a timeline grouped by date. Use the filters at the top to narrow by entry type (note/log/directive), confidence level, source (brain/executor/pi), and phase. Click any entry to see its full content and provenance links.

### Decisions Page

The Decisions page shows an interactive decision tree powered by React Flow. Nodes are color-coded by status: green for active, orange for unresolved, gray dashed for abandoned. Research questions appear with a distinct RQ badge. Click any node to open a side panel with full details including options, rationale, and linked entities.

### Literature Page

The Literature page shows papers in a table/list view with status tabs for each stage of the reading pipeline. Click a paper to expand its detail panel showing abstract, key findings, methodology notes, and related decisions.

### Research Map Page

The Research Map is the primary navigation tool for understanding your research. See [Chapter 10](#chapter-10-the-research-map) for a full explanation of the three-level hierarchy, confidence badges, and evidence gaps.

**How to read it:**
1. The top bar shows aggregate stats: total RQs, clusters, claims, gaps, and contradictions
2. Below that, each Research Question card shows its cluster count, claim count, and gap count
3. Click an RQ to see its topic clusters as cards with confidence badges
4. Click a cluster to see individual claims with types, confidence scores, and source links

### Settings Page

The Settings page shows API health status, database statistics, embedding backend configuration (**Settings → Embeddings**), and project configuration. Use the quick links to access `/docs` (Swagger API reference) and `/api/health`. (The LLM-backed Q&A/summary configuration was removed in v2.4.0.)

---

## Chapter 18: Configuration

### 18.1 — Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RKA_DB_PATH` | `rka.db` | SQLite database file path |
| `RKA_HOST` | `127.0.0.1` | API server bind address |
| `RKA_PORT` | `9712` | API server port |

### 18.2 — Embedding Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RKA_EMBEDDINGS_ENABLED` | `false` | Enable embedding generation (local, lightweight) |
| `RKA_EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | FastEmbed model (~130MB ONNX, no GPU needed) |

### 18.3 — Context Engine

In v2.4 the context engine has no tunable settings. Ranking is deterministic SQL-time: `journal.importance` (CASE: critical=4 → archived=0) × `entity_links` centrality × `created_at` DESC, with a +0.5 lift for PI-sourced entries. The legacy `RKA_CONTEXT_HOT_DAYS`, `RKA_CONTEXT_WARM_DAYS`, and `RKA_CONTEXT_DEFAULT_MAX_TOKENS` env vars were removed (see `dec_01KQQPD6Y6B362T3K08368BDMP`). For multi-hop questions, use `rka_query(operation="multi_hop")` instead of `rka_query(operation="context")`.

### 18.4 — LLM Settings (Removed in v2.4.0)

> **Historical.** Earlier versions exposed server-side LLM features (`rka_ask`, `rka_generate_summary`, and the web-UI Q&A page) configured through `RKA_LLM_*` environment variables. These features were **removed in v2.4.0** and `/api/capabilities` no longer returns an `llm` field. There is no LLM configuration to set: all intelligent enrichment (tagging, claim extraction, cluster synthesis, contradiction resolution) is now performed by the Brain during sessions. The removed `RKA_LLM_ENABLED` / `RKA_LLM_MODEL` / `RKA_LLM_API_BASE` / `RKA_LLM_API_KEY` variables have no effect on current builds.

---

## Chapter 19: Troubleshooting

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| MCP tool not visible in Claude | Claude caches the tool list on connect; or the legacy tool is `tier=deferred` | Restart Claude Desktop; or use `rka_load_tools(names=[…])` to register deferred legacy tools |
| `provenance` operation returns error | Known bug: empty response parsing | Use `rka_query(operation="entity", id=…)` + manual link traversal as workaround |
| Knowledge graph shows disconnected columns | Missing provenance links between entity types | Brain processes `rka_query(operation="pending_maintenance")` items |
| Research map has many "emerging" clusters | Clusters auto-generated by old LLM pipeline with only 1–2 claims | Brain reviews and merges thin clusters over time |
| Docker container unhealthy | API not responding | Check `docker compose logs -f rka`; rebuild with `--build` |
| MCP binary out of date | Source changed but `uv tool` not reinstalled | Run: `UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall .` |
| A project-scoped MCP call is rejected for missing scope | The call omitted required `project_id` | List projects once, pin the intended id in conversation/workspace metadata, and pass it on every scoped operation |
| Brain doesn't run maintenance at session start | Claude sometimes skips the session protocol | Say "check maintenance first" to prompt it |

### Frequently Asked Questions

**Q: Do I need a local LLM (LM Studio, Ollama)?**
No. RKA v2.0+ removed the local LLM requirement, and v2.4.0 removed the remaining server-side LLM features (`rka_ask`, `rka_generate_summary`, web-UI Q&A) entirely. All intelligent enrichment is now handled by the Brain (Claude) during sessions. The only local models are embeddings (FastEmbed, ~130MB, no GPU needed) for semantic search.

**Q: Do I need to tell the Brain to maintain the knowledge base?**
No. The Brain's MCP instructions include a maintenance protocol that runs automatically at session start. It checks for provenance gaps, untagged entries, and orphaned clusters, then silently processes up to 10 items before greeting you. You only need to ask explicitly after large batch operations (e.g., importing 30 papers).

**Q: What's the difference between the Knowledge Graph and the Research Map?**
The Knowledge Graph (`/graph`) is a low-level debugging view showing all entities and raw links. The Research Map (`/research-map`) is a structured three-level hierarchy (Research Questions → Topic Clusters → Claims) designed for navigation. Use the Research Map for day-to-day work; use the Knowledge Graph when you need to debug link issues.

**Q: Can I use RKA without Claude Desktop?**
Yes. The web dashboard and REST API work independently. You can browse, search, create entries, and manage projects through the web UI at `http://localhost:9712`. However, the Brain (Claude Desktop) is needed for intelligent enrichment, claim extraction, and cluster synthesis.

**Q: How do I export and share a project?**
Use `GET /api/projects/export` or the export button in the dashboard. This creates a `.rka-pack.zip` containing all project data. Import it into another RKA instance with `POST /api/projects/import`. IDs are automatically remapped to avoid conflicts.

Native manuscripts are included with their complete claim-wording history,
typed evidence and unit links, explicit PI ratifications, checkpoints, and
immutable validation attestations. Import never infers or creates a
ratification that was absent from the source pack.

Packs intentionally exclude `change_events`, `jobs`,
`manuscript_migration_issues`, and
`reference_validation_migration_issues`. Change cursors, migration
diagnostics, and worker leases/retries are installation-local; importing the
semantic rows emits a fresh target-local change ledger, and pending external
validation must be requested again. Completed validation attestations are
semantic history and are included. Any attestation-to-worker-job link is
cleared on import because the producing job does not exist on the target
installation.

Legacy `jrn_` manuscript bindings remain supported and are remapped together
with their native `man_` aliases. When an accepted format-v1 or format-v2 pack
predates native manuscripts, import conservatively creates only an unambiguous
native identity and metadata binding. It never synthesizes claims, evidence,
ratifications, units, or checkpoints.

**Q: How do I delete a project?**
Click the trash icon next to the project selector in the sidebar. A confirmation dialog shows you how many entities will be deleted, recommends exporting first, and requires you to type the project name to confirm. The default project (`proj_default`) cannot be deleted.

---

*RKA v2.3.2 — Research Knowledge Agent*
*UNC Charlotte, CS / IoT / CPS Security Research*
*https://github.com/infinitywings/rka*
