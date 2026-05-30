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
- **D3b** — SerpAPI augmentation for `research_toolkit_node`
- **D6** — `pi_extend_toolkit` for mid-mission tool addition
- **Phase E** — Capability categories replacing static WRITE_TOOLS
- **Phase F** — Topology variants (light/heavy mission classes)
- **Phase G** — Actuator subagent (Bash/Edit/Write tools behind ratification)
