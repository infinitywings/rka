# ADR 0004: Experiment, run, observation, and evidence-locator contracts

- Status: accepted for M1 / PR 3 implementation
- Date: 2026-08-15
- Baseline: `infinitywings/rka` `main` at
  `9a9ef74f40909b58b217b6692f6bf0c03b590bc3`
- Scope: experiment plans, execution runs, observations, exact locators,
  reviewed claim relations, portability, and manuscript change impact

## Context

ADR 0002 established this non-negotiable chain:

```text
experiment plan -> execution run -> observed result -> interpretation candidate
                  (execution fact)   (measurement)     (scientific meaning)
```

RKA can currently register a file artifact and extract figures, but it cannot
represent which plan a run executed, which measurements were observed, or
which exact output record supports an interpretation. Journals and artifacts
therefore cannot substitute for experiment records. In particular, a command
that exits successfully is not scientific support, while a failed run may
still contain useful partial, negative, or diagnostic observations.

The new aggregate must fit the current RKA contracts: every row is explicitly
project scoped; semantic histories are preserved; state transitions use
optimistic concurrency; raw observations remain distinct from interpretation;
knowledge packs round-trip the complete research substrate; and semantic
changes can identify affected manuscript claims and units.

## Decision

### 1. Use a versioned experiment-plan aggregate

An `exp_` record is the stable experiment identity. Its current plan is an
immutable `epv_` version containing the objective, hypothesis, protocol,
conditions, variables, metrics, baselines, success criteria, failure criteria,
and optional code snapshot. Appending a plan requires the current experiment
revision and records a reason. Existing runs always retain the exact plan
version they used.

Experiment lifecycle is `planned`, `active`, `completed`, or `abandoned`.
Lifecycle transitions advance the experiment revision. A later plan revision
does not rewrite or reinterpret earlier runs.

### 2. Separate run identity from append-only run history

A `run_` binds one exact experiment-plan version to a runner, command, config,
environment, and optional repository snapshot. Its lifecycle is `queued`,
`running`, `succeeded`, `failed`, or `cancelled`. Every transition requires the
expected revision and appends an immutable `rue_` event.

The allowed transitions are:

```text
queued -> running | cancelled
running -> succeeded | failed | cancelled
```

Terminal runs cannot be reopened or rewritten. A successful status records an
execution fact only; it never changes a claim's evidence status.

### 3. Make observations immutable and outcome-complete

An `obs_` is an append-only record attached to a run. It contains a typed
observation kind, a descriptive name and summary, an optional numeric or text
value, unit, sample size, uncertainty note, observed time, and recorder.

Its result direction is one of `positive`, `negative`, `inconclusive`,
`neutral`, or `error`. Direction is relative to the experiment's stated
criterion; it is not a claim-support verdict. Observations are allowed for
running and terminal runs, including failed runs. They cannot be updated or
deleted outside an explicitly authorized whole-project deletion.

### 4. Pin every terminal evidence reference with a typed exact locator

An `elc_` locator belongs to one observation and identifies either:

- a registered `art_` whose stored content hash is copied into the locator; or
- a repository URL, immutable commit SHA, and relative path.

The locator kind is `whole_artifact`, `page`, `line_range`, `table`,
`table_cell`, `json_pointer`, `notebook_cell`, or `record`. Numeric locators
require a start and optional end; structural locators require a non-empty
canonical value. A locator is immutable and carries the content hash used when
it was recorded. A mutable branch name, bare working-tree path, or file name
without a hash/commit is not an exact evidence locator.

### 5. Reuse Interpretation Staging for scientific meaning

`interpretation_candidates.source_type` gains
`experiment_observation`. The source locator is the observation record itself
(`record: full_record`); its terminal files/tables/records remain accessible
through the observation's `elc_` rows. Existing journal-only claim promotion
does not change.

A reviewed experiment interpretation can be classified against one canonical
claim with role `support`, `qualifier`, `counterevidence`, or `context`. This
creates an immutable `evr_` relation and resolves the candidate as
`classified_evidence`. Classification requires the candidate revision, a
review actor, rationale, claim, and role. It never changes
`claims.evidence_status` automatically.

Revocation is explicit and non-destructive: the `evr_` row becomes revoked,
the candidate reopens, and both histories remain visible. Reopening a
classified candidate without revoking its relation is rejected.

### 6. Propagate evidence changes without inferring conclusions

The semantic cursor records inserts and lifecycle transitions for all new
objects. Manuscript impact expands a changed run, observation, locator, or
active evidence relation to the related canonical claim, then uses the current
native manuscript evidence topology to identify affected manuscript claims
and units.

A new plan version is not retroactive. A run-status change, new observation,
new locator, evidence classification, or evidence revocation is impact-worthy
when an active relation connects that chain to a manuscript-bound claim.

### 7. Preserve the complete aggregate in project operations

All new tables are core knowledge-pack data and are remapped in foreign-key
order. Import rejects broken plan-version chains, cross-project references,
or orphaned observation/locator/relation rows. Project deletion removes the
aggregate in reverse dependency order under the existing deletion
authorization mechanism.

REST and MCP expose the same read and mutation capabilities. Typed models use
`extra="forbid"`; project scope is validated by the service even when a
database foreign key would also reject the operation.

## Consequences

- Positive, negative, inconclusive, neutral, failed, and revoked evidence all
  remain auditable.
- Execution success cannot silently become scientific support.
- Exact result files and repository snapshots can be traced and rechecked.
- The Writer can receive localized stale-impact signals when empirical
  evidence changes.
- Existing artifact, claim, and manuscript records remain backward compatible.
- Generalized multi-source canonical claims and automatic evidence aggregation
  remain out of scope; reviewed relations are explicit inputs to later
  readiness logic.
