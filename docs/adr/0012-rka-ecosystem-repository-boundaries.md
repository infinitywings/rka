# ADR 0012: RKA ecosystem repository and authority boundaries

- Status: accepted for E0 boundary freeze; Agentic portions superseded by
  [ADR 0013](0013-shelve-agentic-and-focus-core-writer.md)
- Date: 2026-08-25
- Decision owner: Chenglong Fu
- Scope: repository ownership, data authority, integration contracts, migration,
  packaging, and release sequencing for RKA Core, RKA Writer, and RKA Agentic
- Detailed execution plan:
  [`2026-08-25-rka-ecosystem-repository-separation.md`](../superpowers/plans/2026-08-25-rka-ecosystem-repository-separation.md)

> **2026-08-27 amendment:** the active ecosystem is Core + Writer. The proposed
> Agentic repository and extraction milestone are shelved. The Agentic text
> below is retained as the historical decision record, not as an active
> implementation or installation plan.

## Context

The current `infinitywings/rka` repository contains a stable research-knowledge
core together with substantial manuscript, Writer, Workbench, plugin, and
agent-orchestration work. These layers have different users, release cadences,
data lifecycles, and failure modes. Continuing to develop all of them inside one
repository makes it difficult to focus testing on the durable journal,
provenance, retrieval, and research-graph guarantees that give RKA its value.

The separation must not reduce RKA Core to journal CRUD. Claims, evidence,
clusters, research questions, scientific decisions, experiment evidence,
freshness, and provenance are part of the durable research record. Conversely,
paper spines, manuscript units, editorial choices, authoring files, and agent
runtime state should not be required in order to install or validate the core.

Existing databases already contain migrations and schemas for manuscript and
planning features. Existing Workbench ADRs and implementation evidence also
record useful behavior. The separation therefore needs an explicit authority
change and compatibility migration rather than deletion or a history rewrite.

## Decision

### 1. One ecosystem, three independently released repositories

The RKA ecosystem will consist of:

| Repository | Product responsibility |
|---|---|
| `infinitywings/rka` | Local-first research knowledge, provenance, retrieval, integrity, and stable REST/MCP interfaces |
| `infinitywings/rka-writer` | Manuscript semantics, Writer skill and tools, academic-writing workflows, and the manuscript Workbench |
| `infinitywings/rka-agentic` | Brain/Executor orchestration, runs, scheduling, approvals, interrupts, and runtime checkpoints |

The repositories remain under the existing `infinitywings` account. A GitHub
Project named **RKA Ecosystem** will provide the shared roadmap and milestones.
Creating a GitHub organization or a fourth umbrella repository is not required
for this separation.

### 2. RKA Core owns canonical research knowledge

RKA Core owns:

- projects and project isolation;
- journals, literature, research decisions, mission records, and reports;
- claims, evidence, evidence clusters, research questions, and their lifecycle;
- experiment definitions, runs, observations, result evidence, and artifact
  locators, but not execution of experiments;
- typed provenance, entity links, claim edges, tags, change history, temporal
  validity, staleness, contradictions, and integrity;
- import, export, backup, migration, full-text/vector/graph retrieval, and
  deterministic research-context assembly;
- the stable REST, MCP, CLI, and minimal research-record maintenance UI.

Core does not own paper organization, prose, venue behavior, Writer sessions,
model-provider orchestration, or agent runtime state.

### 3. RKA Writer owns canonical manuscript semantics

RKA Writer owns:

- manuscripts, manuscript claims, spines, units, outlines, and planning
  branches;
- problem/gap/contribution/evaluation structures and editorial decisions;
- PI ratification of manuscript wording and manuscript-specific readiness;
- Writer conversations, revision proposals, review state, citation validation,
  venue/style configuration, and selected related-work language conventions;
- Markdown, LaTeX, Word, figures, tables, source synchronization, and Workbench
  UI state.

Writer stores versioned references to Core records using at least
`project_id`, `entity_id`, entity type, revision, content hash, and source
locator. A Writer reference never copies authority from Core: Core remains the
authority for the research claim or evidence, and Writer remains the authority
for how that material is organized and expressed in a manuscript.

### 4. RKA Agentic owns execution and orchestration state

RKA Agentic owns:

- agent runs, sessions, queues, schedules, retries, interrupts, and resumes;
- Brain/Executor/PI orchestration policy, tool/model selection, approval state,
  runtime transcripts, and runtime checkpoints;
- deployment and observability for the orchestration process.

Agentic may create or update mission, journal, decision, and evidence records
through Core's public interfaces. It may not read or write the Core database.
A research checkpoint recorded as durable project knowledge belongs to Core;
an execution checkpoint used to resume an agent belongs to Agentic.

