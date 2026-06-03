# Deployment from scratch - RKA core (main branch) on a fresh Mac

This guide walks a fresh macOS install from "Docker Desktop installed, nothing else done" to a running Research Knowledge Agent (RKA) instance integrated with Claude Desktop and Claude Code. It covers the **`main` branch only**: the core RKA (FastAPI REST API + SQLite/FTS5/sqlite-vec + React web UI + stdio MCP binary), brought up via Docker Compose, and wired into Claude as an MCP server. The PI drives the Brain/Executor/PI workflow themselves by loading skill prompts in a Claude session — there is no long-running orchestrator daemon.

**This covers the main branch (core RKA). For the agentic branch (RKA + orchestrator daemon), see [CLAUDE.md](CLAUDE.md) — the "Agentic Branch + Orchestrator Package" section is where the long-running daemon surface is currently documented.**

---

## Which doc do I need?

Pick **this doc (main)** if you want a research knowledge base + MCP-tool integration with Claude Desktop / Claude Code, and you're happy driving the Brain/Executor/PI loop yourself by loading skills in a chat. Pick the **"Agentic Branch + Orchestrator Package" section of [CLAUDE.md](CLAUDE.md)** if you also want the LangGraph orchestrator daemon that runs missions autonomously (Brain ⇄ Executor ⇄ PI with parked interrupts, mid-session ratification, and a second MCP binary). The agentic surface is a strict superset of this one — start here if you're unsure.

---

## Audience + prerequisites assumptions

Two readers in parallel:

- **Human developer** following this top-to-bottom on a fresh Mac.
- **Autonomous code agent** (Claude Code) executing the same steps; see [§ For autonomous code agents](#for-autonomous-code-agents) for the pass/fail checklist.

**Already installed (assumed):**
- macOS 12 (Monterey) or newer; Apple Silicon or Intel both supported
- Claude Desktop
- Claude Code (`claude` CLI)
- Docker Desktop (running, daemon reachable)

**Not needed on main (in contrast to agentic):**

| Tool / artifact | Why main doesn't need it |
|---|---|
| Node.js / npm | Web UI is built **inside** the Docker image during `docker build`. The host never runs `npm`. |
| `claude setup-token` / `CLAUDE_CODE_OAUTH_TOKEN` | No `claude-agent-sdk` subprocess. The MCP binary is a thin stdio proxy. |
| Repo-root `.venv` with LangGraph deps | Nothing on the host imports `rka.*`. Everything runs in Docker. |
| `HOST_WORKSPACE_ROOT` in `.env` | No bind-mounted PI workspace. |
| `rka-orchestrator-mcp` binary | Doesn't exist on main. |
| 6 GB Docker memory floor | 4 GB is the floor (6 GB still recommended to avoid `rka-worker` OOM headroom issues — see [§ 1.1 Worker-OOM note](#11a-rka-worker-memory-floor-context)). |

**Still required on main** (installed in [§ Prerequisites](#1-prerequisites)):
- Xcode Command Line Tools (provides `git`)
- `uv` (Astral) for the optional smoke-test install of the `rka` MCP binary
- Stock macOS `/usr/bin/python3` is sufficient for the validation snippets in this doc; you only need Homebrew Python 3.11+ if you also intend to run the pytest suite on the host (not covered here).

---

## Layout overview

```
                           Host (macOS)
                           ============
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   Claude Desktop  ─────┐         Claude Code  ─────┐                │
│   (GUI app)            │         (terminal)        │                │
│                        │                           │                │
│                  reads │                     reads │                │
│                        v                           v                │
│   ~/Library/Application Support/Claude/                             │
│      claude_desktop_config.json   (shared MCP-server scope on mac)  │
│                        │                           │                │
│                        └─────────────┬─────────────┘                │
│                                      │                              │
│                          spawns MCP stdio process                   │
│                                      │                              │
│                                      v                              │
│             ┌──────────────────────────────────────────┐            │
│             │  docker exec -i rka-server rka mcp       │            │
│             │  (stdio JSON-RPC <--> HTTP)              │            │
│             └──────────────────────────────────────────┘            │
│                                      │                              │
│                                      │ HTTP localhost:9712          │
│                                      v                              │
│ ┌─────────────────────── Docker Desktop ────────────────────────┐   │
│ │                                                               │   │
│ │   ┌───────────────────┐         ┌──────────────────┐          │   │
│ │   │ rka-server        │         │ rka-worker       │          │   │
│ │   │ FastAPI :9712     │<───────>│ background       │          │   │
│ │   │ + web/dist/       │  shared │ embedding queue  │          │   │
│ │   │   (React SPA)     │  volume │ (FastEmbed)      │          │   │
│ │   └─────────┬─────────┘         └─────────┬────────┘          │   │
│ │             │                             │                   │   │
│ │             └─────────────┬───────────────┘                   │   │
│ │                           v                                   │   │
│ │             ┌───────────────────────────┐                     │   │
│ │             │ Docker volume: rka-data   │                     │   │
│ │             │ /data/rka.db (SQLite +    │                     │   │
│ │             │  FTS5 + sqlite-vec)       │                     │   │
│ │             └───────────────────────────┘                     │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
│   Host binary (optional, only for smoke test):                      │
│   ~/.local/bin/rka  (created from this repo via pyproject.toml      │
│                      [project.scripts].rka entry; the recommended   │
│                      setup uses the docker-exec MCP shape above     │
│                      and never invokes this binary directly)        │
└─────────────────────────────────────────────────────────────────────┘
```

The MCP binary is **stateless**: every tool call is forwarded over HTTP to the FastAPI in `rka-server`. The SQLite DB lives only in the Docker-managed `rka-data` volume — never on the host filesystem.

Note on Claude config paths: on macOS, both Claude Desktop and Claude Code read MCP-server config from `~/Library/Application Support/Claude/claude_desktop_config.json`. Claude Code additionally maintains `~/.claude.json` for user-level credentials/session state, but the MCP-server entries used by this doc live in the shared Claude config path. Cross-platform config locations are tabulated in `INSTALL.md` § 4.

---

## 1. Prerequisites

### 1.1 Verify macOS + Docker Desktop

```bash
sw_vers -productVersion
uname -m
docker --version
docker info --format 'CPUs={{.NCPU}}  MemMiB={{div .MemTotal 1048576}}'
docker compose version
docker ps
```

**Expected output:**
- `sw_vers` reports `12.0` or higher (`13.0+` matches CI).
- `uname -m` reports `arm64` or `x86_64`.
- `docker --version` reports `Docker version 24.x` or newer.
- `MemMiB` is **≥ 4096** (≥ 6144 strongly recommended — see [§ 1.1a](#11a-rka-worker-memory-floor-context) and [§ 7.3](#73-rka-worker-oom-docker-memory--4-gb)).
- `docker compose version` reports `v2.x`.
- `docker ps` returns without error.

If memory is too low: Docker Desktop → Settings → Resources → Memory → slide to ≥ 4 GB (6 GB preferred) → Apply & Restart.

**Scripted fallback (Apple Silicon).** The Docker Desktop memory limit is persisted at `~/Library/Group Containers/group.com.docker/settings-store.json` (key `memoryMiB`). If you cannot drive the GUI (running headless / via remote agent), edit that file directly with a JSON-aware tool, then `osascript -e 'tell application "Docker" to quit'` and relaunch `open -a Docker`. Wait for `docker ps` to succeed before continuing.

### 1.1a `rka-worker` memory-floor context

The `rka-worker` container loads the FastEmbed `nomic-ai/nomic-embed-text-v1.5` model (~250 MB) plus onnxruntime at startup. Under tight memory allocation (≤ 4 GB, with rka-server competing), the worker can be OOM-killed during model load and enter a crash loop. The worker is **not** on the critical path for the PI/Brain/Executor MCP-tool flow — losing it only degrades vector search recall on newly-added entries until it catches up. But the simplest avoidance is 6 GB; treatment is in [§ 7.3](#73-rka-worker-oom-docker-memory--4-gb).

### 1.2 Xcode Command Line Tools

```bash
xcode-select -p
git --version
```

**Expected:** `xcode-select -p` prints a non-empty path. `git --version` prints `2.x`.

**If missing:** `xcode-select --install` (5-minute GUI install).

### 1.3 Python (host)

The validation snippets in this doc use stock macOS `/usr/bin/python3` for `python3 -m json.tool` and basic checks. That's sufficient.

```bash
python3 --version
which python3
```

**Expected:** any `Python 3.9.x` or later; the path resolves to `/usr/bin/python3`, a Homebrew path, or a python.org path — **not** a conda interpreter (conda's interpreter has its own dependency tree that you don't need for this guide and can confuse `uv tool install`).

If you also intend to run pytest on the host (not part of this guide), install Homebrew Python 3.11+ separately — but the bring-up below does not require it.

### 1.4 `uv` (Astral)

`uv` builds the `rka` MCP stdio binary entry from `pyproject.toml`. It is only needed for the **optional** host-side smoke test in [§ 4](#4-optional-install-the-mcp-stdio-binary-host-side-smoke-test); the recommended docker-exec config path in [§ 5](#5-configure-claude-desktop--claude-code) does not need this binary.

```bash
uv --version
```

**If missing:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or: brew install uv
```

Ensure `~/.local/bin` is on `PATH`:

```bash
echo $PATH | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo "OK" || \
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

**Verify with:** `uv --version` prints `uv 0.x` or newer.

### 1.5 AppleDouble pre-check (skip if cloning under `~/`)

If you clone into `~/Code/rka` or `~/Documents/rka` on the boot APFS volume, skip this. If you clone onto **`/Volumes/*`**, OneDrive, Dropbox, iCloud, or an SMB/AFP mount, macOS will create `._*` AppleDouble files that break both `docker compose build` (`failed to xattr ... operation not permitted`) and `uv tool install` (`No such file or directory: '._requires.txt'`).

**Recommendation:** clone into `~/Code/rka`. If you must use an external volume, see [§ 7.4 AppleDouble fix](#74-appledouble-blocks-docker-build--uv-tool-install).

---

## 2. Clone the repo + pin a reference

```bash
git clone https://github.com/infinitywings/rka.git
cd rka
git branch --show-current
```

**Expected output:** `git branch --show-current` prints `main`.

**If it prints anything else:**

```bash
git fetch origin main && git checkout main
```

**Pin the reference you're deploying.** `main` HEAD moves. To deploy a reproducible build, either checkout a tagged release:

```bash
git checkout v2.5.12
```

or, if you intend to track HEAD, capture the SHA you actually deployed for the deployment log:

```bash
git rev-parse HEAD > .deployed-sha
```

This runbook is verified against `v2.5.12` (current `main` HEAD as of the [§ 9](#9-versioning) stamp). Later versions are likely compatible — the v2.5.12+ `project_id`-required MCP contract is the relevant behavioral floor — but the literal output strings in [§ 3.1](#31-rest-health-check) and [§ 6.1](#61-list-projects-from-claude) track whatever `pyproject.toml` ships.

No `.env` file is required on main. Both `docker-compose.yml` and the auto-loaded `docker-compose.override.yml` use `${VAR:-default}` syntax for every variable, so unset env vars resolve to baked-in defaults. The only reason to create `.env` is to set optional keys like `SEMANTIC_SCHOLAR_API_KEY` or `ZOTERO_API_KEY` — these can also be added later via the `mcp-credentials` skill (see [§ 8](#8-optional-cross-project-mcp-credentials)).

---

## 3. Docker build + bring-up

```bash
docker compose up -d --build
```

This consumes `docker-compose.yml` + the auto-loaded `docker-compose.override.yml`. No `-f` flags needed. The build runs three Dockerfile stages: (1) Node web-UI build, (2) `sqlite-vec` compile, (3) Python runtime + `pip install`.

**Cold build expectation:** 5–10 minutes on a typical residential connection — the first build pulls `node:22-alpine` and `python:3.13-slim` (~600 MB combined) from Docker Hub before any of your code is compiled. On a slow / metered link the pull dominates; pre-warm with `docker pull node:22-alpine python:3.13-slim` if you want to separate "pulling images" from "building rka" in your timing.

**Warm rebuild:** < 30 s.

**Expected output:** Compose streams `=> [N/M] ...` lines, then:

```
 ✔ Container rka-server  Started
 ✔ Container rka-worker  Started
```

**Verify with:**

```bash
docker compose ps
```

Two rows, both running:

```
NAME         IMAGE     STATUS                   PORTS
rka-server   rka-rka   Up X minutes (healthy)   0.0.0.0:9712->9712/tcp
rka-worker   rka-rka   Up X minutes
```

**Common failures:** see [§ 7 Troubleshooting](#7-troubleshooting).

### 3.1 REST health check

```bash
curl -sS http://localhost:9712/api/health | python3 -m json.tool
```

**Expected output (against `v2.5.12`):**

```json
{
    "status": "ok",
    "version": "2.5.12",
    "vec_available": true
}
```

The `version` field tracks whatever `pyproject.toml` ships at the SHA you deployed — `"2.5.x"` against current `main`, `"2.6.x"` once v2.6.0 is cut from `CHANGELOG.md`'s Unreleased section. `vec_available: true` confirms `sqlite-vec` loaded. If `false`, semantic search silently degrades to FTS5-only — fixable by rebuilding on native arch.

### 3.2 Web UI

```bash
open http://localhost:9712/
```

**Expected:** React dashboard with sidebar (Projects, Knowledge Graph, Inbox, Settings, …). Empty-state cards (no projects yet). The page title is `Research Knowledge Agent`.

**Verify with:**

```bash
curl -sI http://localhost:9712/ | head -1
# HTTP/1.1 200 OK
```

### 3.3 `rka-worker` memory check

```bash
docker inspect rka-worker --format '{{.RestartCount}}'
docker logs rka-worker 2>&1 | grep -iE "killed|MemoryError|OOM" | tail -5
```

**Expected:** RestartCount `0`, no `killed`/`MemoryError`/`OOM` lines in logs. If RestartCount > 0 **or** the log grep returns matches, go to [§ 7.3](#73-rka-worker-oom-docker-memory--4-gb). Note: `docker inspect --format '{{.State.OOMKilled}}'` only reflects the **most recent** termination — a worker that OOM'd once then started cleanly will read `false`, so the log grep is the more reliable historical signal.

---

## 4. (Optional) Install the MCP stdio binary — host-side smoke test

This installs `~/.local/bin/rka`, produced from the repo's `[project.scripts].rka` entry. **The recommended config path in [§ 5](#5-configure-claude-desktop--claude-code) uses the docker-exec MCP shape and does not need this binary.** Install it only if you want a host-side smoke test or plan to use the Dockerless config shape in [§ 5.3](#53-alternative-host-binary-config-dockerless--advanced).

If you're following the runbook top-to-bottom and just want the fastest working setup, **skip to [§ 5](#5-configure-claude-desktop--claude-code) now**.

### 4.1 Standard install (stock APFS volumes)

```bash
cd /path/to/rka       # repo root
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

**Verify with:**

```bash
test -x ~/.local/bin/rka && echo PASS
~/.local/bin/rka --version
~/.local/bin/rka mcp --help
```

The `test -x` line is the deterministic pass criterion (`uv tool install` output strings vary across `uv` versions and between stdout/stderr). The `--help` invocation should print stdio/http transport help text.

### 4.2 AppleDouble fallback (external drives, sync folders)

If `uv tool install --force .` fails on `._requires.txt`:

```bash
# 1. Purge AppleDouble companions across the whole tree (excluding scratch dirs)
find . -name '._*' \
       -not -path './.git/*' \
       -not -path './.venv/*' \
       -not -path './node_modules/*' \
       -delete

# 2. If still failing, install from a /tmp clone (stock APFS, no xattr quirk)
rm -rf /tmp/rka-build && git clone -q --depth 1 "$PWD" /tmp/rka-build
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

The `find` pattern intentionally has **no `-maxdepth` limit** because the build process can write `._*` companions at any depth inside `build/`, `rka.egg-info/`, `web/dist/`, and `orchestrator/build/` — `-maxdepth 2` misses the deeper ones.

---

## 5. Configure Claude Desktop + Claude Code

The recommended install is via the **Claude Code plugin marketplace** ([§ 5.0](#50-recommended-install-via-the-plugin-marketplace)), which wraps the docker-exec MCP shape with a version-compatibility wrapper, a SessionStart hook, and six pre-baked slash commands (`/rka-status`, `/rka-search`, …). If you'd rather hand-roll the config, [§ 5.1](#51-claude-desktop) and [§ 5.2](#52-claude-code) document the minimal docker-exec JSON; [§ 5.3](#53-alternative-host-binary-config-dockerless--advanced) covers the Dockerless variant.

### 5.0 Recommended: install via the plugin marketplace

The repo ships a Claude Code marketplace + plugin (`.claude-plugin/marketplace.json`, `plugin/.mcp.json`, `plugin/bin/rka-mcp-bridge.py`). The bridge runs a version-compatibility check (`COMPATIBLE_VERSION_PREFIX` pinned in `rka-mcp-bridge.py`) before forwarding stdio, so a mismatched server/plugin pair fails fast with a clear error instead of producing confusing tool-registration errors deep in MCP startup.

From a Claude Code session, with the rka repo already checked out and `docker compose up -d` already done:

```
/plugin marketplace add /path/to/rka
/plugin install rka@rka
/rka-setup-claude-desktop
```

The first command registers the local marketplace; the second installs the plugin (which writes the MCP-server entry, the SessionStart hook at `plugin/hooks/session-start.py`, and six slash commands); the third configures the Claude Desktop config to match. Full details and cross-platform paths are in [`INSTALL.md`](INSTALL.md).

After install, skip to [§ 6 Smoke tests](#6-smoke-tests).

### 5.1 Claude Desktop (hand-rolled minimal install)

Use this only if you didn't run [§ 5.0](#50-recommended-install-via-the-plugin-marketplace). Claude spawns `docker exec -i rka-server rka mcp`, which runs the MCP binary **inside the container** alongside the REST API. This guarantees MCP/REST schemas stay in sync and avoids the GUI PATH issue (`docker` is at `/usr/local/bin/docker`, which **is** on Claude Desktop's launchd PATH).

**Config path:** `~/Library/Application Support/Claude/claude_desktop_config.json` (note the space in `Application Support`).

**Create the parent dir if needed + backup:**

```bash
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CFG")"
[ -f "$CFG" ] && cp "$CFG" "${CFG}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
```

The `mkdir -p` is required for a fresh Claude Desktop install that has never been opened (the parent dir doesn't exist yet, and the `cp` backup would fail with `ENOENT`).

**Create or merge** so the file contains:

```json
{
  "mcpServers": {
    "rka": {
      "command": "docker",
      "args": ["exec", "-i", "rka-server", "rka", "mcp"]
    }
  }
}
```

If the file already exists with other MCP servers, **deep-merge** — add the `rka` key inside `mcpServers`, do not clobber the whole file.

**Validate JSON parses:**

```bash
python3 -m json.tool "$CFG" > /dev/null && echo "JSON valid"
```

**Restart Claude Desktop:** Cmd-Q (fully quit — closing the window is not enough) → relaunch.

**Verify with (programmatic):**

```bash
tail -100 ~/Library/Logs/Claude/mcp.log | grep -E "rka.*(connected|registered|tools)"
```

A connection/registration line for `rka` confirms the server loaded. (UI alternative: Settings → Developer → "MCP servers" panel — the `rka` entry should show a green dot — but the log-grep is the deterministic check for headless / agent runs.)

### 5.2 Claude Code

On macOS, Claude Code reads MCP-server entries from the same `~/Library/Application Support/Claude/claude_desktop_config.json` path as Claude Desktop — so if you completed [§ 5.1](#51-claude-desktop), Claude Code already sees the `rka` server. The per-repo `<repo>/.mcp.json` scope is also honored; use it when you want a project-local override.

**Validate any config you create:**

```bash
python3 -m json.tool "$CFG" > /dev/null && echo "JSON valid"
```

**Restart:** Claude Code picks up MCP config changes on next session start. Close + reopen the terminal session.

**Verify with:** in a Claude Code session, run `/mcp`. The `rka` server should appear with a tool count.

Cross-platform locations (Windows, Linux) are tabulated in `INSTALL.md` § 4 — `~/.claude.json` is **not** the MCP-server config on macOS.

### 5.3 Alternative: host-binary config (Dockerless / advanced)

If you'd rather have Claude launch the host binary directly (and you ran the optional [§ 4](#4-optional-install-the-mcp-stdio-binary-host-side-smoke-test)):

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

**Replace `<your-username>` with your actual macOS username** — the path must be absolute. macOS GUI apps inherit PATH from `launchd`, not from your shell rc; `~/.local/bin` is **not** on the GUI PATH, so `"command": "rka"` (bare) or `"~/.local/bin/rka"` (tilde-prefixed) will fail with `ENOENT`. The docker-exec shape (5.1) avoids this problem entirely.

---

## 6. Smoke tests

The natural-language asks below are what a human PI will type into a Claude chat. Each one has a **REST equivalent** for agent execution — a `curl` call directly to `http://localhost:9712/api/...` that proves the same round-trip without needing a Claude session.

### 6.1 List projects from Claude

**Human (Claude chat):**

> list rka projects

**Expected:** Claude invokes `mcp__rka__rka_list_projects` and renders:

```
## Projects

No projects found.

**Note (v2.6+):** there is no longer an 'active project' concept at the MCP layer.
Every project-scoped tool requires `project_id` explicitly.
```

(The "v2.6+" wording in the user-facing template is baked into the MCP server source as of `v2.5.12`; the behavior — `project_id` required on every project-scoped tool — is live on `main` HEAD now.)

**Agent / REST equivalent:**

```bash
curl -sS http://localhost:9712/api/projects | python3 -m json.tool
docker logs rka-server 2>&1 | tail -50 | grep "GET /api/projects"
```

The first call returns a JSON array (initially empty). The log grep confirms the request hit the server.

**Failure mode:** Claude says "I don't have an `rka_list_projects` tool" → MCP not loaded; see [§ 7.5](#75-mcp-server-shows-red-dot).

### 6.2 Create a test project

**Human (Claude chat):**

> create rka project named smoke-test

**Expected:** Claude calls `rka_execute(args={"operation": "create_project", "name": "smoke-test"})` and reports:

```
Created project **smoke-test** (`prj_01K…`).
```

**Agent / REST equivalent:**

```bash
curl -sS -XPOST http://localhost:9712/api/projects \
     -H "Content-Type: application/json" \
     -d '{"name":"smoke-test"}' | python3 -m json.tool
```

The returned JSON includes the 26-char ULID `prj_01K…` — capture it; you'll thread it through every subsequent call. If you get a 409 conflict, use a different name.

### 6.3 Verify in the web UI

Reload `http://localhost:9712/` and navigate to **Projects**. The `smoke-test` project should appear with the generated ID. Clicking it shows an empty-state phase/focus/blockers dashboard.

**Agent / REST equivalent:**

```bash
curl -sS http://localhost:9712/api/projects | python3 -m json.tool
```

The smoke-test project must be in the returned array, matching the ID from [§ 6.2](#62-create-a-test-project).

If steps 6.1–6.3 all pass, your MCP ↔ REST ↔ UI ↔ DB round-trip is verified end-to-end.

---

## 7. First project workflow

The canonical first-session pattern. Substitute the actual `prj_01K…` ID from §6.2 wherever you see `prj_…`.

**Step 7.1 — Pin the project and load Brain.** First message in a new chat:

> We're working on `prj_01K…` (smoke-test). Load the Brain skill.

Claude loads the `brain_skill` MCP prompt (which expands to `rka/skills/brain/SKILL.md`). Per the skill's Session-Start protocol, it will:
1. Pin `project_id` for the whole conversation.
2. Call `rka_query(args={"operation": "status", "project_id": "prj_…"})` (may 404 on brand-new projects until you set state).
3. Call `rka_query(args={"operation": "get_changelog", "project_id": "prj_…"})`, `rka_query(args={"operation": "get_pending_maintenance", "project_id": "prj_…"})`, `rka_query(args={"operation": "get_research_map", "project_id": "prj_…"})`.

**Step 7.2 — Initialize project state:**

> Set the phase to `planning` and the focus to `verifying the workflow`.

**Step 7.3 — Record a PI directive:**

> Note that we want to prove the journal + decision + mission round-trip works.

Claude calls `rka_execute(args={"operation": "record_note", "project_id": "prj_…", "type": "directive", "source": "pi", "verbatim_input": "...", ...})`. The `verbatim_input` field is **load-bearing** — the PI's exact wording is ground truth.

**Step 7.4 — Record a decision linking back to the journal:**

> Decide we will execute one happy-path mission to confirm round-trip.

Claude calls `rka_execute(args={"operation": "record_decision", "project_id": "prj_…", "related_journal": ["jrn_01K…"], ...})`. **`related_journal` is the documented provenance convention** — the maintenance scanner (operation `get_pending_maintenance`) flags decisions missing it as a hygiene gap. The decisions service does **not** hard-reject the write if it's absent (`rka/services/decisions.py` stores it as a JSON list and only writes entity_links when present), but the Brain skill prompt enforces it and you should treat it as required for any decision you intend to keep.

**Step 7.5 — Create a mission linked to the decision:**

> Create the verification mission.

Claude calls `rka_execute(args={"operation": "create_mission", "project_id": "prj_…", "motivated_by_decision": "dec_01K…", ...})`. Same shape as the previous step: **`motivated_by_decision` is the documented provenance convention** — flagged by the maintenance scanner when missing, enforced by the skill prompt, not a hard schema constraint at the service layer (`rka/services/missions.py` writes the link conditionally on `if data.motivated_by_decision`).

**Step 7.6 — Hand off to Executor:**

> Load the Executor skill and pick up `mis_01K…`.

Executor reads the mission, reads the decision, activates the mission (`pending → active`), executes, then calls `rka_execute(args={"operation": "submit_report", "project_id": "prj_…", "mission_id": "mis_01K…", "summary": "...", ...})` which transitions it to `complete`.

**Step 7.7 — PI verifies in the web UI.** Missions tab shows `mis_01K…` as `complete`. Decisions tab shows `dec_01K…` linked to `jrn_01K…`. Research Map shows the project's first node.

**v2.5.12+ contract reminder:** every project-scoped `rka_*` tool requires `project_id` as a kwarg. Omitting it raises `TypeError`. The Brain/Executor/PI skill prompts handle this for you when loaded.

---

## 8. Optional: cross-project MCP credentials

All optional. The rka MCP is fully usable without any of these. They unlock additional tools or raise rate limits.

Cataloged in `rka/skills/mcp-credentials/catalog.md`. To install any of them, ask Claude:

> set up Zotero credentials

and Claude invokes the `mcp-credentials` skill, which deep-merges into `claude_desktop_config.json` atomically with a backup.

| Service | Env vars | What it unlocks |
|---|---|---|
| **Zotero** | `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE` | `rka_link_literature_to_zotero` + full-text PDF reads. Requires the separate `zotero-mcp` server. |
| **Semantic Scholar** | `SEMANTIC_SCHOLAR_API_KEY` | Raises `rka_search_semantic_scholar` rate limit from 100 req/5min to 1 req/sec. |
| **SerpAPI** | `SERPAPI_KEY` | Open-web search fallback. 250 free searches/month on the free tier. |
| **OpenAlex** | `OPENALEX_MAILTO` | Adds your email to OpenAlex requests for the "polite pool" — higher rate limit. Not a secret. Set as default. |

Walkthroughs live under `rka/skills/mcp-credentials/walkthroughs/`.

---

## For autonomous code agents

Execute these steps in order. After each, run the verification command and confirm the pass signal before moving on.

D1–D3 (host binary install) are **optional** smoke-test rows — the docker-exec path in E1 does not depend on them. Skip directly from C5 to E1 if you don't want a host-side binary.

| Step | Action | Pass signal | Fail → action |
|---|---|---|---|
| **A1** | `docker info --format '{{div .MemTotal 1048576}}'` | Output ≥ `4096` | Bump Docker Desktop memory → Resources → Memory → ≥ 4096 MiB → Restart (or edit `~/Library/Group Containers/group.com.docker/settings-store.json` `memoryMiB` key and relaunch Docker) |
| **A2** | `xcode-select -p && git --version` | Non-empty path + `git version 2.x` | `xcode-select --install` |
| **A3** | `python3 --version` | `Python 3.9.x` or higher | `brew install python` (only needed if stock `/usr/bin/python3` is missing) |
| **A4** | `uv --version` (only required if running D1–D3) | `uv 0.x` or newer | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **B1** | `git clone https://github.com/infinitywings/rka.git && cd rka && git branch --show-current` | Prints `main` | `git fetch origin main && git checkout main` |
| **B1a** | `git rev-parse HEAD > .deployed-sha; cat .deployed-sha` | 40-char SHA recorded | Capture for deployment log; or `git checkout v2.5.12` for a pinned reference |
| **B2** | `find . -name '._*' -not -path './.git/*' -not -path './.venv/*' -not -path './node_modules/*' \| wc -l` | Prints `0` | Re-run with `-delete` |
| **C1** | `docker compose up -d --build` | Exits 0; ends with `Started` lines | See [§ 7](#7-troubleshooting) by error class |
| **C2** | `docker compose ps` | Both `rka-server` (`healthy`) and `rka-worker` (`running`) | `docker compose logs --tail 200` |
| **C3** | `curl -sS http://localhost:9712/api/health` | JSON with `"status":"ok"` and `"vec_available":true` | [§ 7.1](#71--api-returns-connection-refused-or-non-200) |
| **C4** | `curl -sI http://localhost:9712/ \| head -1` | `HTTP/1.1 200 OK` | [§ 7.2](#72--web-ui-blank-or-404) |
| **C5** | `docker inspect rka-worker --format '{{.RestartCount}}'` + `docker logs rka-worker 2>&1 \| grep -iE "killed\|MemoryError\|OOM"` | RestartCount `0` and grep is empty | [§ 7.3](#73-rka-worker-oom-docker-memory--4-gb) — bump Docker memory to ≥ 6 GB |
| **D1** *(optional)* | `find . -name '._*' -not -path './.git/*' -not -path './.venv/*' -not -path './node_modules/*' -delete && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .` | `test -x ~/.local/bin/rka && echo PASS` returns `PASS` | [§ 7.4](#74-appledouble-blocks-docker-build--uv-tool-install) — install from `/tmp` clone |
| **D2** *(optional)* | `~/.local/bin/rka --version` | Prints `rka, version 2.x.x` | Re-run D1 |
| **D3** *(optional)* | `docker exec -i rka-server rka mcp --help` | Prints stdio/http transport help | `docker compose up -d --build` (rebuild image) |
| **E1** | Create parent dir (`mkdir -p "$(dirname "$CFG")"`) + write `claude_desktop_config.json` with the docker-exec block from [§ 5.1](#51-claude-desktop-hand-rolled-minimal-install); `python3 -m json.tool "$CFG"` | Prints valid JSON | Fix syntax error in JSON file |
| **E2** | `osascript -e 'tell application "Claude" to quit'`, then relaunch via `open -a Claude` | `tail -100 ~/Library/Logs/Claude/mcp.log \| grep -E "rka.*(connected\|registered\|tools)"` returns matches | [§ 7.5](#75-mcp-server-shows-red-dot) |
| **F1** | `docker logs rka-server 2>&1 \| tail -50 \| grep "GET /api/projects"` after any client invokes `rka_list_projects` (or `curl -sS http://localhost:9712/api/projects` directly) | Returns an empty JSON array `[]` initially; subsequent calls show GET log lines | [§ 7.5](#75-mcp-server-shows-red-dot) |
| **F2** | `curl -sS -XPOST http://localhost:9712/api/projects -H "Content-Type: application/json" -d '{"name":"smoke-test"}'` | Returns JSON with a `prj_01K…` ULID | If 409 conflict, use a different name; if 5xx, check `docker logs rka-server` |
| **F3** | `curl -sS http://localhost:9712/api/projects` | JSON array including the smoke-test project | Check `docker logs rka-server` |

**Overall pass:** all rows A1–F3 (skipping D1–D3 if not installing the host binary) pass. Stop and report findings at the first FAIL — do not skip ahead.

---

## 7. Troubleshooting

### 7.1 — API returns Connection refused or non-200

**Diagnose:** `docker compose ps` (is `rka-server` running?), `docker compose logs --tail 200 rka-server` (startup tracebacks).

**Fix:**
- Container not up → `docker compose up -d`.
- Port 9712 in use → `lsof -i :9712`; stop offender.
- Migration error in logs → see [§ 7.6](#76-database-schema-wedged).

### 7.2 — Web UI blank or 404

**Diagnose:** `docker compose exec rka-server ls /app/web/dist/index.html`.

**Fix:**
- `index.html` missing → Dockerfile stage 1 (web build) failed. Rebuild: `docker compose build --no-cache rka`.
- File present but browser blank → hard-refresh (Cmd-Shift-R) or open a private window.

### 7.3 — rka-worker OOM (Docker memory < 4 GB)

**Diagnose:**

```bash
docker inspect rka-worker --format '{{.RestartCount}}'
docker logs rka-worker 2>&1 | grep -iE "killed|MemoryError|OOM"
```

A non-zero RestartCount **or** any matches in the log grep is sufficient evidence. (`docker inspect --format '{{.State.OOMKilled}}'` only reflects the most recent termination — a worker OOM'd at startup and then OOM'd a second time and then started cleanly would show `OOMKilled=false`, so the log grep is the reliable historical signal.)

**Fix:** Docker Desktop → Settings → Resources → Memory → ≥ 6 GB → Apply & Restart. Then `docker compose up -d --force-recreate`. Scripted alternative on Apple Silicon: edit `~/Library/Group Containers/group.com.docker/settings-store.json` `memoryMiB` key, then `osascript -e 'tell application "Docker" to quit' && open -a Docker`.

**Impact if you leave it broken:** PI/Brain/Executor workflow still works (MCP tools are synchronous and don't depend on the worker). Search recall degrades for newly-added notes/decisions until the worker catches up.

### 7.4 — AppleDouble blocks docker build / uv tool install

**Symptom (build):** `docker compose build` fails with `failed to xattr ... operation not permitted`.

**Symptom (install):** `uv tool install --force .` fails with `No such file or directory: '._requires.txt'`.

**Fix:**

```bash
# Purge across the whole tree (excluding scratch dirs)
find . -name '._*' \
       -not -path './.git/*' \
       -not -path './.venv/*' \
       -not -path './node_modules/*' \
       -delete

# If uv install still fails, build from /tmp (stock APFS)
rm -rf /tmp/rka-build && git clone -q --depth 1 "$PWD" /tmp/rka-build
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

### 7.5 — MCP server shows red dot

**Diagnose:**

```bash
tail -F ~/Library/Logs/Claude/mcp.log     # in one pane
docker logs --tail 50 rka-server          # in another
```

**Fix by error class:**
- `command not found` for `rka` → using host-binary shape with non-absolute path. Switch to docker-exec shape (§ 5.1) or use the absolute path `/Users/<you>/.local/bin/rka`.
- `No such container: rka-server` → run `docker compose up -d`.
- `httpx.ConnectError` → REST API not reachable; check [§ 7.1](#71--api-returns-connection-refused-or-non-200).
- `pydantic.ValidationError` on tool registration → MCP binary version mismatch. Reinstall: `uv tool uninstall rka; rm -rf /tmp/uv-cache; UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall .` then Cmd-Q + relaunch Claude.

### 7.6 — Database schema wedged

**Symptom:** rka-server in restart loop; logs show migration errors.

**Fix (DESTROYS DATA):**

```bash
docker compose down
docker volume rm rka_rka-data
docker compose up -d
```

**Prevention:** export periodically via `rka_export` from any session, or `docker compose cp rka-server:/data/rka.db ./rka.db.bak`.

### 7.7 — `TypeError: rka_X() missing 1 required keyword-only argument: 'project_id'`

**Why:** v2.5.12+ contract. Every project-scoped tool requires `project_id` as a kwarg.

**Fix:** in chat, remind Claude: "We're on `prj_01K…`, retry with that project_id." Better: load the Brain/Executor/PI skill at session start so the discipline is automatic.

### 7.8 — Stale code after rebuild

**Symptom:** code changes don't take effect after `docker compose restart`.

**Why:** `docker compose restart` does **not** reload service code.

**Fix:** `docker compose up -d --build`. If the new image still isn't picked up (Compose decides nothing changed): `docker compose up -d --force-recreate`.

### 7.9 — Search returns nothing for newly-added notes

**Why:** `rka_search` blends FTS5 + vector similarity. Without the worker (or with a backed-up queue), new content has FTS5 hits but no vector hits.

**Fix:**
- Verify worker health ([§ 7.3](#73-rka-worker-oom-docker-memory--4-gb)).
- Shorten the query — FTS5 returns empty on overly long natural-language queries. Use 2–4 word queries.

---

## 8. What's NOT covered

Explicitly out of scope for this doc:

- **The agentic orchestrator daemon** (LangGraph Brain ⇄ Executor ⇄ PI loop with parked interrupts, the second MCP binary `rka-orchestrator-mcp`, Phase-A/B/D credential bootstrap, the `~/Research/{slug}/` workspace bind mount). See the "Agentic Branch + Orchestrator Package" section in [CLAUDE.md](CLAUDE.md).
- **Production hardening** (TLS termination, reverse proxy, auth layer in front of FastAPI, log shipping, monitoring). The main-branch stack is designed for single-user localhost.
- **Multi-host setups** (separate DB host, distributed workers, K8s). RKA is a single-node SQLite app by design.
- **Backup / DR strategy.** Use `rka_export` for knowledge-pack exports, or `docker compose cp rka-server:/data/rka.db ./backup.db` for raw SQLite snapshots. No automated backup ships out of the box.
- **Embedding backend tuning** (FastEmbed vs OpenAI-compatible HTTP vs Ollama). Documented separately in `docs/embedding_backends.md`. Default FastEmbed works for the smoke tests above.
- **Skill authoring** (writing new MCP-prompt-surfaced skills under `rka/skills/`). Use the `skill-creator` skill in Claude.

---

## 9. Versioning

Last updated **2026-05-30**. Verified against `main` HEAD at `v2.5.12` (the `project_id`-required MCP contract per PR #32 is live as of that release; cross-project credential walkthroughs via the `mcp-credentials` skill per PR #33; v2.6.0 is in `CHANGELOG.md` Unreleased and will tighten the same surface further). Future v2.7+ may shift the default embedding backend, add new `rka_*` tools, or change the web UI layout — the bring-up sequence in [§ 3](#3-docker-build--bring-up) and the MCP config in [§ 5](#5-configure-claude-desktop--claude-code) are stable across minor versions. Pin a specific SHA via [§ 2](#2-clone-the-repo--pin-a-reference) if you need reproducibility.