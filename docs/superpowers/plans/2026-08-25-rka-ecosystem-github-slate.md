# RKA Ecosystem GitHub Milestone and Issue Slate

- Status: prepared from a read-only GitHub snapshot; no remote changes applied
- Snapshot date: 2026-08-25
- Repository inspected: `infinitywings/rka`
- Governing decision: ADR 0012
- Active execution plan:
  `2026-08-25-rka-ecosystem-repository-separation.md`

## 1. Tracking model

GitHub milestones are repository-specific. E0-E6 span three repositories, so
they should not all be created as milestones in `infinitywings/rka`.

Use two coordinated layers:

1. A user-level GitHub Project named **RKA Ecosystem**, with a single-select
   field `Ecosystem phase` containing E0 through E6.
2. Repository-local milestones for the work owned by each repository.

Recommended Project fields:

| Field | Values |
|---|---|
| Ecosystem phase | E0 Boundary; E1 Core reliability; E2 Contract; E3 Agentic extraction; E4 Writer extraction; E5 Future Core slimming; E6 Integration |
| Component | Core; Writer; Agentic; Integration |
| Status | Backlog; Ready; In progress; Review; Blocked; Done |
| Release gate | Not started; Partial; Passed |

The Project is the cross-repository roadmap. Repository milestones remain
release-sized containers and can be closed independently.

## 2. Existing milestone disposition

The live repository currently has seven Workbench-era milestones.

| Existing milestone | Live issue state | Recommended disposition |
|---|---:|---|
| M0 Foundation and validation | 0 open / 2 closed | Already closed; retain as history |
| M1 Epistemic research substrate | 0 open / 3 closed | Already closed; retain as history |
| M2 Read-only manuscript workbench MVP | 0 open / 1 closed | Already closed; retain as history |
| M3 Deliberation and safe editing | 0 open / 2 closed | Close after the roadmap pivot is merged |
| M4 Contribution and evaluation workflow | 0 open / 2 closed | Close after the roadmap pivot is merged |
| M5 Outline and drafting | 0 open / 3 closed | Close after the roadmap pivot is merged |
| M6 Intake, artifact views, and hardening | 4 open / 0 closed | Reclassify #62-#65, then close or rename as a historical backlog |

Issue #61 is closed but still carries `priority: next`. Remove that label when
the new E1 claim-edge issue is created, and apply `priority: next` to exactly
one open E1 issue.

## 3. New repository-local milestones

### `infinitywings/rka`

Create after the documentation branch is reviewed:

1. **E0 — Core boundary freeze**
2. **E1 — Core reliability baseline**
3. **E2 — Stable external contract**
4. **E5 — Future Core slimming**

### Future `infinitywings/rka-agentic`

Create after the repository exists:

1. **A1 — Repository extraction and contract-only runtime** (ecosystem E3)
2. **A2 — Core integration and independent release gate** (ecosystem E6)

### Future `infinitywings/rka-writer`

Create after the repository exists:

1. **W1 — Skill/tools extraction** (ecosystem E4)
2. **W2 — Legacy state migration and Workbench authority** (ecosystem E4)
3. **W3 — Core integration and independent release gate** (ecosystem E6)

Do not create E3/E4/E6 as placeholder milestones in the Core repository. Until
the downstream repositories exist, track those phases as draft items in the
RKA Ecosystem Project.

## 4. Labels

Reuse current labels where their meaning remains accurate:

- `roadmap`
- `documentation`
- `enhancement`
- `priority: next`
- `area: substrate` for canonical research semantics

Add only the missing labels:

| Label | Purpose |
|---|---|
| `area: core` | Core runtime, storage, retrieval, contracts, packaging |
| `area: agentic` | Agent orchestration and runtime |
| `area: integration` | Cross-repository compatibility and deployment |
| `type: contract` | REST/MCP/version/capability contract |
| `type: migration` | Database, state, or repository extraction migration |
| `breaking-change` | Requires a major-version or explicit compatibility plan |

Keep `area: writer`, `area: workbench`, and `area: artifact` on historical
issues. New Writer work receives those labels in the future Writer repository,
not as active Core work.

## 5. PR-sized issue slate

### E0 — Core boundary freeze

#### E0.1 Ratify ADR 0012 and the repository ownership inventory

Scope:

- merge ADR 0012, the active roadmap, execution plan, GitHub slate, and complete
  ownership inventory;
- mark prior Workbench ownership decisions as superseded in part without
  deleting their behavioral history.

Acceptance:

- every table, REST route family, MCP operation, skill, entry point, web page,
  and major test family has one target owner or legacy disposition;
- local Markdown links and repository documentation checks pass;
- no runtime, database, plugin, or remote repository changed.

Labels: `roadmap`, `documentation`, `area: core`, `type: contract`.

#### E0.2 Freeze optional-layer feature growth inside Core

