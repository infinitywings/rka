# RKA Ecosystem Repository Separation Execution Plan

- Status: superseded as an active execution source on 2026-09-03; retained as
  separation history
- Date: 2026-08-25
- Decision owner: Chenglong Fu
- Superseded by:
  [`2026-09-03-rka-ecosystem-active-roadmap.md`](2026-09-03-rka-ecosystem-active-roadmap.md)
- Reason: E0-E2 and the initial repository split are complete, Agentic
  extraction was shelved by ADR 0013, RKA App now exists, and Writer has been
  re-baselined around the Authoring IR and convergence protocol.
- Current repository: `infinitywings/rka`
- Clean planning baseline: `origin/main` at `57fa8f0`
- Related integrity candidate: `fix/claim-edge-integrity` at `eb9faa3`
- Ownership inventory:
  [`2026-08-25-rka-ecosystem-ownership-inventory.md`](2026-08-25-rka-ecosystem-ownership-inventory.md)
- GitHub tracking slate:
  [`2026-08-25-rka-ecosystem-github-slate.md`](2026-08-25-rka-ecosystem-github-slate.md)
- Core-only baseline:
  [`2026-08-25-rka-core-only-baseline.md`](../specs/2026-08-25-rka-core-only-baseline.md)
- Claim-edge audit and remediation evidence:
  [`2026-08-25-claim-edge-integrity-audit.md`](../specs/2026-08-25-claim-edge-integrity-audit.md)

> This document describes the original separation program. Its Agentic and
> pre-rebaseline Writer steps are historical, not current authorization.

## 1. Objective

Separate the current RKA implementation into three independently installable
and releasable products while preserving the existing research database,
provenance, implementation history, and already validated Writer/Workbench
behavior:

1. `infinitywings/rka`: research-knowledge core;
2. `infinitywings/rka-writer`: academic-writing application and Workbench;
3. `infinitywings/rka-agentic`: agent orchestration runtime.

The immediate product priority is Core correctness and retrieval. Repository
extraction is a controlled consequence of that priority, not a reason to pause
or dilute Core reliability work.

## 2. Constraints

- Preserve the current `infinitywings/rka` repository and its public URL.
- Preserve all user databases and identifiers.
- Do not develop new Writer/Workbench behavior inside Core after E0.
- Do not use the dirty root checkout as an extraction source.
- Do not require Writer or Agentic to run Core.
- Do not permit Writer or Agentic to import Core internals or open its database.
- Do not automatically drop legacy manuscript/planning tables.
- Do not require lockstep releases or a new GitHub organization.
- Do not add an event bus, shared-model repository, or fourth umbrella
  repository without measured need.

## 3. Component ownership

| Current area | Target owner | Disposition |
|---|---|---|
| `rka/db`, general models, project/journal/literature/decision/mission services | Core | Keep and harden |
| claims, clusters, RQs, provenance, freshness, experiments, artifacts | Core | Keep and harden |
| FTS/vector/graph retrieval, knowledge packs, integrity, migration | Core | Keep and harden |
| Core REST/MCP/CLI and minimal maintenance UI | Core | Keep and stabilize |
| `rka/skills/writer`, `plugin/skills/writer`, Writer tools/tests | Writer | Extract with history |
| manuscript, manuscript-claim/unit, outline, planning and source-sync services | Writer | Migrate behind compatibility export |
| Workbench-specific web components and routes | Writer | Extract after API boundary is stable |
| Brain/Executor/PI autonomous orchestration runtime | Agentic | Extract from the agentic branch |
| agent runs, scheduling, interrupts, runtime checkpoints and transcripts | Agentic | Store outside Core |
| generic Core usage/retrieval/provenance guidance | Core | Retain as a small connector skill |
| legacy manuscript tables and migrations | Core legacy | Preserve read-only during compatibility window |

Before extraction, E0 produces a machine-readable or tabular inventory of all
tables, API routes, MCP operations, skills, tests, package entry points, and web
pages. Ambiguous items block extraction until one owner is selected.

## 4. Integration contract

### 4.1 Core contract

Core provides:

- version and capability discovery;
- an OpenAPI contract and MCP operation descriptions;
- explicit project scoping;
- revision/content-hash information for durable references;
- idempotent retry support for consumer writes;
- change-cursor retrieval for detecting stale downstream references;
- export/import and integrity reports.

