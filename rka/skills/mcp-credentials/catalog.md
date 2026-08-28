# Catalog — supported MCP credentials

Quick-reference table for every credential this skill knows how to set up. When you need a deeper walkthrough, load the relevant `walkthroughs/<service>.md`.

| Service | Env var(s) | Target | Validation regex | Walkthrough |
|---|---|---|---|---|
| Zotero | `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE` | `mcpServers.zotero.env` in `claude_desktop_config.json` | key: `^[A-Za-z0-9]{24}$`; id: `^\d+$`; type: `user\|group` | [zotero](walkthroughs/zotero.md) |
| Semantic Scholar | `SEMANTIC_SCHOLAR_API_KEY` | `mcpServers.rka.env` in `claude_desktop_config.json` | `^[A-Za-z0-9]{32,48}$` (s2k-prefix common but not required) | [semantic-scholar](walkthroughs/semantic-scholar.md) |
| SerpAPI | `SERPAPI_KEY` | `mcpServers.rka.env` | `^[a-f0-9]{64}$` (lowercase hex, 64 chars) | [serpapi](walkthroughs/serpapi.md) |
| OpenAlex | `OPENALEX_MAILTO` | `mcpServers.rka.env` (and/or any OpenAlex-aware server's env) | RFC 5322 email | [openalex](walkthroughs/openalex.md) |

## Target file paths

### Claude Desktop config

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### Claude Code config

| OS | Path |
|---|---|
| All | `~/.claude.json` (per-user, all-projects) OR `<repo>/.claude/mcp.json` (per-repo) |

## Standard env-var → MCP server mapping

When you persist a credential, route the env var to the right server block based on this table:

| Env var | Belongs in MCP server block | Why |
|---|---|---|
| `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE` | `zotero` (the zotero-mcp server) | Service-specific |
| `SEMANTIC_SCHOLAR_API_KEY` | `rka` (the rka MCP server) | Read by `rka_search_semantic_scholar` |
| `SERPAPI_KEY` | `rka` (the rka MCP server) | Used by deep-research augmentation if installed |
| `OPENALEX_MAILTO` | `rka` (the rka MCP server) AND any OpenAlex-aware server | Polite-pool email, harmless to set broadly |

## Service-availability check

Before suggesting a service, you can verify the corresponding MCP server is actually installed by reading the user's `claude_desktop_config.json` and checking for the `mcpServers.<service>` block. If absent, the credential won't help — point the user at the MCP server's own install docs first.

The exception is `rka` — assume it is installed because this skill ships inside RKA's own repository.
