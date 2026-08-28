# RKA Installation Guide

> **How to read this guide**
> - **Humans**: read top-to-bottom; the quick install path is §3.
> - **A coding agent (Claude Code, Codex, or similar) asked to "install RKA" / "finish my RKA setup"**: this file is your runbook. Execute §3 in order; §6 (Claude Desktop wiring) and §7 (diagnosis) are procedures to run when the relevant step calls for them. Follow the **execution contract** in §0 before you start. §11 is retained only as an unsupported historical reference; do not install it.

## 0. Execution contract (read first if you are the installing agent)

You are running on a machine that already has Docker and a coding agent. Your job is to bring RKA up and wire it into the surfaces the user actually wants. Follow these rules:

1. **Confirm scope first.** Do **Step 0** in §3 before running anything — ask the user which surfaces to set up. Do not assume "all of them."
2. **Go in order; verify as you go.** After each step, check its **✅ success signal** before moving on. If a signal doesn't appear, **⛔ stop**, run the step's recovery/failure note, and surface the exact output — don't push forward on a broken step.
3. **Stop and ask at every 🟡 gate.** A **🟡 ASK THE USER** marker means the next action needs information or an action only the user can supply — an install location, an API key, an ngrok authtoken, an OAuth passphrase, a "yes, do the destructive thing." **Never invent, generate, or guess a secret, token, path, or scope choice.** Ask, wait for the answer, then continue.
4. **Never write secrets into the repo or a chat transcript.** Tokens, passphrases, and API keys go only into the user's local credential vault (`rka cred`, see §5.5) or their own shell/env. If the user pastes a secret to you, use it in memory only; do not echo it back or commit it.
5. **Idempotence.** Every step is safe to re-run. If something is already configured correctly, report that and move on rather than clobbering it.

**Legend used throughout:** ✅ = success signal to confirm before proceeding · 🟡 = stop and ask the user · ⛔ = stop on failure and surface the error.

---

## 1. What you get when you're done

