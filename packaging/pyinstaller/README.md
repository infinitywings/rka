# PyInstaller specs for the bundled sidecar binaries

Two specs produce single-file executables embedded in `Contents/Resources/` of `RKA.app`:

| Spec | Binary | Role |
|------|--------|------|
| `rka-serve.spec` | `dist/rka-serve` | FastAPI + worker — the long-running sidecar Tauri spawns |
| `rka-mcp.spec` | `dist/rka-mcp` | Stateless MCP stdio proxy — referenced by the per-client launcher script |

## Build

```
./packaging/pyinstaller/build.sh
```

The wrapper does:
1. AppleDouble cleanup (FuSpace volumes mint `._*` resource forks that break PyInstaller).
2. Ensure a virtualenv exists with `pyinstaller` + the LLM extras (`fastembed`, `sqlite-vec`, etc.) installed.
3. Build both specs.
4. Strip extended attributes from the resulting binaries (`xattr -cr dist/`).

If a build mid-step recreates `._*` files in `build/`, use the `/tmp` clone fallback (see CLAUDE.md d2a9388 "AppleDouble Quirks" section).

## Bundled-sidecar defaults

Per Brain greenlight tightening A4 (`jrn_01KRH8EQ1RZN3DHWJ0AYDXC3FT`), the bundled sidecar defaults `RKA_EMBEDDINGS_ENABLED=true`. The runtime hook `hooks/rt_rka_env.py` sets this unconditionally before `RKAConfig` reads the environment, but `os.environ.setdefault` preserves any user override.

D7 integration test asserts `GET /api/capabilities` returns `embedding: ✓` on a bundled fresh launch.

## Entry-point scripts

`entry_points/entry_serve.py` and `entry_points/entry_mcp.py` are the targets of each spec's `Analysis()`. They invoke the existing `rka.cli:main` Click group with the correct subcommand argv injected, so the binaries do not duplicate command implementations.

## What's bundled as data

- `rka/db/schema.sql` + all `rka/db/migrations/*.sql` (schema + idempotent migrations)
- `rka/skills/SKILL.md` + `rka/skills/{brain,executor,pi}/**/*.md` (MCP prompts)
- `web/dist/index.html` + `web/dist/assets/*` (FastAPI-served React UI) — only in `rka-serve` spec
