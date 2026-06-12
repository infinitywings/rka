# CLAUDE.md — RKA Codebase (Executor instructions)

This is the **Research Knowledge Agent (RKA)** source repository.
When working here you are modifying the tool itself, not using it for research.

---

## Stack

| Layer | Technology |
|---|---|
| MCP server | `rka/mcp/server.py` — FastMCP, stdio, thin HTTP proxy to REST |
| REST API | `rka/api/` — FastAPI, mounted under `/api/` |
| Services | `rka/services/` — all business logic, shared by MCP + REST |
| DB | SQLite + FTS5 + sqlite-vec, schema in `rka/db/schema.sql` |
| Web UI | `web/` — React + Vite + shadcn/ui, built to `web/dist/` (served by FastAPI) |
| CLI | `rka/cli.py` — `rka serve` (REST+UI), `rka mcp` (MCP stdio) |

## Key Conventions

- **Actor values**: `brain | executor | pi | llm | web_ui | system` — enforced by DB CHECK constraint
- **ID prefix**: `jrn_` journal, `lit_` literature, `dec_` decision, `mis_` mission, `clm_` claim, `ecl_` evidence cluster, `chk_` checkpoint, `prj_` project, `lnk_` entity link, `scn_` scan
- **MCP tools**: all prefixed `rka_`, defined in `server.py` via `@mcp.tool()`
- **MCP prompts**: defined at end of `server.py` via `@mcp.prompt()`
- **API routes**: thin adapters only — no business logic, always delegate to service layer
- **Tests**: `tests/` using pytest; run with `docker compose exec rka pytest`
- **v2.7.0+ tool surface (MCP)**: 3 always-on dispatch tools (`rka_query` / `rka_execute` / `rka_describe`) + 2 escape hatches (`rka_load_tools` / `rka_help`) = 5 broadcast tools. 91 typed Pydantic operation models in `rka/mcp/operation_args.py` provide per-branch enum + required-field enforcement at the FastMCP `inputSchema` layer (`Union[Args1, …, Args91]` rendered as `oneOf` with `discriminator='operation'`). Operations split: 42 read (`rka_query`, incl. v2.8.0 `collect_report_context` / `staleness_impact` / `mission_guard` / `belief_as_of`) + 49 write/lifecycle (`rka_execute`). 91 legacy tools + 8 v2.7.0a2 verbs remain at `tier='deferred'`, callable via `rka_load_tools`. Setting `RKA_LEGACY_TOOLS=1` in env restores the v2.7.0a2 surface (20 always-on tools) — used in `orchestrator/docker-compose.yml` (this branch) to preserve TWO-TAP gate granularity at `pi_decision_select`. Full empirical arc + 4 pre-mortem compromises (all closed at schema layer) documented in [`docs/v2.6.x-v2.7.0-tool-surface-arc.md`](docs/v2.6.x-v2.7.0-tool-surface-arc.md) and `CHANGELOG.md` v2.7.0 entry.
- **Credential management**: use `rka cred` subcommands (`init` / `set` / `get` / `env` / `propagate` / `check`) — vault lives at `~/.config/rka/creds.env` (XDG-compliant, mode 0600). Never commit creds to any repo or `.env` tracked by git. Full reference: [`docs/CRED_VAULT.md`](docs/CRED_VAULT.md).

## Running (Docker only)

```bash
# Start all services (API + web dashboard + background worker)
docker compose up -d

# View logs
docker compose logs -f rka

# Rebuild after code changes
docker compose up -d --build

# Run tests
docker compose exec rka pytest

# Rebuild web UI after frontend changes (done automatically during docker build)
# For local iteration: cd web && npm run build, then rebuild container
```

## After Frontend Changes

The web UI is built during `docker build`. To apply frontend changes:
```bash
docker compose up -d --build
```

## MCP Configuration

The MCP binary is installed via `uv tool` (outside the Docker container) because
Claude Desktop/Code needs a local stdio process. It proxies all calls to the
Docker container's REST API.

```bash
# Install / re-install after code changes:
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .   # from repo root
# Binary lands at: ~/.local/bin/rka
```

`~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
"rka": { "command": "/Users/<user>/.local/bin/rka", "args": ["mcp"] }
```

After code changes to `rka/mcp/server.py` or other source files:
1. `UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .` — update the MCP binary
2. `docker compose up -d --build` — update the API server + worker

## Common Pitfalls

- `actor="import"` is not a valid actor — use `actor="system"` for programmatic ingestion
- The MCP server is stateless; it proxies all calls to the REST API at `RKA_API_URL` (default: `http://localhost:9712`)
- `web/` previously had a nested `.git` — do not re-introduce submodule state there
- Large files (>10 MB) use fast composite hashing; text files are capped at 200K chars in scan
- The database lives in the Docker volume `rka-data` at `/data/rka.db` — do not use a local `rka.db`
- There is no local `.venv` — all server/worker processes run in Docker
- `docker compose restart` does **not** reload service code — always use `docker compose up -d --build` for any change under `rka/`. Restart only suffices for migration-only changes (the migration runner queries `schema_migrations` on startup).
- **Auto-mode push-to-main is gated**: when an Executor session runs in auto-mode (no per-tool-call confirmation), direct `git push origin main` is blocked by a safety classifier and requires explicit PI authorization in the transcript (a sentence like *"push to main"* or *"go ahead and push to main"*) to unblock. For any main-branch mission spec, the T5/release task should anticipate this and PI should plan to ratify the push step explicitly. The block is one-shot per push — after PI authorizes, the push proceeds and subsequent operations resume normal flow. Surfaced empirically during D4 mission (v2.5.4) per `dec_01KS0BVPCYK4CBG5TKKG1QK4HM` close-out.
- **v2.7.0 dispatch surface (current MCP shape)**: only 5 tools broadcast on connect — 3 always-on dispatch (`rka_query` / `rka_execute` / `rka_describe`) + 2 escape hatches (`rka_load_tools` / `rka_help`). The legacy 91 tools + 8 v2.7.0a2 verbs are tier=`deferred`; load them on demand via `rka_load_tools(names=[…])`. To restore the v2.7.0a2 surface (20 always-on tools, e.g. for orchestrator subprocesses that depend on per-tool dispatch for autonomy-contract granularity), set `RKA_LEGACY_TOOLS=1` in env — already wired into `orchestrator/docker-compose.yml` on this branch. Enum hallucinations (e.g. `confidence='confirmed'`) and missing-required-field errors are caught at the `inputSchema` `oneOf` branch level — they fail BEFORE leaving the cockpit, not as 422s at the API. Empirical proof + 4 pre-mortem compromises closed: see [`docs/v2.6.x-v2.7.0-tool-surface-arc.md`](docs/v2.6.x-v2.7.0-tool-surface-arc.md). Pre-v2.7 docs may still teach the v2.6.3 "navigator architecture" (12 always-on + ~79 deferred) — that surface is superseded.

## Embedding backend configuration (v2.4.0+)

Pluggable embedding backends (FastEmbed, OpenAI-compat HTTP, Ollama) configurable
in the web UI at **Settings → Embeddings**. Persistent config at
`/data/embedding_config.json` (file-mode 0600, owner-readable only because of the
optional `api_key`). Full reference: [`docs/embedding_backends.md`](docs/embedding_backends.md).

LLM-driven features (`rka_ask`, `rka_generate_summary`, web-UI Q&A page) were
removed in v2.4.0 per `jrn_01KRNZBS50K250HHHHEC58E4GC`; server-side LLM code is
preserved for future re-wiring through the orchestrator's Claude Code SDK
(separate Phase-2 mission). `/api/capabilities` no longer returns the `llm`
field (BREAKING-IN-MINOR; documented in `CHANGELOG.md`).

## macOS AppleDouble Quirks (external / network / sync volumes)

On macOS, certain volumes — external drives, SMB/AFP network mounts, OneDrive / Dropbox / iCloud sync folders, and some case-insensitive filesystems — don't fully support extended attributes. macOS works around this by creating `._*` AppleDouble companion files alongside every file Python tools write (in `build/`, `rka.egg-info/`, project root). These break both `docker compose build` (fails with "failed to xattr ... operation not permitted") and `uv tool install` (fails with "No such file or directory: '._requires.txt'") even with `COPYFILE_DISABLE=1` set. If you cloned the repo into `~/Documents` on a stock APFS volume you'll never see this; if you cloned it onto an external drive or a synced folder, you will.

**Before any rebuild**, purge resource-fork files:

```bash
find . -maxdepth 2 -name '._*' -not -path './.git/*' -delete
```

**If `uv tool install --force .` still fails on `._requires.txt`** (the build process re-creates AppleDouble files in `build/` on the fly), install from a `/tmp` clone instead — `/tmp` is on a stock APFS volume that doesn't have the xattr quirk:

```bash
rm -rf /tmp/rka-build && git clone -q --depth 1 "$PWD" /tmp/rka-build
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

**If `docker compose build` succeeds but the new image isn't picked up**, force-recreate:

```bash
docker compose up -d --force-recreate
```

(Plain `docker compose up -d --build` can hit the build cache or skip recreation if Compose decides nothing changed; `--force-recreate` is the reliable post-rebuild path.)

---

## Agentic Branch + Orchestrator Package

The `agentic` branch hosts the `orchestrator/` package — a LangGraph-driven
Brain ⇄ Executor ⇄ PI loop that runs against RKA via the REST API. It is a
**peer to `rka/`**, not a submodule. The branch is long-lived parallel to
`main`; merges are deliberate, not continuous.

### Hard invariants

When working on `agentic`:

- **Bookkeeper invariant** — `git diff main -- rka/` must remain empty across
  every commit. Touching `rka/` from this branch requires an explicit
  checkpoint and Brain greenlight.
- **Worker invariant** — `git diff main -- rka/services/worker.py` always empty.
- **Grep-gate** — `grep -rn "from rka\|import rka" orchestrator/` returns
  none. The orchestrator talks to RKA only through the `MCPClient` Protocol
  (`orchestrator/mcp_client.py`); the production binding is `RestMCPClient`
  hitting `http://localhost:9712`.
