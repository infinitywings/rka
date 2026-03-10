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
- **ID prefix**: `jnl_` journal, `lit_` literature, `dec_` decision, `msn_` mission, `scn_` scan
- **MCP tools**: all prefixed `rka_`, defined in `server.py` via `@mcp.tool()`
- **MCP prompts**: defined at end of `server.py` via `@mcp.prompt()`
- **API routes**: thin adapters only — no business logic, always delegate to service layer
- **Tests**: `tests/` using pytest; run with `.venv/bin/pytest`

## Running Locally

```bash
# Start REST API + web dashboard (port 9712)
.venv/bin/rka serve

# MCP stdio server (used by Claude Desktop / Claude Code)
.venv/bin/rka mcp

# Run tests
.venv/bin/pytest

# Rebuild web UI after frontend changes
cd web && npm run build
```

## After Frontend Changes

Always rebuild before testing: `cd web && npm run build`
The FastAPI server serves `web/dist/` as static files — changes are not live-reloaded.

## Common Pitfalls

- `actor="import"` is not a valid actor — use `actor="system"` for programmatic ingestion
- The MCP server is stateless; it proxies all calls to the REST API at `RKA_API_URL` (default: `http://localhost:9712`)
- `web/` previously had a nested `.git` — do not re-introduce submodule state there
- Large files (>10 MB) use fast composite hashing; text files are capped at 200K chars in scan
- The venv has a dependency conflict between `pyzotero` (needs `bibtexparser<2`) and RKA (needs `bibtexparser>=2`); use `.venv/bin/pytest` directly rather than `uv sync`