| Surface | What you'll have |
|---|---|
| **RKA backend** | FastAPI + worker + SQLite + FTS5 + sqlite-vec running in Docker on `localhost:9712`. Web dashboard at the same URL. |
| **Claude Code (Executor)** | Core plugin: 3 role skills (`rka:rka-brain`, `rka:rka-executor`, `rka:rka-pi`), the credential setup utility, 5 slash commands (`/rka-status`, `/rka-search`, `/rka-pending`, `/rka-set-project`, `/rka-setup-claude-desktop`), a SessionStart backend check, and the typed MCP dispatch surface. |
| **Writer (optional, separate)** | Install the explicit-only [`rka-writer`](https://github.com/rka-project/rka-writer) plugin only when manuscript drafting or revision is wanted. It is not included in or activated by RKA Core. |
| **Claude Desktop (Brain)** | Typed RKA tool surface via the `mcpServers.rka` entry in `claude_desktop_config.json`. Wrapper-based config gives version checking; every scoped operation still requires an explicit project id. Skills and slash commands are Claude Code only (Claude Desktop's plugin format is separate). |
| **ChatGPT (optional remote connector)** | RKA reachable from ChatGPT as a custom MCP connector over an OAuth-protected ngrok tunnel — an 8-tool surface (5 dispatch + 3 skill tools). Opt-in; set up in **Step 6** (§3). The web UI is never exposed. |

For contributor installs, dependency ownership, the Core-only pytest selector,
and the disposable startup gate, see
[`docs/CORE_PROFILE.md`](docs/CORE_PROFILE.md). The production Docker image uses
that Core dependency profile and does not install legacy LLM-provider SDKs.

### 1.1 Core tool surface (v3.x)

In Claude Desktop and Claude Code, you'll see **5 always-on `rka` tools** at session start:

| Tool | Role | Operations behind it |
|---|---|---|
| `rka_query` | Read dispatch (the "search/list/get" entry point) | Typed read operations; inspect the live catalog with `rka_describe` |
| `rka_execute` | Write dispatch (the "add/update/create/submit" entry point) | Typed write/lifecycle operations; inspect the live catalog with `rka_describe` |
| `rka_describe` | Schema lookup + examples for any operation | — |
| `rka_load_tools` | Escape hatch: register legacy tool aliases for the rest of the session | — |
| `rka_help` | Alias for `rka_describe` (mnemonic surface) | — |

The typed Pydantic operations under `rka_query` / `rka_execute` carry per-branch enum and required-field enforcement at the **FastMCP schema layer**, so invalid values are rejected before dispatch. `rka_describe("")` is the authoritative operation index; do not rely on a copied count in documentation. Legacy per-tool aliases are `tier=deferred` and load on demand via `rka_load_tools`; `RKA_LEGACY_TOOLS=1` remains only as a compatibility switch for historical callers.

---

## 2. Prerequisites (5 minutes if not already installed)

| # | Component | Why | Where |
|---|---|---|---|
| 1 | **Docker Desktop** | Runs RKA's FastAPI + worker in a container | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) — installer for macOS / Windows / Linux |
| 2 | **Claude Desktop** (the native app) | Hosts the Brain (strategy + synthesis) | [claude.ai/download](https://claude.ai/download) — macOS / Windows. **Windows note**: install via Microsoft Store OR standalone `.exe`; both write the config to `%APPDATA%\Claude\`, so this guide works either way. |
| 3 | **VSCode** | Hosts the Claude Code extension | [code.visualstudio.com](https://code.visualstudio.com/) — macOS / Windows / Linux |
| 4 | **Claude Code extension for VSCode** | Hosts the Executor | VSCode → Extensions → search `Claude Code` → install. Or: `code --install-extension anthropic.claude-code` from a terminal. |
| 5 | **Python 3** | Required for the cross-platform wrapper script that proxies between Claude and the Docker backend | macOS: ships with Xcode Command Line Tools — run `xcode-select --install` if `python3 --version` fails on a fresh machine (or `brew install python3`). Windows: [python.org/downloads](https://www.python.org/downloads/) — **check the "Add Python to PATH" box during install**. Linux: `apt install python3` / `dnf install python3`. Verify with `python3 --version` (or `python --version` on Windows). |
| 6 | **git** | Clones the RKA repo for the Docker compose file | macOS/Linux: built in or via package manager. Windows: [git-scm.com/downloads](https://git-scm.com/downloads). |
| 7 | **Zotero desktop + Connector** *(recommended)* | Persistent literature library — the AI reads paper full text from here. Zotero Connector captures papers via your institution's authenticated browser session, so the AI inherits your access without you sharing credentials. | Desktop: [zotero.org/download](https://www.zotero.org/download/) (or `brew install --cask zotero`). Connector: [zotero.org/download/connectors](https://www.zotero.org/download/connectors) (Chrome / Safari / Firefox / Edge). |

> **Why two Claude apps?** Brain and Executor are different roles. Brain (in Claude Desktop) reasons about research direction, makes decisions, processes maintenance. Executor (in Claude Code) writes code, runs experiments, picks up missions. They share the same RKA knowledge base, so context survives across roles and sessions.

### Required API keys (one-time, used by every project)

Set these once in `claude_desktop_config.json` env blocks:

| Key | Source | Why |
|---|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api#api-key-form) | Free; lifts S2 rate limits. Used by RKA literature integrations and paper-search; external reference-checking clients may also use it. |
| `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` | [zotero.org/settings/keys](https://www.zotero.org/settings/keys) | Generate a "Save to Server" + "Full library access" key. Library ID is the 7-digit userID on the same page. Used by Zotero integrations. |
| `PAPER_SEARCH_MCP_UNPAYWALL_EMAIL` | Your institutional email | Used for rate-limit identification (not authentication). |

Optional:
| Key | Use |
|---|---|
| `SERPAPI_KEY` | Web search fallback when curated catalogs miss something |
| `PAPER_SEARCH_MCP_CORE_API_KEY` | Open-access full-text search via CORE |

---

## 3. Quick install (the recommended path)

The plugin handles most of the work. Follow the steps in order. Step 0 decides which of the later steps you run.

### Step 0 — 🟡 Confirm scope with the user

Before installing anything, ask the user which surfaces they want. Their answer decides which steps below you run. Present these options and wait for a reply:

| Surface | What it gives them | Steps to run |
|---|---|---|
| **Claude Desktop (Brain)** | Strategy/synthesis role in the Claude desktop app | Steps 1–5 |
| **Claude Code (Executor)** | The full plugin — skills, slash commands, hook — in VSCode/Claude Code | Steps 1–3 (+ Step 4 wires Desktop) |
| **Codex or another MCP client** | RKA's stdio MCP surface in a non-Claude client | Step 1 + the **Manual install** in §8 (Codex uses its own MCP config, not the Claude plugin) |
| **ChatGPT (remote connector)** | RKA reachable from ChatGPT over an OAuth tunnel | Steps 1 + **Step 6** (needs ngrok; you will ask for a token and passphrase there) |

Also ask whether they have any of the **optional API keys** in §2 (Semantic Scholar, Zotero, Unpaywall email, SerpAPI). You'll wire those in at Step 5.5 — RKA runs without them, but literature features are richer with them.

Everyone runs **Step 1** (the backend). Then run only the steps their chosen surfaces need. If the user just says "install RKA" without specifics, the sensible default is Claude Desktop + Claude Code (Steps 1–5); confirm that read-back with them before proceeding, and mention ChatGPT is available as an add-on.

### Step 1 — Start the RKA backend

**Pre-check**: Docker Desktop must be running before `docker compose up -d` will work. Confirm with `docker info` (non-zero exit means Docker isn't running — launch Docker Desktop and wait until the whale icon says "running", then retry).

**🟡 Precondition (clone location)**: ask the user where they want the repo cloned (default: `~/Code` on macOS/Linux, `%USERPROFILE%\Code` on Windows). `cd` into that parent, so the repo lands at `<parent>/rka-core`. **Record the absolute `<parent>/rka-core` path** — Step 2 needs it as the marketplace path. Don't clone into an unstated cwd; if the user has no preference, state the default you're using and proceed.

> **⚠️ Windows: do not clone into a OneDrive-synced folder.** On most Windows installs `Desktop` and `Documents` are backed up by OneDrive. OneDrive's Files On-Demand will silently dehydrate untouched repo files into cloud placeholders, and Docker BuildKit then refuses to send them in the build context — a later `docker compose up -d --build` fails with `invalid file request <path>`. The clone works fine; the breakage appears weeks later on the first rebuild. `%USERPROFILE%\Code` (the default above) is outside OneDrive and is the safe choice. If the repo is already in a synced folder, see [§9 Windows: rebuilding and updating](#windows-rebuilding-and-updating-an-existing-install) for the recovery procedure.

```bash
# Example: pick a parent dir and cd into it first
mkdir -p ~/Code && cd ~/Code              # macOS/Linux
# Windows (PowerShell): New-Item -ItemType Directory -Force "$env:USERPROFILE\Code" | Set-Location

git clone https://github.com/rka-project/rka-core.git
cd rka-core
docker compose up -d
```

Wait ~1 minute. Verify:

```bash
curl http://localhost:9712/api/health
# Expect: {"status":"ok","version":"3.x.x", ...}
```

Open http://localhost:9712 in your browser to confirm the dashboard loads.

**✅ Success signal**: `curl` returns JSON with `"status":"ok"` and a `"version"` field beginning with `3.` AND `http://localhost:9712` renders the dashboard HTML.

> **⚠️ Windows: if this fails, try `http://127.0.0.1:9712` before assuming the backend is broken.** `localhost` resolves to IPv6 `::1` first, and Docker Desktop's WSL2 backend publishes the container on IPv4 only. WSL2's `localhostForwarding` proxy still *accepts* the `::1` connection and then resets it, so the browser shows `ERR_CONNECTION_RESET` and `curl` reports `Recv failure: Connection was reset` — both look like a dead server when the API is perfectly healthy. Because the TCP handshake succeeds, no automatic IPv4 fallback happens. If `127.0.0.1` works and `localhost` doesn't, the backend is fine; use `127.0.0.1` throughout and see [§9 Windows](#windows-specifically) for the permanent fix.

**Recovery**: if curl returns non-zero or non-2xx, run `docker compose ps` to confirm both `rka-server` and `rka-worker` are up. If a container is restarting, run `docker compose logs --tail=20 rka` and surface the output. If the worker is `OOMKilled`, bump Docker Desktop's Resources → Memory ceiling to ≥6 GB (per the operational note in CLAUDE.md) and re-up.

> **What this does**: starts two containers (`rka-server` for the API + web UI, `rka-worker` for background jobs). Data is persisted in a Docker volume named `rka-data`. To stop: `docker compose down`. To stop AND wipe data: `docker compose down -v` (don't do this unless you mean it).

#### Optional: LM Studio suggestions in the manuscript workbench

RKA does not require a local language model. If you want the workbench's **Ask
LM Studio** action, start LM Studio's local API server, load a model that
supports structured JSON output, and verify the served model ID:

```bash
curl http://127.0.0.1:1234/v1/models
```

Put that exact ID in a repo-local `.env` file (do not commit it), then recreate
only the API container:

```dotenv
RKA_WORKBENCH_LM_STUDIO_MODEL=the-served-model-id
```

```bash
docker compose up -d --force-recreate rka
```

Compose routes the container to
`http://host.docker.internal:1234/v1`. A non-Docker RKA process defaults to
`http://127.0.0.1:1234/v1`. The adapter accepts only those local-machine forms,
uses no API key, never falls back to a cloud model, and stores the result as an
unapplied semantic proposal.

### Step 2 — Add the local RKA marketplace in Claude Code

The marketplace lives inside the cloned RKA repo (at `.claude-plugin/marketplace.json`).

**Pre-check**: `ls <path>/.claude-plugin/marketplace.json` must succeed. If the file is missing, the path is wrong or the user didn't clone the right repo — surface a clear error before invoking `/plugin`.

In any Claude Code chat window (in VSCode), run:

```
/plugin marketplace add /absolute/path/to/your/cloned/rka-core
```

Replace `/absolute/path/to/your/cloned/rka-core` with the actual path where you cloned the repo in Step 1 (e.g., `/Users/<you>/Code/rka-core` on macOS, `C:\Users\<you>\Code\rka-core` on Windows). Use the absolute path, not `~`.

**Success signal**: Claude Code prints "Marketplace 'rka' added" (or equivalent confirmation).

### Step 3 — Install the plugin

```
/plugin install rka@rka
```

Wait for the install to complete (~5–10 seconds).

**Post-check**: run `/plugin list` and string-match against `rka@rka`. If absent, surface the install log and stop.

**Success signal**: `/plugin list` output contains `rka@rka`.

### Step 4 — Have Claude Code set up Claude Desktop too

In the same Claude Code chat:

```
/rka-setup-claude-desktop
```

Or if you prefer natural language, just say:

> Set up RKA for Claude Desktop too.

The plugin's `rka-pi` skill teaches Claude Code how to:
1. Detect your OS (macOS / Windows / Linux).
2. Locate `claude_desktop_config.json` at the right path.
3. Back up the existing config to `claude_desktop_config.json.backup-YYYYMMDD-HHMMSS`.
4. Atomically merge the `mcpServers.rka` entry pointing at the plugin's wrapper script.
5. Verify the merge by re-reading the file.
6. Tell you to fully quit + reopen Claude Desktop.

If anything fails at any step, the original config is restored from the backup automatically. No silent overwrites.

**Success signal**: Claude Code prints `✅ Claude Desktop config updated. The RKA MCP server entry is in place at <config_path>.` After Step 5's full quit + reopen, a fresh Claude Desktop chat will list the 5 Core dispatch tools (`rka_query`, `rka_execute`, `rka_describe`, `rka_load_tools`, `rka_help`).

### Step 4.5 (optional) — Install the standalone Writer plugin

Manuscript drafting is intentionally outside this repository. If it is wanted,
install [`rka-writer`](https://github.com/rka-project/rka-writer) by following
that repository's README. Writer is explicit-only and may use this Core MCP as
an evidence source, but Core does not install Writer tools, commands, hooks, or
dependencies.

### Step 5 — Fully quit and reopen Claude Desktop

The Claude Desktop MCP loader reads its config at startup, so the config change won't apply until you do a full quit + reopen. On macOS this means **Cmd+Q** (the red close button only minimizes — it does NOT quit, and the MCP loader will not re-read the config).

| OS | Quit |
|---|---|
| macOS | Cmd+Q (not just clicking the red close button — that minimizes) |
| Windows | Right-click the Claude tray icon → Quit, then reopen |
| Linux | Same shortcut as your desktop environment's Quit |

Open a fresh chat in Claude Desktop. Ask:

> List my RKA projects.

Brain should call `rka_query(operation="list_projects")` through the typed dispatch surface and return the list (empty on a fresh install). If you also see a SessionStart hook line like `✅ RKA reachable at http://localhost:9712 (version 3.x.x, default project ...)` at session start in Claude Code, you're done. The `✅ RKA reachable` line with a `version 3.x` substring confirms that the hook handshake reached the split Core runtime.

**✅ Success signal**: SessionStart hook line contains `✅ RKA reachable` (with a `version 3.x` substring) AND Brain returns a project list (empty or otherwise) without error.

### Step 5.5 — 🟡 First-run credentials (`rka cred init`)

With the backend up and the plugin wired, bootstrap the global credential vault before the first real session. **Ask the user for each API key you're going to store** (from the list they gave you at Step 0) — never invent or hard-code a key. RKA runs fine with zero keys; each one just enriches literature features.

```bash
rka cred init          # creates ~/.config/rka/creds.env (mode 0600, XDG-compliant)
rka cred set SEMANTIC_SCHOLAR_API_KEY <value-the-user-gave-you>   # repeat per key: ZOTERO_API_KEY, etc. from §2
rka cred check         # verifies which keys are present + reachable
```

The key values are secrets: pass them straight to `rka cred set` and do not echo them back or write them into any file the repo tracks. `rka cred env` prints export lines for shell sourcing; `rka cred propagate` syncs the vault into downstream consumers (Claude Desktop config, `orchestrator/.env`). Full reference: [`docs/CRED_VAULT.md`](docs/CRED_VAULT.md). The keys from §2 (Semantic Scholar, Zotero, Unpaywall email, optionally SerpAPI / CORE / Claude OAuth) all live here — this is the recommended path instead of hand-editing `claude_desktop_config.json` env blocks.

### Step 6 (optional) — Expose RKA to ChatGPT (custom connector)

Run this **only if** the user chose ChatGPT at Step 0. It exposes the local MCP server to ChatGPT over an OAuth-protected tunnel; the web UI stays private and secrets never leave the machine. This step has three 🟡 gates because it needs an install, a token, and a passphrase that only the user can provide. The full reference (with every env var, health check, and troubleshooting) is [`docs/CHATGPT_CONNECTOR.md`](docs/CHATGPT_CONNECTOR.md) — this step is the executable summary.

**Architecture**: `ChatGPT ──HTTPS──▶ ngrok ──▶ OAuth proxy (:9720) ──▶ RKA HTTP MCP (:9713) ──▶ RKA API (:9712)`.

> Steps 3, 4, and 5 each start a **long-running foreground process**. Run them in the background or in separate terminals (don't block waiting on them), then confirm each with its health check before moving on. To keep the connector working, all three must stay running.

1. **🟡 Confirm + check ngrok.** Confirm the user still wants the ChatGPT connector, then check `command -v ngrok`. If it's missing, ask the user to install it ([ngrok.com/download](https://ngrok.com/download)) and, one-time, authenticate it with their own authtoken: `ngrok config add-authtoken <their-token>`. The authtoken is a personal secret — **ask them to run that command themselves, or paste the token for you to use in-memory only; never store it in the repo.**

2. **🟡 Choose an OAuth passphrase.** Ask the user to choose a strong passphrase for the connector login (this is what they'll enter in ChatGPT's OAuth flow). Keep it in the environment only — do not write it to a tracked file. Export it for the proxy:
   ```bash
   export RKA_MCP_OAUTH_PASSPHRASE='<passphrase-the-user-chose>'
   ```

3. **Start the HTTP MCP with skill tools on** (port 9713). `RKA_SKILL_TOOLS=1` gives ChatGPT the 8-tool surface (the 5 dispatch tools plus `rka_start_session`, `rka_list_skills`, `rka_read_skill`); local stdio clients are unaffected:
   ```bash
   RKA_API_URL=http://127.0.0.1:9712 RKA_SKILL_TOOLS=1 \
     rka mcp --transport http --host 127.0.0.1 --port 9713
   ```
   (A `406` from `curl http://127.0.0.1:9713/mcp` is expected — that endpoint needs the MCP handshake, not a plain GET.)

4. **Start the OAuth proxy** (port 9720), reading the passphrase from step 2:
   ```bash
   RKA_MCP_UPSTREAM='http://127.0.0.1:9713/mcp' RKA_MCP_OAUTH_PORT=9720 \
     python3 scripts/rka_mcp_oauth_proxy.py
   ```
   **✅ Success signal**: `curl -sS http://127.0.0.1:9720/healthz` returns `{"status":"ok"}`.

5. **Start the tunnel** and read the public host:
   ```bash
   ngrok http 9720
   ```
   Note the `https://<something>.ngrok.app` host it prints.

6. **🟡 Hand the user the connector settings** and let them finish in ChatGPT (you can't drive their ChatGPT UI):
   - Connection type: **Server URL**
   - Server URL: `https://<ngrok-host>/mcp`
   - Authentication: **OAuth**, then enter the passphrase from step 2.

**✅ Success signal**: in ChatGPT, `rka_start_session(role="pi")` returns a role skill + checklist, and `rka_query(args={"operation": "list_projects"})` returns the project list. If ChatGPT shows only 5 tools, the MCP was started without `RKA_SKILL_TOOLS=1` (or ChatGPT cached the old list — reconnect the connector). The free ngrok host changes on restart; if it does, update the Server URL in ChatGPT.

---

## 4. Cross-platform reference

### Config file paths

| OS | Claude Desktop config | RKA `integration.json` (created by the plugin in §6) |
|---|---|---|
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` | `~/Library/Application Support/RKA/integration.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` (resolves to `C:\Users\<you>\AppData\Roaming\Claude\`) | `%APPDATA%\RKA\integration.json` |
| **Linux** | `~/.config/Claude/claude_desktop_config.json` | `~/.local/share/RKA/integration.json` (XDG default) |

### Wrapper script paths (after plugin install)

The plugin install copies its files to `~/.claude/plugins/cache/rka/rka/<version>/` (macOS/Linux) or `%USERPROFILE%\.claude\plugins\cache\rka\rka\<version>\` (Windows). The wrapper script at `bin/rka-mcp-bridge.py` is invoked by Claude apps via `python3 <path>/bin/rka-mcp-bridge.py`.

### Backend connection (used by the wrapper)

The wrapper reads `integration.json` to know which RKA instance to bridge to. By default, the plugin's setup writes one pointing at the Docker backend at `http://localhost:9712`. To override (e.g., for a remote RKA instance), edit `integration.json` directly.

### Remote access: ChatGPT custom connector (optional)

RKA can also be reached from ChatGPT as a custom MCP connector: local HTTP MCP on `127.0.0.1:9713` (with `RKA_SKILL_TOOLS=1` for the 8-tool surface) → OAuth reverse proxy (`scripts/rka_mcp_oauth_proxy.py`) on `127.0.0.1:9720` → ngrok HTTPS → ChatGPT "Server URL" + OAuth. Only the MCP server is tunneled — the web UI stays private, and the passphrase and API keys never leave the machine. The executable steps (with the 🟡 ngrok/passphrase gates) are **Step 6** in §3; the full reference is [`docs/CHATGPT_CONNECTOR.md`](docs/CHATGPT_CONNECTOR.md). Never paste real secrets into a chat transcript.

---

## 5. Verifying the install

After Step 5, run these checks:

### In Claude Code

1. `/help` should list five `rka:rka` slash commands. String-match each of: `/rka-status`, `/rka-search`, `/rka-pending`, `/rka-set-project`, `/rka-setup-claude-desktop`. All five must be present.
2. `/context` should show the three RKA Core roles (`rka-brain`, `rka-executor`, and `rka-pi`) plus the credential setup utility. It must not show `rka-writer` unless that separate plugin was independently installed and explicitly invoked.
3. Run `/rka-status`. Expected output: project name, phase, focus, open checkpoints (or "none").
4. New chat sessions should start with an automatic line. **Expected stdout snippet**: `✅ RKA reachable at http://localhost:9712 (version 3.x.x, default project ...)`.

### In Claude Desktop

Ask in any new chat:

> What RKA tools do you have access to?

Brain should list **5 always-on tools (3 dispatch + 2 escape hatches)**: `rka_query`, `rka_execute`, `rka_describe`, plus `rka_load_tools` and `rka_help` as navigator escape hatches. This matches the §1.1 surface count exactly. Confirm by asking: *"Call `rka_describe` with an empty string"* — Brain should return the current 152-operation index (68 reads and 84 writes).

If you instead see a long list of legacy tool names (e.g., `list_projects`, `get_status`, `add_note`, etc. — surfaced as one MCP tool each), your Brain is running with `RKA_LEGACY_TOOLS=1` (orchestrator daemon mode). For the user-facing Claude Desktop session, unset this env var and restart.

### Backend

```bash
docker compose ps
# Expect both rka-server and rka-worker as "Up" / "healthy"

curl http://localhost:9712/api/health
# Expect {"status":"ok","version":"3.x.x", ...}
```

---

## 6. For Claude Code: `/rka-setup-claude-desktop` execution steps

When the user invokes `/rka-setup-claude-desktop` (or asks something like "set up RKA for Claude Desktop"), execute these steps in order. Stop and report any error before continuing.

### 6.1 — Detect the OS and resolve paths

> **Variable-plumbing note** for agent executors: §6.1 (this section), §6.3, §6.5, and §6.6 are designed to be executed as a **single Python process** — the names `config_path`, `integration_path`, `bridge_path`, and `backup` are defined once and reused. If you run §6.1 as a Python block and §6.5 as a separate bash block, the bash block will see an unbound `$config_path`. Either: **(a)** concatenate §6.1 + §6.3 + §6.5 + §6.6 into one Python script (recommended), OR **(b)** export the resolved Path values to env vars (`os.environ['CONFIG_PATH'] = str(config_path); os.environ['BRIDGE_PATH'] = str(bridge_path); os.environ['BACKUP'] = str(backup)`) and reference them as `"$CONFIG_PATH"` / `"$BRIDGE_PATH"` / `"$BACKUP"` in the bash variants. The Python concatenation path is fewer moving parts; the env-var path is for agents who want to keep bash + Python blocks separate.

```python
import sys, os, shutil
from pathlib import Path


def _python_launcher() -> str:
    """Resolve the python3 launcher the user has on PATH (py / python / python3).

    Used everywhere this guide invokes Python from a wrapper config (Claude
    Desktop's mcpServers entry, the §6.2 health probe, etc.) so Windows users
    without a `python3` shim on PATH still resolve to a working interpreter.
    """
    for name in ("python3", "py", "python"):
        if shutil.which(name):
            return name
    # Fallback to the current interpreter if nothing is on PATH (last resort).
    return sys.executable


if sys.platform == "darwin":
    config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    integration_path = Path.home() / "Library/Application Support/RKA/integration.json"
elif sys.platform == "win32":
    # %APPDATA% may resolve to a path containing spaces (e.g.,
    # "C:\Users\First Last\AppData\Roaming"); pathlib handles this
    # transparently. Avoid shell-quoting; use the Path object directly.
    config_path = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    integration_path = Path(os.environ["APPDATA"]) / "RKA" / "integration.json"
else:
    config_path = Path.home() / ".config/Claude/claude_desktop_config.json"
    integration_path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "RKA" / "integration.json"

# Post-check: parent directory must exist and be writable
config_path.parent.mkdir(parents=True, exist_ok=True)
assert os.access(config_path.parent, os.W_OK), f"Cannot write to {config_path.parent}"

# Export for downstream bash blocks (only needed if you split §6.1 from §6.5/§6.6).
os.environ["CONFIG_PATH"] = str(config_path)
os.environ["INTEGRATION_PATH"] = str(integration_path)
print(f"CONFIG_PATH={config_path}")
print(f"INTEGRATION_PATH={integration_path}")
```

**Failure modes**: if `os.environ["APPDATA"]` raises `KeyError` on Windows, the user is running from an environment without standard Windows env vars (e.g., MSYS / Cygwin / WSL) — surface the error and ask the user to run Claude Code from a normal PowerShell or cmd terminal.

### 6.2 — Verify the RKA backend is reachable

Use the `_python_launcher()` helper defined in §6.1 to resolve the right Python invocation on the host (Windows users without `python3` on PATH will get `py` or `python`):

```bash
# macOS/Linux — python3 is usually on PATH
curl -sf http://localhost:9712/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok' and d['version'].startswith('3.'), d; print('healthy')"
```

```powershell
# Windows (PowerShell) — uses the `py` launcher (most common) with a python fallback
$json = curl.exe -sf http://localhost:9712/api/health
$py = (Get-Command py -ErrorAction SilentlyContinue) ?? (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
$json | & $py.Source -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok' and d['version'].startswith('3.'), d; print('healthy')"
```

Or, fully cross-platform from inside a single Python process (recommended when running the §6 sequence as one script — this is the same `_python_launcher()` semantics the wrapper config will use):

```python
import json, urllib.request
d = json.loads(urllib.request.urlopen("http://localhost:9712/api/health", timeout=5).read())
assert d["status"] == "ok" and d["version"].startswith("3."), d
print("healthy")
```

**Success signal**: stdout prints `healthy`.

**Failure modes**: if non-zero exit, the user needs to run `docker compose up -d` from their RKA repo, then retry. If the backend is up but reports a pre-3.0 version, halt and tell the user to upgrade (`git pull && docker compose up -d --build`) before installing the split Core 3.x/plugin 2.x distribution.

### 6.3 — Locate the plugin's wrapper script

The wrapper lives at `${CLAUDE_PLUGIN_ROOT}/bin/rka-mcp-bridge.py` where `CLAUDE_PLUGIN_ROOT` is set by Claude Code's plugin loader. From inside a `/rka-setup-claude-desktop` invocation, the path is the install location of the rka plugin under `~/.claude/plugins/cache/rka/rka/<version>/bin/rka-mcp-bridge.py`.

To find it programmatically:

```bash
# macOS / Linux
find ~/.claude/plugins/cache/rka/rka -name "rka-mcp-bridge.py" | sort | tail -1
```

```powershell
# Windows (PowerShell)
Get-ChildItem -Path "$env:USERPROFILE\.claude\plugins\cache\rka\rka" -Filter rka-mcp-bridge.py -Recurse | Sort-Object FullName | Select-Object -Last 1 -ExpandProperty FullName
```

Cross-platform Python fallback (works everywhere Python is on PATH — and this is the form §6.6 reuses, so prefer this path):

```python
import os
from pathlib import Path
root = Path.home() / ".claude" / "plugins" / "cache" / "rka" / "rka"
bridge_path = sorted(root.rglob("rka-mcp-bridge.py"))[-1]  # last = newest version
os.environ["BRIDGE_PATH"] = str(bridge_path)  # export for downstream bash variants
print(bridge_path)
```

**Failure modes**: if `sorted(...)[-1]` raises `IndexError`, the plugin install didn't land — re-run `/plugin install rka@rka`.

### 6.4 — `integration.json` is optional in v1.0

The wrapper script (`bin/rka-mcp-bridge.py`) auto-detects the `rka` stdio binary via PATH lookup when `integration.json` is missing. So setup can skip writing `integration.json` entirely and rely on the user having run `uv tool install --force --reinstall .` from the rka repo (binary lands at `~/.local/bin/rka` on macOS/Linux, `%USERPROFILE%\.local\bin\rka.exe` on Windows).

If the user does want to pin a default project (recommended once the user knows their primary project id), write the file at the OS path in §4 with this minimal shape:

```json
{
  "version": "2.7.0",
  "binary_path": "/Users/<you>/.local/bin/rka",
  "default_project_id": "prj_01ABC...",
  "api_endpoint_url": "http://localhost:9712"
}
```

(The `version` field is `integration.json`'s own schema version — not the backend's.)

Get the project id by listing projects via the API:

```bash
curl -s http://localhost:9712/api/projects | python3 -c "import sys,json; [print(f\"{p['id']}: {p['name']}\") for p in json.load(sys.stdin)]"
```

`integration.json` is a forward-compatible metadata file used by a future native-app distribution. The plugin treats it as optional in v2.7.0; the wrapper falls back to a PATH-lookup of the rka binary if missing.

### 6.5 — Back up the existing Claude Desktop config

> **Variable plumbing**: this section reads `$CONFIG_PATH` (exported by §6.1). If you ran §6.1 in a separate Python process and lost the env, re-export from the printed `CONFIG_PATH=...` line. The bash block below reads `$CONFIG_PATH` (not `$config_path` — bash and Python use different namespaces). The integrated-Python alternative is at the bottom of this section.

```bash
# Reads CONFIG_PATH exported by §6.1's Python block.
# Capture the backup path as a variable for reuse in §6.9 recovery.
backup="${CONFIG_PATH}.backup-$(date +%Y%m%d-%H%M%S)"
export BACKUP="$backup"          # propagate to §6.9
if [ -f "$CONFIG_PATH" ]; then
    cp "$CONFIG_PATH" "$backup"
else
    mkdir -p "$(dirname "$CONFIG_PATH")"
fi
```

Windows (PowerShell) equivalent:

```powershell
$backup = "$env:CONFIG_PATH.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
$env:BACKUP = $backup
if (Test-Path $env:CONFIG_PATH) {
    Copy-Item $env:CONFIG_PATH $backup
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $env:CONFIG_PATH) | Out-Null
}
```

Pure-Python alternative (use when running §6.1–§6.6 as one script — keeps the `config_path` Path object in scope):

```python
import os, shutil
from datetime import datetime

backup = config_path.with_suffix(config_path.suffix + f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
if config_path.exists():
    shutil.copy2(config_path, backup)
else:
    config_path.parent.mkdir(parents=True, exist_ok=True)
os.environ["BACKUP"] = str(backup)  # for downstream bash variants
```

**Failure modes**: if `cp` fails (read-only volume / no permission), halt and surface the path. Do NOT proceed to §6.6 without a backup-or-empty-parent guarantee.

### 6.6 — Atomically merge the `mcpServers.rka` entry

> **Variable plumbing**: this block reuses `config_path` (§6.1), `bridge_path` (§6.3), and `_python_launcher()` (§6.1). To run as a standalone script, concatenate §6.1 + §6.3 + this block — the names stay in scope. If you split blocks across processes, the block below also accepts `os.environ['CONFIG_PATH']` and `os.environ['BRIDGE_PATH']` as a fallback.

Use the following Python block. It reads the existing config (or starts empty), runs the conflict detection from §6.7 inline, writes atomically via tmp+rename, and re-reads to verify. The launcher (`py` / `python` / `python3`) is resolved at runtime by `_python_launcher()` from §6.1 — no hard-coded `sys.platform == 'win32'` branch.

```python
import json
import os
import sys
from pathlib import Path

# Fallback: if running as a separate process, re-hydrate from env vars
# exported by §6.1 and §6.3.
config_path = config_path if "config_path" in globals() else Path(os.environ["CONFIG_PATH"])
bridge_path = bridge_path if "bridge_path" in globals() else Path(os.environ["BRIDGE_PATH"])

# 1. Read existing config (or start empty if missing).
try:
    if config_path.exists() and config_path.stat().st_size > 0:
        existing = json.loads(config_path.read_text())
        if not isinstance(existing, dict):
            raise ValueError("config root is not a dict")
    else:
        existing = {}
except (json.JSONDecodeError, ValueError) as e:
    # Abort: surface the malformed JSON; do NOT silently replace.
    raise SystemExit(
        f"Existing config is malformed at {config_path} — refusing to overwrite. "
        f"Manually fix or restore from the backup written in §6.5. Error: {e}"
    )

existing.setdefault("mcpServers", {})

# 2. Build the rka entry — resolve the launcher at runtime so Windows
# users with `py` (and no `python3` shim) still get a working command.
# _python_launcher() is defined in §6.1; it returns the first of
# python3 / py / python found on PATH.
launcher = _python_launcher() if "_python_launcher" in globals() else (
    # Inline fallback if §6.1 wasn't sourced into this process.
    next(
        (n for n in ("python3", "py", "python") if __import__("shutil").which(n)),
        sys.executable,
    )
)
if launcher == "py":
    # `py` is the Windows Python launcher; `-3` selects Python 3.
    rka_entry = {"command": "py", "args": ["-3", str(bridge_path)]}
else:
    rka_entry = {"command": launcher, "args": [str(bridge_path)]}

# 3. Conflict detection (§6.7 inline).
existing_rka = existing["mcpServers"].get("rka")
if existing_rka is not None:
    if existing_rka == rka_entry:
        print("rka MCP server entry is already correctly configured. No changes needed.")
        sys.exit(0)
    else:
        print(f"Existing rka entry differs:\n  {existing_rka}\nProposed:\n  {rka_entry}")
        confirm = input("Replace? (y/N): ").strip().lower()
        if confirm != "y":
            print("Aborted by user.")
            sys.exit(1)

# 4. Apply the merge.
existing["mcpServers"]["rka"] = rka_entry

# 5. Atomic write: tmp + rename.
tmp = config_path.with_suffix(config_path.suffix + ".tmp")
tmp.write_text(json.dumps(existing, indent=2))
tmp.replace(config_path)

# 6. Re-read to verify.
verified = json.loads(config_path.read_text())
assert verified["mcpServers"]["rka"] == rka_entry, "post-write verification failed"
print(f"✅ Wrote rka MCP entry to {config_path}")
```

Launcher-resolution semantics (codified above in `_python_launcher()` from §6.1): the helper checks PATH for `python3`, `py`, then `python` in that order and returns the first match. On Windows the `py` launcher is preferred when `python3` is absent (`py -3 <bridge>`); on macOS/Linux `python3` is almost always present. No `sys.platform` branching needed at the call site — the helper handles all three OSes uniformly.

**Critical**: preserve any other entries already in `mcpServers`. Never overwrite the file blindly. If the existing JSON is malformed, abort with the parser error pointing at the backup; do NOT replace malformed JSON with parseable JSON silently.

**Failure modes**: if the Python block raises `JSONDecodeError`, abort and tell the user to manually fix or restore from the §6.5 backup — surface the line/column of the parse error. If `tmp.replace(config_path)` fails (e.g., permission denied), the original file is intact and the backup is untouched — surface the error and stop.

### 6.7 — Conflict detection

(Inlined into §6.6 above as the third step of the merge block.) Detection rules:

- If `mcpServers.rka` already exactly equals the proposed entry: no-op exit.
- If `mcpServers.rka` exists with different `command` / `args`: prompt for explicit `y` confirmation; abort otherwise.

Equality is exact dict-equality (`==`) — the wrapper's normal form is `{"command": "python3"|"py", "args": [<bridge_path>]}`. Drift from that shape is treated as a user-managed entry and respected.

### 6.8 — Tell the user what to do next

Output a clear message:

> ✅ Claude Desktop config updated. The RKA MCP server entry is in place at `<config_path>`. Backup of the original is at `<config_path>.backup-...`.
>
> **Now fully quit Claude Desktop** (Cmd+Q on macOS / right-click tray icon → Quit on Windows) and reopen it. Open a fresh chat and ask: *"Show me the available RKA projects."* Brain should call `rka_query(operation="list_projects")` (the v2.7.0 dispatch surface — there is no separate `rka_list_projects` MCP tool any more; the operation lives behind `rka_query`) and return the list, empty on a fresh install.

### 6.9 — On any failure: restore from backup

If any step from 6.4 onward fails, restore the backup captured in §6.5 (`$BACKUP` is the exact path exported there — reuse it directly, do NOT glob). The bash uses `$BACKUP` / `$CONFIG_PATH` (the env-var names exported by §6.1 and §6.5); the Python alternative uses the `backup` / `config_path` Path objects in scope:

```bash
if [ -f "$BACKUP" ]; then
    cp "$BACKUP" "$CONFIG_PATH"
    echo "Restored $CONFIG_PATH from $BACKUP"
else
    echo "No backup at $BACKUP — original config did not exist." >&2
fi
```

```python
# Pure-Python alternative (use when running §6.1–§6.9 as one script).
import shutil
if backup.exists():
    shutil.copy2(backup, config_path)
    print(f"Restored {config_path} from {backup}")
else:
    print(f"No backup at {backup} — original config did not exist.")
```

Then surface the error clearly. Never leave the user's config in a partially-written state.

---

## 7. For Claude Code: skill content for related questions

When the user asks variants of *"set up RKA"*, *"finish RKA install"*, *"connect Brain"*, *"why isn't RKA showing up in Claude Desktop"*, etc., the `rka:rka-pi` skill should:

1. First check whether `/rka-setup-claude-desktop` would address it. If yes, suggest running that command.
2. For diagnosis questions ("why isn't RKA showing"), check in order:
   - Is Docker running? (`docker compose ps` from the rka repo dir)
   - Is the API healthy? (`curl http://localhost:9712/api/health`)
   - Does `claude_desktop_config.json` exist and have an `mcpServers.rka` entry?
   - Does `integration.json` exist?
   - Did the user fully quit + reopen Claude Desktop after the last config change?
3. For "uninstall RKA" requests:
   - Run `/plugin uninstall rka@rka` in Claude Code.
   - Restore Claude Desktop's config from the most recent backup.
   - Optionally: `docker compose down -v` to wipe the backend (warn user this destroys their RKA data — recommend a knowledge-pack export first via the project-scoped REST endpoint `GET /api/projects/export`, or the web dashboard's export control; see [USAGE_GUIDE.md](USAGE_GUIDE.md) for the pack import/export workflow. Note: `export` is not a typed dispatch operation, so it is not directly callable from the default 5-tool surface).

---

## 8. Manual install (advanced)

Use this path if:
- You're on a system without VSCode (e.g., Claude Code CLI on a server)
- You're scripting RKA install in CI (note: plugins don't load in `claude -p` print mode — an empirical finding)
- You want to run RKA without the plugin layer at all

### 8.1 — Install the RKA stdio binary

```bash
git clone https://github.com/rka-project/rka-core.git
cd rka-core
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall .
# Binary lands at ~/.local/bin/rka (macOS/Linux) or %USERPROFILE%\.local\bin\rka.exe (Windows)
```

If you don't have `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or follow [docs.astral.sh/uv/getting-started/installation](https://docs.astral.sh/uv/getting-started/installation/) (Windows).

Verify: `~/.local/bin/rka --version`.

### 8.2 — Start the backend

```bash
docker compose up -d
```

### 8.3 — Configure Claude Desktop manually

Edit `claude_desktop_config.json` at the path for your OS (see §4). Add to `mcpServers`:

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

Replace `<your-username>` with your actual macOS username (Windows: use `C:\\Users\\<you>\\.local\\bin\\rka.exe` and double the backslashes for JSON).

**v2.6+ project discipline (no env var).** Pre-v2.6 the config included an `env.RKA_PROJECT` entry to pin a default project. That was removed in v2.6 because it reintroduced the silent-default failure mode that v2.6 explicitly eliminates: every project-scoped tool now requires `project_id` as a kwarg, and the LLM threads the project from its conversation context. At the start of every conversation, state which project you're working on (e.g., *"I'm working on prj_01KSMW9R…"* or *"the hyperscaler-auditing project"*) — the LLM keeps it in working memory and passes it on every tool call.

**v2.7.0 schema enforcement.** In v2.7.0 the args object is a discriminated Pydantic union — missing `project_id` on a scoped operation now surfaces as a `ValidationError` from FastMCP **before** the call reaches the service layer. Per-branch enum + required-field enforcement (defined in `orchestrator/rka_enums.py` mirror + the per-operation Pydantic models) means wrong values (e.g., `confidence='confirmed'`) are also rejected pre-dispatch with a structured error pointing at the offending field. See §1.1 for the user-facing tool surface this enforcement sits behind.

After restart, Brain will see exactly 5 always-on tools (3 dispatch + 2 escape hatches): `rka_query`, `rka_execute`, `rka_describe`, plus `rka_load_tools` and `rka_help` (alias for `rka_describe`). This is normal — the current operation catalog is dispatched through them and can be inspected with `rka_describe("")`.

Fully quit + reopen Claude Desktop.

### 8.4 — Configure Claude Code manually

Same JSON shape, in `.claude/mcp.json` (per-project) or `~/.claude/settings.json` under `mcpServers`. Reload the VSCode window after saving.

---

## 9. Troubleshooting

### General

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker compose up -d` fails | Docker Desktop not running | Launch Docker Desktop, wait until the whale icon says "running", retry |
| `curl http://localhost:9712/api/health` fails | Container started but unhealthy | `docker compose logs -f rka` to see what's wrong; usually port 9712 conflict — change in `docker-compose.yml` |
| `/plugin marketplace add /path/to/rka` fails | Path is wrong, or `.claude-plugin/marketplace.json` doesn't exist at that path | Verify with `ls /path/to/rka/.claude-plugin/marketplace.json`. Use the absolute path, not `~`. |
| `/plugin install rka@rka` fails after marketplace add | Marketplace file present but plugin source missing | Check the repo's marketplace.json — `source` field must point at a valid path inside the repo |
| `rka_query` / `rka_execute` / `rka_describe` absent from Brain's tool list (Claude Desktop) | Config not saved, or app not fully quit | Verify config at the path in §4 contains the `rka` entry; Cmd+Q fully (not red-X close); reopen. If you see the legacy tools (`rka_list_projects`, `rka_get_status`, etc.) instead, your Brain is running with `RKA_LEGACY_TOOLS=1` (orchestrator daemon mode) — unset and restart. |
| RKA tools missing in Claude Code | Plugin not installed, or VSCode window not reloaded | `/plugin list` to verify; reload window with Cmd+Shift+P → "Developer: Reload Window" |
| All RKA writes land in `proj_default` | LLM forgot to pass `project_id` on a write call (v2.6+ requires it as a kwarg) | In v2.7.0+ the error surface is a Pydantic `ValidationError` (`Field required: project_id for operation X`) raised by FastMCP at schema-validate time, not a `TypeError`. If you see writes silently landing in `proj_default`, you are on a pre-v2.6 install — upgrade. If on v2.7.0+, ask the LLM at conversation start to pin `project_id` and thread it through every call. |
| SessionStart hook says "RKA NOT reachable" | Docker stopped or wrong API URL | Run `docker compose up -d`; check `integration.json`'s `api_endpoint_url` |
| Wrapper says "version incompatible" | RKA backend version doesn't match the plugin's compatibility range | Either upgrade RKA backend (`git pull && docker compose up -d --build` from the repo) or downgrade the plugin to a matching version |

### Windows specifically

| Symptom | Likely cause | Fix |
|---|---|---|
| `python3 --version` fails but `python --version` works | "Add Python to PATH" wasn't checked at install | Reinstall Python 3 from python.org with that checkbox enabled, OR adjust the wrapper invocation in `claude_desktop_config.json` to use `python` instead of `python3` |
| Path with spaces breaks the wrapper | Unquoted path in JSON config | Escape backslashes (`\\\\`) and ensure the entire path is in JSON quotes |
| Microsoft Store install of Claude Desktop doesn't see the config edits | Config path differs (stored in app sandbox) | This appears NOT to happen empirically — both Microsoft Store and standalone .exe write to the same `%APPDATA%\Claude\` path. If you observe otherwise, surface as a bug. |
| Web dashboard shows `ERR_CONNECTION_RESET` at `localhost:9712`, but the container is healthy | `localhost` → IPv6 `::1`; WSL2's `localhostForwarding` proxy accepts the connection and resets it. Docker publishes IPv4-only, and the successful handshake suppresses IPv4 fallback | Use **`http://127.0.0.1:9712`**. Permanent fix: create `%USERPROFILE%\.wslconfig` with `[wsl2]` / `localhostForwarding=false`, then `wsl --shutdown` (stops **all** containers and WSL distros — do it when convenient) |
| `rka_query`/`rka_execute` return `{"status":"unhealthy","error":""}` while `curl http://127.0.0.1:9712/api/health` returns `ok` | An older MCP configuration may still target `http://localhost:9712` and resolve it over IPv6. Current RKA defaults to `http://127.0.0.1:9712`; the empty `error` string is the tell when an old override remains | Remove the stale `RKA_API_URL` override or pin IPv4 with an explicit `env` block in **each** MCP config (see [§9 Windows: rebuilding and updating](#windows-rebuilding-and-updating-an-existing-install)). A user env var is **not** sufficient — see the next row |
| Config or env-var change doesn't take effect after "Developer: Reload Window" | A window reload re-spawns MCP servers as children of the **already-running** VSCode process, which keeps its original environment block. `setx` writes the registry but not that block | Put per-machine settings in the MCP config's `env` block (re-read on reload), not in a user env var. Env vars need a **full application restart**, not a reload |
| `uv tool install --force .` fails: `failed to remove file ... _pydantic_core.<abi>.pyd: Access is denied. (os error 5)` | Windows locks loaded `.pyd`/DLLs. Running `rka mcp` servers (Claude Desktop + every Claude Code window) hold the file open | Quit Claude Desktop and close Claude Code windows, or stop the server processes, then re-run. See [§9 Windows: rebuilding and updating](#windows-rebuilding-and-updating-an-existing-install) for a safe process filter |
| `docker compose up -d --build` fails: `invalid file request <path>` / `failed to solve: invalid file request` | Repo is in a OneDrive-synced folder and Files On-Demand dehydrated some files into cloud placeholders (`ReparsePoint` attribute). BuildKit can't send them in the build context | Materialize the placeholders (procedure below), or move the clone outside OneDrive. `attrib +P` (pin) alone does **not** clear the reparse tag |

<a id="windows-rebuilding-and-updating-an-existing-install"></a>

### Windows: rebuilding and updating an existing install

Upgrading a Windows install (`git pull` → reinstall binary → rebuild containers) hits several platform-specific failures that don't occur on macOS/Linux. Work through these in order; each was observed on a real v2.8.0 → v2.9.0 upgrade.

#### 1. Materialize OneDrive placeholders before building

If the repo lives under a OneDrive-synced folder (`Desktop`, `Documents`), files dehydrate over time and the build fails with `invalid file request <path>`. The files still *read* fine — only BuildKit's context transfer rejects them.

Count them first (a fresh clone reports `0`):

```powershell
$repo = "C:\path\to\rka"
Get-ChildItem $repo -Recurse -File -Force |
  Where-Object { $_.FullName -notlike "*\.git\*" -and $_.FullName -notlike "*\node_modules\*" -and
                 ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) } |
  Measure-Object | Select-Object -ExpandProperty Count
```

`attrib +P` (pin) sets the `Pinned` flag but leaves the reparse tag in place, so it does not fix the build. Rewriting each file in place does — it produces an ordinary local file with byte-identical content:

```powershell
Get-ChildItem $repo -Recurse -File -Force |
  Where-Object { $_.FullName -notlike "*\.git\*" -and $_.FullName -notlike "*\node_modules\*" -and
                 ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) } |
  ForEach-Object {
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
    Remove-Item -LiteralPath $_.FullName -Force
    [System.IO.File]::WriteAllBytes($_.FullName, $bytes)
  }
```

**Verify content is unchanged before building**: `git status --short` and `git diff --stat` must show no modifications to tracked files. If they do, stop — restore from `git checkout --` rather than building. Re-run the count query; expect `0`.

The durable fix is to move the clone outside OneDrive (see the Step 1 warning in §3).

#### 2. Stop the processes that lock the binary

`uv tool install --force .` fails with `Access is denied (os error 5)` on `_pydantic_core.<abi>.pyd` while any `rka mcp` server is running — Windows locks loaded extension modules. Quitting Claude Desktop and closing Claude Code windows is enough. To stop them directly:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { ($_.Name -eq 'rka.exe' -or $_.CommandLine -like '*rka-mcp-bridge.py*') -and
                 $_.ProcessId -ne $PID } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

> **⚠️ Match narrowly — two traps here, both observed.**
> 1. A broader filter such as `CommandLine -like '*rka*'` also matches `docker-buildx.exe`, whose command line contains the repo path. Killing it aborts an in-flight `docker compose build`.
> 2. **The `-ne $PID` guard is not optional.** When you paste this into a console, the filter string becomes part of *your own shell's* command line, so the shell matches its own filter and terminates itself mid-loop, leaving some servers running.
>
> Match on process name and the bridge script only, and always exclude the current process. Run the `Where-Object` clause on its own first and eyeball the list before adding the `Stop-Process` pipe.

If a previous attempt failed partway, `uv` may warn `Failed to uninstall package ... due to missing RECORD file` and `Installation may result in an incomplete environment`. Confirm the result is actually sound before moving on:

```powershell
rka --version                                   # expect the new version
& "$env:APPDATA\uv\tools\rka\Scripts\python.exe" -c "import pydantic_core, rka; print('ok')"
```

If the import fails, run `uv tool uninstall rka` then `uv tool install .` for a clean environment.

#### 3. Pin `RKA_API_URL` to IPv4 in every MCP config

After the upgrade the MCP tools may report `{"status":"unhealthy","error":""}` even though the API is healthy on `127.0.0.1` — the IPv6 fault described in the table above. Add an explicit `env` block to **each** config that launches the bridge:

```json
"rka": {
  "command": "python3",
  "args": ["${CLAUDE_PLUGIN_ROOT}/bin/rka-mcp-bridge.py"],
  "env": { "RKA_API_URL": "http://127.0.0.1:9712" }
}
```

Apply it in `%APPDATA%\Claude\claude_desktop_config.json` (Claude Desktop) and in the `.mcp.json` that Claude Code actually reads. **Do not rely on a user env var** set with `setx`: a VSCode *window reload* re-spawns the MCP server from the already-running process's stale environment block, so the variable never arrives. The `env` block is re-read on every reload.

Verify without restarting anything by driving the bridge directly — a healthy result is `{"status": "healthy", "rest_status_code": 200}`:

```powershell
$env:RKA_API_URL = "http://127.0.0.1:9712"
rka mcp   # then issue an MCP initialize + tools/call for rka_query {"operation":"health"}
```

#### 4. Know which plugin copy Claude Code is reading

When the marketplace source is a **local directory** (`/plugin marketplace add C:\path\to\rka`), `${CLAUDE_PLUGIN_ROOT}` resolves to the repo's own `plugin/` directory, so a `git pull` updates Claude Code immediately — but the copy under `%USERPROFILE%\.claude\plugins\cache\rka\rka\<version>\` can stay behind at the commit it was installed from. Confirm which one is live from the running process:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*rka-mcp-bridge.py*' } |
  Select-Object ProcessId, CommandLine | Format-List
```

The path in the command line is the copy in use. If it points at the cache, refresh it from the repo (`robocopy <repo>\plugin <cache> /E /XF .mcp.json`) so skills and commands match the backend — and keep `/XF .mcp.json` so any machine-specific `env` block or absolute interpreter path survives.

#### 5. `python3` works through a shell, not a bare spawn

`plugin/.mcp.json` uses `command: "python3"`. On Windows that resolves only because the launcher goes through `cmd.exe`, which finds `python3.cmd` on `PATH`. A bare `subprocess` spawn of `python3` instead hits the Microsoft Store app-execution alias and fails with *"Python was not found; run without arguments to install from the Microsoft Store."* Keep `%USERPROFILE%\.local\bin` **ahead of** `%LOCALAPPDATA%\Microsoft\WindowsApps` on `PATH`, or set `command` to an absolute interpreter path. Check the resolution order with `where.exe python3`.

### macOS specifically

| Symptom | Likely cause | Fix |
|---|---|---|
| Hook script fails with permission denied | Wrapper not executable | `chmod +x bin/rka-mcp-bridge.py` (the plugin should set this on install but may not) |
| `python3` resolves to a Python 2 binary | Old system Python | Use `/usr/bin/python3` explicitly, or install via `brew install python3` |
| Spotlight indexes integration.json and creates `._integration.json` | macOS metadata pollution on volumes without full xattr support (external drives, SMB/AFP network mounts, OneDrive/Dropbox/iCloud sync folders) | `dot_clean ~/Library/Application\ Support/RKA/` or move RKA data off the affected volume |

### Linux specifically

| Symptom | Likely cause | Fix |
|---|---|---|
| Claude Desktop's config path differs | Some distros use `~/.var/app/...` for Flatpak installs | Check the actual path your Claude Desktop install uses; `find ~ -name "claude_desktop_config.json" 2>/dev/null` |
| Docker requires sudo | User not in `docker` group | `sudo usermod -aG docker $USER`, log out/in |

---

## 10. What this guide intentionally doesn't cover

- **Local LLM setup (LM Studio, Ollama, etc.) for chat/enrichment** — Chat-style enrichment tools (`rka_ask`, `rka_generate_summary`) were removed in v2.4.0 per `jrn_01KRNZBS50K250HHHHEC58E4GC`. The Brain (Claude Desktop) handles all knowledge enrichment during normal sessions. **However**, RKA v2.4.0+ supports pluggable embedding backends — configure FastEmbed (default, runs in-container), OpenAI-compatible HTTP (e.g., LM Studio, vLLM), or Ollama via **Settings → Embeddings** in the web dashboard at `http://localhost:9712`. Full reference: [`docs/embedding_backends.md`](docs/embedding_backends.md).
- **Cloud LLM API setup (OpenAI, Anthropic API key)** — not required by RKA's core workflow.
- **Knowledge pack import/export** — covered in [USAGE_GUIDE.md](USAGE_GUIDE.md) and [docs/USER_MANUAL.md](docs/USER_MANUAL.md).
- **Per-project conventions** (Brain orientation, Executor mission flow, PI attribution) — covered by the role skills the plugin loads automatically. Once installed, ask Claude Code to "load the rka brain skill" or "show me the executor session protocol" for the workflow guides.
- **Migrating from a pre-v2.3 RKA install** — for users who set up RKA before the plugin existed. See the upgrade notes in [USAGE_GUIDE.md](USAGE_GUIDE.md).

---

## 11. Historical Agentic distribution — unsupported

> **Shelved on 2026-08-27. Do not follow these installation steps.** The
> section is retained only to preserve the historical operating record. RKA
> Core and RKA Writer do not require or support this runtime. Reactivation
> requires a new explicit PI decision; see
> [ADR 0013](docs/adr/0013-shelve-agentic-and-focus-core-writer.md).

If you're on the `agentic` branch, you also have access to the **RKA Orchestrator** — a LangGraph-driven Brain⇄Executor⇄PI workflow engine with a Claude-Code-native PI surface (no stdin terminal needed). This is **optional** — the core main-branch RKA setup above works without it. If you only need the knowledge base + Brain in Claude Desktop + Executor in Claude Code, skip this section.

### When to install

Install the orchestrator if you want to:

- Drive structured Brain⇄Executor missions through PI-ratified gates from any Claude Code session
- Use the **onboarding wizard** to set up per-project tool manifests + credential validation (Phase D MVP)
- Reuse the same MCP entries in Claude Desktop for both ad-hoc work AND structured workflows

### Step 11.1 — Switch to the agentic branch

```bash
cd <your-clone-dir>/rka-core
git checkout agentic
```

**Post-check**: `git rev-parse --abbrev-ref HEAD` must equal `agentic`. If not, halt and surface the actual branch — §11 requires the agentic branch.

### Step 11.2 — Install the orchestrator package + MCP binary

`uv tool install` produces the runtime binary but does **NOT** install dev dependencies (pytest, fakes, LangGraph test fixtures); the `pytest -q` line below requires them. Run the two install commands explicitly — the binary-install gives you the production MCP entry point on PATH; the editable dev-install adds the `[dev]` extras needed by the test suite.

```bash
cd orchestrator
uv tool install --force .                            # produces ~/.local/bin/rka-orchestrator-mcp (binary only)
uv pip install -e ".[dev]"                           # adds dev deps for pytest (pytest, anyio, fakes, …)
pytest -q                                            # optional: 1100+ tests; verifies the install
```

If you skip the `uv pip install -e ".[dev]"` line, the `pytest -q` invocation will fail with `ModuleNotFoundError` (pytest itself, or the LangGraph test fixtures). The `pytest -q` step is OPTIONAL — only needed if you want to verify the install end-to-end. The orchestrator MCP binary works either way.

> **macOS AppleDouble note** (per CLAUDE.md): if you cloned the repo onto an external drive or a synced folder (Dropbox / OneDrive / iCloud), `uv tool install` may fail on `._requires.txt`. Install from a `/tmp` clone instead — `/tmp` is on a stock APFS volume that doesn't have the xattr quirk. See CLAUDE.md "macOS AppleDouble Quirks" for the exact workaround.

**Post-check**: `command -v rka-orchestrator-mcp` (macOS/Linux) or `where rka-orchestrator-mcp` (Windows) prints a path. If absent, check `uv tool list` for partial-install state and re-run with `--reinstall`.

### Step 11.3 — Mint a Claude Max OAuth token

In a **separate terminal** (NOT inside any Claude Code or Desktop session — the token is sensitive):

```bash
claude setup-token           # opens browser flow; outputs a long-lived token
```

### Step 11.4 — Drop the token in a gitignored env file

```bash
nano orchestrator/.env
```

```dotenv
# orchestrator/.env (file mode 0600, gitignored)
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
# Optional — richer tool surface for the Brain subprocess:
SEMANTIC_SCHOLAR_API_KEY=...
SERPAPI_KEY=...
# Required while the orchestrator daemon's Brain⇄Executor subprocess has
# not yet been ported to v2.7.0 dispatch (rka_execute(operation=…)).
# Tracked in v2.7.0+agentic.X. Until then the daemon container needs the
# legacy 20-tool baseline:
RKA_LEGACY_TOOLS=1
```

```bash
# macOS / Linux: POSIX file mode bit 600 (rw owner, no group/other).
chmod 600 orchestrator/.env
```

```powershell
# Windows (PowerShell): no chmod equivalent; use icacls to break inheritance
# and grant the current user full control, denying everyone else by default.
icacls orchestrator\.env /inheritance:r /grant:r "$($env:USERNAME):F"
```

The file holds a long-lived OAuth token and (optionally) API keys — it must not be readable by other accounts on the same machine. The macOS/Linux mode 600 grants read/write to owner only; the Windows icacls invocation removes inherited ACLs and grants only the current user full access.

**Post-check**: verify with `stat -f %A orchestrator/.env` (macOS) / `stat -c %a orchestrator/.env` (Linux). Expect `600`. On Windows, verify with `icacls orchestrator\.env` — output should show only the current user with `(F)` (full control) and no Everyone / Users entries. If the value differs, re-run the platform-appropriate command above. Confirm the token is present with `grep -c "^CLAUDE_CODE_OAUTH_TOKEN=" orchestrator/.env` (expect `1`; on Windows use `Select-String -Pattern '^CLAUDE_CODE_OAUTH_TOKEN=' orchestrator\.env | Measure-Object -Line` and expect `Lines: 1`).

### Step 11.5 — Bring up the orchestrator service

**Pre-check**: `git rev-parse --abbrev-ref HEAD` must equal `agentic` (per Step 11.1).

The Compose overlay adds a third container (`rka-orchestrator`) alongside `rka-server` and `rka-worker` without modifying the root `docker-compose.yml`:

```bash
cd <your-clone-dir>/rka-core
docker compose -f docker-compose.yml \
               -f orchestrator/docker-compose.yml up -d --build
```

Verify:

```bash
curl http://localhost:9713/health
# {"status":"ok","db_path":"/data/orchestrator.db"}

docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml ps
# Should show 3 services healthy: rka-server, rka-worker, rka-orchestrator
```

**Recovery**: if `curl http://localhost:9713/health` fails or `docker compose ps` shows `rka-orchestrator` unhealthy, run:

```bash
docker inspect rka-orchestrator --format '{{.RestartCount}} restarts; OOMKilled={{.State.OOMKilled}}'
```

If `OOMKilled=true`, bump Docker Desktop's Resources → Memory ceiling to ≥6 GB and re-up. (Per the operational note in CLAUDE.md: the FastEmbed model alone is ~250 MB; the full stack benefits from 8 GB.)

### Step 11.6 — Register the orchestrator MCP in Claude Desktop

> **IMPORTANT — do not clobber the wrapper-based `rka` entry from §6.** If you followed §3 + §6 (the recommended path), you already have an `mcpServers.rka` entry pointing at the wrapper script (`bin/rka-mcp-bridge.py`). Keep it untouched. This step adds ONLY the new `mcpServers.rka-orchestrator` entry. If you copy the JSON block below verbatim into your config, you will replace the wrapper-based `rka` entry with the `docker exec` form — that works but loses the version-checking + auto-pin behaviour the wrapper provides. The example below is correct *for users who never ran §6* (agentic distribution from scratch, no plugin install); the §6-path user should ADD only the `rka-orchestrator` key.

> **Note on `RKA_LEGACY_TOOLS=1`**: the user-facing `rka` MCP entry below exposes v2.7.0 dispatch tools (5 always-on — 3 dispatch + 2 escape hatches). The orchestrator daemon container reads `RKA_LEGACY_TOOLS=1` from `orchestrator/.env` (set externally by you in Step 11.4) and propagates it to the daemon's Brain⇄Executor subprocess via the container's env block so that subprocess still sees the v2.7.0a2 baseline (legacy 20 tools). End-users do not need to set this in Claude Desktop — the env var lives in `orchestrator/.env`, not the Desktop config.

For agent executors merging this entry programmatically: read the existing `claude_desktop_config.json`, parse, set `mcpServers.rka-orchestrator` ONLY (do not touch `mcpServers.rka`), write back atomically (same tmp+rename pattern as §6.6).

The JSON below shows the *result* of a from-scratch install (no §6 done previously); the §6-path user's result will have BOTH `rka` (wrapper) AND `rka-orchestrator` keys side-by-side:

```json
{
  "mcpServers": {
    "rka": {
      "command": "docker",
      "args": ["exec", "-i", "rka-server", "rka", "mcp"]
    },
    "rka-orchestrator": {
      "command": "/Users/<your-username>/.local/bin/rka-orchestrator-mcp",
      "args": []
    }
  }
}
```

Substitute your actual username. Fully quit and reopen Claude Desktop.

### Step 11.7 — Verify in Claude Desktop / Claude Code

```
[You:]
> Use orchestrator_health to check the daemon

[Claude:]
[calls orchestrator_health]
{"status":"ok","db_path":"/data/orchestrator.db"}
```

If you also see `orchestrator_run_start`, `orchestrator_inbox`, `orchestrator_onboard_start`, `orchestrator_get_manifest`, etc. in your tool list, the orchestrator MCP is wired correctly.

### Step 11.8 — Day-one use

```
[You:]
> /orchestrator-onboard prj_01XYZ      # for a new project's tool setup
or
> /orchestrator-start mis_01ABC        # to drive an existing mission
```

See [`USAGE_GUIDE.md`](USAGE_GUIDE.md#agentic-distribution--orchestrator-workflows) for the full agentic-distribution workflow walkthrough including the TWO-TAP discipline at `pi_decision_select` (the privileged write-authorization gate).

### Workspace bind mount — `HOST_WORKSPACE_ROOT`

For non-`$HOME` workspace roots (external drives, `/Volumes/...`, etc.), set `HOST_WORKSPACE_ROOT` in the **repo-root `.env`** (i.e., `<your-clone-dir>/rka-core/.env`), **NOT** in `orchestrator/.env`. Docker Compose reads `.env` from the directory of the first `-f` file (the repo root) for YAML `${VAR}` interpolation; the `env_file:` directive only populates env vars inside the running container and does not feed interpolation.

If you put `HOST_WORKSPACE_ROOT` in `orchestrator/.env`, the bind mount falls back to `${HOME}` and the workspace appears empty inside the container — a silent failure.

### Where orchestrator state lives

| | |
|---|---|
| Docker volume `orchestrator-data` | `/data/orchestrator.db` (parked-interrupt queue + workflow_runs) + `/data/orchestrator-saver.db` (LangGraph checkpointer) |
| `orchestrator/.env` (gitignored, mode 0600) | `CLAUDE_CODE_OAUTH_TOKEN`, optional API keys, and `RKA_LEGACY_TOOLS=1` propagated to the subprocess |
| `<your-clone-dir>/rka-core/.env` (gitignored, repo-root) | `HOST_WORKSPACE_ROOT` for non-`$HOME` workspace roots — fed to Compose YAML `${VAR}` interpolation for the workspace bind mount |
| `~/.claude.json` (mounted read-only) | Host's Claude CLI global config |
| `~/rka-projects/{project_id}/` (Phase D MVP convention) | Per-project `tools.json` + `.env` template after onboarding |

> **Phase O note**: a future implementation phase (~13.5 days, design committed) will consolidate the per-project workspace at `~/Research/{project-slug}/.rka/`. A separately installed `rka-writer` workspace may be colocated with it, but is not created or managed by Core. See `orchestrator/docs/phase-o-project-onboarding-design.md` for details. The Phase D MVP convention above continues to work in the meantime.

### Tearing down

```bash
docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml down
# (Leaves the orchestrator-data volume; add -v to delete it.)
```

---

## Appendix: file inventory after a successful install

| Location | What |
|---|---|
| `<your-clone-dir>/rka-core/` | The cloned RKA Core source repo (only docker-compose.yml is needed at runtime; rest is for development) |
| Docker volume `rka-data` (managed by Docker Desktop) | The SQLite database `/data/rka.db` and any project artifacts |
| `~/.claude/plugins/cache/rka/rka/<version>/` (macOS/Linux) or `%USERPROFILE%\.claude\plugins\cache\rka\rka\<version>\` (Windows) | The installed plugin: skills, commands, hooks, wrapper script |
| `~/Library/Application Support/RKA/integration.json` (macOS) or `%APPDATA%\RKA\integration.json` (Windows) | Plugin-written config telling the wrapper which RKA backend to bridge to |
| `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | Claude Desktop's MCP config with the `rka` entry; backups of any prior version live alongside it as `*.backup-YYYYMMDD-HHMMSS` |
| `~/.claude/plugins/installed_plugins.json` | Claude Code's registry of installed plugins (includes `rka@rka` entry after install) |
| `~/.claude/plugins/known_marketplaces.json` | Claude Code's registry of marketplace sources (includes the `rka-project/rka-core` GitHub source after `/plugin marketplace add`) |
| Docker volume `orchestrator-data` *(agentic only)* | `/data/orchestrator.db` (parked-interrupt queue + workflow_runs) and `/data/orchestrator-saver.db` (LangGraph checkpointer) |
| `<your-clone-dir>/rka-core/orchestrator/.env` *(agentic only, mode 0600)* | `CLAUDE_CODE_OAUTH_TOKEN`, `RKA_LEGACY_TOOLS=1`, and optional API keys |
| `<your-clone-dir>/rka-core/.env` *(agentic only, optional)* | `HOST_WORKSPACE_ROOT` for non-`$HOME` workspace bind mount (see §11 Workspace bind mount) |
| `~/.claude.json` *(agentic only, mounted read-only into container)* | Host's Claude CLI global config consumed by the orchestrator daemon's SDK subprocess |
| [`docs/v2.6.x-v2.7.0-tool-surface-arc.md`](docs/v2.6.x-v2.7.0-tool-surface-arc.md) | Canonical narrative of the v2.6 → v2.7.0 tool-surface migration (project_id discipline → dispatch + 91 typed Pydantic operations) |