Scope:

- add contributor guidance that new manuscript, Workbench, and orchestration
  behavior targets downstream backlogs;
- allow only correctness, security, migration, and compatibility fixes on
  legacy optional surfaces.

Acceptance:

- contributor instructions state the freeze and exception policy;
- no Core build requires a future downstream repository.

Labels: `roadmap`, `documentation`, `area: core`.

#### E0.3 Reclassify the Workbench-era backlog

Scope:

- close completed M3-M5 milestones;
- remove `priority: next` from closed issue #61;
- apply the #62-#65 dispositions in Section 6;
- create the RKA Ecosystem Project and fields after explicit review.

Acceptance:

- one open issue carries `priority: next`;
- no Workbench issue appears as immediate Core work;
- historical milestones and issues remain discoverable.

Labels: `roadmap`, `documentation`, `area: integration`.

### E1 — Core reliability baseline

#### E1.1 Make claim-edge membership and cluster linking idempotent

Candidate: `fix/claim-edge-integrity` at `eb9faa3`.

Audit and remediation evidence:
[`2026-08-25-claim-edge-integrity-audit.md`](../specs/2026-08-25-claim-edge-integrity-audit.md).

Acceptance:

- duplicate membership migration is safe and deterministic;
- repeated assignment does not create duplicate edges;
- merge/split preserves claim membership and linked answers;
- knowledge-pack and integrity checks agree with the repaired graph;
- independent audit has no unresolved P0/P1 finding.

Labels: `roadmap`, `area: core`, `area: substrate`, `priority: next`.

#### E1.2 Enforce logical project isolation for vector retrieval

Acceptance:

- no vector search result crosses `project_id`;
- fresh and upgraded databases carry filterable `project_id` metadata;
- migration and re-embedding cost is measured on a disposable copy;
- live re-embedding requires separate approval and a verified backup;
- FTS, vector, graph, and hybrid retrieval isolation tests pass.

Labels: `roadmap`, `area: core`, `type: migration`.

#### E1.3 Add journal and provenance round-trip regression coverage

Acceptance:

- create/read/update/supersede retains attribution and verbatim PI input;
- decision, mission, journal, literature, and artifact links round-trip;
- retries do not duplicate durable entities or edges;
- project isolation is tested at service, REST, and MCP layers.

Labels: `roadmap`, `area: core`, `area: substrate`.

#### E1.4 Establish the Core-only install, startup, and test profile

Acceptance:

- Core installs without Writer extras;
- Core embedding dependencies such as `sqlite-vec` are separated from
  Agentic LLM-provider dependencies rather than sharing the current `llm`
  optional group;
- REST, MCP, worker, migrations, and minimal web dashboard start;
- Core tests are independently selectable and documented;
- Writer/Workbench tests are excluded without being deleted;
- package metadata contains no mandatory Writer backend dependency.

Baseline evidence:
[`2026-08-25-rka-core-only-baseline.md`](../specs/2026-08-25-rka-core-only-baseline.md).

Labels: `roadmap`, `area: core`.

#### E1.5 Validate real-backup upgrade, export/import, and recovery

Acceptance:

- a disposable copy of a current real database upgrades successfully;
- pre/post counts, IDs, links, revisions, and integrity findings are compared;
- knowledge-pack export/import preserves canonical Core state;
- rollback restores the backup and previous runtime version.

Labels: `roadmap`, `area: core`, `type: migration`.

#### E1.6 Fix the retrieval quality and latency baseline

Acceptance:

- journal, claim, decision, literature, and linked-neighborhood tasks have
  recorded recall and latency baselines;
- project isolation and stale/superseded filtering are included;
- no Writer task is required for the Core release gate;
- regression thresholds and environment are documented.

Labels: `roadmap`, `area: core`.

### E2 — Stable external contract

#### E2.1 Publish Core version and capability discovery

Acceptance:

- REST and MCP consumers can discover Core version and stable capabilities;
- preview/deprecated operations are distinguishable;
- unsupported combinations produce an actionable error.

Labels: `roadmap`, `area: core`, `type: contract`.

#### E2.2 Snapshot and test the supported REST/MCP contract

Acceptance:

- OpenAPI and MCP operation snapshots cover the stable Core surface;
- accidental breaking changes fail CI;
- a fixture client imports no Core service/model/database modules;
- `project_id`, revision/hash, and idempotency expectations are documented.

Labels: `roadmap`, `area: core`, `type: contract`.

#### E2.3 Export and verify legacy Writer state

Acceptance:

- export includes manuscript/planning IDs, revisions, bindings, ratifications,
  source references, and checksums;
- export is read-only and runs against a disposable backup;
- a staging importer round-trips the bundle before any authority switch;
- missing/unsupported records fail visibly.

Labels: `roadmap`, `area: core`, `type: migration`.