### 5. Public contracts replace shared internals

- REST is the deterministic service-to-service contract.
- MCP is the agent-facing discovery and action contract.
- Every project-scoped request carries an explicit `project_id`.
- Writes that can be retried use an idempotency key.
- Returned records expose the revision or content hash needed by consumers.
- Core exposes version and capability information, an OpenAPI contract, and a
  change cursor or `changes_since` mechanism.
- Writer and Agentic do not import `rka.services`, `rka.models`, or `rka.db`,
  and do not open `rka.db` directly.
- Cross-repository compatibility is declared and tested; releases are not
  lockstep.

No event bus, shared-model repository, or mandatory client SDK is introduced
in the first separation. Those additions require demonstrated need.

### 6. Existing Writer state migrates without destructive database surgery

Core's existing manuscript and planning interfaces are frozen: they may receive
correctness fixes, but no new Workbench capability. They become preview and
then deprecated compatibility surfaces.

The migration path is:

1. export legacy Writer state with IDs, revisions, links, and checksums;
2. import it into Writer staging storage while preserving existing identifiers;
3. compare counts, hashes, references, ratifications, and version lineage;
4. explicitly switch Writer authority after verification;
5. leave legacy Core state read-only for a compatibility window.

Existing manuscript migrations and tables are not automatically dropped.
Schema compaction is a later major-version decision and is not an exit condition
for repository separation.

### 7. Plugins and skills follow product ownership

- Core distributes the connector, credential support, core usage, retrieval,
  provenance, integrity, and maintenance guidance.
- Writer distributes the Writer skill, manuscript bootstrap, venue/reference
  tools, style adaptation, and Workbench integration.
- Agentic distributes Brain, Executor, PI, and orchestration-specific commands
  and runtime configuration.

Core retains a small agent-usage skill so an agent can use the research record
correctly without installing the autonomous orchestrator.

### 8. Separation is phased

The active milestone sequence is:

1. E0 boundary freeze;
2. E1 Core reliability baseline;
3. E2 stable external contracts and legacy Writer export;
4. E3 Agentic repository extraction;
5. E4 Writer repository extraction and state migration;
6. E5 Core 3.0 slimming;
7. E6 ecosystem compatibility and integration validation.

No repository extraction starts before E1 and E2 pass their exit gates.

## Relationship to earlier ADRs

This ADR supersedes the repository and authority placement in ADR 0001 where
RKA itself owned canonical manuscript semantics. The safety principles remain:
research evidence and manuscript prose are distinct, AI output cannot silently
become evidence, and human/AI edits use reviewable mutation paths.

ADRs 0005 through 0011 remain the behavioral design record for planning,
semantic proposals, contribution/evaluation structures, outlines, typed
academic-writing semantics, and source synchronization. Their eventual
implementation owner becomes `rka-writer`, not RKA Core.

ADRs 0002 through 0004 remain Core decisions because interpretation staging,
claim scope, and experiment evidence are part of canonical research knowledge.

## Consequences

### Positive

- Core correctness and retrieval can be tested without Writer or orchestrator
  dependencies.
- Optional applications can evolve and release independently.
- Research knowledge, manuscript semantics, and runtime state have explicit,
  non-overlapping owners.
- Existing Workbench and Agentic work is preserved rather than discarded.

### Costs and risks

- Existing manuscript state requires an export/import compatibility path.
- Cross-repository version skew must be detected and explained.
- Some currently shared enums and models need generated or pinned contract
  snapshots.
- Integration testing becomes explicit rather than being implied by a monorepo
  test run.

### Rejected alternatives

- **Keep the monorepo and only rename directories:** does not isolate data,
  release, or testing boundaries.
- **Reduce Core to journal save/retrieve:** forces consumers to recreate the
  research graph and provenance semantics.
- **Move code immediately:** risks data loss and freezes an accidental API as
  the cross-repository contract.
- **Drop old manuscript tables during extraction:** creates avoidable migration
  and recovery risk.
- **Create an organization and umbrella repository now:** adds governance and
  release overhead without solving the current reliability problem.

## E0 exit gate

E0 is complete when:

- this ADR and the detailed execution plan are reviewed;
- every current table, REST route, MCP operation, skill, and major directory
  has a target owner or an explicit legacy disposition;
- the active roadmap prioritizes Core reliability over new Writer/Workbench
  features;
- extraction work is based on a clean `origin/main` worktree rather than the
  existing dirty checkout;
- no runtime code, database data, installed plugin, or remote repository has
  been changed as part of the boundary freeze.
