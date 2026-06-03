# Deployment from scratch - RKA orchestrator on a fresh Mac

This runbook brings a fresh macOS host from "Docker Desktop, Claude Desktop, Claude Code installed" to a fully running RKA orchestrator: REST API + worker + LangGraph daemon + two MCP stdio binaries wired into both Claude clients, ready to onboard a project and execute a Brain ⇄ Executor ⇄ PI mission. It synthesizes empirical hardening from Phase A through Phase D2.4 (commits `ada81d0..81b7e05`) — AppleDouble mitigation, workspace mount safety, OAuth-token-only auth, async-resume endpoints, substring-routing exploit fixes, Gap 5 non-root user. Dual-audience: humans copy-paste through §§1–10; an autonomous agent (Claude Code) follows [§11](#11-for-autonomous-code-agents), which restates every step with grep-able pass/fail signals. Every command block is followed by an "Expected" or "Verify"; every named failure has one canonical entry in [§10 Troubleshooting](#10-troubleshooting).

Numbering: §§1–10 canonical procedure; §11 agent restatement (targets §§3–10 by number, appears after); §12 non-goals; §13 versioning. Hardcoded paths: `/Volumes/base/workspace/rka` appears ~30 times. If you cloned elsewhere (e.g. `$HOME/Code/rka`), find/replace globally — see [§4.1](#41-clone-check-out-agentic).

---

## 1. Audience + prerequisites

**Already installed (assumed):** macOS 13 Ventura+ on Apple silicon or Intel; Docker Desktop; Claude Desktop; Claude Code (CLI or VSCode extension); an Anthropic Max account (the orchestrator uses the OAuth path routing to Max billing, not per-token API keys).

**Installed by this runbook:** Xcode CLT (`git`, `clang`); Homebrew; Node.js 20 LTS + npm + npx (Claude CLI and `context7` MCP); Python 3.13 (CI parity; >=3.11 floor); `uv` (Astral; host-side MCP stdio binaries); `@anthropic-ai/claude-code` (host CLI for token minting). Optional: `gh` (GitHub missions); Zotero / Semantic Scholar / SerpAPI / OpenAlex credentials (per-mission).

**Not covered:** see [§12 What's NOT covered](#12-whats-not-covered).

---

## 2. Layout overview

```
HOST (macOS)
  ~/.local/bin/{rka, rka-orchestrator-mcp}      <-- host stdio binaries (uv tool install)
  ~/.claude.json                                <-- ro mounted -> /home/orchestrator/.claude.json
  ~/Library/.../claude_desktop_config.json      <-- Claude Desktop MCP registry
  ~/.claude/mcp.json                            <-- Claude Code user-global MCP registry

  /Volumes/base/workspace/rka/                  <-- repo clone (agentic branch)
    .env                                        <-- HOST_WORKSPACE_ROOT (NOT orch/.env)
    docker-compose.yml                          <-- root compose (rka-server + rka-worker)
    orchestrator/
      docker-compose.yml                        <-- overlay (rka-orchestrator)
      .env                                      <-- CLAUDE_CODE_OAUTH_TOKEN (0600)
      Dockerfile                                <-- Gap 5: user orchestrator (UID 1000),
                                                    HOME=/home/orchestrator

  ~/Research/                                   <-- HOST_WORKSPACE_ROOT, parent of all projects
    iot-edge-llm/
      .rka/{tools.json, .env, workspace.json}
      data/ code/ notebooks/ results/ manuscripts/

  stdio: Claude Desktop / Claude Code -> rka-orchestrator-mcp (host binary)
                                       -> docker exec -i rka-server rka mcp

DOCKER (compose: 3 containers)
  rka-server        :9712/api  (vol rka-data -> /data/rka.db)
  rka-worker        FastEmbed; same volume
  rka-orchestrator  :9713  user=orchestrator (UID 1000), HOME=/home/orchestrator
                    vol orchestrator-data -> /data/{orchestrator,orchestrator-saver}.db
                    bind: orchestrator/.env (rw)
                    bind: ~/.claude.json (ro) -> /home/orchestrator/.claude.json
                    bind: ${HOST_WORKSPACE_ROOT}:${HOST_WORKSPACE_ROOT} (rw, identity)
                    subprocess: claude-agent-sdk -> Brain / Executor LLM calls
```

Three storage planes, never crossed: **RKA SQLite** (volume `rka-data` -> `/data/rka.db`) = domain truth (decisions, missions, journals, claims); **Orchestrator SQLite** (volume `orchestrator-data` -> `/data/orchestrator.db` + `orchestrator-saver.db`) = workflow position (parked interrupts, run rows, LangGraph SqliteSaver checkpoints); **Claude SDK session** (transient subprocess context) = per-node prompt/response, never persisted.

---

## 3. Prerequisites

### 3.1 Xcode Command Line Tools

```bash
xcode-select --install
xcode-select -p && git --version && clang --version
```

Expected: `/Library/Developer/CommandLineTools`, `git >=2.20`, `Apple clang ...`.

### 3.2 Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile   # Apple silicon
eval "$(/opt/homebrew/bin/brew shellenv)"
brew doctor
```

Expected: `Your system is ready to brew.` (warnings OK, errors not).

### 3.3 Docker Desktop tuning

Memory must be >=6 GB (8 GB recommended). `rka-worker` loads FastEmbed + onnxruntime and OOM-loops under low memory ([§10.1](#101-rka-worker-ooms-under-low-docker-memory)).

**Human path (recommended):** Docker Desktop -> Settings -> Resources -> Memory; "Apply & restart".

**Agent / CLI path (best-effort, REQUIRES-HUMAN if it fails):** Docker Desktop persists Resources settings to `~/Library/Group Containers/group.com.docker/settings-store.json` (or older `settings.json`); schema drifts across versions:

```bash
SETTINGS="$HOME/Library/Group Containers/group.com.docker/settings-store.json"
[ -f "$SETTINGS" ] || SETTINGS="$HOME/Library/Group Containers/group.com.docker/settings.json"
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
SETTINGS="$SETTINGS" python3 -c "
import json, os
p=os.environ['SETTINGS']; d=json.load(open(p))
for k in ('MemoryMiB','memoryMiB'):
    if k in d: d[k]=max(d[k],8192); break
else: d['MemoryMiB']=8192
json.dump(d, open(p,'w'), indent=2)"
osascript -e 'quit app "Docker"'; sleep 3; open -a Docker
```

Docker Desktop silently ignores unknown keys; VERIFY via `docker info` after relaunch and fall back to the GUI if the value didn't change. For repo paths outside `$HOME`, also add the parent volume to Settings -> Resources -> File sharing (no CLI; REQUIRES-HUMAN) and grant Docker Desktop Full Disk Access at System Settings -> Privacy & Security (no CLI; see [§10.4](#104-non-home-workspace-mount-shows-empty-inside-container)). For unattended agents, prefer cloning into `$HOME/Code/rka` to sidestep both.

```bash
docker info --format '{{.MemTotal}}' | awk '{ printf "%.2f GB\n", $1/1024/1024/1024 }'
docker compose version
```

Expected: `>= 6.00 GB`; `Docker Compose v2.x.x`.

### 3.4 Node.js 20 LTS

```bash
brew install node@20 && brew link --overwrite node@20
node --version && npm --version && npx --version
```

Expected: `v20.x.x`, npm `>=9`, npx present.

### 3.5 Python 3.13

```bash
brew install python@3.13 && python3.13 --version
```

Expected: `Python 3.13.x`. Fallback: any `python3 >=3.11`.

### 3.6 `uv` (Astral)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && exec zsh -l
uv --version && echo "$PATH" | tr ':' '\n' | grep -F "$HOME/.local/bin"
```

Expected: `uv 0.x.x` and a line printing `~/.local/bin`. (The §11 checklist uses `grep -qx` for the same check; both work since `tr ':' '\n'` produces one PATH entry per line.)

### 3.7 Claude CLI

```bash
npm install -g @anthropic-ai/claude-code
claude --version && claude setup-token --help
```

Expected: version string and `setup-token` help. **Why on the host if the daemon has its own CLI?** The host CLI is used only to MINT the OAuth token ([§5.1](#51-claude-oauth-token)); the daemon's bundled CLI consumes it from `CLAUDE_CODE_OAUTH_TOKEN`. After minting you never need the host CLI unless the token expires.

### 3.8 Optional: GitHub CLI

For missions that push commits / open PRs / read private repos:

```bash
brew install gh && gh auth login && gh auth status
```

Expected: `Logged in to github.com as <user>`.

---

## 4. Repo clone + .env files

### 4.1 Clone, check out `agentic`

Create the parent dir first; the canonical `/Volumes/base/workspace/rka` lives on an external volume not present on a fresh Mac:

```bash
# A) external volume path (matches every later command verbatim)
sudo mkdir -p /Volumes/base/workspace && sudo chown "$USER" /Volumes/base/workspace
git clone https://github.com/infinitywings/rka.git /Volumes/base/workspace/rka
cd /Volumes/base/workspace/rka
# B) $HOME-based path (simpler; find/replace the rest of the doc)
# mkdir -p "$HOME/Code" && git clone https://github.com/infinitywings/rka.git "$HOME/Code/rka" && cd "$HOME/Code/rka"
```

The URL `https://github.com/infinitywings/rka.git` is the canonical upstream at writing; substitute your fork if applicable. A 404 means it moved — check the project homepage. Verify with `git remote -v` (expect `origin`), then:

```bash
git checkout agentic
git rev-parse --abbrev-ref HEAD && test -d orchestrator && echo "agentic layout present"
```

Expected: `agentic`, then `agentic layout present`. Missing `orchestrator/` means you're on `main` — re-checkout. If you chose path B, replace `/Volumes/base/workspace/rka` everywhere below (~30 occurrences); shortcut: `export RKA_REPO="$HOME/Code/rka"`.

### 4.2 macOS AppleDouble prophylaxis

Required for clones on external drives, network mounts, OneDrive / Dropbox / iCloud sync folders, case-insensitive filesystems. `/Volumes/base/workspace/rka` is external, so this is not optional:

```bash
find . -maxdepth 2 -name '._*' -not -path './.git/*' -delete
find . -maxdepth 2 -name '._*' -not -path './.git/*' | wc -l   # expect 0
```

Re-run before every `docker compose build` and every `uv tool install --force`.

### 4.3 Repo-root `.env` — `HOST_WORKSPACE_ROOT`

Single most-stepped-on trap. The file MUST be at the repo root (`/Volumes/base/workspace/rka/.env`), NOT `orchestrator/.env`: Compose reads `.env` from the dir of the first `-f` file for YAML `${VAR}` interpolation; `env_file:` only populates container env vars and does not feed interpolation. See [§10.5](#105-host_workspace_root-set-in-the-wrong-env-file).

```bash
mkdir -p "$HOME/Research"
echo "HOST_WORKSPACE_ROOT=$HOME/Research" >> /Volumes/base/workspace/rka/.env
grep '^HOST_WORKSPACE_ROOT=' /Volumes/base/workspace/rka/.env && git check-ignore -v .env
```

Expected: a line ending in `/Research`, plus gitignore confirmation.

The startup safety check in `orchestrator/orchestrator/server.py` refuses: unset (no mount target); `/` (mounts host root rw); exactly `$HOME` (exposes `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config`); any ancestor of those. Dev-only override: `ORCHESTRATOR_ALLOW_HOME_MOUNT=1` in `orchestrator/.env` (logged on every startup); see [§10.6](#106-workspacemountunsafeerror-on-startup).

### 4.4 `orchestrator/.env` — placeholder file + 0600 mode

Create the file before first `up -d` (so Docker bind-mounts a file, not a directory) AND before [§5.1](#51-claude-oauth-token) appends the token:

```bash
touch /Volumes/base/workspace/rka/orchestrator/.env
chmod 0600 /Volumes/base/workspace/rka/orchestrator/.env
stat -f '%Sp' /Volumes/base/workspace/rka/orchestrator/.env && git check-ignore -v orchestrator/.env
```

Expected: `-rw-------`, plus gitignore confirmation.

---

## 5. Auth

### 5.1 Claude OAuth token

The daemon's SDK subprocess runs in-container and cannot reach the host's `~/.claude/.credentials.json` or Keychain. The only working auth path (Phase D2.3+) is the long-lived OAuth token in env. Prerequisite: [§4.4](#44-orchestratorenv--placeholder-file--0600-mode) (the 0600 placeholder file must exist).

```bash
claude setup-token
```

The command prints a URL (e.g. `https://claude.ai/oauth/authorize?...`). Open it in a browser, sign in with your Max account, click **Authorize**, copy the displayed `sk-ant-oat01-…` token (no quotes, no whitespace). Persist without echoing to shell history. The `-p` prompt is required — without it `read -rs` appears to hang silently:

```bash
read -rs -p 'Paste token, then Enter: ' TOKEN; echo
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" >> /Volumes/base/workspace/rka/orchestrator/.env
unset TOKEN
grep -c '^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-' /Volumes/base/workspace/rka/orchestrator/.env
```

Expected: `1`. Pitfalls: token wrapped in `"..."` (strip quotes); `sk-ant-api03-` prefix (that's an API key, not OAuth — re-run `claude setup-token`); missing trailing newline (the `printf` form above avoids the Phase D2 glued-line bug); wrapped/whitespace-smuggled paste (re-copy as one contiguous string).

### 5.2 Optional auth

GitHub: [§3.8](#38-optional-github-cli) (skip if missions are read-only). Cross-project MCP credentials (Claude OAuth, Zotero, Semantic Scholar, SerpAPI, OpenAlex): the `rka/skills/mcp-credentials` skill walks each one — issue -> curl sanity check -> deep-merge into `claude_desktop_config.json` and/or `orchestrator/.env` with `.bak.<ISO-timestamp>`. Reference: `/Volumes/base/workspace/rka/rka/skills/mcp-credentials/SKILL.md`.

---

## 6. Docker build + bring-up

The `agentic` branch must NOT modify the root `docker-compose.yml` (bookkeeper invariant); the orchestrator daemon comes via overlay. Always pass BOTH `-f` flags, in this order:

```bash
cd /Volumes/base/workspace/rka
find . -maxdepth 2 -name '._*' -not -path './.git/*' -delete
touch orchestrator/.env
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build
```

Why both `-f`: the first brings up `rka-server` + `rka-worker`; the overlay adds `rka-orchestrator`. Without the overlay, port 9713 is closed and every `orchestrator_*` MCP call returns connection refused. Why repo root first: Compose resolves relative paths and `.env` interpolation against the dir of the first `-f` file (`build.context: .`, `env_file:`, `${PWD}`).

Behind a proxy / Docker Hub rate limits, the first build may fail at `FROM python:3.13-slim` — run `docker login docker.io` and retry. Linux (bare-metal Docker Engine) callers should pass UID-matched build args so the non-root `orchestrator` user (UID 1000, `HOME=/home/orchestrator`) can write the bind-mounted workspace:

```bash
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml build \
    --build-arg ORCH_UID=$(id -u) --build-arg ORCH_GID=$(id -g)
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d
```

First build: 60-180s, then 5 lines of `Started`/`Created`. Verify:

```bash
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml ps
curl -sf http://localhost:9712/api/health && echo
curl -sf http://localhost:9713/health && echo
docker inspect rka-worker --format '{{.RestartCount}} restarts; OOMKilled={{.State.OOMKilled}}'
```

Expected: three containers `Up (healthy)`, two 200-OK JSON, low restart count, `OOMKilled=false`. OOM-loop → [§10.1](#101-rka-worker-ooms-under-low-docker-memory).

After changes: code under `rka/` or `orchestrator/` → `up -d --build`; new image but old container clings → add `--force-recreate`; migration-only → `restart` suffices; frontend in `web/` → `--build`; token rotation in `orchestrator/.env` → `up -d --force-recreate rka-orchestrator` (NOT `restart` — env vars baked at container *create*).

---

## 7. MCP stdio install + Claude config

### 7.1 Install both host stdio binaries

```bash
cd /Volumes/base/workspace/rka
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force ./orchestrator
which rka && which rka-orchestrator-mcp
```

Expected: both resolve under `~/.local/bin/`. If either install fails with `No such file or directory: '._requires.txt'`, install from a `/tmp` clone (stock APFS, no AppleDouble):

```bash
rm -rf /tmp/rka-build && git clone -q --depth 1 /Volumes/base/workspace/rka /tmp/rka-build
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force ./orchestrator
```

### 7.2 Claude Desktop config

File: `~/Library/Application Support/Claude/claude_desktop_config.json`. Merge into any existing `mcpServers` block. Replace `<user>` with your macOS username.

```json
{
  "mcpServers": {
    "rka": {"command": "docker", "args": ["exec", "-i", "rka-server", "rka", "mcp"]},
    "rka-orchestrator": {"command": "/Users/<user>/.local/bin/rka-orchestrator-mcp", "args": []}
  }
}
```

Why `docker exec` for `rka`: the in-container binary is single source of truth, no host-install drift after `docker compose up -d --build`. (Host-binary alternative: `"command": "/Users/<user>/.local/bin/rka", "args": ["mcp"]`.) Why absolute paths: macOS GUI apps inherit only launchd's default PATH; `~/.local/bin` is NOT on it, so bare `rka-orchestrator-mcp` fails to spawn.

Validate JSON, then quit Claude Desktop entirely:

```bash
python3 -m json.tool < ~/Library/Application\ Support/Claude/claude_desktop_config.json >/dev/null && echo OK
osascript -e 'quit app "Claude"'    # agent-friendly replacement for Cmd-Q
```

### 7.3 Claude Code MCP config

File: `~/.claude/mcp.json` (user-global) or `<project>/.mcp.json` (per-project, higher precedence).

```json
{
  "mcpServers": {
    "rka": {"command": "docker", "args": ["exec", "-i", "rka-server", "rka", "mcp"]},
    "rka-orchestrator": {
      "command": "/Users/<user>/.local/bin/rka-orchestrator-mcp",
      "args": [],
      "env": {"ORCHESTRATOR_API_URL": "http://localhost:9713", "ORCHESTRATOR_API_TIMEOUT": "600"}
    }
  }
}
```

Verify with `/mcp` in a fresh Claude Code session: both listed, both `connected`. Precise tool counts from outside the GUI (so an agent can assert):

```bash
# Canonical rka tool count = @mcp.tool() decorator count in source:
docker exec rka-server sh -c 'grep -c "^@mcp.tool" /app/rka/mcp/server.py'
# Sanity-check the orchestrator MCP binary exists and is executable:
ls -l ~/.local/bin/rka-orchestrator-mcp && file "$(readlink -f ~/.local/bin/rka-orchestrator-mcp)"
```

Expected: a positive integer for rka (the orchestrator surface registers 14 tools statically). The `rka-orchestrator` binary is a FastMCP stdio server — do NOT run it with `--help` (it hangs on stdin). Smoke-test by driving JSON-RPC `initialize` over stdin:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}\n' \
  | ~/.local/bin/rka-orchestrator-mcp
```

Expected: a JSON-RPC response with `result.capabilities`. (Ctrl-C to kill — stdin stays open for more messages.)

### 7.4 Restart Claude Desktop + Claude Code

Claude Desktop: `osascript -e 'quit app "Claude"'` then `open -a Claude` (or Cmd-Q + relaunch); the MCP indicator should show both servers green. Claude Code: open a new terminal; MCP changes are picked up at session start. After every `uv tool install --force`, restart both — old child processes hold the old binary snapshot.

---

## 8. Smoke tests

### 8.1 HTTP-level

```bash
# Body-shape (HTTP 200 alone insufficient — health may report db:"down"):
curl -sf http://localhost:9712/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok' and d.get('db')=='ok', d; print(d)"
curl -sf http://localhost:9713/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok', d; print(d)"
curl -sfI http://localhost:9713/dashboard | head -1
```

Expected: `status: 'ok'` + `db: 'ok'` from 9712; `status: 'ok'` from 9713; `HTTP/1.1 200 OK` for the dashboard. (`embeddings.enabled` may be `false` on a fresh install; the assertion does not require it.) Open `http://localhost:9713/dashboard` in a browser: three panels render (Runs / Parked / Detail), all empty; footer poll every 4s.

### 8.2 MCP-level

In a Claude Code session: `/mcp` -> both `rka` and `rka-orchestrator` listed `connected`. Ask Claude *"call orchestrator_health"* -> `{"status":"ok","db_path":"/data/orchestrator.db"}`. *"call rka_list_projects"* -> `[]` (fresh) or a JSON array.

### 8.3 Container-level health

```bash
docker exec rka-orchestrator id
docker exec rka-orchestrator sh -c '[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] && echo "token set" || echo "MISSING"'
docker logs rka-orchestrator 2>&1 | grep -q 'workspace mount safety check passed' && echo "safety OK"
# Bind-mount writability under the non-root user (write under /home/orchestrator, NOT /root):
docker exec rka-orchestrator sh -c 'touch /home/orchestrator/.claude/.smoke && rm /home/orchestrator/.claude/.smoke && echo "claude dir writable"'
```

Expected: `uid=1000(orchestrator) ...`, `token set`, `safety OK`, `claude dir writable`. The Gap 5 container runs as `orchestrator` (UID 1000, `HOME=/home/orchestrator`); `/root/.claude` does not exist for that user and would fail the write — that's the regression this smoke catches if a future change moves the mount back to `/root`.

---

## 9. First project onboarding (Phase D MVP)

Tool-discovery wizard — configures the per-project toolkit only; Phase O bootstrap is separate.

**9.1 Create the project.** In Claude: *"create an rka project for IoT-edge LLM benchmarking with slug iot-edge-llm"* -> `rka_create_project(...)` returns `prj_01KS...`.

**9.2 Provision the workspace directory.** The path MUST live under `HOST_WORKSPACE_ROOT` and MUST be absolute (no `~` — the `pi_onboarding_topic` regex rejects tilde paths because `~` resolves to `/root/` inside the container and the bind mount would miss):

```bash
mkdir -p "$HOME/Research/iot-edge-llm"
```

**9.3 Kick off onboarding.** `/orchestrator-onboard prj_01KS...` -> Claude calls `orchestrator_onboard_start(project_id="prj_01KS...", wait_segment=false)` returning `{workflow_thread_id, status: "starting"}` immediately. First segment runs in the background (1-3 min of Brain LLM calls).

### 9.4 Walk the interrupts

Poll the inbox until the first interrupt parks (or `/orchestrator-inbox`):

```bash
curl -s "http://localhost:9713/inbox?status=parked" | python3 -m json.tool   # snapshot
while :; do
  N=$(curl -s "http://localhost:9713/inbox?status=parked" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
  echo "parked: $N"; [ "$N" -gt 0 ] && break; sleep 4
done
```

Walk in order: `pi_onboarding_topic` (provide topic, field, venue, keywords, absolute `workspace_path` — runner stamps `workspace_path` on state and `ParkedStore.set_project_workspace` writes the `project_workspaces` row); `pi_toolkit_ratify` (TWO-TAP — review proposed toolkit: always-on `rka, context7, fs, git` + domain tools, optionally augmented by SerpAPI if `SERPAPI_KEY` set); `pi_credentials_ready` (after PI writes `<workspace>/.rka/tools.json` + `.rka/.env` from `decisions_to_present`, accept — `finalize_node` runs `probe_all_secrets`); terminal (RKA journal entry tagged `[orchestrator, onboarding, baseline]` with manifest sha256 hash; run flips to `complete`).

**The orchestrator does NOT write the host filesystem.** It returns suggested file contents in `decisions_to_present`; the PI session writes them locally; the same `${HOST_WORKSPACE_ROOT}` bind mount exposes them on the daemon's next read.

**9.5 Verify registration.**

```bash
curl -s http://localhost:9713/projects/prj_01KS.../manifest | head -c 400 && echo
ls "$HOME/Research/iot-edge-llm/.rka"
```

Expected: manifest JSON with toolkit; `tools.json` and `.env` present in `.rka/`. The `project_workspaces` row is created by `ParkedStore.set_project_workspace(project_id, workspace_path)` during the `pi_onboarding_topic` interrupt (parked_store.py:471); `set_project_manifest` only UPDATEs the row to attach manifest JSON. The row is load-bearing for `start_run` — `runner._require_workspace_or_raise` refuses missions whose project has no row (see [§10.10](#1010-missionnotfounderror-project-has-no-registered-workspace_path)).

---

## 10. First mission run + Troubleshooting

§§10.1–10.14 are the canonical Troubleshooting table (one entry per known failure mode); §10.0 is the mission-run procedure.

### 10.0 First mission run procedure

**10.0.1 Create the mission.** In Claude: *"create a mission to benchmark inference latency on small LMs at the edge, motivated by dec_01..."*. Claude calls `rka_create_mission(...)` and optionally passes `capabilities=["record_knowledge","literature"]` so the WRITE_TOOLS dispatcher accepts those buckets.

**10.0.2 Start the run.** `/orchestrator-start mis_01ABC prj_01KS...` -> Claude calls `orchestrator_run_start(mission_id, project_id, wait_segment=false)` returning `{workflow_thread_id, status: "starting"}` instantly. First segment (Brain `strategy_node` + `confirmation_brief`) runs as a background task. Poll for the first parked interrupt the same way as [§9.4](#94-walk-the-interrupts).

**10.0.3 PI two-tap ratification cycle.** For each `pi_*` interrupt: dashboard's Parked-interrupts panel updates within 4s; in Claude Desktop the `orchestrator-pi` skill renders the payload via `AskUserQuestion`; **for `pi_decision_select` TWO-TAP IS REQUIRED** (render the proposed RKA writes, ask the user explicitly, then call `orchestrator_accept`); the server emits the type-correct resume token (`accept` -> `"approve"` for greenlight, `"accept"` for decision/acceptance; `correct` -> `REDIRECT_SENTINEL + text`, closing the Phase D2.1 substring-smuggling vector — bare text containing "approve"/"accept" cannot bypass ratification); background segment runs; PI polls; repeat. Pass: `status=complete`, `terminal_state=complete`, `final_report_id` populated. Fail: `failed` with `last_error` on `/runs/{id}`, or `escalated` with an RKA checkpoint.

### 10.1 rka-worker OOMs under low Docker memory

Symptom: `docker inspect rka-worker --format '{{.RestartCount}}'` >= 5, `OOMKilled=true`; `docker logs rka-worker` ends mid-FastEmbed load. Fix: bump Docker Desktop memory to >=6 GB (8 GB recommended), restart Docker. Not on the critical path — Brain/Executor/PI loop works without the worker; only embedding-search recall on new notes degrades.

### 10.2 Bash EROFS in SDK subprocess

Symptom: Executor's `Read`/`Write`/`Edit` succeed; every `Bash` returns `OSError: [Errno 30] Read-only file system: '/home/orchestrator/.claude/shell-snapshots/...'` (or `/root/.claude/...` on an older image).

```bash
docker inspect rka-orchestrator --format '{{json .Mounts}}' | python3 -m json.tool | grep -A2 '/home/orchestrator/.claude'
```

Fix: a regression re-introduced a directory-level `:ro` mount of `~/.claude` into `/home/orchestrator/.claude`. Phase D2.3 removed it because the SDK writes `shell-snapshots/` there on every Bash. Keep ONLY the single-file mount `${HOME}/.claude.json:/home/orchestrator/.claude.json:ro`; let the SDK create `/home/orchestrator/.claude/` as a writable container-local dir. Then `docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build --force-recreate`.

### 10.3 AppleDouble breaks build or `uv tool install`

Symptom: `docker compose build` -> `failed to xattr ... operation not permitted`; OR `uv tool install --force .` -> `No such file or directory: '._requires.txt'`. Fix:

```bash
find /Volumes/base/workspace/rka -maxdepth 2 -name '._*' -not -path '*/.git/*' -delete
# If uv install still fails, install from /tmp (stock APFS, no xattr quirk):
rm -rf /tmp/rka-build && git clone -q --depth 1 /Volumes/base/workspace/rka /tmp/rka-build
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force ./orchestrator
```

`COPYFILE_DISABLE=1` does NOT help — the kernel recreates `._*` files mid-build.

### 10.4 Non-HOME workspace mount shows empty inside container

Symptom: `docker exec rka-orchestrator ls $HOST_WORKSPACE_ROOT` is empty despite host files. Fix: grant Docker Desktop Full Disk Access (System Settings -> Privacy & Security); add the parent volume to Settings -> Resources -> File sharing; `docker compose ... up -d --force-recreate rka-orchestrator`.

### 10.5 HOST_WORKSPACE_ROOT set in the wrong .env file

Symptom: daemon starts but the workspace-mount-safety log line shows `$HOME` as the mount, or mission runs see an empty workspace. Diagnostic: `grep '^HOST_WORKSPACE_ROOT=' /Volumes/base/workspace/rka/orchestrator/.env`. Fix: `orchestrator/.env` is loaded via `env_file:` — container env vars only, does NOT feed Compose YAML interpolation. Move the line to the repo-root `.env`:

```bash
sed -i '' '/HOST_WORKSPACE_ROOT/d' /Volumes/base/workspace/rka/orchestrator/.env
echo "HOST_WORKSPACE_ROOT=$HOME/Research" >> /Volumes/base/workspace/rka/.env
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --force-recreate rka-orchestrator
```

### 10.6 WorkspaceMountUnsafeError on startup

Symptom: `rka-orchestrator` exits immediately; logs show `WorkspaceMountUnsafeError: ... resolves to your $HOME` / `... = /` / `... ancestor of $HOME/.ssh`. Fix: set to a child of `$HOME` that does NOT contain `.ssh`/`.aws`/`.gnupg`/`.config`:

```bash
echo "HOST_WORKSPACE_ROOT=$HOME/Research" >> /Volumes/base/workspace/rka/.env
mkdir -p "$HOME/Research"
```

Dev-only override (warned every startup): `ORCHESTRATOR_ALLOW_HOME_MOUNT=1` in `orchestrator/.env`.

### 10.7 OAuth token expired or missing

Symptom: `/runs/{id}` shows `last_error: ... AuthenticationError(...)`; or `docker exec rka-orchestrator sh -c '[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]'` exits non-zero. Diagnostic: `docker logs rka-orchestrator --tail 50 | grep -iE 'auth|oauth|401|403|credential'`. Fix:

```bash
claude setup-token
# Paste into orchestrator/.env (CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-..., no quotes, trailing newline)
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --force-recreate rka-orchestrator
```

Use `up -d --force-recreate`, NOT `restart`: env vars are baked at *create* time, so `restart` reruns the entrypoint with the old env and silently ignores the new token (footgun until Phase D2.4). If `ORCHESTRATOR_OAUTH_SECRET_PATH=/run/secrets/claude_oauth_token` is set, the secret file takes precedence over `orchestrator/.env`.

### 10.8 MCP server red in Claude Desktop

Symptom: Settings -> MCP shows `rka` or `rka-orchestrator` red.

```bash
tail -F ~/Library/Logs/Claude/mcp*.log
# Drive a JSON-RPC initialize over stdin (do NOT use --help — it hangs on stdin):
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}\n' \
  | ~/.local/bin/rka-orchestrator-mcp
# Or: ls -l ~/.local/bin/rka-orchestrator-mcp && file "$(readlink -f ~/.local/bin/rka-orchestrator-mcp)"
```

Likely causes: wrong path in `claude_desktop_config.json` (must be absolute; GUI apps don't inherit shell PATH); JSON parse error (run `python3 -m json.tool`); container not running (`docker compose ... up -d`); binary broken by AppleDouble (re-install via [§10.3](#103-appledouble-breaks-build-or-uv-tool-install)); forgot to quit Claude Desktop after edit (`osascript -e 'quit app "Claude"'` then `open -a Claude`).

### 10.9 Run stuck in `running` past expected window

Symptom: `status=running` for many minutes, `current_node` not advancing.

```bash
docker logs rka-orchestrator --tail 200 | grep -E "background.*failed|background.*cancelled|workflow_thread_id"
docker logs rka-orchestrator --tail 200 | grep -iE "oom|killed|exit"
```

Causes: background task crashed pre-`compiled.invoke` (`_background_segment` writes `last_error` and flips to `failed` — check `/runs/{id}`); OOM-killed (Phase D2.1 startup reaper `ParkedStore.reap_orphaned_running_runs` flips orphans to `failed` on next daemon start — `docker compose ... up -d --force-recreate rka-orchestrator`); LLM still in flight (Brain `strategy_node` + `confirmation_brief` can take 3-4 min — wait).

### 10.10 MissionNotFoundError: project has no registered workspace_path

Symptom: `orchestrator_run_start` -> 404, `project 'prj_...' has no registered workspace_path. Run /orchestrator-onboard prj_... first ...`. Fix: run onboarding for the project ([§9](#9-first-project-onboarding-phase-d-mvp)); `runner._require_workspace_or_raise` refuses missions whose project has no `project_workspaces` row.

### 10.11 unknown interrupt_type from runner.resume_token

Symptom: `orchestrator_accept`/`reject`/`correct` -> 400 `unknown interrupt_type 'pi_...'`. Use `typing.get_args()` — `InterruptType` is a module-level `Literal[...]` alias; `.__args__` is a CPython implementation detail.

```bash
docker exec rka-orchestrator python -c "import typing; from orchestrator.parked_store import InterruptType; print(typing.get_args(InterruptType))"
docker exec rka-orchestrator python -c "from orchestrator.runner import _ACCEPT_TOKEN_BY_TYPE; print(sorted(_ACCEPT_TOKEN_BY_TYPE.keys()))"
```

Fix: schema-migration drift; image is older than `_ACCEPT_TOKEN_BY_TYPE`. `docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build --force-recreate`. (`_migrate_pre_phase_o_if_needed` in `ParkedStore._init_schema` rebuilds the CHECK constraint at startup if needed.)

### 10.12 WRITE_TOOLS dispatch refused — tool outside capability allowlist

Symptom: `pi_decision_select` shows `ratified_action_call_failed: tool 'rka_...' outside capability allowlist`; or run terminates `escalated` via the Phase D2.4 EC8 routing guard. WRITE_TOOLS and TOOL_CAPABILITIES live in `orchestrator.llm_client`, NOT `orchestrator.dispatcher` (there is no `orchestrator.dispatcher` module):

```bash
docker exec rka-orchestrator python -c "from orchestrator.llm_client import WRITE_TOOLS, TOOL_CAPABILITIES; import json; print(json.dumps(TOOL_CAPABILITIES, indent=2))"
```

Fix paths (preferred -> last resort): widen `allowed_capabilities` on the mission spec, re-run; add the tool to `WRITE_TOOLS` + `MCPClient` Protocol + `RestMCPClient`; `orchestrator_correct` the interrupt and redirect Brain to an allowed tool.

### 10.13 FS Actuator hook denied a Bash / Write / Edit

Symptom: Executor tool call intercepted by the Phase G2 `can_use_tool` hook: `FS escape: path outside workspace`. The hook scopes FS writes to the resolved `workspace_path`; writes to siblings under `HOST_WORKSPACE_ROOT` are denied to prevent cross-project contamination. If the path should be in scope, ensure onboarding ran and `set_project_workspace` succeeded. If a sibling path is legitimately needed, no PI-ratified escape hatch from the parent agent exists today — the Phase G3 `proposed_fs_actions` design is on paper, not implemented in the covered commit window. Workarounds: include the path in the project's workspace layout at onboarding time, or `orchestrator_correct` and redirect Brain into the project workspace.

### 10.14 `docker compose restart` doesn't pick up code or env changes

Symptom: edited source under `rka/` or `orchestrator/`, or rotated the OAuth token in `orchestrator/.env`, ran `docker compose restart <svc>`, container still runs old code/env. Fix: restart does NOT reload code (image unchanged) and does NOT re-read `env_file:` (env vars baked at container create). Use `up -d --build` for code, `--force-recreate` for env (and same-hash images that cling to the old container). Restart suffices only for migration-only changes (migration runner queries `schema_migrations` on process startup) where neither code nor env moved.

---

## 11. For autonomous code agents

Deterministic pass/fail checklist. One command per step, one grep-able success signal. Stop on first failure; the troubleshooting entry is named. All §-refs target sections established above.

```
Step  Command                                                                                  Pass            On fail
P1    xcode-select -p                                                                          /Library/Developer/CommandLineTools  xcode-select --install
P2    brew --version                                                                           starts "Homebrew"           §3.2
P3    docker info --format '{{.MemTotal}}' | awk '{print ($1 >= 6442450944)}'                  prints 1                    §10.1 (REQUIRES-HUMAN)
P4    docker compose version                                                                   contains "v2"               Reinstall Docker Desktop
P5    node --version | sed 's/^v//' | cut -d. -f1                                              >= 18                       §3.4
P6    python3.13 --version || python3 --version                                                3.13.x preferred; 3.11+     §3.5
P7    uv --version                                                                             starts "uv"                 §3.6
P8    echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"                                 exit 0                      Append to ~/.zshrc
P9    claude --version && claude setup-token --help                                            both exit 0                 §3.7
C1    git -C $REPO rev-parse --abbrev-ref HEAD                                                 "agentic"                   git checkout agentic
C2    test -d $REPO/orchestrator                                                               exit 0                      §4.1
C3    find $REPO -maxdepth 2 -name '._*' -not -path '*/.git/*' | wc -l                         0                           §10.3
C4    git -C $REPO remote -v | head -1                                                         non-empty origin URL        §4.1
E1    grep '^HOST_WORKSPACE_ROOT=' $REPO/.env                                                  non-empty                   §10.5
E2    stat -f '%Sp' $REPO/orchestrator/.env                                                    "-rw-------"                chmod 0600
E3    grep -c '^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-' $REPO/orchestrator/.env                 1                           §10.7
D1    docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build    "Started" for 3 containers  §10.2/§10.3/§10.4
D2    docker inspect rka-server --format '{{.State.Status}}'                                   "running"                   Check logs
D3    docker inspect rka-orchestrator --format '{{.State.Status}}'                             "running"                   §10.6/§10.7
D4    docker inspect rka-worker --format '{{.State.OOMKilled}}'                                "false"                     §10.1 (non-blocking)
D5    curl -sf :9712/api/health | python3 -c "..." (see §8.1)                                  exit 0, db:'ok'             rka-server logs
D6    curl -sf :9713/health                                                                    HTTP 200                    §10.6/§10.7
D7    docker logs rka-orchestrator 2>&1 | grep -q 'workspace mount safety check passed'        exit 0                      §10.5/§10.6
D8    docker exec rka-orchestrator id | grep -q 'uid=1000(orchestrator)'                       exit 0                      Rebuild --build-arg ORCH_UID
D9    docker exec rka-orchestrator sh -c 'touch /home/orchestrator/.claude/.smoke && rm /home/orchestrator/.claude/.smoke'  exit 0  §10.2 (EROFS regression)
M1    test -x ~/.local/bin/rka && test -x ~/.local/bin/rka-orchestrator-mcp                    exit 0                      §10.3
M2    python3 -m json.tool < ~/Library/Application\ Support/Claude/claude_desktop_config.json  exit 0                      §10.8
M3    /mcp inside Claude Code                                                                  both "connected"            §10.8
M4    docker exec rka-server sh -c 'grep -c "^@mcp.tool" /app/rka/mcp/server.py'               positive integer            §10.8
S1    Claude call orchestrator_health                                                          {"status":"ok",...}         §10.6/§10.7
S2    Claude call rka_list_projects                                                            JSON array                  rka-server logs
O1    rka_create_project                                                                       returns prj_*               —
O2    mkdir -p "$HOME/Research/<slug>"                                                         dir exists                  Check HOST_WORKSPACE_ROOT
O3    orchestrator_onboard_start(pid, wait_segment=false)                                      {"status":"starting"}       §10.6/§10.7
O4    Walk pi_onboarding_topic / pi_toolkit_ratify / pi_credentials_ready                      terminal "complete"         §10.9/§10.11
O5    GET /projects/<pid>/manifest                                                             JSON with toolkit           Re-run onboarding
R1    orchestrator_run_start(mid, pid, wait_segment=false)                                     {"status":"starting"}       §10.10/§10.11
R2    Walk pi_* interrupts (TWO-TAP on pi_decision_select)                                     terminal "complete"         §10.12/§10.13
```

(`$REPO` = `/Volumes/base/workspace/rka` or your clone path; FAIL maps 1:1 to §§10.1–10.14.)

**REQUIRES-HUMAN (no reliable CLI):** P3 (Docker Desktop memory — see [§3.3](#33-docker-desktop-tuning) for the best-effort JSON path); Full Disk Access; non-`$HOME` File-sharing volumes. For unattended runs, prefer the `$HOME/Code/rka` clone path (variant B in [§4.1](#41-clone-check-out-agentic)) to sidestep all three.

---

## 12. What's NOT covered

Explicit non-goals:

- **Gap 4c ephemeral sandbox.** Firecracker / microVM per-mission isolation is designed in `docs/archive/2026-q2/orchestrator/gap-4c-ephemeral-sandbox-design.md` (archived); current build uses the long-running `rka-orchestrator` container only.
- **Multi-operator deployments.** Concurrent PIs, multi-tenant authz, SIEM forwarding, HA failover — out of scope. The Gap 5 Docker-secrets path (`ORCHESTRATOR_OAUTH_SECRET_PATH`) rotates credentials without `.env` edits but assumes a single PI.
- **Linux (bare-metal Docker Engine).** Mostly works with three caveats: pass `--build-arg ORCH_UID=$(id -u) --build-arg ORCH_GID=$(id -g)`; no AppleDouble; no Full Disk Access.
- **Cloud / remote daemon.** Doable via port-forward + `ORCHESTRATOR_API_URL`, but no auth-at-the-edge story is shipped.
- **API key walkthroughs.** Per-account steps for `SEMANTIC_SCHOLAR_API_KEY`, `ZOTERO_API_KEY`, `SERPAPI_KEY`, etc. live in `rka/skills/mcp-credentials`.
- **Plugin install (`/plugin marketplace add rka@rka`).** One-liner inside Claude Code after this runbook completes.
- **Phase O full project bootstrap.** Designed in `orchestrator/docs/phase-o-project-onboarding-design.md`; this runbook covers Phase D MVP (tool-discovery wizard) only.
- **Phase G3 PI-ratified FS-action escape.** Referenced in [§10.13](#1013-fs-actuator-hook-denied-a-bash--write--edit) as a future design; not implemented in the covered commit window.

---

## 13. Versioning stamp

Last updated 2026-05-30; Gap 1-5 hardening in `ada81d0..81b7e05` (Phase A–D2.4: workspace mount safety, Gap 5 non-root user `HOME=/home/orchestrator`, async-resume endpoints, substring-routing fix, startup orphan-run reaper, Bash EROFS fix, OAuth-token-only auth, `project_workspaces` row required for `start_run`, v2.6 `project_id`-required absorption).

Revision history:
- 2026-05-30 (rev 2): defect-list fixes — collided §§5/6/7/8 renumbered to §§10/11/12/13; `/root/.claude*` -> `/home/orchestrator/.claude*` (Gap 5 user, incl. D9 smoke); `orchestrator.dispatcher` -> `orchestrator.llm_client` (§10.12); `project_workspaces` row attribution -> `ParkedStore.set_project_workspace` (§9.5); `InterruptType` -> `typing.get_args` (§10.11); MCP-binary smoke -> JSON-RPC initialize (§7.3, §10.8); GUI steps annotated osascript/JSON or REQUIRES-HUMAN; OAuth-token rotation `restart` -> `up -d --force-recreate` (§10.7); `read -rs` given `-p` prompt (§5.1); health smoke is now body-shape grep (§8.1); inbox-poll loops (§9.4, §10.0.2); clone-URL + parent-dir gaps closed (§4.1); hardcoded path called out at top with `$HOME/Code/rka` variant; agent checklist moved to §11.
- 2026-05-30 (rev 1): initial runbook covering Phase A–D2.4.