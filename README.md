# Research Knowledge Agent (RKA)

An MCP server and REST API for AI-assisted research orchestration. RKA gives AI assistants a persistent, structured knowledge base for managing research decisions, literature, findings, missions, and checkpoints — enabling a collaborative Brain/Executor workflow between a human researcher (PI), a strategic AI (Brain), and an implementation AI (Executor).

Built for CS/IoT/CPS security research at UNC Charlotte.

---

## Table of Contents

- [Architecture](#architecture)
- [Key Concepts](#key-concepts)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [MCP Tools Reference](#mcp-tools-reference)
- [REST API Reference](#rest-api-reference)
- [Web Dashboard](#web-dashboard)
- [Data Model](#data-model)
- [Search and Context Engine](#search-and-context-engine)
- [LLM Integration](#llm-integration)
- [Development](#development)
- [Build Phases](#build-phases)

---

## Architecture

### Brain / Executor Model

RKA implements a three-actor collaboration:

```
┌───────────────┐     ┌──────────────────┐     ┌───────────────────┐
│      PI        │     │   Brain (Claude   │     │ Executor (Claude   │
│  (Researcher)  │◄───►│    Desktop)       │◄───►│    Code)           │
│                │     │  Strategic layer  │     │ Implementation     │
└───────────────┘     └────────┬─────────┘     └────────┬──────────┘
                               │                         │
                               │    MCP tools (stdio)    │
                               └────────┬────────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │         RKA Server         │
                          │  ┌──────────────────────┐  │
                          │  │    Service Layer       │  │
                          │  │  (shared business      │  │
                          │  │   logic for MCP+REST)  │  │
                          │  └──────────┬─────────────┘  │
                          │             │                 │
                          │  ┌──────────▼─────────────┐  │
                          │  │ Infrastructure Layer     │  │
                          │  │ SQLite + sqlite-vec      │  │
                          │  │ LLM (Ollama/LiteLLM)    │  │
                          │  │ Embeddings (FastEmbed)   │  │
                          │  └─────────────────────────┘  │
                          └──────────────────────────────┘
```

- **Brain** (Claude Desktop): Strategic decisions — what to research, which direction to take, how to interpret findings. Communicates via MCP tools.
- **Executor** (Claude Code): Implementation — runs experiments, writes code, collects data. Receives missions, submits reports, raises checkpoints.
- **PI** (Human): Oversees progress, resolves checkpoints, provides domain expertise.

### Four-Layer Design

1. **MCP Tools Layer** — Thin adapter exposing 34 `rka_*` tools over stdio. Stateless proxy, no business logic.
2. **REST API Layer** — FastAPI endpoints under `/api`. Same thin-adapter pattern, delegates to services.
3. **Service Layer** — All business logic. CRUD operations, auto-enrichment, event emission, context preparation. Shared identically by MCP and REST.
4. **Infrastructure Layer** — Database (SQLite + FTS5 + sqlite-vec), LLM gateway (LiteLLM + Instructor), embeddings (FastEmbed), file storage.

### Two-Process Model

RKA runs as two separate processes:

| Process | Command | Purpose | Port |
|---------|---------|---------|------|
| REST API + Web UI | `rka serve` | HTTP endpoints + static web dashboard | 9712 |
| MCP stdio server | `rka mcp` | Tool interface for Claude Desktop/Code | stdio |

Both processes share the same SQLite database file and service layer code. The MCP server communicates via stdio (stdin/stdout), while the REST server listens on HTTP.

---

## Key Concepts

### Entity Types

| Entity | Prefix | Purpose |
|--------|--------|---------|
| **Journal Entry** | `jrn_` | Research findings, insights, ideas, observations, hypotheses, methodologies |
| **Decision** | `dec_` | Decision tree nodes — questions with options, chosen path, rationale |
| **Literature** | `lit_` | Papers, articles — tracked through reading pipeline |
| **Mission** | `mis_` | Task packages assigned to the Executor with objectives and acceptance criteria |
| **Checkpoint** | `chk_` | Escalation points where Executor needs Brain/PI input |
| **Event** | `evt_` | Audit trail of all state changes with causal chain links |
| **Project State** | — | Singleton: current phase, summary, blockers, metrics |

### ULID-Based IDs

All entities use type-prefixed ULIDs (e.g., `dec_01HXYZ...`). ULIDs are globally unique, sortable by creation time, and the prefix makes debugging easier when reading logs or database rows.

### Mission Lifecycle

```
Brain creates mission → Executor picks up (active) → Work proceeds
    → Checkpoint raised if blocked → Brain/PI resolves
    → Executor submits report → Brain reviews
    → Mission marked complete/partial/blocked
```

### Context Temperature

Entries are classified by recency:

| Temperature | Age | Behavior |
|-------------|-----|----------|
| **HOT** | ≤ 3 days | Included in full, highest priority |
| **WARM** | ≤ 14 days | Included, may be compressed |
| **COLD** | > 14 days | Summarized or excluded |
| **ARCHIVE** | Manually archived | Excluded unless explicitly requested |

The Context Engine uses these temperatures to build focused context packages within token budgets.

---

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Node.js 18+ (for web dashboard, optional)
- [Ollama](https://ollama.com/) (for LLM features, optional)

### Install from Source

```bash
# Clone
git clone <repository-url>
cd rka

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .

# For LLM + semantic search features (includes fastembed + sqlite-vec)
uv sync --extra llm

# For academic API integrations (BibTeX, Zotero, DOI, etc.)
uv sync --extra academic

# For workspace bootstrap (PDF + DOCX extraction)
uv sync --extra workspace

# For everything
uv sync --all-extras
```

### Install Ollama Model (Optional)

If using LLM enrichment:

```bash
ollama pull qwen3.5:35b-a3b
```

---

## Quick Start

### 1. Initialize a Project

```bash
rka init "My Research Project" --description "Investigating X in domain Y"
```

This creates:
- `rka.db` — SQLite database with full schema
- `.env` — Configuration file with sensible defaults

### 2. Start the API Server

```bash
rka serve
```

The server starts at `http://localhost:9712`. If you've built the web dashboard, it's served at the same URL.

### 3. Connect Claude Desktop (MCP)

Add to your Claude Desktop MCP configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rka": {
      "command": "rka",
      "args": ["mcp"],
      "env": {
        "RKA_PROJECT_DIR": "/path/to/your/project"
      }
    }
  }
}
```

Claude Desktop now has access to all `rka_*` tools.

### 4. Connect Claude Code (MCP)

In your `.claude/settings.json` or project MCP config:

```json
{
  "mcpServers": {
    "rka": {
      "command": "rka",
      "args": ["mcp"],
      "env": {
        "RKA_PROJECT_DIR": "/path/to/your/project"
      }
    }
  }
}
```

### 5. Enable LLM Features (Optional)

Edit `.env` in your project directory:

```env
RKA_LLM_ENABLED=true
RKA_LLM_MODEL=ollama/qwen3.5:35b-a3b
RKA_EMBEDDINGS_ENABLED=true
RKA_EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
```

Restart the server. Auto-enrichment (tagging, classification, supersession detection) and semantic search are now active.

---

## CLI Reference

### `rka init <name>`

Initialize a new RKA project.

```bash
rka init "IoT Security Analysis" --description "Systematic review of CPS vulnerabilities"
```

| Option | Default | Description |
|--------|---------|-------------|
| `--description` | `""` | Project description |
| `--dir` | `.` | Project directory |

### `rka serve`

Start the REST API + web dashboard server.

```bash
rka serve --port 9712 --reload
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `9712` | Port number |
| `--reload` | `false` | Auto-reload on code changes (dev mode) |

### `rka mcp`

Start the MCP stdio server for Claude Desktop or Claude Code.

```bash
rka mcp
```

No options — communicates via stdin/stdout per the MCP protocol.

### `rka status`

Show current project state.

```bash
rka status
```

Displays: project name, current phase, active mission, open checkpoints, entity counts.

### `rka backup`

Backup the SQLite database.

```bash
rka backup --output ./backups/rka-backup.db
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output` | Timestamped file | Output path for backup |

### `rka bootstrap scan <folder>`

Scan a workspace folder and classify files for ingestion into the knowledge base.

```bash
rka bootstrap scan ~/research/project_files --no-llm
```

| Option | Default | Description |
|--------|---------|-------------|
| `--ignore` | — | Additional ignore patterns (repeatable) |
| `--no-llm` | `false` | Disable LLM-enhanced classification |
| `--json-output` | `false` | Output raw JSON manifest |

### `rka bootstrap ingest <folder>`

Scan and ingest a workspace folder into the knowledge base.

```bash
rka bootstrap ingest ~/research/project_files --phase phase_1 --tags bootstrap -y
```

| Option | Default | Description |
|--------|---------|-------------|
| `--phase` | `None` | Research phase for all entries |
| `--tags` | — | Tags to add to all entries (repeatable) |
| `--skip` | — | Relative paths to skip (repeatable) |
| `--no-llm` | `false` | Disable LLM-enhanced classification |
| `--dry-run` | `false` | Preview without creating entries |
| `--yes` | `false` | Skip confirmation prompt |

---

## Configuration

All settings use environment variables with the `RKA_` prefix. Place them in a `.env` file in your project directory.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RKA_PROJECT_DIR` | `.` | Project root directory |
| `RKA_DB_PATH` | `rka.db` | SQLite database file path |
| `RKA_HOST` | `127.0.0.1` | API server bind address |
| `RKA_PORT` | `9712` | API server port |

### LLM Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RKA_LLM_ENABLED` | `false` | Enable LLM auto-enrichment |
| `RKA_LLM_MODEL` | `ollama/qwen3.5:35b-a3b` | LiteLLM model identifier |
| `RKA_LLM_API_BASE` | `None` | Custom API base URL (for cloud LLM providers) |
| `RKA_LLM_API_KEY` | `None` | API key (for cloud LLM providers) |
| `RKA_LLM_THINK` | `false` | Enable thinking/reasoning mode |

### Embedding Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RKA_EMBEDDINGS_ENABLED` | `false` | Enable embedding generation |
| `RKA_EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | FastEmbed model name |

### Context Engine Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RKA_CONTEXT_HOT_DAYS` | `3` | Days for HOT temperature classification |
| `RKA_CONTEXT_WARM_DAYS` | `14` | Days for WARM temperature classification |
| `RKA_CONTEXT_DEFAULT_MAX_TOKENS` | `2000` | Default token budget for context packages |

### LLM Provider Examples

**Ollama (local, default):**
```env
RKA_LLM_MODEL=ollama/qwen3.5:35b-a3b
```

**LM Studio:**
```env
RKA_LLM_MODEL=lm_studio/your-model
RKA_LLM_API_BASE=http://localhost:1234/v1
```

**Claude API:**
```env
RKA_LLM_MODEL=anthropic/claude-sonnet-4-20250514
RKA_LLM_API_KEY=sk-ant-...
```

**OpenAI-compatible (vLLM, etc.):**
```env
RKA_LLM_MODEL=openai/your-model
RKA_LLM_API_BASE=http://localhost:8000/v1
RKA_LLM_API_KEY=token-xxx
```

---

## MCP Tools Reference

All tools are prefixed with `rka_` and available through the MCP stdio interface.

### Knowledge Management

| Tool | Purpose |
|------|---------|
| `rka_add_note` | Add a journal entry with optional tags (finding, insight, idea, observation, hypothesis, methodology, pi_instruction, exploration, summary) |
| `rka_update_note` | Update an existing journal entry |
| `rka_add_decision` | Add a decision node to the research decision tree |
| `rka_update_decision` | Update a decision (change status, record chosen option, add rationale) |
| `rka_add_literature` | Add a literature entry (paper, article, book) |
| `rka_update_literature` | Update any literature field (title, authors, year, venue, doi, abstract, status, methodology_notes, tags, etc.) |

### Mission Lifecycle

| Tool | Purpose |
|------|---------|
| `rka_create_mission` | Create a mission for the Executor with objectives, tasks, and acceptance criteria |
| `rka_get_mission` | Get a mission by ID, or the current active mission |
| `rka_update_mission_status` | Update mission status and task progress |
| `rka_submit_report` | Submit an execution report for a completed/partial mission |
| `rka_get_report` | Retrieve a mission report |

### Checkpoints (Escalation)

| Tool | Purpose |
|------|---------|
| `rka_submit_checkpoint` | Raise a decision/clarification/inspection checkpoint |
| `rka_get_checkpoints` | List checkpoints by status (open, resolved, dismissed) |
| `rka_resolve_checkpoint` | Resolve a checkpoint with a decision and rationale |

### Retrieval and Search

| Tool | Purpose |
|------|---------|
| `rka_search` | Hybrid search across all entity types |
| `rka_get_decision_tree` | Get the full decision tree structure |
| `rka_get_literature` | Query literature with filters |
| `rka_get_journal` | Query journal entries with filters |

### Project State

| Tool | Purpose |
|------|---------|
| `rka_get_status` | Get current project state (phase, summary, blockers, metrics) |
| `rka_update_status` | Update project state |

### Context and Summarization (Phase 2)

| Tool | Purpose |
|------|---------|
| `rka_get_context` | Generate a focused context package for a topic within a token budget |
| `rka_summarize` | On-demand topic summarization |
| `rka_eviction_sweep` | Propose entries for archival based on staleness |

### Academic Import and Enrichment (Phase 5)

| Tool | Purpose |
|------|---------|
| `rka_import_bibtex` | Import literature entries from a BibTeX string (auto-detects duplicates by DOI and title) |
| `rka_enrich_doi` | Enrich a literature entry by looking up its DOI via CrossRef (fills missing title, authors, year, venue, abstract) |
| `rka_search_semantic_scholar` | Search Semantic Scholar for papers by query, with optional year/field filters and auto-add to library |
| `rka_search_arxiv` | Search arXiv for papers by query, with sort options and optional auto-add to library |
| `rka_batch_import` | Batch import multiple entities of different types (note, literature, decision) in a single call |
| `rka_ingest_document` | Ingest a markdown document by splitting into journal entries (auto-splits by headings, classifies types, adds tags) |

### Workspace Bootstrap

| Tool | Purpose |
|------|---------|
| `rka_scan_workspace` | Scan a folder and classify files for ingestion (regex heuristics + optional LLM enhancement) |
| `rka_bootstrap_workspace` | One-shot scan + ingest: classify and import all files into the knowledge base |
| `rka_review_bootstrap` | Review a completed bootstrap — entry counts, suggestions, and narrative for Brain handoff |

### Export

| Tool | Purpose |
|------|---------|
| `rka_export` | Export research data as markdown, JSON, or Mermaid diagram (scopes: state, decisions, literature, full) |
| `rka_export_mermaid` | Export the decision tree as a Mermaid flowchart with status-based styling |

---

## REST API Reference

Base URL: `http://localhost:9712/api`

Interactive API docs available at `http://localhost:9712/docs` (Swagger UI).

### Notes (Journal Entries)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/notes` | Create a journal entry |
| `GET` | `/notes` | List entries (filters: type, phase, confidence, importance, source, since, hide_superseded) |
| `GET` | `/notes/{id}` | Get a single entry |
| `PUT` | `/notes/{id}` | Update an entry |

### Decisions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/decisions` | Create a decision node |
| `GET` | `/decisions` | List decisions (filters: phase, status, parent_id) |
| `GET` | `/decisions/tree` | Get the full tree structure (for visualization) |
| `GET` | `/decisions/{id}` | Get a single decision with options |
| `PUT` | `/decisions/{id}` | Update a decision |

### Literature

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/literature` | Add a literature entry |
| `GET` | `/literature` | List entries (filters: status, year range, venue, query) |
| `GET` | `/literature/{id}` | Get a single entry |
| `PUT` | `/literature/{id}` | Update an entry |

### Missions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/missions` | Create a mission |
| `GET` | `/missions` | List missions (filters: phase, status) |
| `GET` | `/missions/{id}` | Get a single mission |
| `PUT` | `/missions/{id}` | Update a mission |
| `POST` | `/missions/{id}/report` | Submit an execution report |
| `GET` | `/missions/{id}/report` | Get the mission report |

### Checkpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/checkpoints` | Create a checkpoint |
| `GET` | `/checkpoints` | List checkpoints (filters: status, mission_id) |
| `GET` | `/checkpoints/{id}` | Get a single checkpoint |
| `PUT` | `/checkpoints/{id}/resolve` | Resolve a checkpoint |

### Search and Context

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/search` | Hybrid search (FTS5 + semantic) |
| `POST` | `/context` | Generate a context package |
| `POST` | `/summarize` | On-demand summarization |
| `POST` | `/eviction-sweep` | Propose entries for archival |

### Project

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/status` | Get project state |
| `PUT` | `/status` | Update project state |
| `GET` | `/health` | Health check (version, sqlite-vec status) |

### Events and Tags

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/events` | List audit events (filters: phase, event_type, entity_type, actor, since) |
| `GET` | `/tags` | List tags with counts (filter: entity_type) |

### Audit Log (Phase 5)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/audit` | List audit entries (filters: action, entity_type, entity_id, actor, since, limit, offset) |
| `GET` | `/audit/counts` | Audit entry counts grouped by action type |

### Workspace Bootstrap

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/workspace/scan` | Scan a workspace folder and classify files for ingestion |
| `POST` | `/workspace/ingest` | Ingest files from a scan manifest into the knowledge base |
| `GET` | `/workspace/review/{scan_id}` | Review a completed bootstrap (entry counts, suggestions) |

### Academic Import (Phase 5)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/import/bibtex` | Import literature entries from BibTeX content |
| `POST` | `/import/bibtex-file` | Import literature entries from an uploaded .bib file |
| `POST` | `/literature/{id}/enrich-doi` | Enrich a literature entry by looking up its DOI via CrossRef |
| `GET` | `/decisions/mermaid` | Export the decision tree as a Mermaid flowchart diagram |
| `POST` | `/import/batch` | Batch import multiple entities of different types |
| `POST` | `/ingest/document` | Ingest a markdown document by splitting into journal entries |

---

## Web Dashboard

The web dashboard provides a visual interface for inspecting project state without using MCP tools or raw API calls.

### Building the Dashboard

```bash
cd web
npm install
npm run build
```

The build output goes to `web/dist/`. When `rka serve` starts, it automatically detects and serves this directory at `http://localhost:9712`.

### Development Mode

```bash
# Terminal 1: API server
rka serve

# Terminal 2: Vite dev server with HMR
cd web
npm run dev
```

The Vite dev server runs at `http://localhost:5173` and proxies API calls to `:9712`.

### Pages

| Page | Path | Features |
|------|------|----------|
| **Dashboard** | `/` | Project overview, active missions, open checkpoints, recent entries, entity counts |
| **Journal** | `/journal` | Timeline view grouped by date, type/confidence filters, create/edit entries |
| **Decisions** | `/decisions` | Interactive decision tree (React Flow + elkjs), click nodes for detail panel |
| **Literature** | `/literature` | Table view with reading pipeline status tabs, add/update papers |
| **Missions** | `/missions` | Active mission with task checklist, checkpoint badges, report viewer |
| **Timeline** | `/timeline` | Event stream grouped by date, entity/actor filters, causal chain visualization |
| **Knowledge Graph** | `/graph` | Entity relationship graph (React Flow), nodes colored by type, relationship edges |
| **Audit Log** | `/audit` | System audit trail table with action/entity/actor filters, action counts summary |
| **Context Inspector** | `/context` | Generate context packages, view temperature badges (HOT/WARM/COLD), copy JSON |
| **Settings** | `/settings` | API health, DB stats, LLM status, project configuration |

### Tech Stack

- React 19 + TypeScript 5.9 with Vite 7
- Tailwind CSS 4 + shadcn/ui (v5)
- TanStack Query 5 for server state
- @xyflow/react for decision tree and knowledge graph visualization

---

## Data Model

### SQLite Schema

All data lives in a single `rka.db` file. The schema includes:

- **Core tables**: `decisions`, `literature`, `journal_entries`, `missions`, `checkpoints`, `project_state`, `events`
- **Junction table**: `tags` — entity-type/entity-id/tag triples for cross-entity tag queries
- **JSON columns**: `options` (decisions), `authors` (literature), `tasks` (missions), `key_findings` (literature)
- **FTS5 virtual tables**: Full-text search indexes on content fields (Phase 2)
- **sqlite-vec virtual tables**: Vector embeddings for semantic search (Phase 2, optional)

### ID Format

All IDs follow the pattern: `{type_prefix}_{ulid}`

| Entity | Prefix | Example |
|--------|--------|---------|
| Decision | `dec_` | `dec_01HXYZ9A2B3C4D5E6F7G` |
| Literature | `lit_` | `lit_01HXYZ...` |
| Journal | `jrn_` | `jrn_01HXYZ...` |
| Mission | `mis_` | `mis_01HXYZ...` |
| Checkpoint | `chk_` | `chk_01HXYZ...` |
| Event | `evt_` | `evt_01HXYZ...` |
| Scan | `scn_` | `scn_01HXYZ...` |

### Event Sourcing

Every write operation emits an event to the `events` table with:
- `event_type` — created, updated, resolved, etc.
- `entity_type` + `entity_id` — what changed
- `actor` — who made the change (brain, executor, pi, system)
- `caused_by` — causal chain link to the triggering event
- `metadata` — JSON blob with change details

This creates a complete audit trail and enables the causal chain visualization.

---

## Search and Context Engine

### Hybrid Search

RKA combines two search strategies using Reciprocal Rank Fusion (RRF):

1. **FTS5 (keyword search)** — SQLite's built-in full-text search. Weight: 0.3
2. **sqlite-vec (semantic search)** — Vector similarity using embeddings. Weight: 0.7

The hybrid approach catches both exact matches and semantically related content. If sqlite-vec is unavailable, the system falls back to FTS5-only.

### Embeddings

- **Model**: `nomic-ai/nomic-embed-text-v1.5` (768 dimensions)
- **Runtime**: FastEmbed (ONNX, fully local, no API calls)
- **Storage**: sqlite-vec virtual tables

Embeddings are generated asynchronously when entries are created or updated.

### Context Engine

The Context Engine builds focused knowledge packages for a given topic:

1. **Search** — Find relevant entries using hybrid search
2. **Temperature classification** — Assign HOT/WARM/COLD based on recency
3. **Token budgeting** — Fit content within `max_tokens` limit, prioritizing HOT entries
4. **Narrative generation** — Optionally use LLM to synthesize a coherent narrative

Request a context package:
```bash
curl -X POST http://localhost:9712/api/context \
  -H 'Content-Type: application/json' \
  -d '{"topic": "evaluation methodology", "max_tokens": 2000}'
```

---

## LLM Integration

### Auto-Enrichment

When `RKA_LLM_ENABLED=true`, write operations trigger asynchronous enrichment:

| Model | Purpose | Input |
|-------|---------|-------|
| **AutoTags** | Generate semantic tags | Entry content → list of tags |
| **AutoClassification** | Classify entry type and confidence | Entry content → type + confidence |
| **SupersessionCheck** | Detect if new entry supersedes old ones | New entry + recent entries → supersession links |

All enrichment is:
- **Async** — Non-blocking; the API responds immediately
- **Graceful** — Failures are logged but never break the main operation
- **Structured** — Uses Instructor + Pydantic for validated LLM outputs

### LLM Gateway

RKA uses LiteLLM as a unified gateway, supporting:
- **Ollama** (default, local)
- **LM Studio** (local)
- **vLLM** (local or remote)
- **OpenAI API** (cloud)
- **Anthropic API** (cloud)
- Any OpenAI-compatible endpoint

The `think=False` parameter is passed by default to prevent reasoning-mode models from including `<think>` blocks in structured output, which breaks JSON extraction.

---

## Development

### Running Tests

```bash
# Using the project's virtual environment
.venv/bin/pytest

# Or with uv
uv run pytest

# Verbose output
.venv/bin/pytest -v
```

All 89 tests cover: database schema, CRUD operations, FTS5 search, context engine, LLM enrichment, event emission, API endpoints, and workspace bootstrap (scan, classify, ingest).

### Project Structure

```
rka/
├── rka/                    # Python package
│   ├── cli.py              # Click CLI (init, serve, mcp, status, backup)
│   ├── config.py           # Pydantic settings (RKAConfig)
│   ├── models/             # Pydantic models for all entities
│   ├── services/           # Business logic (shared by MCP + REST)
│   │   ├── base.py         # BaseService with emit_event()
│   │   ├── notes.py        # Journal entry CRUD + enrichment
│   │   ├── decisions.py    # Decision tree CRUD
│   │   ├── literature.py   # Literature CRUD
│   │   ├── missions.py     # Mission lifecycle
│   │   ├── checkpoints.py  # Checkpoint CRUD + resolution
│   │   ├── search.py       # Hybrid FTS5 + vector search
│   │   ├── context.py      # Context engine (temperature, token budgeting)
│   │   ├── audit.py        # Audit log queries and counts
│   │   ├── academic.py     # BibTeX import, DOI enrichment, Mermaid export
│   │   └── workspace.py    # Workspace bootstrap (scan, classify, ingest)
│   ├── infra/              # Infrastructure
│   │   ├── database.py     # SQLite + FTS5 + sqlite-vec
│   │   ├── llm.py          # LiteLLM + Instructor wrapper
│   │   └── embeddings.py   # FastEmbed service
│   ├── tools/              # MCP tool definitions
│   └── api/                # FastAPI
│       ├── app.py          # Application factory + static serving
│       ├── deps.py         # Dependency injection
│       └── routes/         # Route modules (one per entity type)
├── web/                    # React dashboard (Vite + TypeScript)
│   ├── src/
│   │   ├── api/            # Fetch client + TypeScript types
│   │   ├── hooks/          # TanStack Query hooks
│   │   ├── components/     # UI components (shadcn + layout + shared)
│   │   ├── pages/          # Page components (10 pages)
│   │   └── lib/            # Utilities
│   └── dist/               # Production build (served by FastAPI)
├── tests/                  # Pytest test suite
├── design.md               # Full design document
├── pyproject.toml          # Python project config
└── .env                    # Project configuration
```

### Adding a New Entity Type

1. Create Pydantic models in `rka/models/`
2. Add service class extending `BaseService` in `rka/services/`
3. Add route module in `rka/api/routes/`
4. Add MCP tool functions in `rka/tools/`
5. Add schema DDL in `rka/infra/database.py`
6. Add TypeScript types in `web/src/api/types.ts`
7. Add TanStack Query hooks in `web/src/hooks/`
8. Add page component in `web/src/pages/`

---

## Build Phases

| Phase | Focus | Status |
|-------|-------|--------|
| **Phase 1** | Core MCP + SQLite — schema, CRUD, 24 MCP tools, REST endpoints, CLI | Complete |
| **Phase 2** | LLM + Semantic Search — LiteLLM, FastEmbed, FTS5, Context Engine, auto-enrichment | Complete |
| **Phase 3** | Web Dashboard — React + Vite, 7 core pages, decision tree visualization, static serving | Complete |
| **Phase 4** | Exploration Visualizations — Timeline page (event stream + causal chains), Knowledge Graph page (entity relationships with React Flow) | Complete |
| **Phase 5** | Academic APIs + Audit — BibTeX import, DOI enrichment (CrossRef), Semantic Scholar + arXiv search, Mermaid decision tree export, batch import, document ingestion, Audit Log viewer + API | Complete |
| **Phase 6** | Workspace Bootstrap — Folder scanning with regex + LLM classification, batch ingestion pipeline, duplicate detection, Brain handoff review (34 MCP tools total) | Complete |

---

## License

Private research tool. Not currently published under an open-source license.
