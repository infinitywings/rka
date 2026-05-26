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