- **CLAUDE.md (root) is the only file outside `orchestrator/` this branch
  may modify.** The root appendage you're reading documents the branch's
  existence; further root-file edits need their own checkpoint.

`orchestrator/tests/test_invariants.py` automates all three checks.

### Three-storage discipline

- **RKA SQLite** — domain truth (decisions, missions, journals, claims).
- **LangGraph SqliteSaver** — workflow position (which node ran, with what input).
- **Claude SDK session** — transient prompt/response context per node.

Never persist workflow position back to RKA; never use the SDK session as a
state bus across nodes. The `workflow_thread_id` (set at workflow start) is
auto-tagged onto every RKA write so a run's artifacts are recoverable via
`rka_get_journal(tags=[workflow_thread_id])` — same shape as v2.3.5
Affordance F.

### Telemetry-zero default

`orchestrator/notifications.py` sends to terminal bell + macOS osascript by
default. The webhook channel is opt-in and gated by a `WEBHOOK_BLOCKLIST`
floor of known telemetry endpoints (Segment, Amplitude, Mixpanel, Statsig,
PostHog, Heap). Extend the blocklist if more surface.

### Local install for development

```bash
cd orchestrator
# Use the repo .venv (langgraph + sqlite checkpointer already installed there
# as part of T7). Else create a local venv:
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

Local pytest expects langgraph + langgraph-checkpoint-sqlite ≥ 1.x/3.x
pinned in `orchestrator/pyproject.toml`. The 162+ unit tests run offline
with fakes; only the e2e graph smoke + the test-count floor invoke the
real LangGraph runtime.

### Python resolution pitfall — `.venv/bin/python` vs `(rka)` conda env

If a conda environment is active (e.g. `(rka)`), a bare `python` invocation may
resolve to the conda interpreter — which does NOT have the orchestrator's
dependencies (`langgraph`, `claude-agent-sdk`, etc.) installed. Symptoms:
`ModuleNotFoundError: No module named 'langgraph'` or similar import failures
when launching `orchestrator/scripts/driver.py`.

**Always invoke the driver via the explicit `.venv` interpreter**:

```bash
.venv/bin/python orchestrator/scripts/driver.py --mission-id mis_... \
    --workflow-thread-id thr_... --output-dir orchestrator/results/...
```

The repo `.venv/` at the root (NOT `orchestrator/.venv/`) is what the
`pip install -e ".[dev]"` step above populates with the orchestrator's
runtime deps. Avoid `cd orchestrator && python ...` from a shell with a
conda env active; the orchestrator's deps land in the repo-root `.venv`,
not the conda env. (Surfaced empirically during Phase 2.14 — Phase 2
chapter close — when a bare `python` invocation pulled the conda
interpreter and shadowed the repo `.venv`.)

### Mission reference

- Mission: `mis_01KRKG9K1SSDZNDH90K2Z7ZM92`
- Decision: `dec_01KRKE6ERDPQTFQS6ZGY9A3CK0`
- Skill-prompt deltas (17 ratified additions): `orchestrator/docs/skill-prompt-deltas.md`

### Phase-A: Claude-Code-native PI surface (orchestrator daemon)

Phase-A added an HTTP + MCP surface so the PI can drive the
orchestrator entirely from Claude Code / Claude Desktop instead of
the stdin-based `driver.py`. The driver remains for headless /
automated runs.

**Components (all under `orchestrator/`):**

- `orchestrator/orchestrator/server.py` — FastAPI daemon on port 9713.
  Endpoints: `/runs`, `/inbox`, `/inbox/{id}/accept|reject|correct`,
  `/runs/{id}` (DELETE = cancel), `/health`.
- `orchestrator/orchestrator/runner.py` — `OrchestratorRunner`. Locks
  the Phase-2.4 v1 response-token regression at the contract level
  (callers pick `action: accept|reject|correct`; the server emits the
  type-correct resume token).
- `orchestrator/orchestrator/parked_store.py` + `db/schema.sql` —
  orchestrator-owned SQLite (`workflow_runs`, `parked_interrupts`).
  Three-storage discipline preserved: never touches `rka.db`.
- `orchestrator/orchestrator/mcp_server.py` — second MCP stdio binary
  (`rka-orchestrator-mcp`). Tools: `orchestrator_run_start`,
  `orchestrator_list_runs`, `orchestrator_inbox`,
  `orchestrator_accept`, `orchestrator_reject`,
  `orchestrator_correct`, `orchestrator_cancel`,
  `orchestrator_get_run`, `orchestrator_get_interrupt`,
  `orchestrator_health`.
- `orchestrator/skills/orchestrator-pi.md` — Claude-the-assistant
  rendering + ratification guide. Enforces TWO-TAP confirm on
  `pi_decision_select` (the privileged write-authorization gate).

**Run with the Compose overlay** (root `docker-compose.yml` untouched):

```bash
docker compose -f docker-compose.yml \
               -f orchestrator/docker-compose.yml up -d --build
```

The overlay mounts `~/.claude/:/root/.claude:ro` so the daemon's
`claude-agent-sdk` subprocess can read the host's `credentials.json`
(the macOS Keychain auth path isn't accessible from a Linux
container). Run `claude login` on the host once if you don't have a
credentials file.

**Add to `claude_desktop_config.json`** (alongside the existing `rka`
entry):

```json
{
  "mcpServers": {
    "rka": { "command": "docker", "args": ["exec", "-i", "rka-server", "rka", "mcp"] },
    "rka-orchestrator": {
      "command": "/Users/<user>/.local/bin/rka-orchestrator-mcp",
      "args": []
    }
  }
}
```

Install the MCP binary on the host (the daemon itself is in Docker,
but Claude Desktop needs a local stdio process to launch):

```bash
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force ./orchestrator
```

**Day-one PI flow:**

1. `docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d`
2. In any Claude Code session: *"start orchestrator on mis_01XYZ"* →
   Claude calls `orchestrator_run_start`.
3. Daemon kicks off the LangGraph; parks at first `pi_*` interrupt.
4. Claude renders the payload using the `orchestrator-pi` skill, asks
   you via `AskUserQuestion`.
5. You pick → Claude calls `orchestrator_accept` / `reject` /
   `correct`. Daemon resumes the graph until the next interrupt or
   terminal state.

### Phase A2 — WRITE_TOOLS expansion + Docker auth fixes

Empirical follow-up from the Phase-A live test (IoT-edge-LLM mission):
Brain proposed write tools outside the dispatcher's allowlist. Added
`rka_update_mission_status` + `rka_ingest_document` to `WRITE_TOOLS`
+ matching MCPClient Protocol methods and RestMCPClient impls.

Auth: mount the host's `~/.claude.json` (single file, separate from
the `.claude/` dir) so the claude CLI subprocess finds its global
config. Compose overlay reads `CLAUDE_CODE_OAUTH_TOKEN` from
`orchestrator/.env` (gitignored, mode 0600).

### Phase B + C — prompt + chain support

- **Phase B**: `EXECUTOR_SYSTEM` dynamically enumerates WRITE_TOOLS by
  name (single source of truth from the constant). Names forbidden
  tool patterns explicitly: `rka_present_decision` (orchestrator
  handles presentation via `pi_decision_select`), `rka_resolve_checkpoint`
  + other lifecycle tools (out of scope for parent-side dispatch).
- **Phase C**: `execute_ratified_actions` supports `{{PA-N.id}}`
  chain substitution (1-indexed). Brain can express multi-step
  writes where later actions consume earlier returns. Forward-refs,
  self-refs, out-of-range refs, references to failed actions all
  yield clean `ratified_action_chain_resolution_failed` ErrorRecord
  and skip the offending action without aborting the chain.

### Phase D MVP — Onboarding subgraph (tool-discovery wizard)

A separate LangGraph subgraph for per-project tool-discovery +
credential setup. Run once at project creation:

```
pi_onboarding_topic → research_toolkit → pi_toolkit_ratify (TWO-TAP)
                                      ↓ accept
                          draft_manifest → pi_credentials_ready
                                                ↓ accept
                                            finalize → END
```

**New components (all under `orchestrator/`):**

- `orchestrator/orchestrator/manifest.py` — `ToolManifest` dataclass
  + IO helpers (workspace dir, save_manifest, load_manifest,
  write_env_template, read_env, manifest_to_mcp_servers). Hybrid
  lifecycle: baseline manifest + per-mission extensions.
- `orchestrator/orchestrator/tool_registry.py` +
  `orchestrator/data/tool_registry.yaml` — curated registry of
  ~10-15 trusted defaults (always-on: rka, context7, fs, git; by
  domain: ml_systems, finance, bioinformatics, legal, natural_sciences).
- `orchestrator/orchestrator/credential_validator.py` — HTTP probe
  + criticality-aware bucketing. Probe results NEVER contain secret
  values (enforced by leak-detection assertion in tests).
- `orchestrator/orchestrator/nodes/onboarding.py` —
  `research_toolkit_node`, `draft_manifest_node`, `finalize_node`.
- `orchestrator/orchestrator/onboarding_graph.py` — subgraph composer.
- `runner.start_onboarding(project_id, ...)` — entry point.

**2 new MCP tools, 2 new slash commands:**

```
orchestrator_onboard_start(project_id) → kicks off onboarding
orchestrator_get_manifest(project_id)  → fetches the effective manifest

