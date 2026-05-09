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

## macOS / FuSpace AppleDouble Quirks

The FuSpace volume creates `._*` resource-fork files alongside any file Python tools write to (in `build/`, `rka.egg-info/`, project root). These break both `docker compose build` (fails with "failed to xattr ... operation not permitted") and `uv tool install` (fails with "No such file or directory: '._requires.txt'") even with `COPYFILE_DISABLE=1` set.

**Before any rebuild**, purge resource-fork files:

```bash
find . -maxdepth 2 -name '._*' -not -path './.git/*' -delete
```

**If `uv tool install --force .` still fails on `._requires.txt`** (the build process re-creates AppleDouble files in `build/` on FuSpace), install from a `/tmp` clone instead:

```bash
rm -rf /tmp/rka-build && git clone -q --depth 1 /Volumes/FuSpace/Projects/rka /tmp/rka-build
cd /tmp/rka-build && UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

**If `docker compose build` succeeds but the new image isn't picked up**, force-recreate:

```bash
docker compose up -d --force-recreate
```

(Plain `docker compose up -d --build` can hit the build cache or skip recreation if Compose decides nothing changed; `--force-recreate` is the reliable post-rebuild path.)