REST is the deterministic application contract. MCP is the agent-facing
contract. Neither contract exposes database paths or service-layer classes.

### 4.2 Writer references to Core

A durable Writer binding contains:

```json
{
  "project_id": "prj_...",
  "entity_id": "clm_...",
  "entity_type": "claim",
  "revision": 7,
  "content_hash": "sha256:...",
  "locator": "source-specific locator"
}
```

Writer uses Core's change cursor to recheck these bindings. A changed or
missing reference becomes a Writer review finding; Writer never overwrites the
Core record to make its draft appear current.

### 4.3 Agentic references to Core

Agentic records durable research outcomes through Core and stores only runtime
execution details locally. Mission IDs, decision IDs, journal IDs, and artifact
IDs are references across the boundary. Agent retry state, model messages,
interrupt positions, and scheduler leases are not Core journal content unless
the agent explicitly promotes a bounded research result.

## 5. Milestones and exit gates

### E0: Boundary freeze and inventory

Deliverables:

- ADR 0012;
- this execution plan;
- active roadmap update;
- component/operation/table ownership inventory;
- initial GitHub issue and milestone slate.

Exit gate:

- no ambiguous authority owner;
- old Workbench design remains discoverable but is no longer Core's active
  implementation priority;
- no runtime or database change has been made.

Rollback: revert documentation only. No product state is affected.

### E1: Core reliability baseline

Scope:

- journal create/read/update and provenance round trips;
- project isolation across SQL, tags, FTS, vector retrieval, graph traversal,
  imports, and background jobs;
- claim-edge uniqueness and cluster merge/split integrity;
- freshness/staleness behavior;
- export/import, backup/restore, and migration correctness;
- deterministic retrieval-quality and latency baselines;
- Core-only installation and test profile.

Candidate PR sequence:

1. claim-edge membership and merge/split integrity;
2. project-scoped vector partitioning and migration decision;
3. journal/retrieval/integrity regression suite;
4. Core-only packaging and startup gate.

Exit gate:

- exact journal round trip passes;
- no cross-project retrieval leakage in any backend;
- repeated writes and edge assignments are idempotent;
- a real database backup upgrades and passes integrity;
- export/import preserves IDs, links, revisions, and hashes;
- Core starts and passes its supported tests without Writer dependencies.

Rollback: restore the pre-migration database backup and previous container;
every migration must be tested on a disposable copy before live use.

### E2: Stable external contract and Writer compatibility export

Scope:

- freeze stable Core REST/MCP operations;
- publish capability and version information;
- snapshot the OpenAPI and MCP contracts in tests;
- classify optional operations as preview/deprecated;
- add legacy Writer-state export with counts, versions, and checksums;
- register external sources as non-canonical, hash-verified artifacts and make
  interpretation admission explicit;
- document compatibility errors and supported version ranges.

Exit gate:

- a client using only the public contract can complete a project/journal/
  claim/cluster/RQ/evidence workflow;
- mock Writer and Agentic clients contain no imports from `rka.services`,
  `rka.models`, or `rka.db`;
- legacy Writer export round-trips on a disposable database copy;
- registered bytes, provenance, and explicit admissions round-trip, while
  missing or modified managed bytes fail closed.

Rollback: consumers continue using the prior Core version; no authority switch
occurs in E2.

### E3: Agentic repository extraction

Scope:

- extract the `orchestrator/` history from the agentic branch;
- create `infinitywings/rka-agentic`;
- make `RKA_API_URL` and supported Core versions explicit;
- replace manually synchronized Core internals with a generated or pinned
  public-contract snapshot;
- establish independent tests, packaging, and deployment documentation.

Exit gate:

- Core and Agentic each install and test independently;
- Agentic does not import Core internals or open Core storage;
- a real integration test performs mission pickup, checkpoint, report, and
  provenance recording through the public contract;
- failure on an incompatible Core version is immediate and actionable.

Rollback: the existing agentic branch remains available until the extracted
repository passes the integration gate.

### E4: Writer repository extraction and state migration

Scope:

- extract Writer skill, tools, tests, templates, and history;
- create `infinitywings/rka-writer`;
- introduce Writer-owned state and Workbench service boundaries;
- import legacy manuscript/planning state while preserving identifiers;
- move Writer-specific UI and provider integration;
- establish stale-Core-reference detection and end-to-end manuscript tests.

