# ADR 0014: Core distribution and installer boundary

- **Status:** Accepted
- **Date:** 2026-08-28
- **Decision:** `dec_01M14MT0Z5CR3ERZ7R8MC4QJJ9`
- **First implementation mission:** `mis_01M14MZ49G9TRR93BYAK43EJCC`

## Context

RKA Core is reliable when developed and deployed through Docker, but that is
too much installation machinery for many researchers. A normal user should be
able to start with Python and a supported coding agent. At the same time, the
Docker stack is valuable for development, reproducible integration tests, and
managed deployments and must remain a first-class profile.

The previous repository also mixed three different responsibilities:

1. durable research records, provenance, retrieval, REST, and MCP;
2. manuscript authoring and researcher-facing writing workflows; and
3. installation, service lifecycle, and AI-client configuration.

Keeping those concerns in one release makes Core harder to test and makes a
friendly installer depend on implementation details that should remain private.

## Decision

The repository's `main` branch remains the canonical source for RKA Core. The
published Python distribution will be named **`rka-core`** to avoid the
unrelated package already using the `rka` name on PyPI. The stable Python import
and command remain **`rka`**, including `python -m rka` and the `rka` console
script.

Core has two supported runtime profiles:

- **Base Python profile:** provenance-aware storage, SQLite/FTS retrieval,
  migrations, REST, MCP, backup, and knowledge-pack portability. Optional
  embeddings are disabled unless their extra is installed and explicitly
  enabled.
- **Docker/full profile:** the existing server, worker, dashboard, and local
  embedding stack. Docker sets `/data` explicitly; Core never infers Docker
  merely because a host has a `/data` directory.

For a normal Python installation, persistent state defaults to
`RKA_DATA_DIR/rka.db`, where `RKA_DATA_DIR` defaults to `~/.rka`. This path is
independent of the shell's working directory. An explicitly supplied absolute
`RKA_DB_PATH` remains authoritative. An explicitly supplied relative
`RKA_DB_PATH` remains relative to `RKA_PROJECT_DIR` so existing project-local
deployments and `rka init` projects continue to work.

The separately developed **`rka-app`** distribution will own installation and
machine integration: a private environment, version pinning, background
service registration, stable launchers, safe Claude/Codex configuration,
diagnostics, upgrades, rollback, and eventual native UI packaging. It will
consume released Core artifacts and must not copy or fork Core source.

RKA Writer remains a separate downstream product. The shelved Agentic runtime
is neither a Core dependency nor an installation target.

## Release and branch policy

There is no permanent app or distribution branch. Core release changes are
developed on short-lived feature branches, reviewed through pull requests, and
merged into `main`. Release artifacts are built from tagged `main` commits.
The future `rka-app` has its own repository, tests, and release cadence.

The first distribution foundation deliberately does not publish to PyPI and
does not alter user configuration. Its gate builds a wheel, installs only that
artifact in a fresh environment, changes to an unrelated working directory,
and verifies the module entry point, migrations, REST health, worker pass, and
five-tool MCP surface.

## Deferred work

The following belong to later, independently reviewable slices:

- bundling the prebuilt dashboard into wheel and sdist artifacts without
  requiring Node on an end user's machine;
- readiness-aware and atomic `start`/`stop` lifecycle commands plus
  machine-readable diagnostics;
- a portable replacement for the Unix-only Phase-2 file lock before claiming
  Windows support;
- automatic Claude Code, Claude Desktop, and Codex registration;
- service managers, updates, backups before upgrade, rollback, GUI/tray,
  signing, and notarization.

This staging is intentional. A small, verifiable Core contract is the
dependency for a trustworthy one-command installer.
