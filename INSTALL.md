# RKA Installation Guide

> **How to read this guide**
> - **Humans**: read top-to-bottom; quick install path is in §3 below.
> - **Claude Code**: this is the authoritative reference for any user request like *"install RKA"*, *"set up RKA for Claude Desktop"*, or *"finish my RKA setup"*. The procedural steps in §6 and §7 are written for you to execute when invoked.

---

## 1. What you get when you're done

| Surface | What you'll have |
|---|---|
| **RKA backend** | FastAPI + worker + SQLite + FTS5 + sqlite-vec running in Docker on `localhost:9712`. Web dashboard at the same URL. |
| **Claude Code (Executor)** | Full plugin: 4 role skills (`rka:rka-brain`, `rka:rka-executor`, `rka:rka-pi`, `rka:rka-writer`), 6 slash commands (`/rka-status`, `/rka-search`, `/rka-pending`, `/rka-set-project`, `/rka-setup-claude-desktop`, `/rka-start-manuscript`), a SessionStart hook that pings the backend on every new session, and the full `mcp__plugin_rka_rka__*` tool surface (~89 tools). |
| **Writer (manuscript drafting)** | The `rka:rka-writer` skill drafts venue-targeted manuscripts (CHI, EMNLP, NeurIPS, USENIX, IEEE-SP, OSDI, Nature seed venues). Bootstrap a per-manuscript workspace via `/rka-start-manuscript` (creates `.mcp.json`, `main.tex`, `refs.bib`, `.planning/` directory). Reference-validation MCP server (`rka-writer-tools`) wraps Crossref + OpenAlex + Semantic Scholar + arXiv + SerpAPI; install separately via `uv tool install '.[writer-tools]'` (see §3.6). |
| **Claude Desktop (Brain)** | `mcp__rka__*` tool surface via the `mcpServers.rka` entry in `claude_desktop_config.json`. Wrapper-based config gives you version-checking + auto-pin to your active project. Skills and slash commands are Claude Code only (Claude Desktop's plugin format is separate). |

---

## 2. Prerequisites (5 minutes if not already installed)

| # | Component | Why | Where |
|---|---|---|---|
| 1 | **Docker Desktop** | Runs RKA's FastAPI + worker in a container | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) — installer for macOS / Windows / Linux |
| 2 | **Claude Desktop** (the native app) | Hosts the Brain (strategy + synthesis) | [claude.ai/download](https://claude.ai/download) — macOS / Windows. **Windows note**: install via Microsoft Store OR standalone `.exe`; both write the config to `%APPDATA%\Claude\`, so this guide works either way. |
| 3 | **VSCode** | Hosts the Claude Code extension | [code.visualstudio.com](https://code.visualstudio.com/) — macOS / Windows / Linux |
| 4 | **Claude Code extension for VSCode** | Hosts the Executor | VSCode → Extensions → search `Claude Code` → install. Or: `code --install-extension anthropic.claude-code` from a terminal. |
| 5 | **Python 3** | Required for the cross-platform wrapper script that proxies between Claude and the Docker backend | macOS: ships by default. Windows: [python.org/downloads](https://www.python.org/downloads/) — **check the "Add Python to PATH" box during install**. Linux: `apt install python3` / `dnf install python3`. Verify with `python3 --version` (or `python --version` on Windows). |
| 6 | **git** | Clones the RKA repo for the Docker compose file | macOS/Linux: built in or via package manager. Windows: [git-scm.com/downloads](https://git-scm.com/downloads). |

> **Why two Claude apps?** Brain and Executor are different roles. Brain (in Claude Desktop) reasons about research direction, makes decisions, processes maintenance. Executor (in Claude Code) writes code, runs experiments, picks up missions. They share the same RKA knowledge base, so context survives across roles and sessions.

---

## 3. Quick install (the recommended path)

The plugin handles most of the work. Follow these five steps in order.

### Step 1 — Start the RKA backend

Open a terminal in the directory where you want the RKA repo:

```bash
git clone https://github.com/infinitywings/rka.git
cd rka
docker compose up -d
```

Wait ~1 minute. Verify:

```bash
curl http://localhost:9712/api/health
# Expect: {"status":"ok","version":"2.5.x", ...}
```

Open http://localhost:9712 in your browser to confirm the dashboard loads.

> **What this does**: starts two containers (`rka-server` for the API + web UI, `rka-worker` for background jobs). Data is persisted in a Docker volume named `rka-data`. To stop: `docker compose down`. To stop AND wipe data: `docker compose down -v` (don't do this unless you mean it).

### Step 2 — Add the local RKA marketplace in Claude Code

The marketplace lives inside the cloned RKA repo (at `.claude-plugin/marketplace.json`). In any Claude Code chat window (in VSCode), run:

```
/plugin marketplace add /absolute/path/to/your/cloned/rka
```

Replace `/absolute/path/to/your/cloned/rka` with the actual path where you cloned the repo in Step 1 (e.g., `/Users/<you>/Code/rka` on macOS, `C:\Users\<you>\Code\rka` on Windows). Use the absolute path, not `~`.

### Step 3 — Install the plugin

```
/plugin install rka@rka
```

Wait for the install to complete (~5–10 seconds). On success, `/plugin list` should show `rka@rka` as installed.

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

### Step 4.5 (optional) — Install Writer reference-validation tooling

The `rka:rka-writer` skill drafts manuscripts; the reference-validation pipeline (Crossref + OpenAlex + Semantic Scholar + arXiv + SerpAPI lookups) runs in a separate MCP server called `rka-writer-tools`, registered per-manuscript-workspace by the `/rka-start-manuscript` slash command. To make the `rka-writer-tools` binary available on `PATH` (required before `cd <manuscript-dir> && claude`):

```bash
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall '.[writer-tools]'
# from the rka repo root
```

This installs the `writer-tools` optional dependency group (habanero + pyalex + semanticscholar + arxiv + serpapi + manubot). Skip this step if you don't plan to use the Writer skill. The Writer SKILL.md itself activates without this binary — only the reference-validation MCP tools require it.

### Step 5 — Fully quit and reopen Claude Desktop

The Claude Desktop MCP loader reads its config at startup, so the config change won't apply until you do a full quit + reopen.

| OS | Quit |
|---|---|
| macOS | Cmd+Q (not just clicking the red close button — that minimizes) |
| Windows | Right-click the Claude tray icon → Quit, then reopen |
| Linux | Same shortcut as your desktop environment's Quit |

Open a fresh chat in Claude Desktop. Ask:

> List my RKA projects.

Brain should call `rka_list_projects` and return the list (empty on a fresh install). If you also see a SessionStart hook line like `✅ RKA reachable at http://localhost:9712 (version 2.5.x, default project ...)` at session start in Claude Code, you're done.

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

---

## 5. Verifying the install

After Step 5, run these checks:

### In Claude Code

1. `/help` should list six `rka:rka` slash commands: `/rka-status`, `/rka-search`, `/rka-pending`, `/rka-set-project`, `/rka-setup-claude-desktop`, `/rka-start-manuscript`.
2. `/context` should show four `rka:rka-*` skills available (`rka-brain`, `rka-executor`, `rka-pi`, `rka-writer`).
3. Run `/rka-status`. Expected output: project name, phase, focus, open checkpoints (or "none").
4. New chat sessions should start with an automatic line: `✅ RKA reachable at http://localhost:9712 (version 2.5.x, default project ...)`.

### In Claude Desktop

Ask in any new chat:

> What RKA tools do you have access to?

Brain should respond with a list including `rka_list_projects`, `rka_get_status`, `rka_add_note`, etc. (~90 tools).

### Backend

```bash
docker compose ps
# Expect both rka-server and rka-worker as "Up" / "healthy"

curl http://localhost:9712/api/health
# Expect {"status":"ok","version":"2.5.x", ...}
```

---

## 6. For Claude Code: `/rka-setup-claude-desktop` execution steps

When the user invokes `/rka-setup-claude-desktop` (or asks something like "set up RKA for Claude Desktop"), execute these steps in order. Stop and report any error before continuing.

### 6.1 — Detect the OS and resolve paths

```python
import sys, os
from pathlib import Path

if sys.platform == "darwin":
    config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    integration_path = Path.home() / "Library/Application Support/RKA/integration.json"
elif sys.platform == "win32":
    config_path = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    integration_path = Path(os.environ["APPDATA"]) / "RKA" / "integration.json"
else:
    config_path = Path.home() / ".config/Claude/claude_desktop_config.json"
    integration_path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "RKA" / "integration.json"
```

### 6.2 — Verify the RKA backend is reachable

```bash
curl -sf http://localhost:9712/api/health
```

If non-zero exit: stop and tell user to run `docker compose up -d` from their RKA repo, then try again.

### 6.3 — Locate the plugin's wrapper script

The wrapper lives at `${CLAUDE_PLUGIN_ROOT}/bin/rka-mcp-bridge.py` where `CLAUDE_PLUGIN_ROOT` is set by Claude Code's plugin loader. From inside a `/rka-setup-claude-desktop` invocation, the path is the install location of the rka plugin under `~/.claude/plugins/cache/rka/rka/<version>/bin/rka-mcp-bridge.py`.

To find it programmatically:

```bash
find ~/.claude/plugins/cache/rka/rka -name "rka-mcp-bridge.py" | sort | tail -1
```

(macOS/Linux. On Windows: `dir /s /b %USERPROFILE%\.claude\plugins\cache\rka\rka\*rka-mcp-bridge.py`.)

### 6.4 — `integration.json` is optional in v1.0

The wrapper script (`bin/rka-mcp-bridge.py`) auto-detects the `rka` stdio binary via PATH lookup when `integration.json` is missing. So setup can skip writing `integration.json` entirely and rely on the user having run `uv tool install --force --reinstall .` from the rka repo (binary lands at `~/.local/bin/rka` on macOS/Linux, `%USERPROFILE%\.local\bin\rka.exe` on Windows).

If the user does want to pin a default project (recommended once the user knows their primary project id), write the file at the OS path in §4 with this minimal shape:

```json
{
  "version": "2.5.10",
  "binary_path": "/Users/<you>/.local/bin/rka",
  "default_project_id": "prj_01ABC...",
  "api_endpoint_url": "http://localhost:9712"
}
```

Get the project id by listing projects via the API:

```bash
curl -s http://localhost:9712/api/projects | python3 -c "import sys,json; [print(f\"{p['id']}: {p['name']}\") for p in json.load(sys.stdin)]"
```

`integration.json` is the design surface RKA.app v2.4 will write at startup; for now the plugin treats it as optional metadata.

### 6.5 — Back up the existing Claude Desktop config

```bash
cp "$config_path" "${config_path}.backup-$(date +%Y%m%d-%H%M%S)"
```

If the file doesn't exist yet, skip this step but ensure the parent directory exists.

### 6.6 — Atomically merge the `mcpServers.rka` entry

Read the existing config (start with `{"mcpServers": {}}` if missing/empty/malformed), set `mcpServers.rka` to:

```json
{
  "command": "python3",
  "args": ["<absolute-path-to-rka-mcp-bridge.py>"]
}
```

(Windows: `"command": "py", "args": ["-3", "<path>"]` if `python3` isn't on PATH.)

**Critical**: preserve any other entries already in `mcpServers`. Never overwrite the file blindly. If the existing JSON is malformed, abort with an error pointing at the backup; do NOT replace malformed JSON with parseable JSON silently.

Write atomically: write to `<path>.tmp` then rename to `<path>`. Re-read the result to verify it parses.

### 6.7 — Conflict detection

If `mcpServers.rka` already exists in the config, check whether it points at the wrapper or somewhere else:
- If it already points at the wrapper: no action; tell user it's already configured.
- If it points elsewhere (different command/args): show user the existing entry, ask whether to replace, and abort if no explicit confirmation.

### 6.8 — Tell the user what to do next

Output a clear message:

> ✅ Claude Desktop config updated. The RKA MCP server entry is in place at `<config_path>`. Backup of the original is at `<config_path>.backup-...`.
>
> **Now fully quit Claude Desktop** (Cmd+Q on macOS / right-click tray icon → Quit on Windows) and reopen it. Open a fresh chat and ask: *"List my RKA projects."* Claude should call `rka_list_projects` and return the list.

### 6.9 — On any failure: restore from backup

If any step from 6.4 onward fails, restore the backup:

```bash
cp "${config_path}.backup-..." "$config_path"
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
   - Optionally: `docker compose down -v` to wipe the backend (warn user this destroys their RKA data — recommend a knowledge-pack export first via `rka_export`).

---

## 8. Manual install (advanced)

Use this path if:
- You're on a system without VSCode (e.g., Claude Code CLI on a server)
- You're scripting RKA install in CI (note: plugins don't load in `claude -p` print mode — an empirical finding)
- You want to run RKA without the plugin layer at all

### 8.1 — Install the RKA stdio binary

```bash
git clone https://github.com/infinitywings/rka.git
cd rka
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
| RKA tools missing in Claude Desktop | Config not saved, or app not fully quit | Verify config at the path in §4 contains the `rka` entry; Cmd+Q fully (not red-X close); reopen |
| RKA tools missing in Claude Code | Plugin not installed, or VSCode window not reloaded | `/plugin list` to verify; reload window with Cmd+Shift+P → "Developer: Reload Window" |
| All RKA writes land in `proj_default` | LLM forgot to pass `project_id` on a write call (v2.6+ requires it as a kwarg) | The tool should have raised `TypeError: rka_X() missing 1 required keyword-only argument: 'project_id'`. If you see writes silently landing in `proj_default`, you may be on a pre-v2.6 install — upgrade. If on v2.6+, ask the LLM at conversation start to pin `project_id` and thread it through every call. |
| SessionStart hook says "RKA NOT reachable" | Docker stopped or wrong API URL | Run `docker compose up -d`; check `integration.json`'s `api_endpoint_url` |
| Wrapper says "version incompatible" | RKA backend version doesn't match the plugin's compatibility range | Either upgrade RKA backend (`git pull && docker compose up -d --build` from the repo) or downgrade the plugin to a matching version |

### Windows specifically

| Symptom | Likely cause | Fix |
|---|---|---|
| `python3 --version` fails but `python --version` works | "Add Python to PATH" wasn't checked at install | Reinstall Python 3 from python.org with that checkbox enabled, OR adjust the wrapper invocation in `claude_desktop_config.json` to use `python` instead of `python3` |
| Path with spaces breaks the wrapper | Unquoted path in JSON config | Escape backslashes (`\\\\`) and ensure the entire path is in JSON quotes |
| Microsoft Store install of Claude Desktop doesn't see the config edits | Config path differs (stored in app sandbox) | This appears NOT to happen empirically — both Microsoft Store and standalone .exe write to the same `%APPDATA%\Claude\` path. If you observe otherwise, surface as a bug. |

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

## Appendix: file inventory after a successful install

| Location | What |
|---|---|
| `<your-clone-dir>/rka/` | The cloned RKA source repo (only docker-compose.yml is needed at runtime; rest is for development) |
| Docker volume `rka-data` (managed by Docker Desktop) | The SQLite database `/data/rka.db` and any project artifacts |
| `~/.claude/plugins/cache/rka/rka/<version>/` (macOS/Linux) or `%USERPROFILE%\.claude\plugins\cache\rka\rka\<version>\` (Windows) | The installed plugin: skills, commands, hooks, wrapper script |
| `~/Library/Application Support/RKA/integration.json` (macOS) or `%APPDATA%\RKA\integration.json` (Windows) | Plugin-written config telling the wrapper which RKA backend to bridge to |
| `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | Claude Desktop's MCP config with the `rka` entry; backups of any prior version live alongside it as `*.backup-YYYYMMDD-HHMMSS` |
| `~/.claude/plugins/installed_plugins.json` | Claude Code's registry of installed plugins (includes `rka@rka` entry after install) |
| `~/.claude/plugins/known_marketplaces.json` | Claude Code's registry of marketplace sources (includes the `infinitywings/rka` GitHub source after `/plugin marketplace add`) |
