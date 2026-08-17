# RKA Technical Reference

This is the compact entry point for RKA's command-line, MCP, REST, configuration, and development surfaces. Runtime schemas and the live OpenAPI document remain authoritative when they differ from static documentation.

## Runtime

The default Docker deployment starts:

| Component | Purpose | Address |
|---|---|---|
| RKA server | REST API and web dashboard | `http://127.0.0.1:9712` |
| Worker | Indexing and embedding jobs | internal |
| SQLite volume | Persistent project data | `/data/rka.db` in the container |

```bash
docker compose up -d
docker compose ps
docker compose logs -f rka
```

After source changes, rebuild rather than restarting:

```bash
docker compose up -d --build
```

## CLI

| Command | Purpose |
|---|---|
| `rka init <name>` | Initialize a workspace and project. |
| `rka serve` | Start the REST API, dashboard, and worker outside Docker. |
| `rka mcp` | Start the default stdio MCP adapter. |
| `rka mcp --transport http --host 127.0.0.1 --port 9713` | Start local Streamable HTTP MCP. |
| `rka status` | Show current project status. |
| `rka backup` | Create a database backup. |
| `rka migrate` | Run pending migrations. |
| `rka bootstrap scan <folder>` | Inspect a workspace before ingestion. |
| `rka bootstrap ingest <folder>` | Ingest an approved workspace scan. |
| `rka cred ...` | Initialize, inspect, and propagate the credential vault. |

Use `rka --help` and `rka <command> --help` for the installed version's complete option set.

## MCP

The MCP binary is a thin proxy to the REST API configured by `RKA_API_URL`, which defaults to `http://localhost:9712`.

### Default dispatch tools

| Tool | Purpose |
|---|---|
| `rka_query` | Read and navigation operations. |
| `rka_execute` | Writes and lifecycle transitions. |
| `rka_describe` | Runtime operation index and typed schemas. |
| `rka_load_tools` | Load deferred compatibility tools when required. |
| `rka_help` | Discovery and help alias. |

Use `rka_describe("")` for the operation index and `rka_describe("<operation>")` for exact required fields, enums, and provenance constraints. This runtime description is authoritative and should be preferred over copied operation lists.

Project-scoped operations require an explicit `project_id`. `list_projects` and `create_project` are intentionally unscoped.

### Transport modes

- **stdio:** `rka mcp`
- **local HTTP:** `rka mcp --transport http --host 127.0.0.1 --port 9713`

The HTTP transport does not provide authentication by itself. Bind it to loopback and use the supported authenticated connector for remote access. See [CHATGPT_CONNECTOR.md](CHATGPT_CONNECTOR.md).

## REST API

- Base URL: `http://localhost:9712/api`
- OpenAPI UI: `http://localhost:9712/docs`
- Health: `http://localhost:9712/api/health`

Most endpoints are project-scoped. Pass the project identifier through the documented header or query parameter. Use the live OpenAPI schema for exact request and response models.

Major route families include projects, status, notes, decisions, literature, missions, checkpoints, claims, clusters, research maps, freshness, search, context, graphs, artifacts, workspace ingestion, audit history, and knowledge-pack import/export.

## Configuration

Core runtime settings use the `RKA_` prefix. Common settings include:

| Variable | Default | Purpose |
|---|---|---|
| `RKA_API_URL` | `http://localhost:9712` | REST target used by MCP. |
| `RKA_HOST` | `127.0.0.1` | API bind address outside Docker. |
| `RKA_PORT` | `9712` | API port. |
| `RKA_DB_PATH` | `rka.db` | Database path outside the default Docker deployment. |
| `RKA_MANUSCRIPT_WORKSPACE_ROOTS` | empty | `os.pathsep`-separated allowlist for local Markdown/LaTeX source access; an empty value disables source synchronization. |
| `RKA_MANUSCRIPT_SOURCE_MAX_BYTES` | `2097152` | Maximum UTF-8 bytes accepted for one synchronized manuscript source file. |
| `RKA_SKILL_TOOLS` | unset | Promote ChatGPT skill-adapter tools on the connector surface. |
| `RKA_LEGACY_TOOLS` | unset | Restore the compatibility always-on tool surface when required. |

Store credentials with `rka cred`; do not commit secrets to `.env` files. See [CRED_VAULT.md](CRED_VAULT.md).

Embedding backends are configured through the dashboard or persistent embedding configuration. See [embedding_backends.md](embedding_backends.md).

## Data model

RKA uses prefixed ULIDs to keep entity identity explicit and sortable. Core prefixes include:

| Entity | Prefix |
|---|---|
| Project | `prj_` |
| Journal entry | `jrn_` |
| Decision | `dec_` |
| Literature | `lit_` |
| Mission | `mis_` |
| Checkpoint | `chk_` |
| Claim | `clm_` |
| Evidence cluster | `ecl_` |
| Entity link | `lnk_` |
| Workspace scan | `scn_` |

Every write emits audit/event information with the responsible actor. Valid actor values are `brain`, `executor`, `pi`, `llm`, `web_ui`, and `system`.

## Knowledge packs

Projects can be exported and imported as portable knowledge packs. Import creates a separate project and remaps project-scoped entity IDs and internal references. Export/import behavior must be covered by tests whenever a new persisted entity or relationship is introduced.

## Development

Run tests in the Docker environment:

```bash
docker compose exec rka pytest
```

The principal source directories are:

```text
rka/models/      typed domain models
rka/services/    shared business logic
rka/api/         FastAPI adapters
rka/mcp/         MCP adapter and operation schemas
rka/db/          schema and migrations
rka/skills/      packaged role skills
web/             React dashboard
tests/           service, API, MCP, workflow, and serialization tests
```

Before modifying the repository, read [`CLAUDE.md`](../CLAUDE.md). It is the authoritative working-instructions file for both human contributors and coding agents.

## Further documentation

- [Installation](../INSTALL.md)
- [Usage Guide](../USAGE_GUIDE.md)
- [User Manual](USER_MANUAL.md)
- [Architecture](ARCHITECTURE.md)
- [Embedding Backends](embedding_backends.md)
- [Credential Vault](CRED_VAULT.md)
- [ChatGPT Connector](CHATGPT_CONNECTOR.md)
- [MCP tool-surface design history](v2.6.x-v2.7.0-tool-surface-arc.md)
