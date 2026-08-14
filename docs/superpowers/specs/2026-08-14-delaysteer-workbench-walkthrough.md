# M0 Manuscript Workbench Walkthrough

- Date: 2026-08-14
- Build under test: RKA `2.9.0` from `main` baseline `9db7bd8` plus the
  local M0 changes
- Primary project: DelaySteer (`prj_01KZVF35ESDGKZKTG1D1J59TCF`)
- Full-manuscript control: CPSEval (`prj_01KPVB7NHJ0N33C024TD0E6CZ6`),
  manuscript `man_01M00D9BPMA60CN3FXTE86C4W1`
- Data safety: the browser test used a SQLite-consistent backup in a disposable
  Docker volume. The live RKA `2.8.1` containers and `rka_rka-data` volume were
  not restarted or modified.

## Purpose

Validate the M0 authority and stage contracts against real RKA state before
introducing planning-artifact or experiment-schema migrations. The walkthrough
must expose unsupported or incomplete material rather than filling gaps with
generated prose.

## DelaySteer: project-only path

DelaySteer has no canonical `man_` record in the snapshot. That is a normal and
important pre-manuscript state, not an error. The workbench therefore opened in
project-only mode and rendered:

- 5 active research questions;
- 13 evidence clusters;
- 69 grounded claims;
- no manuscript claim, unit, readiness, or impact aggregate.

The stage rail correctly treated the early project state as:

| Stage | Verdict | Reason |
|---|---|---|
| Seed insight | Exploratory | author intent is not yet a canonical record |
| Paper spine | Exploratory | no native claim or eligible manuscript candidate |
| Problem and scope | Blocked | no manuscript claim scope contract |
| Literature and SOTA | Ready | active RQs and clusters are navigable |
| Gap and motivation | Exploratory | no explicit gap signal is promoted automatically |
| Insight and response | Exploratory | project evidence is inspiration, not a manuscript claim |
| Research questions | Ready | five active RQ decisions are visible |
| Contributions | Blocked | no native or admissible contribution claim |
| Evaluation contract | Blocked | no native result units or experiment contract |
| Outline | Blocked | no manuscript units |

The strongest diagnostic was RQ
`dec_01KZVQ7N0G5FHRKGFP7GGFY2BE`, concerning compositional temporal
programmability. The workbench showed **0 clusters and 0 claims** for this RQ,
while the other four RQs retained their own cluster and claim counts. It did
not reinterpret the unsupported RQ as a validated novelty claim.

## Full-manuscript control path

The CPSEval control exercised all five manuscript read projections:

- `/api/manuscripts/:id/context`
- `/api/manuscripts/:id/spine`
- `/api/manuscripts/:id/writing-candidates`
- `/api/manuscripts/:id/readiness?target_phase=drafting`
- `/api/manuscripts/:id/impact?since_cursor=0&limit=100`

Every request returned HTTP 200. The context capsule showed 2 RQs, 6 clusters,
and 81 claims for CPSEval. The native drafting gate remained `BLOCK` with three
specific findings:

1. `NO_ACTIVE_CLAIMS`: the argument spine has no active claims;
2. `CHECKPOINT_REQUIRED`: the venue checkpoint is unresolved;
3. `CHECKPOINT_REQUIRED`: the outline checkpoint is unresolved.

The Evaluation stage also stated that the current schema has no first-class
experiment, run, measurement, baseline, metric, or condition objects and that
no result units exist for this manuscript. It did not infer experiments from
journal prose or repository execution.

## Defects found and corrected

### Project-switch request race

On the first pass, React published the new project query keys before the API
client's project header was updated. The first DelaySteer fetch therefore
cached Default Project data under the DelaySteer query key. The provider now
updates the API request boundary synchronously before publishing the new
project state. A repeated DelaySteer load showed the correct name and the
5/13/69 RQ-cluster-claim counts.

### Stale inspector selection across projects

The first full-manuscript switch retained a previously selected DelaySteer RQ
in the CPSEval evidence inspector. Inspector selections are now scoped to the
exact `(project_id, manuscript_id-or-project-only)` context. The regression
walkthrough confirmed that switching to CPSEval resets the inspector to the
current CPSEval stage contract.

### MCP dependency-major drift

A clean Docker build resolved `mcp` 2.0.0, which removed the
`mcp.server.fastmcp` import used by RKA and caused six Writer MCP-wrapper tests
to error. `pyproject.toml` now declares `mcp>=1.26.0,<2.0.0` until RKA is
deliberately migrated to the 2.x API. The rebuilt image resolved `mcp` 1.29.0,
and `rka mcp --help` succeeded.

## Verification evidence

- Web TypeScript/Vite build: pass.
- Changed-file ESLint set: pass.
- Writer, Writer packaging, native manuscript API, and change-tracking API
  suites: **397 passed**.
- Docker image smoke test: `rka mcp --help` pass.
- Browser walkthrough: DelaySteer project-only path and CPSEval full-manuscript
  path pass; all observed workbench API calls returned HTTP 200.
- Desktop visual inspection: stage rail, context capsule, stage canvas, and
  evidence inspector remained legible and navigable in dark mode.

The repository-wide web lint command still reports 8 errors and 2 warnings in
pre-existing files (`FirstRunBanner`, shared UI variants, `useTheme`, Journal,
ResearchMap, and Settings). No reported error is in the changed M0 file set.
The production bundle also retains the existing large-chunk warning. These are
baseline cleanup items, not evidence that the M0 workflow semantics failed.

## Design revisions from the walkthrough

1. **Project-only mode is first-class.** A researcher must be able to begin
   with an insight and inspect RQs/clusters/claims before registering a
   manuscript. Creating `man_` is an explicit promotion step, not an entry
   requirement.
2. **The context key is an authority boundary.** Project and manuscript
   changes must invalidate request and selection state synchronously. No card
   may survive a context-key change unless its trace is revalidated.
3. **Zero coverage is actionable information.** An active RQ with zero
   clusters/claims is shown as unsupported even when adjacent RQs are rich.
4. **M1 experiment semantics remain necessary.** Result-like prose and generic
   claims cannot substitute for planned experiment/run/result entities.
5. **No migration is justified by UI fluency alone.** The next schema work must
   start with the interpretation-staging and experiment-contract ADRs and
   preserve this project-only path.

## Exit decision

The M0 implementation is technically validated and suitable for researcher
review. The remaining M0 gate is explicit approval of the authority and stage
contracts. After that approval, M1 Interpretation Staging/schema design and M2
read-only workbench expansion may proceed in parallel. No canonical data was
created or modified during this walkthrough.
