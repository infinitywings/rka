# RKA Orchestrator (agentic branch)

LangGraph-driven orchestrator that drives Brain ⇄ Executor ⇄ PI research
workflows against the RKA backend, with a **Claude-Code-native PI surface**:
the PI drives the workflow from any Claude Code or Claude Desktop session
via MCP tools — no stdin terminal sessions required.

This package lives **only on the `agentic` branch**. The `main` branch is
the core RKA distribution (knowledge base + REST + MCP); `agentic` adds
this orchestrator on top. They are sibling branches, not a feature-branch /
main pair — main does not absorb orchestrator code; agentic absorbs main's
core updates periodically.

## At a glance

| | |
|---|---|
| Mission graph | 16 nodes (Brain × 6 + Executor × 4 + PI × 3 + Utility × 3) |
| Onboarding subgraph | 6 nodes (research_toolkit + 3 PI interrupts + draft_manifest + finalize) |
| MCP surface | 12 tools (`orchestrator_run_start`, `orchestrator_inbox`, `orchestrator_accept`, `orchestrator_onboard_start`, …) |
| Server | FastAPI on `:9713` — `/runs`, `/inbox`, `/onboard`, `/projects/{id}/manifest`, `/health` |
| State | Three-storage discipline: RKA SQLite + LangGraph SqliteSaver + orchestrator-owned `orchestrator.db` |
| Tests | 494 orchestrator unit + integration, 799 RKA core (1293 total, all green) |

