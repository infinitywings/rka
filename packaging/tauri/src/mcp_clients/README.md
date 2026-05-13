# Per-client MCP-config registry

This module owns the seven-client onboarding surface. Each supported MCP
client implements the `McpClient` trait declared in `mod.rs`:

| # | Module | Format | Root key | Notes |
|---|--------|--------|----------|-------|
| 1 | `claude_desktop` | JSON | `mcpServers` | — |
| 2 | `claude_code` | JSON | `mcpServers` | `claude mcp add` CLI may be canonical; verify at impl |
| 3 | `cursor` | JSON | `mcpServers` | global `~/.cursor/mcp.json` only (project-scope out of scope) |
| 4 | `vscode_copilot` | JSON | **`servers`** | **NOT `mcpServers`** — copy-paste hazard |
| 5 | `codex_cli` | **TOML** | `[mcp_servers.rka]` | preserve user's other `[mcp_servers.*]` tables |
| 6 | `codex_app` | TOML | `[mcp_servers.rka]` | shares write target with `codex_cli` |
| 7 | `antigravity` | JSON (verify) | `mcpServers` (verify) | schema sparse in Google docs; D3 hard-checkpoint gate |

## Adding a new client

1. Create a new module file `mcp_clients/<id>.rs`.
2. Implement `McpClient` with all six trait methods.
3. Append a `Box::new(<id>::Client)` to the `registry()` vector in `mod.rs`.
4. Add per-client integration tests in `packaging/tests/test_<id>.py`
   covering the standard nine cases plus any client-specific quirks
   (round-trip preservation of unrelated entries, conflict detection,
   malformed-config refusal).

## Mandatory round-trip preservation test

Per `jrn_01KR4GVDXYRVTT6RXTX7BP3JW6` audit-symmetry discipline, every
new client's test suite must include:

- write-then-read-back asserting both `rka` and unrelated servers are
  present;
- remove-then-read-back asserting `rka` is gone and unrelated servers
  are still present.

Any merger that serializes via `json::dumps` or `toml::dumps` must be
paired with a parse-back assertion. Grep the module for `serde_json::to_string`
or `toml::to_string` and verify each call has a matching parse-back
assertion nearby.

## Antigravity schema verification gate

Before coding `antigravity.rs`, the implementer:

1. Opens the Antigravity IDE.
2. Runs "Manage MCP Servers → View raw config".
3. Records the actual JSON shape in a journal note linked to mission
   `mis_01KQJGR4WZXYFSDP9DN2WEXTJJ`.

If the shape differs from the assumed `mcp_config.json` with `mcpServers`
root key, raise a checkpoint per mission checkpoint trigger #1. No silent
fallback.

The same "verify before coding" rule applies to VSCode-Copilot's
user-scope config path and Codex CLI+App shared-config behavior — three
sister-uncertainties per `jrn_01KRH8EQ1RZN3DHWJ0AYDXC3FT` Brain greenlight.

## WebFetch attribution

Each per-client module's top-of-file docstring cites:

- the WebFetch'd documentation URL the implementer consulted,
- the access date.

This keeps the merger grounded in the actual current API rather than
training-data drift.
