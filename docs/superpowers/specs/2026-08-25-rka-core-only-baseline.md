# RKA Core-only baseline

- Status: E0 measurement baseline
- Date: 2026-08-25
- Source baseline: `origin/main` at `57fa8f07bf6f298bc5b3a9cf113cf492898d8a03`
- Worktree: `rka-ecosystem-roadmap`
- Authority: [ADR 0012](../../adr/0012-rka-ecosystem-repository-boundaries.md)
- Detailed ownership inventory: [E0 Component Ownership Inventory](../plans/2026-08-25-rka-ecosystem-ownership-inventory.md)

## 1. Purpose

This document establishes what can currently be treated and tested as RKA
Core without changing the live Docker database or rebuilding/restarting a live
service. It is a baseline, not a claim that the repository is already
physically separable.

The intended Core boundary is the canonical research-knowledge substrate:
projects, journal entries, literature, decisions, missions, claims, evidence
clusters, research questions, experiments, provenance, retrieval, integrity,
import/export, and stable REST/MCP contracts. Manuscript semantics belong to
Writer, and agent runtime/model-driven synthesis belongs to Agentic.

## 2. Safety boundary used for this run

The following were deliberately not used:

- the running `rka-server` or `rka-worker` containers;
- the `rka-data` Docker volume or any real `rka.db`;
- Docker rebuild, restart, or force-recreate;
- the installed MCP connector as a data client;
- network-dependent academic, citation, or model-provider calls;
- Writer workspaces or user manuscripts.

Database and API checks used `tempfile.TemporaryDirectory()` and test fixtures
backed by `tmp_path`. Imports ran with `PYTHONDONTWRITEBYTECODE=1`, so they did
not create `__pycache__` files in the worktree.

The repository has no local virtual environment. The installed RKA uv-tool
Python 3.13 runtime provided the application dependencies, while a temporary
`/tmp/rka-core-baseline-pytest` directory supplied only pytest and
pytest-asyncio. This was sufficient for an isolated baseline, but it is not a
replacement for the clean CI environment defined in `.github/workflows/pytest.yml`.

## 3. Current test ownership

The repository contains 232 Python test files: 218 under `tests/` and 14 in
the eval harnesses. The detailed inventory assigns them as follows:

| Owner | Files | Current disposition |
|---|---:|---|
| Core | 163 | Remain with Core, although six mixed files require assertion-level splitting. |
| Writer | 65 | Move to `rka-writer`; this includes 30 Writer-skill tests and manuscript/planning/reference-validation tests. |
| Agentic | 4 | Move to `rka-agentic`; these cover LLM health, bounded LLM calls, visible LLM failure, and summary/Q&A. |

The six mixed Core files are:

- `tests/test_services/test_knowledge_pack.py`
- `tests/test_services/test_project.py`
- `tests/test_services/test_update_scope_guards.py`
- `tests/test_api/test_app_lifespan.py`
- `tests/test_mcp/test_skill_adapter_tools.py`
- `tests/test_skills_packaging.py`

They should be split during extraction rather than copied into multiple
repositories. Today there are no pytest ownership markers, so a Core-only run
must be assembled through explicit paths/exclusions. Adding stable `core`,
`writer`, `agentic`, and `requires_vec` markers is therefore an E1 prerequisite
for a durable Core CI job.

## 4. Dependency and process boundary findings

### 4.1 Package dependencies

`pyproject.toml` currently declares 10 base dependencies and five optional
groups: `academic`, `dev`, `llm`, `workspace`, and `writer-tools`.

The base set is a plausible Core runtime foundation:

- MCP, FastAPI/Uvicorn, aiosqlite, Pydantic/settings;
- HTTPX, Click, dotenv, and ULID support.

The optional groups are not yet aligned with the target repository boundary:

- `writer-tools` is entirely Writer-owned and should move.
- `llm` mixes Agentic provider packages (`litellm`, `instructor`) with
  Core-owned embedding packages (`fastembed`, `sqlite-vec`). It must be split;
  otherwise Core cannot test vector retrieval without installing Agentic
  dependencies.
- `academic` and `workspace` remain useful Core capabilities after
  Writer-specific callers are removed.

The current installed uv-tool runtime did not contain `sqlite_vec`. As a
result, a base-style installation could start in non-vector mode but applied
only 49 of the 51 migration files to a fresh temporary database: the two
vector-dependent migrations were skipped. Integrity then correctly reported
six unverified vector index tables. This is the principal packaging gap found
by this baseline.

### 4.2 Unconditional Writer coupling

Core process entry points still import Writer code eagerly:

- `rka/cli.py` imports `rka.cli_writer` and always registers `rka writer`.
- `rka/api/app.py` imports and mounts manuscript, manuscript-source, planning,
  and semantic-patch routes.
- `rka/api/deps.py` imports Writer-owned services at module import time.
- `rka/mcp/operation_args.py` imports Writer models into the combined typed
  dispatch union.
- `rka/services/worker.py` mixes Core embedding jobs with Writer reference
  validation.
- `rka/services/knowledge_pack.py` mixes Core export/import with Writer rows.

Consequently, the present package can run with Writer code included, but a
physical Core-only package cannot yet import its CLI, API app, or MCP schema
after simply deleting the Writer modules. These are extraction seams, not
runtime failures in the current monorepo.

### 4.3 Entry points and web surface

The package publishes two console scripts:

- `rka` (Core target, currently with a Writer subcommand);
- `rka-writer-tools` (Writer target).

The CLI help smoke check passed and confirmed that `writer` is still exposed
by the Core command. The FastAPI app similarly remains a combined Core and
Workbench application. The web application has no frontend unit-test files;
its current CI gate is a full TypeScript/Vite production build, which was not
run here because this task excluded rebuilds and focused on the Python Core
boundary.

## 5. Executed checks and results

All commands ran from the roadmap worktree. Counts below are not additive
because some focused groups overlap with broader groups.

### 5.1 Source, metadata, and CLI smoke

The application source was parsed with Python's AST, `pyproject.toml` was read
with `tomllib`, and the Click root command was invoked with `--help`.

Result:

- 182 Python source files parsed successfully;
- package name and dependency metadata loaded successfully;
- both console entry points were present;
- root CLI help exited successfully;
- the root CLI still advertised the Writer command, confirming the coupling
  described above.

### 5.2 Temporary database and API startup smoke

The smoke script performed the following entirely in a temporary directory:

1. initialized the schema and all migrations available without `sqlite-vec`;
2. created two projects;
3. wrote and read back a journal entry including its summary;
4. wrote the same search terms in another project;
5. verified FTS returned only the requested project's entry;
6. started and stopped the FastAPI lifespan with LLM and embeddings disabled.

Result:

```text
source_version=2.9.0
migrations_applied=49 latest=051_scope_tags_primary_key_per_project.sql
journal_roundtrip=pass fts_project_isolation=pass hits=1
api_lifespan_no_llm_no_embeddings=pass
```

The migration count is intentionally reported rather than normalized away:
it records the missing `sqlite-vec` capability in this base-style runtime.

### 5.3 Core service sweep

First, the service suite was run with the clearly Writer-owned service files
excluded. This broad pass produced:

```text
832 passed, 22 skipped, 20 failed
```

All 20 failures were attributable to the baseline boundary/environment:

- 19 depended on vector tables or embedding metadata unavailable without
  `sqlite-vec` (backfill, embedding workers, and integrity completeness);
- one was `test_evaluation_contract.py`, which the ownership inventory assigns
  to Writer and which also reached the same incomplete-index integrity result.

A second pass additionally excluded the vector-dependent files and the Writer
evaluation contract:

```text
794 passed, 16 skipped in 116.85s
```

This is the clean non-vector Core service baseline for this environment.

### 5.4 Core schema and project-scope tests

A focused set covered Core migrations 017--023, 030--031, multi-project
foundation, Phase-2 startup behavior, project-scoped tag keys, v2 migration,
database transactions, and project-scope request models.

```text
79 passed in 15.33s
```

All databases were fixture-created temporary files.

### 5.5 Core REST tests

The REST suite was run with the five clearly Writer-owned API files excluded.

```text
148 passed, 1 failed in 40.88s
```

The sole failure was `test_integrity_check_clean_db`: the API returned six
`index_check_incomplete` findings because the isolated runtime lacked
`sqlite-vec`. The same condition was independently observed during the service
sweep. No journal, project-scope, claim, decision, graph, hook, experiment, or
change-tracking REST failure occurred.

### 5.6 Core MCP contract and dispatch tests

A focused MCP set covered claims, evidence status, project scope, context
currency, dispatch coercion, experiments, hooks, decision compatibility,
outcomes, report fields, server behavior, and v2.6/v2.7 dispatch contracts.

```text
378 passed in 7.86s
```

This validates the current combined server's Core branches. It does not yet
prove that the Writer branches can be physically removed from the shared
Pydantic union; that requires the E2 contract split.

## 6. Checks intentionally deferred

The following are not part of this baseline result:

- full `python -m pytest` in a fresh CI-equivalent environment;
- vector migration, embedding backfill, model-swap, and vector-isolation tests;
- package/wheel build and installation into a new clean environment;
- Core import after physically removing Writer modules;
- Writer or Workbench functional tests;
- eval-harness replay against live projects;
- frontend production build;
- live Docker startup, migration, backup, or restore;
- any test involving network providers or user credentials.

They should not be represented as passing until their own safe environments
and gates are available.

## 7. Baseline verdict and immediate E1 actions

The non-vector Core logic has a strong baseline: journal round-trip,
project-scoped FTS, temporary API startup, 794 non-vector service tests, 79
schema/scope tests, 148 REST tests, and 378 focused MCP tests passed. However,
the repository is not yet a Core-only distributable because Writer modules are
eagerly imported and vector support is bundled with Agentic LLM dependencies.

The smallest next actions are:

1. Split the current `llm` extra into a Core embedding extra and an
   Agentic-owned provider extra; define whether the Core release installs the
   embedding extra by default.
2. Add test ownership markers or checked-in test manifests for `core`,
   `writer`, `agentic`, and `requires_vec`, then create a Core-only CI job.
3. Make CLI subcommands, API routers/dependencies, MCP operation unions, worker
   handlers, and knowledge-pack record families separable without importing
   Writer modules.
4. Add a clean package-install smoke gate that proves `rka --help`, API
   lifespan, Core MCP schema, journal round-trip, and integrity checks with the
   declared Core dependency profile.
5. Run the vector-dependent Core tests in a fresh environment containing the
   new embedding extra before declaring the Core package release-ready.

No production/runtime data was read or changed while producing this baseline.
