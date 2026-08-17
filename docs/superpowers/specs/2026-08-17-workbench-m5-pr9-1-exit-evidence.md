# M5 / PR 9.1 integrity-hardening exit evidence

- Date: 2026-08-17
- Baseline: `23c9518bdf40ffecbafaca042ad704fa34c0fd86`
- Branch: `codex/m5-integrity-hardening`
- Scope: cross-version staleness provenance, knowledge-pack and outline
  integrity, semantic change attribution, evidence-narrowing disclosure,
  rationale-readiness naming, and quiet native-spine writes
- Data safety: the running RKA database and research projects were not
  modified. Real-project validation used a transactionally consistent SQLite
  backup copied into `/private/tmp`; migrations, the disposable manuscript,
  export, and re-import affected only that snapshot.

## Contract exercised

The implementation enforces the PR 9.1 contract recorded in
[`2026-08-17-m5-pr9-1-integrity-hardening.md`](../plans/2026-08-17-m5-pr9-1-integrity-hardening.md):

- the already-deployed `030_staleness_resolution.sql` identity is restored on
  main without dropping its five claim and evidence-cluster fields;
- exact and embedded entity IDs are rekeyed in staleness resolution and all
  four outline-intention JSON fields;
- imported outlines use the same cycle, parent-depth, active-parent,
  parent-before-child, and contiguous-subtree validator as native writes;
- absent and cross-manuscript outline parents fail during untrusted-pack
  preflight instead of being silently converted into roots;
- outline-profile insert, update, and delete events identify their manuscript
  and unit;
- expansion warns when a child removes inherited support, qualifier, or
  counterevidence bindings;
- `rationale_complete` is the canonical completeness field while the old
  `checkpoint_ready` value remains a deprecated compatibility alias; and
- native spine upserts compare individual rows and binding sets, so an exact
  replay is revision-, checkpoint-, audit-, and cursor-neutral.

## Automated verification

| Gate | Result |
|---|---|
| Focused migrations, service, knowledge-pack, REST, and MCP suite | `104 passed in 13.41s` |
| Exact no-op and one-rationale-edit regression | Passed; no-op emitted no events/audit/revision, one edit changed only its profile plus manuscript revision |
| Changed Python Ruff lint and format | Passed |
| Patch whitespace check | Passed |
| Production TypeScript/Vite build | Passed; 2,421 modules transformed |
| Changed frontend ESLint | Passed with zero findings |
| Full Python suite | `3105 passed, 21 skipped, 11 failed in 183.07s` |
| Untouched-main embedding baseline | Identical 11 failures, 24 passes, and 6 skips across the five failing files |

The 11 full-suite failures are not introduced by this branch. They all concern
the local sqlite-vector embedding metadata/backfill path. Running those exact
five files against untouched main commit `23c9518` produced the same 11
failures. Repository-wide ESLint also retains main's unrelated seven errors
and two warnings in shared UI, Journal, Research Map, and Settings files; all
three changed frontend files pass targeted ESLint. The production build keeps
the repository's existing large-chunk advisory.

## Real-project-derived pack round-trip

A consistent backup of the running RKA database supplied DelaySteer project
`prj_01KZVF35ESDGKZKTG1D1J59TCF`. On the disposable copy only, current
migrations were applied and a two-unit L2/L3 native outline was created around
one actual DelaySteer claim. The outline included the real claim ID inside a
citation-intention sentence, then the complete project was exported and
re-imported under a new project ID.

Source and target counts matched exactly:

| Table | Rows |
|---|---:|
| journal | 95 |
| claims | 69 |
| claim_edges | 70 |
| evidence_clusters | 13 |
| decisions | 33 |
| literature | 60 |
| manuscripts | 1 |
| manuscript_claims | 1 |
| manuscript_units | 2 |
| manuscript_unit_outline_profiles | 2 |
| manuscript_claim_evidence | 1 |
| manuscript_unit_evidence | 1 |
| manuscript_claim_units | 1 |

The imported L3 unit retained its parent, evidence, and claim bindings; the
claim ID embedded in citation prose changed to the imported ID; and the target
project reported zero critical integrity issues. Synthetic round-trip tests
separately cover non-null staleness-resolution fields because the live
DelaySteer records currently leave those new fields empty.

## Exit decision

The PR 9.1 feature scope is ready for branch publication and GitHub CI. The
local environment's embedding and repository-wide ESLint baselines remain
explicitly unresolved and out of scope; they are not presented as green.
PR 9.2 remains dependent on this hardening slice.
