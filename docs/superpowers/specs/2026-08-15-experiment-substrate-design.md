# M1 / PR 3 experiment-substrate design and acceptance plan

Date: 2026-08-15

Status: design frozen for implementation on
`9a9ef74f40909b58b217b6692f6bf0c03b590bc3`

Authority: [ADR 0004](../../adr/0004-experiment-run-observation-and-evidence-locator-contracts.md)

## Audit of the current tree

The implementation extends these existing contracts rather than replacing
them:

- migration `040` provides project-scoped Interpretation Staging, immutable
  review events, revision-guarded transitions, and journal-only promotion;
- migration `041` provides immutable claim-scope versions and stale-content
  detection;
- `artifacts` records a file path and content hash but no experiment, run, or
  exact result locator;
- native manuscript evidence bindings point to canonical `clm_` records;
- the change cursor can already project claim changes to manuscript claims and
  units through current topology;
- knowledge-pack format 4 explicitly inventories every project-scoped table
  and fails closed on uncategorized semantic data;
- project deletion uses a dependency-ordered table registry and explicit
  deletion authorization;
- REST and the three always-on MCP verbs share strict project pinning and
  typed discriminated-operation models.

The missing layer is therefore semantic, not presentational. An `art_`, journal
entry, successful process, or fluent interpretation cannot be treated as an
experiment result.

## Aggregate and identity map

| Object | Prefix | Mutability | Purpose |
| --- | --- | --- | --- |
| Experiment | `exp_` | revision-guarded lifecycle | Stable experiment identity and current plan head |
| Plan version | `epv_` | immutable | Exact protocol and evaluation contract used by runs |
| Run | `run_` | revision-guarded lifecycle only | One execution attempt bound to an exact plan version |
| Run event | `rue_` | append-only | Complete status-transition history |
| Observation | `obs_` | append-only | Measured, qualitative, failure, or output observation |
| Evidence locator | `elc_` | append-only | Hash/commit-pinned terminal result location |
| Claim-evidence relation | `evr_` | immutable except revocation | Reviewed interpretation-to-claim role |
| Interpretation candidate | existing `icd_` | existing review lifecycle | Scientific meaning proposed for one `obs_` |

## Service operations

### Reads

- list experiments with status filters;
- fetch one experiment with plan history and run summaries;
- list/fetch runs by experiment and status;
- list/fetch observations by run, direction, kind, or related claim;
- fetch one observation detail with exact locators, interpretation candidates,
  and active/revoked claim relations.

Every read requires a project ID and returns no cross-project existence hint.

### Writes

- create experiment and its first immutable plan version atomically;
- append a plan version using experiment `expected_revision`;
- transition experiment lifecycle using `expected_revision`;
- create a queued run against an existing exact plan version;
- transition a run using `expected_revision` and the state machine in ADR 0004;
- append an immutable observation to a running or terminal run;
- append an exact locator after validating the artifact hash or repository
  commit/path contract;
- create an `experiment_observation` interpretation candidate through the
  existing Interpretation Staging API;
- classify that candidate as reviewed claim evidence with an explicit role;
- revoke the relation and reopen the candidate without deleting history.

No operation executes an experiment, edits a result, derives a support verdict,
or updates `claims.evidence_status`.

## Data-validation invariants

- Every parent lookup includes `project_id` even when the schema also has a
  composite foreign key.
- Plan versions are consecutive, immutable, and point to their exact
  predecessor.
- A run can only bind an existing version of its own experiment.
- Config and environment snapshots are JSON objects; plan collections are JSON
  arrays; services serialize them canonically.
- Observation numeric and text payloads cannot both be absent for metric,
  comparison, or test observations; failure/qualitative records require
  explanatory text.
- Failed runs can own observations and locators.
- Artifact locators require a registered same-project artifact with a
  non-empty 64-character content hash.
- Repository locators require an absolute HTTPS repository URL, a hexadecimal
  commit SHA, and a safe relative path without traversal.
- Observation source candidates require `record: full_record`.
- Evidence classification requires an unresolved observation-backed candidate
  and a same-project claim; one candidate represents one claim-relative
  interpretation.
- Revocation retains the relation, rationale, actor, and timestamps.

## Change-impact contract

Change events expose typed endpoints and never a prose-only explanation.
Expansion adds active canonical claims for:

```text
run -> observations -> active evidence relations -> claims
observation -> active evidence relations -> claims
locator -> observation -> active evidence relations -> claims
evidence relation -> claim
```

The existing manuscript topology then maps those claims to native manuscript
claims and units. Revocation remains impact-worthy even though the relation is
no longer active because its change event carries the exact claim endpoint.

## Knowledge-pack and deletion contract

Pack format advances to 5. Export/import order is:

```text
experiments
-> experiment_plan_versions
-> experiment_runs
-> experiment_run_events
-> experiment_observations
-> evidence_locators
-> interpretation_candidates and review history
-> claim_evidence_relations
```

The actual registry order may place Interpretation Staging earlier to satisfy
all existing foreign keys, but every direct reference is remapped and every
new table is categorized. Integrity checks treat broken experiment heads,
plan chains, run bindings, observation parents, locator sources, and claim
relations as critical.

Project deletion removes relations and locators first, then observations, run
events, runs, plan versions, and experiments.

## Acceptance tests

### Migration and model

- fresh database and upgrade from migration 041;
- all CHECK, composite-FK, immutable-trigger, and authorized-project-deletion
  paths;
- JSON and locator validators; unknown request fields fail with 422;
- migration runner idempotence and concurrent startup safety remain green.

### Service and API

- full positive lifecycle from plan through reviewed relation;
- negative, inconclusive, neutral, error, failed-run, and cancelled-run paths;
- stale experiment/run/candidate revisions return conflicts;
- terminal run rewrites and observation/locator edits fail;
- cross-project reads and writes fail without leaking foreign records;
- artifact hash and repository path/commit validation;
- successful run leaves claim evidence state unchanged;
- evidence revocation reopens the candidate and preserves both histories.

### MCP

- strict discriminated schemas and `rka_describe` entries for every operation;
- REST/MCP serialization parity;
- explicit project ID on every experiment operation;
- legacy/always-on tool-surface lock tests updated without increasing the
  always-on verb count.

### Change impact and portability

- locator and run-status changes reach only manuscript units bound through an
  active claim relation;
- unrelated projects and unrelated manuscript claims remain absent;
- revoked relation event still marks the exact bound claim as affected;
- pack 5 export/import round trip preserves every ID relation after remapping;
- malformed or orphaned aggregate rows fail the integrity gate;
- project deletion clears the aggregate without bypassing immutable-history
  protections.

### Real-project validation

Use disposable online backups only; do not mutate live semantic records.

- CPSEval supplies a bounded positive path: create one synthetic experiment
  contract tied to a real scoped method claim, record one failed/partial run,
  one negative or inconclusive observation, one exact disposable artifact
  locator, one reviewed interpretation, and one qualifier/counterevidence
  relation; verify localized manuscript impact.
- InvarLLM supplies the scale/isolation path: confirm list/detail pagination,
  project pinning, and absence of invented experiment semantics for legacy
  journals and claims.

The release gate is the focused suite, full Python suite, production web build,
isolated container smoke test, pack round trip, and disposable real-project
walkthrough. Green unit tests alone do not establish end-to-end semantics.