Migration gate for each database:

1. export legacy state from an online or offline backup;
2. import into Writer staging;
3. compare entity counts, IDs, hashes, bindings, ratifications, and lineage;
4. run a read-only Workbench acceptance pass;
5. explicitly activate Writer authority;
6. retain the Core copy read-only for recovery.

Exit gate:

- Writer installs without Core source code;
- Core runs without Writer;
- a real project completes Core claim -> Writer spine -> outline -> draft ->
  provenance inspection;
- a revised Core claim causes a visible Writer stale-reference finding;
- the approved human writing-quality pilot remains passing.

Rollback: switch back to the legacy Core Writer surface; do not delete either
copy until the compatibility window ends.

### E5: Future Core slimming

Scope:

- remove Writer skills, tools, routes, MCP operations, services, optional
  dependencies, and Workbench UI from the active Core distribution;
- remove orchestration-specific mirrors and documentation;
- retain the narrow legacy Writer export path and migration history;
- update installation, plugin, and user documentation.

Exit gate:

- no active Core operation depends on Writer or Agentic packages;
- Core-only tests, migration tests, retrieval evaluation, packaging, Docker,
  MCP, and REST smoke tests pass;
- Writer and Agentic compatibility suites pass against the release candidate;
- existing databases open without destructive schema changes.

Rollback: remain on the current compatibility release. No future breaking
release is scheduled until downstream suites pass and removal is explicitly
approved.

### E6: Ecosystem integration and release discipline

Scope:

- maintain the `RKA Ecosystem` GitHub Project;
- publish a compact compatibility matrix;
- test Core alone, Core+Writer, Core+Agentic, and all three together;
- document installation, upgrade, backup, and recovery for each supported
  combination.

Exit gate:

- every supported combination has a reproducible smoke test;
- independent releases do not require lockstep tags;
- unsupported combinations fail with a clear version message;
- the integration documentation is tested from a clean machine or disposable
  environment.

## 6. Release sequence

1. Final RKA 2.x compatibility release: stable contracts, deprecations, and
   Writer export.
2. RKA Agentic 1.0: public-contract-only orchestrator.
3. RKA Writer 1.0: public-contract-only Writer and verified legacy import.
4. Future Core breaking release: active optional-layer code removed only after
   downstream gates and explicit approval.

The releases are independent. Each downstream repository publishes the Core
major versions it supports.

## 7. Git and worktree discipline

- Do not modify the currently dirty repository root.
- Start each change from a clean worktree based on `origin/main`.
- Keep Core reliability fixes separate from architecture documentation and
  extraction work.
- Extract repository history rather than copying a snapshot when new remote
  repositories are created.
- Preserve the current remote branches until extraction and compatibility
  gates pass.
- Do not merge, push, create remote repositories, or migrate live data as an
  incidental part of documentation work.

## 8. Work that can start immediately

The following work is safe to complete before creating either downstream
repository:

1. Review and merge the boundary ADR and roadmap documentation.
2. Produce the complete ownership inventory for tables, routes, MCP operations,
   skills, entry points, tests, and web pages.
3. Freeze new Writer/Workbench features inside Core and route new proposals to
   the future Writer backlog.
4. Review the existing `fix/claim-edge-integrity` candidate independently and,
   if accepted, merge it as the first E1 Core reliability change.
5. Decide and test the project-scoped vector partition migration on a
   disposable database copy; do not run the expensive live re-embedding without
   explicit approval.
6. Prepare the cross-repository GitHub Project phases, repository-local
   milestones, and initial PR-sized issues after the documentation branch is
   reviewed; do not model cross-repository E3/E4/E6 work as Core milestones.
7. Define the Core-only test profile and record the current test, retrieval,
   migration, and startup baseline.

Do not start today:

- remote repository creation;
- live Writer-state migration;
- deletion of manuscript tables or routes;
- future Core removal work;
- installed plugin/runtime replacement;
- merging unrelated dirty-root changes.

## 9. Decision checkpoints

Human confirmation is required before:

- creating the two new GitHub repositories;
- switching legacy manuscript authority from Core to Writer;
- running a long live re-embedding or irreversible data migration;
- publishing a future Core breaking release;
- deleting any legacy branch, table, compatibility code, or remote artifact.