#### E2.4 Deprecate optional Core surfaces without removing them

Acceptance:

- manuscript/Workbench operations are hidden from the default stable index;
- documentation points new development to Writer;
- existing callers receive a compatibility notice rather than data loss;
- removal is deferred to E5 and a future explicitly approved breaking release;
  the already-released Core 3.0.0 does not remove these surfaces.

Labels: `roadmap`, `area: core`, `breaking-change`.

#### E2.5 Register sources safely with hashing and provenance

Acceptance:

- registration is project-scoped, idempotent, and preserves exact bytes or a
  stable locator with ownership and provenance;
- unreviewed sources remain outside canonical journal, claim, and decision
  records;
- admission is explicit, revision-guarded, hash-verified, and auditable;
- source envelopes, admissions, hashes, provenance, and artifact bytes
  round-trip through Knowledge Packs and fail closed on tampering.

Labels: `roadmap`, `area: core`, `type: contract`.

### E3 — Agentic extraction draft items

Create these in the RKA Ecosystem Project now and move them into
`infinitywings/rka-agentic` after that repository exists:

1. Preserve and extract `orchestrator/` history.
2. Replace Core internal mirrors with a pinned/generated public contract.
3. Establish independent packaging, CI, deployment, and version checks.
4. Pass mission pickup, checkpoint, report, and provenance integration tests.

### E4 — Writer extraction draft items

Create these in the RKA Ecosystem Project now and move them into
`infinitywings/rka-writer` after that repository exists:

1. Extract Writer skill, tools, templates, tests, and history.
2. Establish Writer-owned state and Core-reference schema.
3. Import and verify legacy manuscript/planning state.
4. Move Workbench services, UI, source synchronization, and provider adapters.
5. Pass real-project claim-to-draft and stale-reference tests.

### E5 — Future Core slimming

#### E5.1 Remove active Writer and Agentic code from Core

Acceptance:

- active Core packages, routes, MCP operations, UI, and dependencies contain no
  downstream implementation;
- legacy export and migration history remain available;
- existing databases open without destructive table removal;
- downstream compatibility suites pass.

Labels: `roadmap`, `area: core`, `breaking-change`.

#### E5.2 Split plugin distribution by component

Acceptance:

- Core plugin contains connector/core-use/maintenance guidance;
- Writer and Agentic plugins install independently;
- version/capability mismatch guidance is visible;
- local clients can use Core without Agentic.

Labels: `roadmap`, `area: integration`, `breaking-change`.

#### E5.3 Publish the future Core migration and recovery guide

Acceptance:

- clean install, 2.x upgrade, backup, rollback, Writer export, and plugin
  transition are tested from disposable environments;
- no step assumes deletion of legacy manuscript tables;
- release checklist cites exact test and compatibility evidence.

Labels: `roadmap`, `documentation`, `area: core`, `type: migration`.

### E6 — Ecosystem integration draft items

Track at Project level and assign to the repository that owns the failing
boundary:

1. Publish the Core/Writer/Agentic compatibility matrix.
2. Test Core-only, Core+Writer, Core+Agentic, and all-three deployments.
3. Test clean install, upgrade, backup, rollback, and unsupported-version UX.
4. Publish one ecosystem release checklist without requiring lockstep tags.

## 6. Existing open issue disposition

### #62: Source Inbox

Split after E0:

- Core issue: safe source registration, hashing, provenance, and interpretation
  admission into canonical research knowledge.
- Writer draft item: manuscript-specific source selection and Workbench UX.

Close #62 as superseded only after both successor items exist.

### #63: ARA-inspired artifact profile and viewer

Remove from immediate Core priority. Keep as an E6 Project-level draft item
until its authority is narrowed. Deterministic export of canonical research
records may belong to Core; interactive artifact/paper views belong to Writer
or a future integration component. Do not create a fourth repository now.

### #64: Grounded research foresight

Move to the future Agentic backlog. Core may expose the evidence and temporal
queries it needs, but advisory next-step generation is orchestration behavior.

### #65: End-to-end reliability and usability hardening

Split:

- Core correctness/retrieval/migration parts become E1 issues;
- Writer/Workbench usability moves to Writer;
- combined deployment and compatibility parts become E6 Project items.

Close #65 as superseded only after the successor items exist.

## 7. Remote-change gate

This document is a proposal slate, not authorization to mutate GitHub. After
the documentation branch is reviewed, apply remote changes in this order:

1. merge the roadmap documentation;
2. close completed M3-M5 milestones;
3. create the RKA Ecosystem Project and fields;
4. create Core E0/E1/E2/E5 milestones and labels;
5. create E0-E2 issues, setting exactly one E1 issue to `priority: next`;
6. reclassify #62-#65 without deleting their history;
7. create downstream repositories and their milestones only at their approved
   extraction gates.