/orchestrator-onboard <project_id>     → drives the onboarding flow
/orchestrator-manifest <project_id>    → introspect the manifest
```

**Per-project workspace**: Phase D MVP writes `tools.json` + `.env`
under `~/rka-projects/{project_id}/`. Phase O design (next) unifies
this with the Writer skill's manuscript workspace under
`~/Research/{slug}/.rka/`.

**Criticality tiers (Q2 design choice)**:
- `required` missing → escalate via checkpoint
- `recommended` missing → escalate once at session start
- `optional` missing → skip with journal note

**Audit (Q5 design choice)**: onboarding emits a summary journal entry
(`source=system, tags=[orchestrator, onboarding, baseline]`)
referencing the manifest sha256 hash. Extensions trigger new entries
with `supersedes` linkage.

### Phase O — Full project-onboarding wizard (design only)

See [`orchestrator/docs/phase-o-project-onboarding-design.md`](orchestrator/docs/phase-o-project-onboarding-design.md)
for the detailed design. Phase O extends Phase D MVP into the full
project-bootstrapping workflow:

- **O1** Idea capture & scope confirmation
- **O2** Workspace + Deep Research (async pause for Claude Desktop's deep-research feature)
- **O3** Hygiene + claim extraction
- **O4** Plan synthesis + ratification (THE autonomy-licensing contract)
- **O5** Tool setup (current Phase D, repositioned to read the ratified plan)
- **H** Mission queue handoff (per-phase pi_phase_entry_ack)

**Workspace consolidation (Phase O)**:
`~/Research/{project-slug}/` becomes the canonical per-project home:

```
~/Research/iot-edge-llm/
├── .rka/{project_id, tools.json, .env, workspace.json}
├── data/, code/, notebooks/, results/
├── manuscripts/{venue}/    ← Writer skill workspace
└── README.md (auto-generated)
```

**Critical repo boundary**: project-specific content
(`~/Research/{slug}/{data,code,notebooks,results,manuscripts}/`)
lives in the PI's home at runtime, NEVER in the rka repo. The repo
holds only template + scaffold code.

Build estimate: ~13.5 days; deferred for the next implementation
session.

### Phase D2 — async resume + workspace bind mount + Executor FS tools

Empirical follow-ups from the hyperscaler-auditing live test
(`prj_01KSMW9RBFXRY6HRRADH3SX7ZP`, mission `mis_01KSTWTJNZMV3893S2FWG4HBYZ`).

**Async PI-response endpoints.** Previously `runner.respond()` drove
the LangGraph segment synchronously after committing the PI's answer
to the parked-interrupt store — a 4+ minute segment blew past the
120s MCP `httpx` timeout and surfaced as an empty error in
`orchestrator_correct` (the answer was committed; the client just
couldn't see the next outcome). Split:

- `runner.commit_response()` — Phase 1, synchronous; commits the
  interrupt answer + flips run to `running`. Returns a handoff dict.
- `runner.resume_segment()` — Phase 2, may take minutes; drives the
  graph until next interrupt or terminal. Backgrounded by the server.
- `runner.respond()` — kept as the synchronous composition for tests
  and any caller that explicitly passes `?wait_segment=true`.

The `/inbox/{id}/{accept,reject,correct}` endpoints accept
`wait_segment: bool = True`. The MCP-stdio binary
(`orchestrator_accept/reject/correct`) now passes
`wait_segment=false`, so the HTTP call returns immediately after the
answer is committed (`{status: "resuming", workflow_thread_id, ...}`).
The PI session polls `orchestrator_get_run` / `orchestrator_inbox` to
discover the next state. `ORCHESTRATOR_API_TIMEOUT` default bumped
120 → 600s for any caller that still uses the sync path.

**Workspace bind mount (`HOST_WORKSPACE_ROOT`).** The orchestrator
daemon runs in Docker but its `claude-agent-sdk` subprocess (the
Executor) needs to read/write the PI's workspace at the *same
absolute path* the PI sees on the host. The Compose overlay now
mounts:

```yaml
- ${HOST_WORKSPACE_ROOT:-${HOME}}:${HOST_WORKSPACE_ROOT:-${HOME}}:rw
```

Default `$HOME` covers the typical `~/Research/{slug}` layout. For
non-HOME workspace roots (external drives, `/Volumes/base/projects`,
etc.), set `HOST_WORKSPACE_ROOT` in the **repo-root** `.env` (i.e.,
`/Volumes/base/workspace/rka/.env`, gitignored), **not** in
`orchestrator/.env`. Docker Compose reads `.env` from the directory
of the first `-f` file (the repo root here) for YAML `${VAR}`
interpolation; the `env_file:` directive on the service only
populates env vars inside the running container and does not feed
interpolation. Putting `HOST_WORKSPACE_ROOT` in `orchestrator/.env`
fails silently: the mount falls back to `${HOME}` and the workspace
appears empty at runtime. Docker Desktop may need filesystem access
granted for non-`$HOME` roots (System Settings → Privacy → Full Disk
Access). Path translation is identity — the workspace_path the PI
types resolves the same inside and outside the container.

**Executor built-in filesystem tools.** The SDK subprocess's
`allowed_tools` previously contained only the read-side MCP tools
(`mcp__rka__*`, `mcp__context7__*`). The Executor LLM was being
denied `Bash`, `Read`, `Write`, etc. when missions asked it to probe
`.env`, run Python, or write workspace outputs. Added:

```
Bash, Read, Write, Edit, Grep, Glob, WebFetch, WebSearch
```

to `allowed_tools` via the new `_BUILTIN_FILESYSTEM_TOOLS` tuple.
The Phase-2.7 read-only-subprocess invariant is preserved at the RKA
layer — `WRITE_TOOLS` stay on `disallowed_tools` and writes still
flow through `pi_decision_select` → `execute_ratified_actions` —
because built-in FS tools touch the PI's workspace (which the PI
mounted explicitly), not RKA state.

### Phase D2.1 — post-review fixes (background-task lifecycle + substring-routing exploit + thread-safety)

Multi-lens code+design review (workflows w69b6e8kg + wuew2xgc9)
surfaced 95 confirmed findings — 22 bugs, 31 design issues, 20 doc
inconsistencies, 12 risks, 10 nits. Bugs were fixed in this Phase
D2.1 pass.

**Background-task lifecycle.** The `asyncio.create_task(_drive_segment_bg(ack))`
fire-and-forget from Phase D2 had four interlocking gaps that the
review exposed:

- Task could be GC'd mid-run (event loop only keeps weak refs).
  Fixed: tracking on `app.state.bg_segments: set[Task]` with
  `task.add_done_callback(set.discard)`.
- Daemon SIGTERM left runs stuck in `status='running'` forever.
  Fixed: lifespan `finally` block awaits `asyncio.gather(*pending,
  return_exceptions=True)` for 30s before cancelling.
- Daemon restart's startup left previously-running rows orphaned.
  Fixed: new `ParkedStore.reap_orphaned_running_runs()` called from
  lifespan startup; flips orphans to `status='failed'`,
  `last_error='daemon restarted while segment in flight'`.
- `_drive_segment_bg` only logged on failure — left runs in
  `status='running'` with no `last_error`. Fixed: exception path
  now writes `last_error` via `store.update_run(...)` and flips
  status to `'failed'`.

**Substring-routing exploit (privileged-write bypass).** The graph's
`_route_after_pi_*` and `pi_*` node helpers substring-match on
`"approve"` / `"accept"`. Any `action="correct"` text smuggling those
substrings (e.g. "I cannot approve" / "do not accept this") would
silently route to the accept branch, bypassing the TWO-TAP
ratification gate on `pi_decision_select` / `pi_greenlight` /
`pi_acceptance` / `pi_credentials_ready` / `pi_bootstrap_fill_ack`.
Fixed via a sentinel-prefix contract:

- New module `orchestrator/orchestrator/response_tokens.py`:
  `REDIRECT_SENTINEL = "__RKA_REDIRECT__::"` and
  `is_redirect_token()`.
- `runner.resume_token()`: for `action="correct"`, the resume token
  is now `REDIRECT_SENTINEL + response_text` (bare PI text would
  reach the substring routers; the sentinel prefix forces a redirect
  route regardless of what English the PI types).
- All 4 routing helpers (`_route_after_pi_greenlight`,
  `_route_after_pi_decision`, `_route_after_credentials_ready`,
  `_route_after_fill_ack`) and 9 `is_accept` sites in `nodes/pi.py`
  now call `is_redirect_token()` first and short-circuit to the
  escalation/redirect branch.
- Tests pin every routing site with adversarial inputs containing
  "approve"/"accept" substrings.

**SQLite thread-safety.** `ParkedStore` opens one sqlite3 connection
with `check_same_thread=False` and shares it across FastAPI threads
dispatched via `asyncio.to_thread`. No lock guarded `_tx()`, so
concurrent BEGIN/COMMIT could raise OperationalError. Fixed:
`threading.RLock` added; `_tx()` acquires before BEGIN.

**`cancel_run` terminal-state guard.** `cancel_run` was unguarded —
a late cancel arriving after the workflow had auto-completed would
silently rewrite `status='complete'` to `status='cancelled'`, losing
the terminal_state record. Fixed: UPDATE now guarded by `AND status
IN ('running', 'awaiting_pi')`.

**Tilde-prefixed workspace paths.** `pi_onboarding_topic`'s regex
captured `~/Research/...` style paths and stored them verbatim.
Inside the container, `~` would resolve to `/root/` (not the host
`$HOME`), so the HOST_WORKSPACE_ROOT bind mount would miss. Fixed:
regex now matches absolute paths only; PI prompt explicitly forbids
tilde-prefixed paths and explains why.

**Brain + Executor prompts (Phase D2 follow-through).** Both LLMs
were unaware of the newly-granted Bash/Read/Write/Edit/Grep/Glob/
WebFetch/WebSearch tools. Fixed: `BRAIN_SYSTEM` now describes the
read-FS tools as available + warns Brain to stay read-only at the
host FS layer; `EXECUTOR_SYSTEM` now describes the full FS toolkit
+ clarifies that built-in FS tools are unratified workspace-scoped
operations distinct from the ratified RKA writes that flow through
`proposed_actions`.

**HOST_WORKSPACE_ROOT lives in the REPO-ROOT `.env`, NOT
`orchestrator/.env`.** Empirical bug surfaced when the PI followed
the original (incorrect) doc. `orchestrator/.env` is loaded via
`env_file:` for container-internal env vars and does NOT feed
Compose YAML interpolation; only the project-root `.env` (or shell
env, or `--env-file`) does. Both CLAUDE.md and the overlay comment
updated to point to `/Volumes/base/workspace/rka/.env`.

### Phase D2.2 — async-start endpoints (empirical follow-up)

Phase D2 only backgrounded the segment on `/inbox/*/{accept,reject,
correct}`. The hyperscaler-auditing test relaunch hit the same
4-minute-client-timeout failure on `orchestrator_run_start` because
the first segment (Brain strategy_node + confirmation_brief = 2 LLM
calls) takes minutes too. Fixed by giving `/runs`, `/onboard`, and
`/bootstrap` the same `wait_segment=true` (default, sync, for tests)
vs `wait_segment=false` (async-start, for MCP) split:

- `runner.start_run` / `start_onboarding` / `start_phase_b` each
  split into `*_commit` (mints workflow_runs row + loads mission
  spec — fast) and `*_drive` (builds factories + invokes graph —
  slow). The legacy `start_*` methods are kept as the sync
  composition for tests.
- `server._background_segment` is a shared helper used by all
  async-resume paths (start + inbox respond) — tracks the task on
  `app.state.bg_segments`, writes `last_error` on failure,
  participates in lifespan drain.
- MCP `orchestrator_run_start` / `_onboard_start` / `_bootstrap_start`
  now send `?wait_segment=false`. Return shape on the async path is
  `{workflow_thread_id, mission_id, project_id, status: "starting",
   wait_segment: false}`. PI polls `/runs/{id}` and `/inbox` to
  discover the first parked interrupt.
- The MissionNotFoundError → 404 mapping still happens in the
  synchronous commit phase (rka_get_mission is fast) so a missing
  mission still fails-fast at the HTTP layer; only the slow graph
  invoke is backgrounded.

### Phase D2.3 — Bash EROFS fix (empirical follow-up)

The Phase D2 grant of built-in filesystem tools
(Bash/Read/Write/Edit/Grep/Glob/WebFetch/WebSearch) to the SDK
subprocess landed, but **three consecutive runs** of the hyperscaler-
auditing mission's T1 readiness probe surfaced `EROFS` ("read-only
filesystem") on every `Bash` invocation while `Read`, `Write`,
`Edit`, `Grep`, and `Glob` all succeeded. Root cause: the Compose
overlay mounted `${HOME}/.claude:/root/.claude:ro` to expose the
host's Claude credentials, but the claude-agent-sdk subprocess
writes shell-state snapshots (`shell-snapshots/snapshot-zsh-*.sh`)
under `/root/.claude/` on every `Bash` tool call — the `:ro` flag
on the mount made the write fail. Fix:

- Removed the `${HOME}/.claude:/root/.claude:ro` mount entirely
  from `orchestrator/docker-compose.yml`. The container's
  `/root/.claude/` is now a writable container-local directory; the
  SDK creates `shell-snapshots/`, `sessions/`, `file-history/`,
  etc. there as needed and Bash works.
- Kept the `${HOME}/.claude.json:/root/.claude.json:ro` single-file
  mount — the SDK only reads it, no write risk, and it preserves
  the CLI's "global config recognized" warning suppression.
- Auth: the daemon now uses `CLAUDE_CODE_OAUTH_TOKEN` (priority-2
  auth path) exclusively. Run `claude setup-token` on the host
  once to mint a long-lived token, put it in `orchestrator/.env`
  as `CLAUDE_CODE_OAUTH_TOKEN=…`. If the token expires (rare for
  long-lived tokens but possible), the SDK fails fast with a
  clear auth error — much better than the silent EROFS we had
  before.

Trade-off accepted: the daemon and host now have isolated
`.claude` state. The container can't see host's session history,
shell snapshots, or per-project conversation logs — by design.
Daemon Executor is a different actor than the PI's local Claude
Code session and the isolation is desirable for reproducibility +
audit.

### Operational note: rka-worker OOM under low Docker memory

The `rka-worker` container loads the FastEmbed
`nomic-ai/nomic-embed-text-v1.5` model (~250 MB) plus onnxruntime
on startup. Under low Docker Desktop memory allocation (≤ 4 GB,
plus orchestrator + rka-server competing for RAM), the worker can
be OOM-killed during the model load and enter a crash loop
(observed empirically: `OOMKilled=true`, 28+ restarts in minutes).

Workaround: bump Docker Desktop's Resources → Memory to ≥ 6 GB
(8 GB recommended for the full stack). Verify with:

```bash
docker inspect rka-worker --format '{{.RestartCount}} restarts; OOMKilled={{.State.OOMKilled}}'
```

The worker isn't on the PI's critical path — it processes
background jobs for embedding queue / LLM enrichment. The
orchestrator workflow (Brain ⇄ Executor ⇄ PI) does NOT depend on
the worker; the worker being down only degrades search recall on
newly-added notes/decisions. Safe to leave for later.

The root `docker-compose.yml` (the file that defines `rka-worker`)
is off-limits to the `agentic` branch per the bookkeeper
invariant, so this is documentation-only here. A proper fix
(memory limit + `restart: on-failure:N` + lazy embedding load)
belongs upstream on `main`.



### Phase D2.5 — v2.6 (project_id required) absorption

`main` merged the v2.6 contract change (PR #32,
`feat(mcp)!: require project_id on every project-scoped tool`) that
removes the silent-default-to-`proj_default` failure mode at the RKA
MCP layer. Every project-scoped rka_* tool now requires `project_id`
as a kwarg-only parameter; `rka_set_project` is a deprecated no-op;
the `RKA_PROJECT` env var was removed at both the MCP layer
(`rka/mcp/server.py`) and the REST layer (`rka/constants.py`).

`agentic` absorbed this via `git merge origin/main`. Two surface
areas needed updating to keep the orchestrator's Brain ⇄ Executor ⇄
PI loop working against the new contract:

- **Brain + Executor system prompts** (`nodes/brain.py`,
  `nodes/executor.py`) — both now explicitly instruct the LLM that
  every rka_* tool call (read or write) requires `project_id`.
  Without this, the Brain LLM's first `rka_get_status()` would
  raise `TypeError` because the v2.6 server rejects calls without
  `project_id`. The Brain's `proposed_actions` JSON also has to
  carry `project_id` in each action's `args` dict — otherwise
  `execute_ratified_actions` raises `ratified_action_call_failed`
  and the Phase D2.4 EC8 routing guard escalates the run.

- **`llm_client._build_mcp_servers_config`** still passes
  `RKA_PROJECT=<project_id>` to the SDK subprocess's `rka mcp`
  child env. v2.6 RKA no longer reads this env var, so the
  threading is functionally dead — but the kwarg is preserved
  for now as a hint the LLM could read (via `Bash echo
  $RKA_PROJECT`) if it loses track of project context. Future
  cleanup: remove the kwarg threading, or wire a per-call
  project_id injection via a tool decorator.

The orchestrator's parent-side `RestMCPClient` already threads
project_id via the `X-RKA-Project` header on every REST call —
unchanged by v2.6. WRITE_TOOLS dispatched from
`execute_ratified_actions` therefore continue to land correctly,
provided the LLM included `project_id` in each action's `args`.


### Phase-X — Cross-Run Correction Channel

Landed during PI live-test of Run-5: a `pi_greenlight` redirect's
`response_text` was thread-scoped (lived only in `state["interrupts"]` /
`parked_interrupts.response_text` for that workflow_thread_id). After
`orchestrator_run_start` created a fresh thread, `_build_strategy_prompt`
saw `make_initial_state`'s empty `interrupts=[]` and Brain regenerated
the brief from mission body alone — reproducing whatever framing the
redirect was meant to correct. Cross-run continuity was not plumbed.

**Architecture** — adds a `run_overrides JSON` column to `workflow_runs`
(the orchestrator-owned Layer-2 storage that was always the right
seam — the redirect just had no surface there). Two write paths
converge on the same column:

1. **Manual.** `orchestrator_run_start(..., run_instructions=…)`
   accepts an optional PI string. `start_run_commit` writes it as
   `run_overrides["pi_instructions"]`. Redacted from the ack dict so
   it doesn't leak to FastAPI access logs.
2. **Auto-rehydration.** `start_run_commit` calls
   `ParkedStore.list_answered_redirects_for_mission(mission_id,
   since_last_terminal_complete=True, limit=3)` and merges the prior
   `pi_greenlight` `correct` response_texts as
   `run_overrides["prior_redirects"]`. The PI does not need to retype
   a redirect they already submitted on an earlier run of the same
   mission.

Read path: `start_run_drive` reads the column, seeds
`state["run_overrides"]`, and `_build_strategy_prompt` prefixes a
delimited `--- BEGIN PI OVERRIDES (highest priority) --- ... --- END ---`
block at the top of the strategy prompt (BEFORE project status / context /
mission body). The block explicitly instructs Brain to treat the text as
PI directive and prefer it over contradicting mission-body wording.

**PI escape valve.** `orchestrator_cancel_overrides(mission_id)` (new
MCP tool) stamps `mission_metadata.overrides_cleared_at = now()`.
Future runs filter out any prior redirects with
`responded_at <= cleared_at`. Useful when the PI has confirmed prior
corrections are fully absorbed and wants a fresh planning slate without
GC'ing `parked_interrupts`.

**Industry precedent.** Airflow `dag_run.conf` + OpenAI Assistants
`additional_instructions`. The pattern: per-run override lives on the
run record, not the workflow definition. Our `workflow_runs` table was
designed for this; we just hadn't exposed it.

**Excluded designs (with reason).**
- Mission-body append (Option i in design doc) — pollutes RKA's
  system-of-record with workflow-position concerns; inverts the
  three-storage discipline.
- Phase-aware mission structure (Option C / Phase E or F) — correct
  long-term model for budgets/gates/queues, orthogonal to the
  redirect bug; multi-day refactor that needs Phase O's H-step
  semantics to land first.

**Schema migration.** Existing `workflow_runs` rows get the new
nullable column via `_migrate_workflow_runs_run_overrides_if_needed`
in `ParkedStore._init_schema` (sniff-`sqlite_master` pattern,
consistent with `_migrate_project_workspaces_columns_if_needed`).
Also creates `mission_metadata` + `schema_migrations` tables (the
latter is for future migrations; the migration-version-tracking
implementation is its own follow-up).

**Timestamp precision.** `_now_iso()` was bumped from second to
millisecond precision (and `db/schema.sql`'s `strftime` DEFAULTs match).
Two events <1s apart now get distinct stamps — critical because the
`overrides_cleared_at > responded_at` filter would otherwise drop a
legitimate post-clear redirect.

Reference: [`orchestrator/docs/cross-run-correction-channel.md`](orchestrator/docs/cross-run-correction-channel.md)
for the full architectural recommendation including option analysis,
industry comparison, adversarial critique, and acceptance criteria.

### Phase-X² — In-Run Redraft Channel (sibling of Phase-X)

Empirical follow-up surfaced live during attempt-3 of Run-5 on the
hyperscaler-auditing test harness. Phase-X solved cross-run
durability of `pi_greenlight` redirect text; Phase-X² closes the
corresponding in-run gap.

**Bug surfaced.** In `_route_after_pi_greenlight`, a `correct` action
(REDIRECT_SENTINEL-prefixed token) routed to `escalation_router`
identically to a hard `reject`. `escalation_router` is an error
handler — when `state['errors']` was empty (the redirect is not a
genuine error), it synthesized a generic "unclassified" `ErrorRecord`,
emitted a junk checkpoint into RKA, and dead-ended to terminal
`pi_acceptance`. The PI's redirect text was preserved in
`parked_interrupts.response_text` but never reached Brain inside the
same run — the intended semantic ("Brain redrafts the Confirmation
Brief incorporating the PI's correction, then re-parks for
ratification") was never implemented. Phase-X masked this for the
*next* run via auto-rehydration; Phase-X² fixes the *in-run*
dynamic.

**Architecture — Option C** (dedicated redraft node + bounded
back-edge; chosen over the simpler direct-back-edge Option A
because that path silently no-ops if `_build_confirmation_prompt`'s
override prefix is forgotten, and over the heavier auto-restart
Option B because it would require new authorization surface for
cross-thread loops):

- **New node `brain.confirmation_brief_redraft`** owns the redraft
  policy: (1) locate the latest `pi_greenlight` redirect in
  `state['interrupts']` (filtered by node_name to avoid cross-gate
  leakage), (2) sanitize via the existing Phase-X
  `_sanitize_override_text` (H1 delimiter-defang + H2
  REDIRECT_SENTINEL-strip), (3) append to
  `state['run_overrides']['in_run_redirects']` capped at
  `MAX_GREENLIGHT_REDRAFTS` entries, (4) increment
  `state['greenlight_redrafts']`. On cap-exceed (or defensive
  missing-record / empty-text), emit a *real*
  `greenlight_redraft_budget_exceeded` `ErrorRecord` and set
  `next_node_override='escalation_router'` so escalation flows from
  a genuine error, not a synthetic one. Zero LLM calls in this node
  — pure state mutation, cheap.
- **`_format_pi_overrides_block` extended** with a third sub-section
  ("IN-RUN PI REDIRECT (this segment — supersedes any prior framing
  including the prior-run redirects above)") rendered after the
  Phase-X `pi_instructions` + `prior_redirects` sections. Same fence,
  same sanitizer — H1/H2 protections symmetric across cross-run and
  in-run paths.
- **`_build_confirmation_prompt` updated** to prepend the override
  block — symmetric with `_build_strategy_prompt`. On a fresh
  (first-time) brief the block is empty and the prompt is unchanged.
- **`_route_after_pi_greenlight` rewired** to a three-way distinction:
  `approve` → `backbrief_draft` (unchanged), `correct` (sentinel) →
  `confirmation_brief_redraft` (NEW back-edge), `reject`/other →
  `escalation_router` (unchanged genuine hard-reject path). The
  sentinel short-circuit still fires FIRST, preserving the Phase D2.1
  substring-smuggling guard.
- **Bounded loop**: `MAX_GREENLIGHT_REDRAFTS=3` (state.py constant).
  This is the first concrete node-incremented loop counter — closes
  the deferred-followup risk that CLAUDE.md previously flagged
  ("`loop_iterations` never written by any node, so MAX_LOOP_DEPTH
  and budget caps are unreachable"). Sets a positive precedent for
  future loop-bound work.
- **Latent pi.py bug fix** (exposed by redraft cycling exercising
  `pi_greenlight` more often): the original `is_accept` check at
  `nodes/pi.py:115` used `"accept" in response_text`, but
  `pi_greenlight`'s accept token is `"approve"` (per
  `_ACCEPT_TOKEN_BY_TYPE` in `runner.py:46`). Since `"accept"` is
  NOT a substring of `"approve"`, `is_accept` was always False on a
  legitimate approve and the
  `proposed_capabilities → allowed_capabilities` plumbing never
  fired. Fix: also check for `"approve"` substring; sentinel guard
  still short-circuits any approve-smuggling correct token.

**Three-storage discipline preserved.** Redirect text lives in
`state['interrupts']` (LangGraph SqliteSaver) for in-run plumbing and
in `parked_store.parked_interrupts.response_text` (orchestrator
SQLite) for cross-run durability. RKA is unaffected — no domain
truth involves redraft policy.

**Acyclic-convention divergence (documented).** Phase B and
onboarding subgraphs deliberately keep their redirect paths acyclic
(`redirect → END + re-enter`) because their PI-correction lifecycle
crosses workspace state on disk (`.env.example` files persisted,
RKA project records created). The mission graph's pi_greenlight
redirect operates entirely inside one segment's state — no disk
side effects to preserve — so the back-edge is the right tradeoff.
Documented in `_route_after_pi_greenlight` and the topology header
comment.

**Sibling bug filed, NOT bundled.** `_route_after_pi_decision` has
the identical dead-end shape — but `pi_decision_select` is the
TWO-TAP autonomy-licensing gate for privileged WRITE_TOOLS dispatch.
Its redirect-routing fix deserves isolated review (different cost
profile for the redraft target — `decision_present` vs full
`strategy_node` re-run; different EC8 set-identity invariants).
Tracked in the **Deferred follow-ups** list below ("pi_decision_select
redirect dead-ends at escalation_router — same Phase-X² topology shape,
fix as separate PR for autonomy-contract review").

NODE_NAMES tuple grows from 17 → 18 (`confirmation_brief_redraft`).
`test_invariants.py` automatically audits the new node's
`current_node` writes against NODE_NAMES.

**Validated in production traffic on Run-5** (mission
`mis_01KSTWTJNZMV3893S2FWG4HBYZ`, hyperscaler-auditing test harness,
2026-05-31). End-to-end: 4 PI redirects exercised the in-run redraft
loop across the cap, EC8 partial-dispatch routing caught a real
PA-2 422, terminal close at `terminal_state='complete'` activated
the Phase-X C1 cutoff. Empirical follow-ups (validation-chain
hardening) shipped as the Phase-X² polish PR — see CLAUDE.md
"Phase-X² polish — validation-chain hardening" section below.

### Phase-X² polish — validation-chain hardening (Run-5 follow-ups)

Consolidated follow-up PR for the four architectural findings
surfaced during Run-5's live test. All four are validation-layer
hardening that shortens the diagnostic chain when a Brain proposal
hits the API boundary:

- **`RestMCPClient._request` preserves FastAPI 422 detail** —
  Run-5's PA-2 failure surfaced as the opaque "knowledge-pack
  integrity" label. The actual API response carried structured
  detail (`body.confidence='confirmed'` + the valid-values list)
  that got collapsed. The 422 branch now renders the Pydantic
  validation-error list into the `CheckpointError` reason string
  (field-name + offending value + message) while preserving the
  full parsed body on `mcp_response` for programmatic inspection.
  Falls through to the legacy "knowledge-pack integrity" label
  for Affordance-G shapes (custom `{error, detail: str, hint}`).
  Includes Unicode-codepoint-safe truncation at 80 chars per
  value + ~500 chars total with `+N more` overflow marker +
  secret-redaction when the `loc` path matches the extended
  `_SECRET_LOC_HINTS` vocabulary (token/key/secret/password/auth
  + credential/passphrase/bearer/pwd/pin/cookie/session/cert/
  signature/private).
- **`execute_ratified_actions` pre-dispatch enum validator** —
  new module `orchestrator/rka_enums.py` provides per-tool
  `TOOL_ARG_ENUMS` lookup + `validate_action_args(tool, args)`.
  Catches Run-5's `confidence='confirmed'` (and structurally
  equivalent failure modes — decision kind mismatch, importance
  typo, etc.) BEFORE the network round-trip. Emits a new
  `ratified_action_arg_invalid_enum_value` ErrorRecord with
  skip-and-continue semantics (mirrors `ratified_action_tool_not_allowed`).
  EC8 partial-dispatch routing already escalates on any
  ErrorRecord scoped to `execute_ratified_actions`, so the new
  error type integrates without graph changes.
- **BRAIN_SYSTEM + EXECUTOR_SYSTEM enumerate valid RKA enum values
  + forbidden lifecycle tools** — Run-5 v3 PA-2 surfaced two
  Brain-prompt gaps. (a) Brain proposed `rka_advance_rq` despite it
  not being in WRITE_TOOLS (skill docs in `rka/skills/brain/workflows.md`
  list it as a Brain tool for direct-Claude flows; the orchestrator
  parent-side dispatcher does NOT allowlist it). BRAIN_SYSTEM now
  expands WRITE_TOOLS inline + explicitly forbids
  `rka_advance_rq` / `rka_resolve_checkpoint` /
  `rka_supersede_decision` / `rka_present_decision` with rationale.
  (b) Brain proposed `confidence='confirmed'` because no
  field-value enum was in the prompt. BRAIN_SYSTEM (and
  EXECUTOR_SYSTEM) now enumerate the canonical sets for
  `confidence`, `importance`, `source`, `type` (v2 canonical),
  `status` (journal lifecycle), `decided_by`, `kind` (decision),
  `status` (decision lifecycle), `type` (checkpoint), `status`
  (mission). Includes negative callout: *"The value 'confirmed' is
  NOT valid (common Brain hallucination)."*
- **Bookkeeper invariant preserved** — new `rka_enums.py` is a
  **manual mirror** of `rka/db/schema.sql` + `rka/models/*.py`,
  documented as such. NO `from rka` / `import rka` anywhere in
  the new module (test_rka_enums.py::test_module_does_not_import_rka
  AST-scans the source to enforce). Drift is reconciled manually
  when RKA's schema or Pydantic models change.

Adversarial-review hardening (workflow w6de8mbjz, 4 lenses):
- `rka_ingest_document` added to `TOOL_ARG_ENUMS` (was a gap —
  in WRITE_TOOLS but missing from the validator's lookup).
- `rka_create_mission` removed from `TOOL_ARG_ENUMS` —
  `MissionCreate` has no `status` field (`extra='forbid'`), so
  advertising a `status` enum check would mislead about coverage.
- `_SECRET_LOC_HINTS` extended from 7 → 17 fragments to cover the
  common credential vocabulary (the 422 reason surface crosses
  workflow_runs → parked_interrupts → RKA journal — leaving any
  credential-naming field unredacted was a real secret-leak path).
- Three "dead" `TOOL_ARG_ENUMS` entries (`rka_update_decision`,
  `rka_add_literature`, `rka_update_literature`) pruned because
  they're not in WRITE_TOOLS — re-add when/if they land in the
  dispatcher allowlist.

Test count delta: +64 net (1084 → 1148). Bookkeeper invariant
(`git diff main -- rka/`) unchanged from Phase-X² shipped state.

**Cross-references.** PI-facing wording lives in
[`orchestrator/skills/orchestrator-pi.md`](orchestrator/skills/orchestrator-pi.md)
("What `correct` does at each gate"); the Phase-X sibling design
(cross-run channel; shares the `run_overrides` field) is at
[`orchestrator/docs/cross-run-correction-channel.md`](orchestrator/docs/cross-run-correction-channel.md).
The sibling bug (`_route_after_pi_decision` has the same dead-end
shape) is filed in the **Deferred follow-ups** list below — fix
deserves isolated review because pi_decision_select is the TWO-TAP
autonomy-licensing gate for privileged WRITE_TOOLS.

### Phase D2.6 — async-resume watchdog (silent post-segment stall fix)

Empirical follow-up from the 2026-06-01 hyperscaler-auditing live
test. After a `pi_decision_select` `accept`, the orchestrator returned
`{status: 'resuming', ...}` but the actual run sat at `status='running'`
for minutes with no parked interrupt, no terminal_state, no exception.
Workflow `wqicgntwi` (5-facet discovery) converged on the root cause:
the background thread driving `compiled.invoke()` deadlocked on the SDK
subprocess stdout pipe wait. The bg helper's only failure path was
exception → write `last_error`; clean-but-no-progress was unhandled.

**Architecture.** Added module-level helpers in
`orchestrator/orchestrator/server.py`:

- `_WatchdogProbe` (frozen dataclass) — snapshots four structural
  signals: `status`, `checkpoint_id`, `pending_interrupt_ids`,
  `terminal_state`. Plus `live_current_node` + `live_usd_spent` from
  the LangGraph checkpoint and `cached_current_node` + `cached_usd_spent`
  from `workflow_runs` for the cache-sync side effect.
- `_read_live_probe_fields(thread_id, saver_path)` — opens a fresh
  `sqlite3` connection + `SqliteSaver`, reads `tup.checkpoint['id']`
  and `channel_values['current_node' / 'usd_spent']`. Graceful
  degradation: returns `(None, None, 0.0)` on any failure.
- `_capture_probe(store, saver_path, thread_id)` — composes the probe
  from workflow_runs (cache) + parked_interrupts.list_pending_interrupts
  (orchestrator-owned) + the live checkpoint.
- `_probe_advanced(before, after) -> bool` — disjunction over four
  signals: status flipped away from 'running', terminal_state newly
  set, checkpoint_id changed (tolerates None on either side), or
  pending interrupt set IDENTITY changed (catches park-then-answer
  races where cardinality is equal but identity differs).
- `_cache_sync(store, thread_id, probe)` — idempotent push of live
  `current_node` and (monotonic-non-decreasing) `usd_spent` into
  the workflow_runs cache row at the watchdog boundary. Best-effort:
  a write failure logs but does not derail the watchdog's primary
  purpose.

**Watchdog wiring** (`_background_segment` inside `create_app`):

1. Capture `before = _capture_probe(...)` before await.
2. `await coro_factory()` in existing try/except.
3. On clean return, capture `after = _capture_probe(...)`.
4. If `_probe_advanced(before, after)` → `_cache_sync`, return.
5. Else log warning + perform ONE bounded retry of the same
   `coro_factory()`.
6. After retry, if still no advance → `update_run(status='failed',
   last_error='watchdog: ... returned without advancing after single
   retry; likely SDK subprocess pipe wait or LangGraph internal
   early return (checkpoint_id=...)')`.

The retry is bounded to a single attempt — Option A from the
synthesis. Empirical evidence (the manual kick on
`thr_19e838ecc3054efe626` advanced 5 nodes) shows the LangGraph-
internal-early-return class recovers on a fresh invoke; deterministic
stalls (SDK pipe-wait deadlock) need surfacing rather than masking,
hence the escalation after one retry.

**Consolidation.** The previously-inline `_drive_segment_bg` closure
inside `/inbox/{id}/{accept,reject,correct}` (server.py:1281-1318)
had structurally identical lifecycle handling but WITHOUT the
watchdog. Refactored to call the shared `_background_segment` helper.
All four async-resume callsites (`/runs`/start_run_drive,
`/onboard`/start_onboarding_drive, `/bootstrap`/start_phase_b_drive,
`/inbox/*`/resume_segment) now share one set of probe-and-retry
semantics.

**Runner-side hardening** (`runner._execute_segment`). Two
amplifier-class defects fixed:

- Non-dict `compiled.invoke()` return previously fell through to
  the terminal branch's `output.get(...)` which raised
  `AttributeError`. Now wrapped in `try/except`; the AttributeError
  surfaces as `status='failed'` with a structured `last_error`.
- The silent `or 'complete'` default on missing `terminal_state`
  labelled any non-interrupt early return as success — the LangGraph
  internal early-return class (`pregel/_loop.py:645-647`
  `if not self.tasks: ... return False` when `prepare_next_tasks`
  returns empty). Removed; explicit `RuntimeError` now fires for
  dict outputs that have neither `__interrupt__` nor
  `terminal_state`. Unexpected terminal_state VALUES are still
  normalised to 'complete' (back-compat).

**Three-storage discipline preserved.** Probe reads workflow_runs
(orchestrator-owned), the LangGraph checkpoint (workflow-position
storage), and parked_interrupts (orchestrator-owned). It does NOT
touch RKA domain truth. Bookkeeper invariant intact (`git diff main
-- rka/` empty); grep-gate intact (no new `from rka` imports).

**Tests** (`orchestrator/tests/test_watchdog.py`, 37 tests).
Coverage: probe-advance disjunction over each signal + None-
checkpoint tolerance + fresh-saver advance + status-already-non-
running guard (adversarial review MEDIUM #1); capture_probe reads
workflow_runs / parked_interrupts / live + graceful degrade +
swallowed-exception paths for get_run and list_pending_interrupts;
cache_sync writes-when-differs + noop-in-sync + noop-no-live +
monotonic-usd + swallowed-exception path; integration via FastAPI
TestClient for /inbox/{id}/accept (happy-path / transient stall /
deterministic stall / exception bypass) AND start_run_drive /
start_onboarding_drive / start_phase_b_drive (the three async-start
paths previously uncovered by the watchdog integration suite);
set-identity test for the park-then-answer race; real SqliteSaver
round-trip; terminal_safe overwrite-protection (cancel races
watchdog escalation → cancel wins); last_error 500-char truncation
cap; 4 runner-side tests (non-dict / None output / missing-
terminal-state warning-default / unexpected-terminal-state
normalisation).

**Adversarial review** (workflow `wdxj6zm3b`, 4 lenses + verify):
32 findings surfaced, 23 confirmed, 9 refuted. Landed in this PR:

- **Critical #1** — runner's strict `terminal_state` required
  check broke legitimate END terminals for Phase B / onboarding /
  Phase O. **Fix**: defaulted to 'complete' with a warning log;
  the watchdog catches the silent-stall class authoritatively.
- **High #1 + #2** — escalation overwrites terminal states via
  unguarded update_run. **Fix**: added
  `terminal_safe: bool = False` kwarg to
  `ParkedStore.update_run`; when True, adds
  `AND status IN ('running', 'awaiting_pi')` to the WHERE clause
  and returns rowcount. Applied at all watchdog escalation
  sites (initial-crash, retry-crash, deterministic-stall
  escalation, retry-cancelled diagnostic).
- **High #3** — start-path watchdog not covered. **Fix**: added
  3 integration tests + extended `_WatchdogFakeRunner` with
  scriptable `start_run_drive` / `start_onboarding_drive` /
  `start_phase_b_drive`.
- **Medium #1** — `_probe_advanced` disjunct 1 false-positive
  when before.status was already non-running. **Fix**:
  tightened to `before.status == 'running' and after.status !=
  'running'`.
- **Medium #3** — probe sqlite I/O on event loop. **Fix**:
  wrapped each `_capture_probe` invocation in
  `await asyncio.to_thread(...)`.
- **Medium #4, #5, #6, #7, #8** — five test-gap items. **Fix**:
  10 new tests addressing each gap.
- **NIT #4** — test-count floor 50 was so generous it provided
  no real CI guarantee. **Fix**: bumped to 1100 in
  `test_invariants.py` (leaves ~80 deletes' headroom for
  refactors but catches catastrophic regressions).

Deferred to follow-up PRs (added to the **Deferred follow-ups**
list below):

- **MEDIUM #2** — coro hang detection (asyncio.wait_for around
  the await). Watchdog catches the silent-return case empirically
  observed; the hung-subprocess case would need configurable
  per-coro timeout. Design decision: defer until a real hung
  case surfaces in production.
- **LOW #5** — _read_live_state vs _read_live_probe_fields code
  duplication; refactor to shared `_open_checkpoint_tuple` helper.
- **LOW #6** — roadmap doc test-count claim. Reconciled in-PR.
- **LOW #7** — _background_segment grew to 130 lines; extract
  `_safe_update_run_last_error` + `_watchdog_drive_once` helpers
  for testability. Pure refactor, no behaviour change.
- **NIT #3** — `run_overrides` not probed (intentional, per
  three-storage discipline). Documentation-only follow-up.

Reference: workflow `wqicgntwi` (5-facet root-cause synthesis,
2026-06-01); workflow `wdxj6zm3b` (4-lens adversarial review,
2026-06-01);
[`orchestrator/docs/v2.6.x-roadmap.md`](orchestrator/docs/v2.6.x-roadmap.md)
§4 — PR1; orchestrator/pyproject.toml bumped 0.6.0 → 0.6.1.

### Phase-X²' polish — schema-divergence validation chain (field-NAME layer)

Sibling fix to the Phase-X² polish (validation-chain hardening at the
field-VALUE layer). Phase-X² closed the enum-VALUE validation gap;
Phase-X²' closes the field-NAME validation gap that empirically
surfaced on 2026-06-01 hyperscaler-auditing PA-2:
`rka_submit_checkpoint(content=...)` instead of `description=...`.
The enum-VALUE validator returned empty; the adapter at
`mcp_client.py:574` then raised `ValueError` at dispatch time and
EC8 escalated to a failure checkpoint. The PI session manually
resolved per Path (i) (resolve EC8 failure checkpoint with the
substantive Q1-Q4 answers + root cause).

**5-facet root-cause analysis** (workflow `wjyk2x82n`, 2026-06-01)
identified the structural mechanism: RKA's 9 WRITE_TOOLS use FIVE
different vocabularies for the same semantic role ("primary body
field"): `content` (3 tools: rka_add_note, rka_update_note,
rka_ingest_document), `question` (rka_add_decision), `objective`
(rka_create_mission), `description` (rka_submit_checkpoint),
`summary` (rka_submit_report). Brain's only worked example in
EXECUTOR_SYSTEM uses `content=` for rka_add_note, which generalises
incorrectly across sibling write tools.

**Four-layer fix** (per the design doc at
[`orchestrator/docs/phase-x-prime-polish-design.md`](orchestrator/docs/phase-x-prime-polish-design.md)
§5; all four ship atomically because any one alone is a treadmill):

- **Layer 1 — `content` alias on `rka_submit_checkpoint` adapter.**
  `orchestrator/orchestrator/mcp_client.py:567-579`. Symmetric with
  `rka_submit_report` (which has accepted `content` since Phase
  D2.4). The asymmetry between sibling EXECUTION_GATES tools was
  the proximate bug. Collision rule: `description` wins when both
  are supplied.
- **Layer 2 — `TOOL_REQUIRED_FIELDS` + `check_required_fields`.**
  `orchestrator/orchestrator/rka_enums.py`. Alias-set-of-sets
  data structure (`dict[str, list[frozenset[str]]]`) so legitimate
  `message=`-only or `reason=`-only calls satisfy the body-field
  set. Wired into `execute_ratified_actions` immediately after the
  Phase-X² enum check. New
  `ratified_action_arg_missing_required_field` ErrorRecord with
  skip-and-continue semantics; integrates with EC8 routing without
  graph changes. Per-tool entries for 9 WRITE_TOOLS; excludes
  `project_id` (dispatcher-injected per Phase E6); bookkeeper-safe
  manual mirror of `mcp_client.py` adapter signatures, lock-tests
  pin each entry against drift.
- **Layer 3 — Canonical-field-name block in BRAIN_SYSTEM +
  EXECUTOR_SYSTEM.** Per-tool canonical-name table for all 9
  WRITE_TOOLS + explicit "common Brain hallucination" negative
  callout for `content=` on `rka_submit_checkpoint`. Symmetric
  with the existing Phase-X² `confidence='confirmed'` callout.
- **Layer 4 — PI diagnostic surface on `pi_acceptance` payload.**
  Three new top-level fields: `latest_error_type`,
  `latest_failed_tool`, `latest_checkpoint_reason`. Closes the
  drill-into-errors[] gap that made the 2026-06-01 mission's
  triage take longer than necessary; the PI cockpit can now read
  the specific escalation cause from the top-level interrupt
  payload.

**Order in `execute_ratified_actions`**: enum validator FIRST,
then required-field validator, then project_id consistency check,
then dispatch. An action with both a wrong enum value AND a
missing required field surfaces the enum error first (more
actionable for Brain — wrong values give Brain a hint about what
to fix; missing fields don't carry that signal).

**Three-storage discipline preserved.** New validator reads
proposed_actions args (LangGraph state); writes ErrorRecord into
state.errors (LangGraph state); never touches RKA domain truth.
Phase-X² + Phase-X²' share the `rka_enums.py` manual-mirror
module — same bookkeeper-safe posture, same drift-detection
lock-tests.

**Tests** (27 new): 11 in `test_rka_enums.py` (validator unit
semantics + alias-set + lock-tests + project_id-excluded
invariant), 4 in `test_mcp_client.py` (Layer 1 adapter alias +
collision rule + missing-body), 3 in `test_executor.py` (dispatcher
integration: missing-required emits ErrorRecord, content alias
satisfies, message alias satisfies), 9 in new
`test_phase_x_prime_polish.py` (Layer 3 prompt assertions + Layer
4 PI surface). 3 pre-existing test fixtures tightened to satisfy
the new validator (the fixtures were sloppy — the validator caught
them, which is correct behaviour).

**Deferred to follow-up PRs** (in the **Deferred follow-ups** list
below): `rka_add_decision` adapter expansion to accept canonical
`question` kwarg; `rka_create_mission` adapter expansion for
canonical `tasks`/`context`/`checkpoint_triggers`; `**kw` adapter
tightening (silent-drop unknown kwargs); pre-dispatch ID-prefix
validator; pre-dispatch type-shape validator. RKA-side
improvements (additive aliases, Annotated Literal type hints,
schema-lie fix on rka_submit_report, docstring sweep, 4xx/5xx
response enrichment) land separately as main v2.6.1 + v2.6.2 per
the roadmap.

Reference: design doc
[`orchestrator/docs/phase-x-prime-polish-design.md`](orchestrator/docs/phase-x-prime-polish-design.md);
roadmap
[`orchestrator/docs/v2.6.x-roadmap.md`](orchestrator/docs/v2.6.x-roadmap.md)
§5 — PR2; root-cause workflow `wjyk2x82n` (2026-06-01);
`orchestrator/pyproject.toml` 0.6.1 → 0.6.2.

### Phase S4 — per-call LLM-timeout layer (silent in-segment stall fix)

Empirical follow-up from the 2026-06-03 hyperscaler-auditing live test
on `mis_01KT0HP12N51TXXKGKQ097RD1P` / thread `thr_19e8eebfb58ef007ac2`.
PI cockpit observed a backbrief stall measured in minutes during the
backbrief → confirmation_brief → acceptance transition; the run sat
at `status='running'` with no parked interrupt, no terminal_state,
no exception, until the Phase D2.6 segment-level watchdog eventually
fired an opaque "no progress" escalation. Phase S4 closes the gap
ONE LEVEL DOWN: per-call timeouts that surface a classified
`llm_call_timeout` ErrorRecord BEFORE the segment ever finishes.

**Architecture (Protocol-level seam).** The single point of injection
is `SDKClient.complete()`. A new `timeout_s: float | None = None`
kwarg propagates to `_RealSDKClient._async_complete`, which wraps the
streaming-consumption loop in `asyncio.wait_for` and converts
`asyncio.TimeoutError` to a new `SDKTimeoutError` at the Protocol
boundary. Per-node constants live in `llm_client.py`:

- `SDK_TIMEOUT_DEFAULT_S = 240.0` — plain LLM call (5 of 6 Brain
  sites + `submit_report`).
- `SDK_TIMEOUT_BACKBRIEF_S = 480.0` — `backbrief_draft` (does MCP
  reads to research the mission body).
- `SDK_TIMEOUT_TOOL_USE_S = 600.0` — `mission_execute` (iterates
  tool-use turns; needs the largest budget).

Defaults are GENEROUS (3-10× a typical call) so we only intercept
genuine hangs, never slow legitimate calls.

**Per-node wraps.** All 9 `sdk.complete()` call sites across
`nodes/brain.py` (6: `strategy_node`, `confirmation_brief`,
`decision_present`, `cluster_review`, `gate1_validation`,
`final_synthesis`) and `nodes/executor.py` (3: `backbrief_draft`,
`mission_execute`, `submit_report`) are now wrapped in a
try/except SDKTimeoutError. On hit, the node returns a state update
shaped identically to the Phase-X² `confirmation_brief_redraft`
cap-exceeded pattern: real ErrorRecord with `error_type='llm_call_timeout'`
+ `next_node_override='escalation_router'`. The escalation_router
sees a classified error rather than synthesizing an unclassified one.

Helper `_sdk_timeout_error_state(...)` is duplicated across
`nodes/brain.py` and `nodes/executor.py` (parallel implementations
rather than a shared module — keeps the two node files independently
reviewable, matches the existing `_now_iso`/`_artifact`/`_accrue_cost`
parallel-helper convention).

**Complementarity with Phase D2.6 watchdog.** The watchdog catches
the OUTER class of stall — a segment that returns cleanly but did
not advance (e.g. SDK subprocess pipe-wait deadlock detected only
after the LangGraph segment finishes). Phase S4 catches the INNER
class — a single hung LLM call inside that segment. Both layers
remain in place: the watchdog is the final safety net for residual
no-progress cases; S4 surfaces a specific classified cause when the
hang is at a single LLM turn (which is the empirical 2026-06-03
failure shape).

**Coverage gates.** `test_sdk_timeouts.py` includes lock-tests that
fail if a new `sdk.complete()` call site lands in either node file
without a `try:` line within the prior 3 source lines. Future
contributors cannot ship a new LLM call site that bypasses the
timeout discipline.

**Three-storage discipline preserved.** The new ErrorRecord lives in
`state.errors` (LangGraph state); the timeout config lives in
`llm_client.py`; nothing new in RKA. Bookkeeper invariant intact
(`git diff main -- rka/` empty); grep-gate intact (no new
`from rka`/`import rka` in orchestrator/).

**Tests** (+18 net). `tests/test_sdk_timeouts.py` covers three layers:
(1) Protocol contract — `timeout_s` kwarg + `SDKTimeoutError` class
shape + constants ordering; (2) `asyncio.wait_for` integration —
real `_RealSDKClient._async_complete` against a SimpleNamespace
stub of `claude_agent_sdk` proving hung-stream-raises +
fast-stream-returns + None-timeout-disabled paths; (3) per-node
wraps — `_TimeoutSDK` fake raises `SDKTimeoutError`, all 9 nodes
return the canonical error_state with the correct per-node budget.

Full suite: 1296 passed, 2 skipped, 0 failures.

Reference: empirical bug surfaced 2026-06-03 hyperscaler-auditing
run; `orchestrator/pyproject.toml` 0.6.9 → 0.6.10.

### Deferred follow-ups

Deferred from the Phase D2.1 review — non-blocking but should
land before the next major orchestrator pass:

- **`pi_extend_toolkit`** is registered in the type literal +
  `_ACCEPT_TOKEN_BY_TYPE` + `_ONBOARDING_INTERRUPT_TYPES` but
  has no node and no graph wiring — half-built feature.
- **`loop_iterations` / `usd_spent`** are read by `budget_check`
  + `consensus_check` but never written by any node — the
  MAX_LOOP_DEPTH and budget caps are unreachable. SDK token-cost
  threading + per-node loop increment needed.
- **`Phase B bootstrap` writes `orchestrator/.env` inside the
  container** — host file is consumed via `env_file:` but not
  bind-mounted, so the bootstrap-emit-template and bootstrap-verify
  nodes write/read at `/app/orchestrator/.env` which the PI never
  sees. Needs either a bind mount or a path-translation strategy.
- **`$HOME` bind-mount over-broad** — when `HOST_WORKSPACE_ROOT`
  isn't set, the daemon RW-mounts the entire `$HOME` (including
  `~/.ssh`, `~/.aws`). Workspace-scoped mount needs a refusal to
  start with a `$HOME`-equivalent root.
- **`WebFetch` / `WebSearch` un-policed** — granted to the
  subprocess with `permission_mode='dontAsk'`. No egress allowlist.
- **Brain over-escalation risk** — Brain prompt now mentions FS
  tools but no per-call policy enforces read-only at the host FS;
  audit trail for any Brain-initiated Bash/Write would be valuable.
- **Phase-X² sibling — `_route_after_pi_decision` dead-end** —
  `pi_decision_select` `correct` routes to `escalation_router` which
  synthesizes an unclassified checkpoint and terminates. Same shape
  as the Phase-X² pi_greenlight bug, but the redraft target is the
  TWO-TAP autonomy-licensing gate. Fix as separate PR for
  autonomy-contract review; decide redraft target (`decision_present`
  cheap re-render vs `strategy_node` full re-strategize) with
  explicit EC8 set-identity check on the loop-back.
- **Phase-X² polish (from wrhahen1y adversarial review)** —
  non-blocking but worth a sweep: (a) `confirmation_brief_redraft`
  cap-exceeded return omits `greenlight_redrafts: next_count` (counter
  freezes at pre-increment) — cosmetic for current topology; (b) align
  `_route_after_pi_greenlight` substring check with `pi.py:115` (both
  `accept` and `approve`) via a shared `_is_accept_token` helper;
  (c) bump `nodes/pi.py:_now_iso` to millisecond precision (parked_store
  already does; `state['interrupts'][*].timestamp` currently seconds);
  (d) collapse dead `in_run_redirects[-MAX:]` trim into an `assert`
  (budget guard makes it unreachable); (e) surface
  `latest_error_type` and `latest_checkpoint_reason` on the
  `pi_acceptance` payload so the PI sees specific escalation cause
  rather than only `error_count`; (f) tighten orchestrator-pi.md
  AskUserQuestion 'Correct' description to surface gate-specific
  Phase-X² semantics before the option choice; (g) add BRAIN_SYSTEM
  instruction defining literal override-block delimiters to defend
  against XML / setext / `</PI_OVERRIDES>` fence-equivalent markers
  (separate class from H1's Unicode/case/markdown defenses, already
  hardened).
- **D3b** — SerpAPI augmentation for `research_toolkit_node`
- **D6** — `pi_extend_toolkit` for mid-mission tool addition
- **Phase E** — Capability categories replacing static WRITE_TOOLS
- **Phase F** — Topology variants (light/heavy mission classes)
- **Phase G** — Actuator subagent (Bash/Edit/Write tools behind ratification)
- **v2.6 dead env-var threading** — `llm_client._build_mcp_servers_config`
  still sets `RKA_PROJECT` on the rka MCP child env, which v2.6
  doesn't read. Remove or repurpose as an LLM hint.
- **Per-call project_id injection** — explicit pass-through on every
  rka_* call is verbose; consider a tool-call decorator that auto-injects
  project_id from workflow state.