## Architecture in one diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Claude Code / Claude Desktop (PI session)                       │
│  ─ loads orchestrator-pi skill                                   │
│  ─ uses MCP tools: orchestrator_run_start, orchestrator_inbox,   │
│    orchestrator_accept, orchestrator_onboard_start, …            │
│  ─ uses RKA MCP tools directly for ad-hoc work                   │
└─────────────────┬────────────────────────────────────────────────┘
                  │ (stdio MCP)
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│  rka-orchestrator-mcp (host binary, thin proxy to HTTP)         │
└─────────────────┬───────────────────────────────────────────────┘
                  │ HTTP
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│  rka-orchestrator daemon (Docker, port 9713)                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ FastAPI server.py  ◄─ OrchestratorRunner ◄─ LangGraph   │    │
│  │ /runs, /inbox/*,    ─ Mission subgraph  ─ build_graph   │    │
│  │ /onboard, /projects ─ Onboarding subgraph              │    │
│  └─────────────────────────────────────────────────────────┘    │
│  parked_store.py   →   /data/orchestrator.db                    │
│  (parked_interrupts + workflow_runs)                            │
│  LangGraph SqliteSaver → /data/orchestrator-saver.db            │
│                                                                  │
│  Subprocess (Claude Agent SDK)                                  │
│  ─ spawns `claude` CLI for each Brain/Executor LLM call         │
│  ─ subprocess sees read-only RKA MCP tools (Phase 2.7 Option C) │
│  ─ writes execute parent-side via execute_ratified_actions      │
└─────────────────┬───────────────────────────────────────────────┘
                  │ HTTP (http://rka:9712)
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│  rka-server (Docker, port 9712) — the RKA knowledge base        │
│  FastAPI + SQLite + FTS5 + sqlite-vec                            │
└──────────────────────────────────────────────────────────────────┘
```

## Phase history (where we are)

The orchestrator is built in phases, each PI-ratified and locked at the
contract level. The current state on `agentic`:

### ✅ Phase A — Claude-Code-native PI surface

- FastAPI daemon (`server.py`) + runner (`runner.py`) + parked-interrupt store (`parked_store.py`).
- 10 MCP tools shipped as a second stdio binary (`rka-orchestrator-mcp`).
- Locks the Phase-2.4 v1 response-token regression at the contract level: callers pick `action: accept|reject|correct`; server emits the type-correct resume token (`approve` for greenlight, `accept` for decision/acceptance). Caller-side raw strings are impossible.
- Plugin bundle: orchestrator-pi skill + 3 slash commands shipped with the rka plugin.
- READ_TOOLS expanded to include external-API search (`rka_search_semantic_scholar`, `rka_search_arxiv`, `rka_enrich_doi`).
- API keys (`SEMANTIC_SCHOLAR_API_KEY`, `SERPAPI_KEY`) propagated to the subprocess; context7 MCP server registered when `npx` available.

### ✅ Phase A2 — WRITE_TOOLS expansion

- Added `rka_update_mission_status` + `rka_ingest_document` to the dispatcher allowlist after the live test surfaced Brain proposing them.
- Docker auth fixes: `orchestrator/.env` env_file path corrected; mount `~/.claude.json` so the SDK subprocess finds its global config.

### ✅ Phase B + C — prompt + chain support

- `EXECUTOR_SYSTEM` enumerates WRITE_TOOLS by name (dynamically from the constant). Names forbidden patterns explicitly (`rka_present_decision`, `rka_resolve_checkpoint`, etc.).
- `execute_ratified_actions` supports `{{PA-N.id}}` chain substitution (1-indexed). Brain can now express multi-step writes where later actions consume earlier returns. Forward-refs / self-refs / out-of-range refs all yield clean errors.

### ✅ Phase D MVP — Onboarding subgraph

A separate LangGraph subgraph for per-project tool-discovery + credential setup, run once at project creation:

```
START
  → pi_onboarding_topic (PI: topic + field + venue)
  → research_toolkit     (Brain: registry + scoring)
  → pi_toolkit_ratify    (PI: TWO-TAP set-identity ratification)
  → draft_manifest       (writes tools.json + .env template)
  → pi_credentials_ready (PI edits .env, signals ready)
  → finalize             (probes secrets, emits audit journal entry)
  → END
```

Components:
- `manifest.py` — ToolManifest + extension manifests (Q1 hybrid lifecycle)
- `tool_registry.py` + `data/tool_registry.yaml` — small curated registry (4 always-on + 5 domains)
- `credential_validator.py` — HTTP probe + criticality-aware bucketing (required / recommended / optional)
- `onboarding_graph.py` — subgraph composer
- `runner.start_onboarding(project_id, ...)` — entry point
- 2 new HTTP endpoints + 2 new MCP tools (`orchestrator_onboard_start`, `orchestrator_get_manifest`)
- 2 new slash commands (`/orchestrator-onboard`, `/orchestrator-manifest`)

### 📄 Phase O — Full project-onboarding wizard (design only)

Comprehensive design doc at [`docs/phase-o-project-onboarding-design.md`](docs/phase-o-project-onboarding-design.md) extending Phase D MVP into the full project-bootstrapping workflow:

- **O1** Idea Capture & Scope (capture + Brain polish + TWO-TAP ratify)
- **O2** Workspace + Deep Research (async pause for PI in Claude Desktop)
- **O3** Hygiene + Claim Extraction (`rka_check_integrity` + `rka_extract_claims`)
- **O4** Plan Synthesis + Ratification (THE autonomy-licensing contract)
- **O5** Tool Setup (current Phase D, repositioned to read the ratified plan)
- **H** Mission Queue Handoff (per-phase pi_phase_entry_ack between missions)

Workspace consolidated at `~/Research/{project-slug}/` (PI-chosen slug). Project content NEVER lives in the rka repo — only the orchestrator code that knows how to create the workspace.

Build estimate: ~13.5 days. See the design doc for the detailed 17-sub-task breakdown.

### ⏸️ Deferred follow-ups

- **D3b** — SerpAPI augmentation for `research_toolkit_node` (registry-only works for now)
- **D6** — `pi_extend_toolkit` for mid-mission tool addition
- **Phase E** — Capability categories replacing static WRITE_TOOLS allowlist (depends on Phase D's manifest)
- **Phase F** — Topology variants (light/heavy mission classes)
- **Phase G** — Actuator subagent (Bash/Edit/Write tools behind ratification — strategic, separate scope)

## Hard invariants (machine-checked)

All three are enforced by `tests/test_invariants.py`:

- **Bookkeeper invariant** — `git diff origin/main -- rka/` returns empty. The agentic branch never originates `rka/` changes; main-originated `rka/` changes absorb via deliberate merge commits.
- **Grep-gate** — `grep -rn "from rka\|import rka" orchestrator/` returns zero. The orchestrator talks to RKA only through the `MCPClient` Protocol (`mcp_client.py`); the production binding is `RestMCPClient`.
- **Audit-symmetry** — every string literal assigned to `current_node` in `nodes/*.py` appears in either `graph.NODE_NAMES` or `graph.ONBOARDING_NODE_NAMES`.

Plus:
- **Three-storage discipline** — RKA SQLite owns domain truth; LangGraph SqliteSaver owns workflow position; orchestrator's own SQLite (`orchestrator.db`) owns parked-interrupt queue + workflow_runs. No cross-DB joins.
- **Response-token contract** — `_ACCEPT_TOKEN_BY_TYPE` in `runner.py` is the single source of truth for what string each interrupt type expects on accept. The 7 interrupt types map to 2 distinct tokens (`approve` for greenlight-class, `accept` for set-identity-class).

## Local install + run

```bash
# 1. From repo root: install orchestrator package + the MCP binary
cd orchestrator
pip install -e ".[dev]"      # or `uv tool install --force .` for the binary
pytest -q                     # 494 tests; takes ~7s

# 2. Set up Claude Max auth (one-time)
claude setup-token            # generates a long-lived OAuth token
echo "CLAUDE_CODE_OAUTH_TOKEN=<paste>" > orchestrator/.env
chmod 600 orchestrator/.env
# Optionally add SEMANTIC_SCHOLAR_API_KEY and SERPAPI_KEY to .env

# 3. Bring up the orchestrator service (alongside rka)
cd ..
docker compose -f docker-compose.yml \
               -f orchestrator/docker-compose.yml up -d --build
curl http://localhost:9713/health   # {"status":"ok",...}

# 4. Register the second MCP server in Claude Desktop / Claude Code config
#    (see CLAUDE.md root section "Phase-A: Claude-Code-native PI surface")
```

## Driving a workflow from Claude Code

After the MCP entry is registered:

```
[PI types in any Claude Code session:]
> start orchestrator on mis_01XYZ

[Claude:]
[invokes orchestrator_run_start(...)]
[graph runs; parks at pi_greenlight]
[invokes orchestrator_inbox; renders the Confirmation Brief]
[uses AskUserQuestion to present Accept/Reject/Correct]

[PI picks Accept]

[Claude invokes orchestrator_accept(interrupt_id)]
[graph resumes; parks at pi_decision_select]
... and so on
```

For onboarding a new project (Phase D MVP):

```
[PI:]
> /orchestrator-onboard prj_01XYZ
```

See [`plugin/skills/orchestrator-pi/SKILL.md`](../plugin/skills/orchestrator-pi/SKILL.md) for the
rendering + TWO-TAP discipline Claude follows.

## Three-storage discipline

| Storage | What it owns | Where |
|---|---|---|
| **RKA SQLite** | Domain truth: decisions, missions, journals, claims, evidence clusters | `/data/rka.db` in the `rka-server` container |
| **LangGraph SqliteSaver** | Workflow position: which node ran, with what input | `/data/orchestrator-saver.db` in the `rka-orchestrator` container |
| **Orchestrator SQLite** | Parked-interrupt queue + workflow_runs lifecycle | `/data/orchestrator.db` in the `rka-orchestrator` container |

The `workflow_thread_id` is auto-tagged on every RKA write so a run's artifacts
are recoverable via `rka_get_journal(tags=[workflow_thread_id])`. The same
pattern carries through Phase O — onboarding artifacts are queryable via
`tags=[project_id, 'polished-idea']`, `tags=[project_id, 'literature']`, etc.

## Layout

```
orchestrator/
├── orchestrator/
│   ├── server.py              # FastAPI daemon
│   ├── runner.py              # OrchestratorRunner — segment-by-segment graph driver
│   ├── parked_store.py        # SQLite CRUD for parked_interrupts + workflow_runs
│   ├── mcp_server.py          # FastMCP stdio → HTTP proxy (12 tools)
│   ├── llm_client.py          # Claude SDK wrapper (WRITE_TOOLS, READ_TOOLS, auth chain)
│   ├── mcp_client.py          # RestMCPClient — workflow-thread-tagged RKA writes
│   ├── manifest.py            # ToolManifest dataclass + IO (Phase D)
│   ├── tool_registry.py       # Curated registry loader (Phase D)
│   ├── credential_validator.py# HTTP probe + criticality bucketing (Phase D)
│   ├── graph.py               # Mission subgraph (Phase A)
│   ├── onboarding_graph.py    # Onboarding subgraph (Phase D)
│   ├── state.py               # ResearchWorkflowState TypedDict
│   ├── nodes/
│   │   ├── brain.py           # 6 Brain nodes
│   │   ├── executor.py        # 4 Executor nodes (incl. execute_ratified_actions w/ chain support)
│   │   ├── pi.py              # 7 PI interrupt nodes (3 mission + 3 onboarding + 1 deferred)
│   │   ├── onboarding.py      # 3 onboarding system nodes (research_toolkit, draft_manifest, finalize)
│   │   └── utility.py         # 3 utility nodes
│   ├── data/
│   │   └── tool_registry.yaml # Curated tool registry (4 always-on + 5 domains)
│   └── db/
│       └── schema.sql         # workflow_runs + parked_interrupts
├── tests/                     # 494 tests
├── docs/
│   ├── operational-rollout-v1..v6.md  # historical Phase A rollouts
│   ├── phase-2-9-subprocess-context.md
│   ├── phase-2-11-investigation.md
│   ├── phase-d-onboarding-design.md   # Phase D MVP design
│   ├── phase-o-project-onboarding-design.md  # Phase O full-workflow design
│   └── skill-prompt-deltas.md
├── scripts/
│   ├── driver.py              # Legacy stdin driver (still supported for headless runs)
│   └── pilot_t12.py
├── Dockerfile
├── docker-compose.yml         # Compose overlay (adds rka-orchestrator service)
├── pyproject.toml
└── README.md                  # this file
```

## Mission reference

- Phase 1 mission: `mis_01KRKG9K1SSDZNDH90K2Z7ZM92`
- Phase 1 decision: `dec_01KRKE6ERDPQTFQS6ZGY9A3CK0`
- Skill-prompt deltas (17 ratified additions, Phase 2.5): [`docs/skill-prompt-deltas.md`](docs/skill-prompt-deltas.md)

## Cross-references

- Root [`CLAUDE.md`](../CLAUDE.md) — agent operating instructions; agentic-branch section documents Phase A configuration
- Root [`README.md`](../README.md) — RKA project overview (main-branch facing)
- Root [`USAGE_GUIDE.md`](../USAGE_GUIDE.md) — user-facing how-to; agentic distribution section covers orchestrator usage
- [`plugin/skills/orchestrator-pi/SKILL.md`](../plugin/skills/orchestrator-pi/SKILL.md) — PI cockpit rendering + ratification rules
